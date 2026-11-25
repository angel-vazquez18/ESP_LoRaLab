"""Exercise observer ownership, bounded windows and workload linkage."""

import asyncio

from test_multi_fragment_radio import Pair
from test_node_control_native import NativeSerial
from test_node_control_native import native_library as native_library

from lora_testbed.host import Host
from lora_testbed.integration_matrices import MatrixRequest, compile_matrix


def test_memory_plan_counts_and_negotiated_cap():
    plan = compile_matrix(MatrixRequest(catalog_id="MEM-01"), message_limit=9000)
    assert plan["full_plan"]
    cases = plan["cases"]
    assert len([c for c in cases if c["group"] == "C1"]) == 6
    linked = [case for case in cases if case["group"] == "C2"]
    assert len(linked) == 36
    assert {case["message_bytes"] for case in linked} == {64, 160, 321, 1200, 9000, 48000}
    assert {case["message_bytes"] for case in cases if case["group"] == "C4"} == {9001}
    assert all(case["observation_ms"] == 30000 for case in cases)


def test_single_node_idle_observation_round_trips_through_evidence(tmp_path, native_library):
    async def scenario():
        host = Host(tmp_path)
        node = host.physical["A"]
        peer = NativeSerial(native_library)
        node.opener = lambda _: peer
        try:
            await node.connect("fixture-only-A")
            spec = MatrixRequest(
                catalog_id="MEM-01",
                groups=["C1"],
                roles=["A"],
                repetitions=1,
                memory_window_ms=1000,
            )
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(10):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            [case] = saved["cases"]
            assert saved["status"] == "completed" and saved["assessment"] == "pass", saved
            assert case["cleanup_verified"]
            summary = case["measurements"]["A"]
            assert summary["sampled_stages"] == ["idle"]
            assert summary["stop_reason"] == "deadline" and summary["observed_idle_us"] >= 1_000_000
            full = host.observations.get(summary["evidence_id"])
            assert full["evidence_sha256"] == summary["evidence_sha256"]
            assert full["assessments"]["memory"]["observed"]["sample_count"] >= 9
            assert not saved["hardware_validated"]
        finally:
            await host.close()

    asyncio.run(scenario())


def test_link_memory_captures_two_nodes_and_identifies_radio_workload(tmp_path, native_library):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library)
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            spec = MatrixRequest(
                catalog_id="MEM-01",
                groups=["C2", "C3"],
                directions=["A_TO_B"],
                repetitions=1,
                memory_window_ms=1000,
                subset_sizes=[64],
            )
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(30):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert saved["status"] == "completed", saved
            linked, *unavailable = saved["cases"]
            assert linked["assessment"] == "pass" and linked["cleanup_verified"], linked
            assert all(case["status"] == "blocked" for case in unavailable)
            [run_id] = linked["run_ids"]
            assert host.radio.get(run_id)["verification"]["bytes_equal"]
            for role in ("A", "B"):
                measurement = linked["measurements"][role]
                assert measurement["linked_run_id"] == run_id
                assert measurement["observed_idle_us"] >= 800000
                evidence = host.observations.get(measurement["evidence_id"])
                assert any(
                    row["data"]["workload_id"] == run_id
                    for row in evidence["evidence"]["memory"]["events"]
                )
        finally:
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            await host.close()

    asyncio.run(scenario())


def test_stopping_idle_matrix_releases_only_its_observer(tmp_path, native_library):
    async def scenario():
        host = Host(tmp_path)
        node = host.physical["B"]
        peer = NativeSerial(native_library)
        node.opener = lambda _: peer
        try:
            await node.connect("fixture-only-B")
            spec = MatrixRequest(catalog_id="MEM-01", groups=["C1"], roles=["B"], repetitions=1)
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(5):
                while not host.procedures.current["cases"][0].get("observation_ids"):
                    await asyncio.sleep(0.01)
            await host.stop()
            saved = host.procedures.get(started["id"])
            assert saved["status"] == "cancelled" and saved["cases"][0]["cleanup_verified"]
            status = await node.request("memory.status")
            assert not status["active"] and status["stop_reason"] == "stop"
            assert not host.busy
        finally:
            await host.close()

    asyncio.run(scenario())
