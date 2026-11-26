"""Exercise observer ownership, bounded windows and workload linkage."""

import asyncio

import pytest
from test_multi_fragment_radio import Pair
from test_node_audio_host import AudioSerial
from test_node_control_native import NativeSerial
from test_node_control_native import native_library as native_library
from test_voice_workflows import AudioPair

from lora_testbed import memory_matrix
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
            assert {case["variant"] for case in unavailable if case["status"] == "blocked"} == {
                "capture",
                "playback",
                "reassembly",
                "integrated_voice",
            }
            assert all(
                case["assessment"] == "pass"
                for case in unavailable
                if case["variant"] in ("encode", "decode")
            )
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


def test_memory_audio_keeps_stage_boundaries_readbacks_and_owned_cleanup(tmp_path, native_library):
    async def scenario():
        host = Host(tmp_path)
        node = host.physical["B"]
        peer = AudioSerial(native_library)
        node.opener = lambda _: peer
        try:
            await node.connect("isolated-audio-memory")
            await host.artifacts.start_upload("B", b"owner-retained", name="existing.bin")
            await host.artifacts.task
            preexisting = (await node.request("artifact.list"))["artifacts"]
            spec = MatrixRequest(
                catalog_id="MEM-01",
                groups=["C3"],
                roles=["B"],
                repetitions=1,
                memory_window_ms=1000,
            )
            preview = host.procedures.matrix_preview(spec, host.radio)
            assert preview["ready_case_count"] == 4
            opened = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(45):
                await host.procedures.task
            saved = host.procedures.get(opened["id"])
            assert saved["status"] == "completed" and saved["assessment"] == "inconclusive", saved
            assert set(saved["physical_bindings"]) == {"B"}
            stages = {
                "capture": "capture",
                "encode": "encode",
                "decode": "decode",
                "playback": "play",
            }
            for case in saved["cases"]:
                if case["variant"] not in stages:
                    assert case["status"] == "blocked"
                    continue
                assert case["assessment"] == "pass" and case["cleanup_verified"], case
                proof = case["measurements"]["B"]
                stage = stages[case["variant"]]
                assert proof["target_stage"] == stage
                assert proof["target_sample_sequences"] and proof["observed_idle_us"] >= 800000
                metrics = proof["target_stage_memory"]
                assert metrics["sample_count"] == len(proof["target_sample_sequences"])
                assert metrics["baseline_sample_sequence"] < proof["target_sample_sequences"][0]
                assert metrics["internal"]["sampled_min_free_bytes"] >= 0
                actual = host.audio.get(case["audio_operation_id"])
                assert actual["sample_count"] == 24000 and actual["status"] == "completed"
                assert (
                    proof["target_workload_id"] == actual["workload_command_ids"][f"audio.{stage}"]
                )
                evidence = host.observations.get(proof["evidence_id"])
                assert any(
                    event["event_seq"] in proof["target_sample_sequences"]
                    and event["data"]["stage"] == stage
                    and event["data"]["workload_id"] == proof["target_workload_id"]
                    for event in evidence["evidence"]["memory"]["events"]
                )
            assert (await node.request("artifact.list"))["artifacts"] == preexisting
            assert not (await node.request("memory.status"))["active"]
            assert not saved["hardware_validated"]
        finally:
            await host.close()

    asyncio.run(scenario())


def test_cancelling_memory_capture_releases_audio_and_observer(tmp_path, native_library):
    async def scenario():
        host = Host(tmp_path)
        node = host.physical["A"]
        peer = AudioSerial(native_library)
        peer.audio.hold = True
        node.opener = lambda _: peer
        try:
            await node.connect("isolated-audio-memory-cancel")
            spec = MatrixRequest(catalog_id="MEM-01", groups=["C3"], roles=["A"], repetitions=1)
            opened = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(6):
                while not node.active_operation:
                    await asyncio.sleep(0.01)
            await host.stop()
            saved = host.procedures.get(opened["id"])
            assert saved["status"] == "cancelled", saved
            case = saved["cases"][0]
            assert case["variant"] == "capture" and case["cleanup_verified"]
            assert not host.audio.busy and not host.busy
            assert not (await node.request("memory.status"))["active"]
            assert (await node.request("artifact.list"))["artifacts"] == []
        finally:
            await host.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("speaker_wired", [True, False])
def test_paired_voice_memory_measures_reassembly_separately_from_playback(
    tmp_path, native_library, monkeypatch, speaker_wired
):
    monkeypatch.setitem(memory_matrix.GROUPS["MEM-01"], "C3", ("reassembly", "integrated_voice"))

    async def scenario():
        host = Host(tmp_path)
        pair = AudioPair(host, native_library, missing_playback=None if speaker_wired else "B")
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            spec = MatrixRequest(
                catalog_id="MEM-01",
                groups=["C3"],
                directions=["A_TO_B"],
                repetitions=1,
                memory_window_ms=1000,
            )
            plan = host.procedures.matrix_preview(spec, host.radio, host.voice)
            assert plan["ready_case_count"] == (2 if speaker_wired else 1)
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(40):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert saved["status"] == "completed" and not saved["hardware_validated"], saved
            transfer, integrated = saved["cases"]
            assert transfer["assessment"] == "pass" and transfer["cleanup_verified"], transfer
            case = host.voice.get(transfer["voice_run_id"])
            assert case["delivery_verified"] and case["workload"] == "encoded_reassembly"
            assert not case["playback_completed"] and "decode" not in case["jobs"]
            assert transfer["measurements"]["B"]["reassembly_sample_sequences"]
            assert transfer["measurements"]["B"]["reassembly_memory"]["internal"][
                "baseline_free_bytes"
            ]
            if speaker_wired:
                assert integrated["assessment"] == "pass" and integrated["cleanup_verified"], (
                    integrated
                )
                case = host.voice.get(integrated["voice_run_id"])
                assert case["playback_completed"] and case["workload"] == "voice_playback"
                source = integrated["measurements"]["A"]["audio_stage_samples"]
                receiver = integrated["measurements"]["B"]["audio_stage_samples"]
                assert (
                    source["capture"]
                    and source["encode"]
                    and receiver["decode"]
                    and receiver["play"]
                )
            else:
                assert integrated["status"] == "blocked"
                assert any("play" in blocker for blocker in integrated["blockers"])
            for role in "AB":
                assert not (await host.physical[role].request("memory.status"))["active"]
                assert (await host.physical[role].request("artifact.list"))["artifacts"] == []
        finally:
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            await host.close()

    asyncio.run(scenario())
