"""Integration plan coverage and grouped execution over the shared physical host."""

import asyncio
from collections import Counter

import pytest
from test_multi_fragment_radio import Pair
from test_node_control_native import native_library as native_library

from lora_testbed.host import Host
from lora_testbed.integration_matrices import MatrixRequest, compile_matrix, link_request


def test_full_integration_plans_retain_variants_repetitions_and_transport():
    serial = compile_matrix(MatrixRequest(catalog_id="IF-01", transports=["native_usb", "uart"]))
    assert serial["full_plan"]
    assert {c["transport"] for c in serial["cases"]} == {"native_usb", "uart"}
    assert {
        (c["role"], c["transport"], c["cycles"])
        for c in serial["cases"]
        if c["variant"] == "valid_control_cycles"
    } == {(role, transport, 10) for role in "AB" for transport in ("native_usb", "uart")}
    assert any(c["variant"] == "split_every_boundary" for c in serial["cases"])

    spec = MatrixRequest(catalog_id="IF-02")
    link = compile_matrix(spec)
    assert Counter(c["group"] for c in link["cases"]) == {"C1": 6, "C2": 18, "C3": 6}
    assert sum(c["message_count"] for c in link["cases"] if c["group"] != "C3") == 2400
    assert link["sha256"] == compile_matrix(spec)["sha256"]
    assert {link_request(spec, c, 17).source_seed for c in link["cases"]} == {760, 860, 960}
    short = compile_matrix(MatrixRequest(catalog_id="IF-02", messages_per_case=2))
    assert not short["full_plan"] and short["sha256"] != link["sha256"]

    campaign = compile_matrix(MatrixRequest(catalog_id="IF-03"))
    assert campaign["case_count"] == 25
    assert all(
        c["campaign_cases"] == 6 and c["messages_per_case"] == 100 for c in campaign["cases"]
    )
    assert {c["variant"] for c in campaign["cases"] if c["group"] == "C6"} == {
        "restart_paused",
        "restart_active",
    }


def test_grouped_link_verifies_both_directions_and_recovers_from_peer_mismatch(
    tmp_path, native_library
):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library)
        bridge = None
        try:
            spec = MatrixRequest(catalog_id="IF-02", repetitions=1, messages_per_case=2)
            assert host.procedures.matrix_preview(spec, host.radio)["ready_case_count"] == 0
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            plan = host.procedures.matrix_preview(spec, host.radio)
            assert plan["ready_case_count"] == plan["case_count"] == 10
            started = await host.start_procedure_matrix(spec)
            with pytest.raises(RuntimeError, match="owns"):
                await host.start_lab_trial(None)
            async with asyncio.timeout(20):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert saved["status"] == "completed" and saved["assessment"] == "pass"
            assert not saved["full_procedure_passed"] and not saved["hardware_validated"]
            assert all(c["assessment"] == "pass" for c in saved["cases"])
            children = [host.radio.get(i) for c in saved["cases"] for i in c["run_ids"]]
            assert len({r["session_id"] for r in children}) == 20
            assert (
                sum(bool((r.get("verification") or {}).get("bytes_equal")) for r in children) == 18
            )
            mismatch = [r for r in children if r.get("configuration_check") == "peer_mismatch"]
            assert len(mismatch) == 2
            assert all(r["failure_stage"] == "configuring" and not r["prepared"] for r in mismatch)
            assert len(pair.frames) == 18
            evidence = list(host.procedures.all_evidence(saved["id"]))
            assert len(evidence) == 20
            assert all(e["document"]["wire_sha256"] for e in evidence)
            assert not host.busy
        finally:
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            await host.close()

    asyncio.run(scenario())


def test_serial_matrix_uses_one_node_and_preserves_unavailable_cases(tmp_path, native_library):
    async def scenario():
        host = Host(tmp_path)
        try:
            pair = Pair(host, native_library)
            await pair.connect()
            await host.physical["B"].close()
            spec = MatrixRequest(
                catalog_id="IF-01", groups=["C1", "C2"], repetitions=1, valid_cycles=2
            )
            plan = host.procedures.matrix_preview(spec, host.radio)
            assert plan["ready_case_count"] == 5
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(10):
                await host.procedures.task
            result = host.procedures.get(started["id"])
            assert result["status"] == "completed", result
            assert result["assessment"] == "inconclusive"
            assert set(result["physical_bindings"]) == {"A"}
            assert sum(c["status"] == "completed" for c in result["cases"]) == 5
            assert sum(c["status"] == "blocked" for c in result["cases"]) == 5
            rows = [
                row["document"]["record"]
                for row in host.procedures.all_evidence(result["id"])
                if row["document"]["direction"] == "node_to_host"
            ]
            errors = Counter(r["error"]["code"] for r in rows if not r["ok"])
            assert errors == {
                "NOT_OWNER": 2,
                "INVALID_ARGUMENT": 2,
                "UNSUPPORTED_COMMAND": 1,
                "MISSING_CAPABILITY": 1,
            }
            assert host.physical["A"].health.node_role == "A" and not host.busy
        finally:
            await host.close()

    asyncio.run(scenario())


def test_matrix_stop_waits_for_child_cleanup_and_skips_later_cases(tmp_path, native_library):
    async def scenario():
        host = Host(tmp_path)
        try:
            pair = Pair(host, native_library)
            await pair.connect()
            spec = MatrixRequest(
                catalog_id="IF-02", groups=["C1"], repetitions=1, messages_per_case=2
            )
            started = await host.start_procedure_matrix(spec)
            await host.stop()
            result = host.procedures.get(started["id"])
            assert result["status"] == "cancelled"
            assert [c["status"] for c in result["cases"]] == ["cancelled", "skipped"]
            assert not host.busy
            assert all(not node.rf_run_id for node in host.physical.values())
        finally:
            await host.close()

    asyncio.run(scenario())


def test_campaign_matrix_executes_baseline_pause_resume_and_cancel(tmp_path, native_library):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library)
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            spec = MatrixRequest(
                catalog_id="IF-03",
                groups=["C1", "C2", "C3", "C4", "C5", "C7", "C8"],
                repetitions=1,
                messages_per_case=2,
            )
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(45):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert saved["status"] == "completed", saved
            assert saved["assessment"] == "inconclusive"
            baseline, paused, cancelled, config, blocked, rerun, exported = saved["cases"]
            supported = (baseline, paused, cancelled, config, rerun, exported)
            assert [c["assessment"] for c in supported] == ["pass"] * 6, supported
            assert blocked["status"] == "blocked"
            failed = host.physical_campaigns.get(config["campaign_ids"][0])
            assert failed["status"] == "failed" and failed["case_counts"]["skipped"] == 11
            selected = host.physical_campaigns.get(rerun["campaign_ids"][1])
            assert selected["parent_execution_id"] == rerun["campaign_ids"][0]
            assert selected["case_counts"] == {"completed": 2}
            records = [e["document"] for e in host.procedures.all_evidence(saved["id"])]
            export_record = next(
                row["verified_export"] for row in records if "verified_export" in row
            )
            assert export_record["case_count"] == 12 and export_record["child_count"] == 36
            child = host.physical_campaigns.get(paused["campaign_ids"][0])
            assert child["enclosing_procedure_id"] == saved["id"]
            assert child["case_counts"] == {"completed": 12}
            assert child["pause_count"] == child["resume_count"] == 1
            stopped = host.physical_campaigns.get(cancelled["campaign_ids"][0])
            assert stopped["status"] == "cancelled" and stopped["case_counts"]["skipped"] == 11
            assert not host.busy
        finally:
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            await host.close()

    asyncio.run(scenario())
