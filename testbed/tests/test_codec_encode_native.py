"""Finite committed-PCM encoding through the real portable node control seam."""

import asyncio
import base64
import hashlib
import struct
import subprocess
from uuid import uuid4

import pytest
from native_codec2 import build_codec2
from test_node_commit_native import upload
from test_node_control_native import NativeNode, NativeSerial
from test_node_control_native import native_library as native_library

from lora_testbed.artifact_contract_v2 import Manifest
from lora_testbed.nodes import NodeSession


def encode(node, source):
    destination = str(uuid4())
    accepted = node.request(
        "audio.encode", {"artifact_id": destination, "source_artifact_id": source}
    )
    assert accepted["ok"], accepted.get("error")
    for _ in range(200):
        node.tick(1000)
        terminal = [r["data"] for r in node.drain() if r.get("name") == "operation.result"]
        if terminal:
            return destination, terminal[-1]
    raise AssertionError("Finite codec operation did not finish")


def readback(node, identifier, length):
    data = b""
    while len(data) < length:
        reply = node.request(
            "artifact.get", {"artifact_id": identifier, "offset": len(data), "length_bytes": 1024}
        )
        assert reply["ok"]
        data += base64.b64decode(reply["result"]["data_b64"], validate=True)
    return data


def test_three_second_committed_pcm_encodes_with_fresh_state_and_exact_frame_counts(
    native_library, tmp_path
):
    node = NativeNode(native_library)
    try:
        node.claim()
        pcm = struct.pack("<160h", *[(i % 40 - 20) * 600 for i in range(160)]) * 150
        source = upload(node, pcm, format="pcm_s16le_8000_mono")["artifact_id"]
        assert node.request("artifact.commit", {"artifact_id": source})["ok"]
        reference = tmp_path / "reference.pcm"
        reference.write_bytes(pcm)
        oracle = tmp_path / "reference.codec2"
        subprocess.run(
            [str(build_codec2().parent / "codec2_probe"), str(reference), str(oracle)],
            check=True,
            capture_output=True,
            timeout=10,
        )
        assert oracle.is_file(), "Independent upstream reference did not produce encoded bytes"
        outputs = []
        for _ in range(2):
            identifier, terminal = encode(node, source)
            assert terminal["status"] == "completed"
            result = terminal["result"]
            assert result["input_samples"] == 24000
            assert result["frames_completed"] == result["frame_count"] == 150
            assert result["encoded_bytes"] == 1200
            assert result["source_sha256"] == hashlib.sha256(pcm).hexdigest()
            manifest = Manifest.model_validate(result["artifact"])
            assert manifest.state == "committed" and not manifest.in_use
            assert manifest.format == manifest.codec == "codec2_3200_v1"
            assert manifest.source_artifact_id == source and manifest.sample_count == 24000
            content = readback(node, identifier, 1200)
            assert len(content) == 1200 and len(set(content)) > 1
            assert hashlib.sha256(content).hexdigest() == manifest.sha256
            assert content == oracle.read_bytes()
            outputs.append(content)
        assert outputs[0] == outputs[1]
        assert node.request("artifact.delete", {"artifact_id": source})["ok"]
    finally:
        node.close()


def test_host_session_tracks_negotiated_encoding_and_receives_typed_terminal_result(native_library):
    serial = NativeSerial(native_library)
    serial.core.claim()
    source = upload(serial.core, b"\x00\x08" * 24000, format="pcm_s16le_8000_mono")["artifact_id"]
    assert serial.core.request("artifact.commit", {"artifact_id": source})["ok"]
    assert serial.core.request("control.release")["ok"]

    async def scenario():
        session = NodeSession("A", lambda *_: None, opener=lambda _: serial)
        try:
            await session.connect("fixture-only")
            assert session.snapshot()["codec_support"]["commands"] == [
                "audio.encode",
                "audio.decode",
            ]
            accepted = await session.request(
                "audio.encode", {"source_artifact_id": source, "artifact_id": str(uuid4())}
            )
            assert session.active_operation["operation_id"] == accepted["operation_id"]
            async with asyncio.timeout(5):
                while not session.operation_results:
                    await asyncio.sleep(0.01)
            terminal = session.operation_results[-1]
            assert terminal["operation_id"] == accepted["operation_id"]
            assert terminal["status"] == "completed"
            assert terminal["result"]["frames_completed"] == 150
            assert session.active_operation is None
            assert session.framing_errors == 0
            trace = []
            declaration = session.health.capability_availability.resource_limits["codec_io"]
            current_hash = declaration["schema_sha256"]
            declaration["schema_sha256"] = "0" * 64
            with pytest.raises(ValueError, match="Exact finite codec"):
                await session.request(
                    "audio.encode",
                    {"source_artifact_id": source, "artifact_id": str(uuid4())},
                    on_record=trace.append,
                )
            assert not trace and session.active_operation is None
            declaration["schema_sha256"] = current_hash
            last_health = session.last_health
            session.last_health -= 4
            with pytest.raises(ValueError, match="fresh codec health"):
                await session.request(
                    "audio.encode",
                    {"source_artifact_id": source, "artifact_id": str(uuid4())},
                    on_record=trace.append,
                )
            session.last_health = last_health
            assert not trace
        finally:
            await session.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("samples", [1, 159, 160, 161, 23999])
def test_final_frame_padding_preserves_original_count_and_matches_upstream(
    native_library, tmp_path, samples
):
    node = NativeNode(native_library)
    try:
        node.claim()
        pcm = b"\x00\x10" * samples
        source = upload(node, pcm, format="pcm_s16le_8000_mono")["artifact_id"]
        assert node.request("artifact.commit", {"artifact_id": source})["ok"]
        identifier, terminal = encode(node, source)
        assert terminal["status"] == "completed"
        result = terminal["result"]
        expected_frames = (samples + 159) // 160
        assert result["input_samples"] == samples
        assert result["frame_count"] == result["frames_completed"] == expected_frames
        assert result["padded_samples"] == expected_frames * 160 - samples
        reference, oracle = tmp_path / "source.pcm", tmp_path / "output.codec2"
        reference.write_bytes(pcm)
        subprocess.run(
            [str(build_codec2().parent / "codec2_probe"), str(reference), str(oracle)],
            check=True,
            capture_output=True,
            timeout=10,
        )
        assert readback(node, identifier, expected_frames * 8) == oracle.read_bytes()
    finally:
        node.close()


@pytest.mark.parametrize("invalid", ["unfinished", "checksum_failed", "wrong_format", "same_id"])
def test_invalid_source_rejects_before_work_and_next_clip_can_encode(native_library, invalid):
    node = NativeNode(native_library)
    try:
        node.claim()
        source = upload(
            node,
            b"\x00\x10" * 160,
            format="known_data" if invalid == "wrong_format" else "pcm_s16le_8000_mono",
            **({"sha256": "0" * 64} if invalid == "checksum_failed" else {}),
        )["artifact_id"]
        if invalid != "unfinished":
            committed = node.request("artifact.commit", {"artifact_id": source})
            assert committed["ok"] == (invalid != "checksum_failed")
        before = set(node.allocations)
        destination = source if invalid == "same_id" else str(uuid4())
        reply = node.request(
            "audio.encode", {"source_artifact_id": source, "artifact_id": destination}
        )
        assert not reply["ok"]
        assert reply["error"]["code"] in ("INVALID_STATE", "INVALID_ARGUMENT")
        assert set(node.allocations) == before
        assert node.request("status.get")["result"]["state"] == "idle"
        assert node.request("artifact.delete", {"artifact_id": source})["ok"]
        source = upload(node, b"\x00\x10" * 160, format="pcm_s16le_8000_mono")["artifact_id"]
        assert node.request("artifact.commit", {"artifact_id": source})["ok"]
        assert encode(node, source)[1]["status"] == "completed"
    finally:
        node.close()


@pytest.mark.parametrize("reason", ["operator", "lease", "disconnect", "deadline"])
def test_cancel_or_loss_discards_partial_output_and_releases_source(native_library, reason):
    node = NativeNode(native_library)
    try:
        node.claim()
        source = upload(node, b"\x00\x10" * 24000, format="pcm_s16le_8000_mono")["artifact_id"]
        assert node.request("artifact.commit", {"artifact_id": source})["ok"]
        destination = str(uuid4())
        accepted = node.request(
            "audio.encode", {"source_artifact_id": source, "artifact_id": destination}
        )
        assert accepted["ok"]
        for _ in range(10):
            node.tick(1000)
        node.drain()
        observed = []
        if reason == "operator":
            observed = node.send(
                node.command("operation.stop", {"operation_id": accepted["result"]["operation_id"]})
            )
            assert next(r for r in observed if r["kind"] == "reply")["ok"]
        elif reason == "lease":
            node.tick(5000000)
        elif reason == "disconnect":
            native_library.node_control_link(node.node, False)
            native_library.node_control_link(node.node, True)
        else:
            for _ in range(8):
                node.tick(4000000)
                rows = node.send(node.command("control.keepalive"))
                assert next(r for r in rows if r["kind"] == "reply")["ok"]
                observed.extend(rows)
        observed.extend(node.drain())
        events = [r["data"] for r in observed if r.get("name") == "operation.result"]
        if reason != "disconnect":
            assert len(events) == 1
            assert events[0]["status"] == ("failed" if reason == "deadline" else "cancelled")
            assert 0 < events[0]["result"]["frames_completed"] < 150
            assert events[0]["result"]["artifact"] is None
        if reason in ("lease", "disconnect"):
            node.claim()
        listed = node.request("artifact.list")["result"]["artifacts"]
        assert [m["artifact_id"] for m in listed] == [source]
        assert not listed[0]["in_use"]
        assert len(node.allocations) == 1
        assert encode(node, source)[1]["status"] == "completed"
    finally:
        node.close()


class FailingEncoderNode(NativeNode):
    fail_output = False

    def allocate(self, context, length):
        if self.fail_output and length == 1200:
            return None
        return super().allocate(context, length)


@pytest.mark.parametrize("failure", ["worker", "output"])
def test_encoder_allocation_failure_unwinds_before_acceptance(native_library, failure):
    node = FailingEncoderNode(native_library)
    try:
        node.claim()
        source = upload(node, b"\x00\x10" * 24000, format="pcm_s16le_8000_mono")["artifact_id"]
        assert node.request("artifact.commit", {"artifact_id": source})["ok"]
        node.allocation_fails = failure == "worker"
        node.fail_output = failure == "output"
        reply = node.request(
            "audio.encode", {"source_artifact_id": source, "artifact_id": str(uuid4())}
        )
        assert reply["error"]["code"] == "ALLOCATION_FAILED"
        node.allocation_fails = node.fail_output = False
        assert len(node.allocations) == 1
        listed = node.request("artifact.list")["result"]["artifacts"]
        assert len(listed) == 1 and not listed[0]["in_use"]
        assert encode(node, source)[1]["status"] == "completed"
    finally:
        node.close()


def test_encoder_advances_one_frame_per_step_and_duplicate_start_keeps_one_owner(native_library):
    node = NativeNode(native_library)
    try:
        node.claim()
        source = upload(node, b"\x00\x10" * 24000, format="pcm_s16le_8000_mono")["artifact_id"]
        assert node.request("artifact.commit", {"artifact_id": source})["ok"]
        command = node.command(
            "audio.encode", {"source_artifact_id": source, "artifact_id": str(uuid4())}
        )
        first = next(r for r in node.send(command) if r["kind"] == "reply")
        assert first["ok"]
        allocations = set(node.allocations)
        duplicate = next(r for r in node.send(command) if r["kind"] == "reply")
        assert first == duplicate and set(node.allocations) == allocations
        before = node.request("status.get")["result"]["traffic"]["operation_iterations"]
        after = node.request("status.get")["result"]["traffic"]["operation_iterations"]
        assert after == before + 1
        assert node.request("operation.stop", {"operation_id": first["result"]["operation_id"]})[
            "ok"
        ]
        assert len(node.allocations) == 1
    finally:
        node.close()


def test_all_peripherals_keep_hello_and_health_within_the_bounded_serial_record(native_library):
    from test_node_audio_native import AudioFixture

    audio = AudioFixture()
    node = NativeNode(native_library, audio=audio.port, radio=native_library.native_radio_create())
    try:
        identity = node.request("hello")["result"]
        assert identity["capabilities"]["codec2_3200"]
        assert identity["capabilities"]["audio_capture"] and identity["capabilities"]["radio"]
        node.claim()
        assert node.request("config.set", {"radio": {"spreading_factor": 12}, "link": {}})["ok"]
        rejected = node.request("run.start", {"config_revision": 1}, run_id=str(uuid4()))
        assert rejected["error"]["code"] == "INVALID_STATE"
        assert node.request("status.get")["ok"]
        node.tick(1000000)
        assert any(r.get("name") == "health" for r in node.drain())
    finally:
        node.close()


class FinalizeFailureNode(NativeNode):
    fail_finalize = False

    def hash(self, context, source, length, target):
        if self.fail_finalize and length == 1200:
            return False
        return NativeNode.hash(context, source, length, target)


def test_final_hash_failure_never_publishes_output_and_fresh_encode_recovers(native_library):
    node = FinalizeFailureNode(native_library)
    try:
        node.claim()
        source = upload(node, b"\x00\x10" * 24000, format="pcm_s16le_8000_mono")["artifact_id"]
        assert node.request("artifact.commit", {"artifact_id": source})["ok"]
        node.fail_finalize = True
        _, failed = encode(node, source)
        assert failed["status"] == "failed" and failed["error"]["code"] == "INTERNAL_ERROR"
        assert failed["result"]["frames_completed"] == 150
        assert failed["result"]["artifact"] is None
        node.fail_finalize = False
        listed = node.request("artifact.list")["result"]["artifacts"]
        assert len(listed) == 1 and not listed[0]["in_use"]
        assert len(node.allocations) == 1
        assert encode(node, source)[1]["status"] == "completed"
    finally:
        node.close()


def test_failed_acceptance_allocation_releases_private_codec_and_output(native_library):
    for position in range(100):
        node = NativeNode(native_library)
        try:
            node.claim()
            source = upload(node, b"\x00\x10" * 160, format="pcm_s16le_8000_mono")["artifact_id"]
            assert node.request("artifact.commit", {"artifact_id": source})["ok"]
            command = node.command(
                "audio.encode", {"source_artifact_id": source, "artifact_id": str(uuid4())}
            )
            native_library.native_allocator_fail_after(position)
            rows = node.send(command)
            native_library.native_allocator_fail_after(-1)
            accepted = next((r for r in rows if r["kind"] == "reply" and r["ok"]), None)
            if accepted:
                assert node.request(
                    "operation.stop", {"operation_id": accepted["result"]["operation_id"]}
                )["ok"]
            assert node.request("status.get")["result"]["state"] == "idle"
            listed = node.request("artifact.list")["result"]["artifacts"]
            assert len(listed) == 1 and not listed[0]["in_use"], position
            assert len(node.allocations) == 1, position
        finally:
            native_library.native_allocator_fail_after(-1)
            node.close()
