"""Complete Codec 2 artifacts decode through the actual portable node interface."""

import asyncio
import hashlib
import struct
import subprocess
from uuid import uuid4

import pytest
from native_codec2 import build_codec2
from pydantic import ValidationError
from test_codec_encode_native import encode, readback
from test_node_audio_native import AudioFixture
from test_node_commit_native import upload
from test_node_control_native import NativeNode, NativeSerial
from test_node_control_native import native_library as native_library

from lora_testbed.artifact_contract_v2 import Manifest
from lora_testbed.codec_contract_v2 import DecodeResult
from lora_testbed.nodes import NodeSession


def decode(node, source):
    identifier = str(uuid4())
    accepted = node.request(
        "audio.decode", {"source_artifact_id": source, "artifact_id": identifier}
    )
    assert accepted["ok"], accepted.get("error")
    for _ in range(200):
        node.tick(1000)
        results = [r["data"] for r in node.drain() if r.get("name") == "operation.result"]
        if results:
            return identifier, results[-1]
    raise AssertionError("Finite decoder did not finish")


def test_complete_clip_decodes_to_24000_samples_and_matches_reference_without_playback(
    native_library, tmp_path
):
    audio = AudioFixture()
    node = NativeNode(native_library, audio=audio.port)
    try:
        node.claim()
        pcm = struct.pack("<160h", *[(i % 40 - 20) * 600 for i in range(160)]) * 150
        source = upload(node, pcm, format="pcm_s16le_8000_mono")["artifact_id"]
        assert node.request("artifact.commit", {"artifact_id": source})["ok"]
        encoded_id, encoded_result = encode(node, source)
        assert encoded_result["status"] == "completed"
        encoded = readback(node, encoded_id, 1200)
        output_id, terminal = decode(node, encoded_id)
        assert terminal["status"] == "completed"
        result = terminal["result"]
        assert result["kind"] == "audio_decode" and result["codec"] == "codec2_3200_v1"
        assert result["sample_count"] == result["samples_completed"] == 24000
        assert result["frame_count"] == result["frames_completed"] == 150
        assert result["decoded_bytes"] == 48000 and result["trimmed_samples"] == 0
        assert result["source_sha256"] == hashlib.sha256(encoded).hexdigest()
        memory = result["memory"]
        assert memory["scope"] == "platform_heap_snapshots_not_peak"
        assert set(memory) == {"scope", "before", "ready", "after"}
        assert (
            memory["ready"]["internal"]["free_bytes"] < memory["before"]["internal"]["free_bytes"]
        )
        assert memory["after"]["internal"]["free_bytes"] > memory["ready"]["internal"]["free_bytes"]
        manifest = Manifest.model_validate(result["artifact"])
        assert manifest.format == "pcm_s16le_8000_mono" and manifest.codec is None
        assert manifest.source_artifact_id == encoded_id and manifest.artifact_id == output_id
        decoded = readback(node, output_id, 48000)
        assert len(decoded) == 48000
        assert hashlib.sha256(decoded).hexdigest() == manifest.sha256
        reference, oracle = tmp_path / "clip.codec2", tmp_path / "decoded.pcm"
        reference.write_bytes(encoded)
        subprocess.run(
            [
                str(build_codec2().parent / "codec2_probe"),
                "decode",
                str(reference),
                str(oracle),
                "24000",
            ],
            check=True,
            capture_output=True,
            timeout=10,
        )
        assert decoded == oracle.read_bytes()
        assert audio.starts == 0
    finally:
        node.close()


def encoded_source(node, samples=24000):
    source = upload(node, b"\x00\x10" * samples, format="pcm_s16le_8000_mono")["artifact_id"]
    assert node.request("artifact.commit", {"artifact_id": source})["ok"]
    identifier, terminal = encode(node, source)
    assert terminal["status"] == "completed"
    assert node.request("artifact.delete", {"artifact_id": source})["ok"]
    return identifier, terminal["result"]["artifact"]


@pytest.mark.parametrize("samples", [1, 159, 160, 161, 23999])
def test_partial_final_frame_is_trimmed_and_repeated_decoding_starts_fresh(native_library, samples):
    node = NativeNode(native_library)
    try:
        node.claim()
        source, _ = encoded_source(node, samples)
        outputs = []
        for _ in range(2):
            identifier, terminal = decode(node, source)
            assert terminal["status"] == "completed"
            result = DecodeResult.model_validate(terminal["result"])
            assert result.sample_count == samples and result.decoded_bytes == samples * 2
            assert result.trimmed_samples == (160 - samples % 160) % 160
            data = readback(node, identifier, samples * 2)
            assert len(data) == samples * 2
            assert hashlib.sha256(data).hexdigest() == result.artifact.sha256
            outputs.append(data)
            assert node.request("artifact.delete", {"artifact_id": identifier})["ok"]
        assert outputs[0] == outputs[1]
    finally:
        node.close()


@pytest.mark.parametrize("reason", ["operator", "lease", "disconnect", "deadline"])
def test_interrupted_decode_discards_partial_pcm_releases_source_and_recovers(
    native_library, reason
):
    node = NativeNode(native_library)
    try:
        node.claim()
        source, _ = encoded_source(node)
        accepted = node.request(
            "audio.decode", {"source_artifact_id": source, "artifact_id": str(uuid4())}
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
        elif reason == "lease":
            node.tick(5000000)
        elif reason == "disconnect":
            native_library.node_control_link(node.node, False)
            native_library.node_control_link(node.node, True)
        else:
            for _ in range(8):
                node.tick(4000000)
                observed.extend(node.send(node.command("control.keepalive")))
        observed.extend(node.drain())
        events = [r["data"] for r in observed if r.get("name") == "operation.result"]
        if reason != "disconnect":
            assert len(events) == 1
            assert events[0]["status"] == ("failed" if reason == "deadline" else "cancelled")
            result = DecodeResult.model_validate(events[0]["result"])
            assert 0 < result.frames_completed < 150 and result.artifact is None
            assert (
                result.memory.after.internal.free_bytes == result.memory.before.internal.free_bytes
            )
        if reason in ("lease", "disconnect"):
            node.claim()
        listed = node.request("artifact.list")["result"]["artifacts"]
        assert len(listed) == 1 and listed[0]["artifact_id"] == source and not listed[0]["in_use"]
        assert len(node.allocations) == 1
        assert decode(node, source)[1]["status"] == "completed"
    finally:
        node.close()


class FailingDecoderNode(NativeNode):
    fail_output = fail_finalize = False

    def allocate(self, context, length):
        if self.fail_output and length == 48000:
            return None
        return super().allocate(context, length)

    def hash(self, context, source, length, target):
        if self.fail_finalize and length == 48000:
            return False
        return NativeNode.hash(context, source, length, target)


@pytest.mark.parametrize("failure", ["worker", "output", "final_hash"])
def test_decode_resource_failure_never_publishes_pcm_and_next_clip_succeeds(
    native_library, failure
):
    node = FailingDecoderNode(native_library)
    try:
        node.claim()
        source, _ = encoded_source(node)
        node.allocation_fails = failure == "worker"
        node.fail_output = failure == "output"
        node.fail_finalize = failure == "final_hash"
        if failure == "final_hash":
            _, terminal = decode(node, source)
            assert terminal["status"] == "failed" and terminal["error"]["code"] == "INTERNAL_ERROR"
            result = DecodeResult.model_validate(terminal["result"])
            assert result.frames_completed == 150 and result.artifact is None
        else:
            reply = node.request(
                "audio.decode", {"source_artifact_id": source, "artifact_id": str(uuid4())}
            )
            assert reply["error"]["code"] == "ALLOCATION_FAILED"
        node.allocation_fails = node.fail_output = node.fail_finalize = False
        listed = node.request("artifact.list")["result"]["artifacts"]
        assert len(listed) == 1 and not listed[0]["in_use"] and len(node.allocations) == 1
        assert decode(node, source)[1]["status"] == "completed"
    finally:
        node.close()


@pytest.mark.parametrize("length", [1, 7, 8, 1199, 1200])
def test_untyped_or_truncated_bytes_are_rejected_before_decode_or_playback(native_library, length):
    audio = AudioFixture()
    node = NativeNode(native_library, audio=audio.port)
    try:
        node.claim()
        source = upload(node, b"\x00" * length)["artifact_id"]
        assert node.request("artifact.commit", {"artifact_id": source})["ok"]
        reply = node.request(
            "audio.decode", {"source_artifact_id": source, "artifact_id": str(uuid4())}
        )
        assert reply["error"]["code"] == "INVALID_ARGUMENT"
        assert len(node.allocations) == 1 and audio.starts == 0
        assert node.request("status.get")["result"]["state"] == "idle"
    finally:
        node.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"length_bytes": 1199},
        {"frame_count": 149},
        {"codec": "codec2_2400"},
        {"sample_count": 23840},
    ],
)
def test_encoded_manifest_rejects_incomplete_or_unsupported_frame_declarations(
    native_library, changes
):
    node = NativeNode(native_library)
    try:
        node.claim()
        _, manifest = encoded_source(node)
        with pytest.raises(ValidationError):
            Manifest.model_validate({**manifest, **changes})
    finally:
        node.close()


def test_host_session_tracks_decode_and_gates_stale_capability_before_writing(native_library):
    serial = NativeSerial(native_library)
    serial.core.claim()
    source, _ = encoded_source(serial.core)
    assert serial.core.request("control.release")["ok"]

    async def scenario():
        session = NodeSession("A", lambda *_: None, opener=lambda _: serial)
        try:
            await session.connect("fixture-only")
            assert "audio.decode" in session.snapshot()["codec_support"]["commands"]
            accepted = await session.request(
                "audio.decode", {"source_artifact_id": source, "artifact_id": str(uuid4())}
            )
            assert session.active_operation["operation_id"] == accepted["operation_id"]
            async with asyncio.timeout(5):
                while not session.operation_results:
                    await asyncio.sleep(0.01)
            terminal = session.operation_results[-1]
            assert (
                terminal["status"] == "completed" and terminal["result"]["kind"] == "audio_decode"
            )
            DecodeResult.model_validate(terminal["result"])
            assert session.active_operation is None and session.framing_errors == 0
            declaration = session.health.capability_availability.resource_limits["codec_io"]
            declaration["schema_sha256"] = "0" * 64
            trace = []
            with pytest.raises(ValueError, match="Exact finite codec"):
                await session.request(
                    "audio.decode",
                    {"source_artifact_id": source, "artifact_id": str(uuid4())},
                    on_record=trace.append,
                )
            assert not trace
        finally:
            await session.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", range(1, 13))
def test_actual_decoder_constructor_failure_retires_context_and_next_decode_succeeds(failure):
    result = subprocess.run(
        [str(build_codec2().parent / "codec2_allocation_probe"), str(failure), "decode"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_decode_duplicate_start_keeps_one_worker_and_cannot_replace_source(native_library):
    node = NativeNode(native_library)
    try:
        node.claim()
        source, _ = encoded_source(node)
        command = node.command(
            "audio.decode", {"source_artifact_id": source, "artifact_id": str(uuid4())}
        )
        first = next(row for row in node.send(command) if row["kind"] == "reply")
        assert first["ok"]
        allocations = set(node.allocations)
        duplicate = next(row for row in node.send(command) if row["kind"] == "reply")
        assert duplicate == first and set(node.allocations) == allocations
        assert node.request("artifact.delete", {"artifact_id": source})["error"]["code"] == "BUSY"
        before = node.request("status.get")["result"]["traffic"]["operation_iterations"]
        after = node.request("status.get")["result"]["traffic"]["operation_iterations"]
        assert after == before + 1
        assert node.request("operation.stop", {"operation_id": first["result"]["operation_id"]})[
            "ok"
        ]
        assert len(node.allocations) == 1
    finally:
        node.close()


def test_interleaved_decoder_contexts_do_not_share_random_phase_state():
    result = subprocess.run(
        [str(build_codec2().parent / "codec2_probe"), "independent-states"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
