"""Exercise grouped controlled faults without touching physical USB or radio."""

import asyncio
from collections import Counter

import pytest
from test_multi_fragment_radio import Pair
from test_node_control_native import native_library as native_library

from lora_testbed import fault_matrices
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
                messages_per_case=3,
                repetitions=1,
            )
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(35):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            [case] = saved["cases"]
            assert saved["assessment"] == "pass", saved
            assert case["measurements"] == {
                "message_outcomes": ["pass", "pass", "pass"],
                "target_ordinal": 3,
            }
            assert len(case["run_ids"]) == 2
            assert all(host.radio.get(i)["verification"]["bytes_equal"] for i in case["run_ids"])
            [trial_id] = case["trial_ids"]
            fault = host.radio.get(host.lab_trials.get(trial_id)["children"]["fault"])
            assert fault["missing_evidence"]["missing_indexes"] == [4]
            assert fault["summaries"]["B"]["delivered_messages"] == 0
            assert fault["plan"]["spec"]["source_seed"] == spec.seed + 2
        finally:
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            await host.close()

    monkeypatch.setattr(fault_matrices, "PACKET_FRAGMENT_SIZES", (160,))
    asyncio.run(scenario())


def test_retry_exhaustion_accounts_for_every_attempt_timeout_and_missing_fragment(
    tmp_path, native_library
):
    from copy import deepcopy

    from lora_testbed import fault_accounting
    from lora_testbed.experiments_v2 import known_data

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
