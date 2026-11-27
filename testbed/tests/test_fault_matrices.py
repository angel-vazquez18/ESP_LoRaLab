"""Exercise grouped controlled faults without touching physical USB or radio."""

import asyncio
from collections import Counter
from copy import deepcopy

import pytest
from test_multi_fragment_radio import Pair
from test_node_control_native import native_library as native_library

from lora_testbed import fault_accounting, fault_matrices
from lora_testbed.experiments_v2 import known_data
from lora_testbed.host import Host
from lora_testbed.integration_matrices import MatrixRequest, compile_matrix


def test_fault_plans_preserve_required_variants_and_planned_target():
    for identifier, counts in (
        ("SEC-02", {"C1": 6, "C2": 6}),
        ("SEC-03", {"C1": 6, "C2": 6}),
        ("PKT-02", {"C1": 24, "C2": 24, "C3": 24, "C4": 24}),
        ("PKT-03", {"C1": 24, "C2": 24, "C3": 12, "C4": 24}),
    ):
        spec = MatrixRequest(catalog_id=identifier)
        plan = compile_matrix(spec)
        assert plan["full_plan"]
        assert Counter(case["group"] for case in plan["cases"]) == counts
        if identifier.startswith("PKT"):
            assert all(case["target_ordinal"] == 3 for case in plan["cases"])
            case = next(c for c in plan["cases"] if c["group"] == "C2")
            assert fault_matrices.selected_request(spec, case, 2).injection.message_id == 1
    replay_cases = compile_matrix(MatrixRequest(catalog_id="SEC-03"))["cases"]
    old_window = [case for case in replay_cases if case["group"] == "C2"]
    assert len(old_window) == 6
    assert {case["message_count"] for case in old_window} == {132}
    assert all(case["driver"] == "fault_window_unavailable" for case in old_window)

    spec = MatrixRequest(catalog_id="SEC-02")
    cases = compile_matrix(spec)["cases"]
    offsets = {
        fault_matrices.selected_request(spec, case, 0).injection.byte_offset for case in cases
    }
    assert offsets == {40, 104}


@pytest.mark.parametrize("identifier", ["SEC-02", "SEC-03"])
def test_security_cases_reuse_three_bound_child_runs(tmp_path, native_library, identifier):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library, lab=True)
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            spec = MatrixRequest(catalog_id=identifier, directions=["A_TO_B"], repetitions=1)
            started = await host.start_procedure_matrix(spec)
            with pytest.raises(RuntimeError, match="owns"):
                await host.start_lab_trial(None)
            async with asyncio.timeout(35):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert saved["status"] == "completed", saved
            assert saved["cases"][0]["assessment"] == "pass", saved
            assert saved["cases"][1]["status"] == (
                "blocked" if identifier == "SEC-03" else "completed"
            )
            for case in saved["cases"]:
                if not case["ready"]:
                    assert not case.get("trial_ids")
                    continue
                [identifier_] = case["trial_ids"]
                trial = host.lab_trials.get(identifier_)
                assert trial["outcome"] == "pass"
                assert trial["enclosing_procedure_id"] == saved["id"]
                assert set(trial["children"]) == {"before", "fault", "after"}
                children = [host.radio.get(run_id) for run_id in trial["children"].values()]
                assert all(child["cleanup"]["confirmed"] for child in children)
                assert len({child["session_id"] for child in children}) == 3
                wire = host.radio.content(trial["children"]["fault"], "wire").read_text()
                assert '"tx_key_hex":' not in wire and '"rx_key_hex":' not in wire
            assert not saved["hardware_validated"] and not host.busy
        finally:
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            await host.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("direction", ["A_TO_B", "B_TO_A"])
def test_intact_packet_retains_exact_archive_and_fragment_lengths(
    tmp_path, native_library, direction
):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library)
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            spec = MatrixRequest(
                catalog_id="PKT-02",
                groups=["C1"],
                directions=[direction],
                messages_per_case=1,
                repetitions=1,
            )
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(60):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert saved["assessment"] == "pass", saved
            assert not saved["hardware_validated"]
            assert [
                (
                    row["fragment_payload_bytes"],
                    row["measurements"]["intact_packets"][0]["expected_fragment_lengths"][-1],
                )
                for row in saved["cases"]
            ] == [(16, 16), (64, 48), (160, 80), (199, 6)]

            case = saved["cases"][-1]
            [identifier] = case["run_ids"]
            request = fault_matrices.selected_request(spec, case, 0)
            result = host.radio.get(identifier)
            assert result["cleanup"]["confirmed"]
            assert case["measurements"]["intact_packets"][0]["archive_matches"] == {
                "source": True,
                "recovered": True,
            }
            archive = host.radio.content(identifier, "recovered")
            archive.write_bytes(b"x" * 1200)
            reviewed = fault_matrices.intact_packet_evidence(result, request, host.radio.content)
            assert reviewed["outcome"] == "inconclusive"
        finally:
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            await host.close()

    asyncio.run(scenario())


def test_packet_fault_targets_third_workload_and_preserves_other_deliveries(
    tmp_path, native_library, monkeypatch
):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library, lab=True)
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            spec = MatrixRequest(
                catalog_id="PKT-02",
                groups=["C2"],
                directions=["A_TO_B"],
                messages_per_case=4,
                repetitions=1,
            )
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(60):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            [case] = saved["cases"]
            assert saved["assessment"] == "pass", saved
            measurements = case["measurements"]
            assert measurements["message_outcomes"] == ["pass"] * 4
            assert measurements["target_ordinal"] == 3
            records = [host.radio.get(i) for i in case["run_ids"]]
            assert [r["message_id"] for r in records] == [1, 2, 3, 4]
            assert len({r["wire_run_id"] for r in records}) == 1
            assert len({r["security"]["key_set_id"] for r in records}) == 1
            assert {r["session_id"] for r in records} == {measurements["session_id"]}
            assert len({r["id"] for r in records}) == 4
            assert all(records[i]["verification"]["bytes_equal"] for i in (0, 1, 3))
            assert all(r["cleanup"]["session_retained"] for r in records[:-1])
            assert records[-1]["cleanup"]["confirmed"] and not host.busy
            assert all(not node.rf_run_id for node in host.physical.values())
            fault = records[2]
            assert fault["missing_evidence"]["missing_indexes"] == [4]
            assert fault["summaries"]["B"]["delivered_messages"] == 0
            assert fault["plan"]["spec"]["source_seed"] == spec.seed
            expected = known_data(spec.seed, 3, 1200)
            changed = deepcopy(fault)
            accepted = [event for event in changed["events"] if event["name"] == "rx.accepted"]
            changed["events"].remove(accepted[-1])
            findings = fault_accounting.assess(changed, expected)
            assert findings["outcome"] == "inconclusive"
            assert any(
                check["code"] == "all_other_fragments_inserted_once"
                and check["outcome"] == "inconclusive"
                for check in findings["checks"]
            )
            changed = deepcopy(fault)
            next(event for event in changed["events"] if event["name"] == "message.result")["data"][
                "status"
            ] = "delivered"
            assert fault_accounting.assess(changed, expected)["outcome"] == "fail"

        finally:
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            await host.close()

    monkeypatch.setattr(fault_matrices, "PACKET_FRAGMENT_SIZES", (160,))
    asyncio.run(scenario())


@pytest.mark.parametrize(
    "group,expected_check",
    [
        ("C3", "exactly_one_rejected_duplicate_after_insertion"),
        ("C4", "complete_reversed_block"),
    ],
)
def test_same_session_packet_control_preserves_its_own_arrival_evidence(
    tmp_path, native_library, monkeypatch, group, expected_check
):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library, lab=True)
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            spec = MatrixRequest(
                catalog_id="PKT-02",
                groups=[group],
                directions=["B_TO_A"],
                messages_per_case=4,
                repetitions=1,
            )
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(60):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            [case] = saved["cases"]
            assert case["assessment"] == "pass", case
            members = case["measurements"]["members"]
            assert [m["first_frame_seq"] for m in members] == [1, 8, 15, 22]
            assert [m["last_frame_seq"] for m in members] == [7, 14, 21, 28]
            actual = host.procedures.evidence(saved["id"], case_id=case["id"])
            injected = next(row["document"] for row in actual if "packet_fault" in row["document"])
            assert injected["message_id"] == 3
            assert any(
                row["code"] == expected_check and row["outcome"] == "pass"
                for row in injected["packet_fault"]["checks"]
            )
            assert all(not node.rf_run_id for node in host.physical.values())
        finally:
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            await host.close()

    monkeypatch.setattr(fault_matrices, "PACKET_FRAGMENT_SIZES", (199,))
    asyncio.run(scenario())


def test_cancellation_between_members_closes_retained_session(
    tmp_path, native_library, monkeypatch
):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library)
        bridge = None
        reached_next = asyncio.Event()
        original_start = host.radio.start

        async def hold_before_next(request, *, numbered=None):
            if numbered and numbered.next_message == 2:
                reached_next.set()
                await asyncio.Event().wait()
            return await original_start(request, numbered=numbered)

        monkeypatch.setattr(host.radio, "start", hold_before_next)
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            spec = MatrixRequest(
                catalog_id="PKT-02",
                groups=["C1"],
                directions=["A_TO_B"],
                messages_per_case=2,
                repetitions=1,
            )
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(30):
                await reached_next.wait()
            assert all(node.rf_run_id for node in host.physical.values())
            stopped = await host.procedures.stop(expected_run_id=started["id"])
            assert stopped["status"] == "cancelled"
            [case] = stopped["cases"]
            assert len(case["run_ids"]) == 1
            assert all(not node.rf_run_id for node in host.physical.values())
            for role in "AB":
                status = await host.physical[role].request("status.get")
                assert status["state"] == "idle" and not status["security_ready"]
            assert not host.busy
        finally:
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            await host.close()

    monkeypatch.setattr(fault_matrices, "PACKET_FRAGMENT_SIZES", (199,))
    asyncio.run(scenario())


def test_retry_exhaustion_accounts_for_every_attempt_timeout_and_missing_fragment(
    tmp_path, native_library
):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library, lab=True)
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            spec = MatrixRequest(
                catalog_id="PKT-03",
                groups=["C4"],
                directions=["B_TO_A"],
                messages_per_case=1,
                repetitions=1,
            )
            preview = host.procedures.matrix_preview(spec, host.radio)
            assert preview["ready_case_count"] == 4
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(75):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert saved["status"] == "completed" and saved["assessment"] == "pass", saved
            assert not saved["hardware_validated"]
            for case in saved["cases"]:
                [identifier] = case["trial_ids"]
                trial = host.lab_trials.get(identifier)
                assert trial["outcome"] == "pass" and case["cleanup_verified"]
                fault = host.radio.get(trial["children"]["fault"])
                assert fault["summaries"]["A"]["delivered_messages"] == 0
                assert all(
                    host.radio.get(trial["children"][name])["verification"]["bytes_equal"]
                    for name in ("before", "after")
                )
                if case["ack_mode"] == "none":
                    assert fault["missing_evidence"]["missing_indexes"] == [1]
                    continue
                assert fault["missing_evidence"]["missing_indexes"] == [1, 2]
                targets = fault["lab"]["exhaustion_targets"]
                count = 1 + case["max_retries"]
                assert len(targets) == fault["lab"]["report"]["count"] == count
                assert [entry["attempt_index"] for entry in targets] == list(range(1, count + 1))
                assert len({entry["injection_id"] for entry in targets}) == count
                assert {entry["state"] for entry in fault["lab"]["report"]["entries"]} == {
                    "applied"
                }
                seq = fault["lab"]["report"]["entries"][0]["target_frame_seq"]
                acks = [
                    event
                    for event in fault["events"]
                    if event["name"] == "ack.result" and event["data"]["acked_frame_seq"] == seq
                ]
                assert [event["data"]["status"] for event in acks] == ["timeout"] * count
                assert [event["data"]["attempt_index"] for event in acks] == list(
                    range(1, count + 1)
                )
                expected = known_data(spec.seed, 1, 321)
                incomplete = deepcopy(fault)
                incomplete["events"].remove(acks[-1])
                assert fault_accounting.assess(incomplete, expected)["outcome"] == "inconclusive"
        finally:
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            await host.close()

    asyncio.run(scenario())
