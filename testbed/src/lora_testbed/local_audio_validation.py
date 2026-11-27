"""Run fixed local audio negative controls and verify recovery on the same node."""

import asyncio
import base64
import hashlib
import zlib
from time import monotonic_ns
from uuid import uuid4

from .artifact_contract_v2 import ARGUMENTS
from .audio_contract_v2 import MAX_SAMPLES

RECOVERY_SAMPLES = 160


def blockers(voice, role):
    if voice is None:
        return ["Local audio preflight is unavailable"]
    node = voice.nodes[role]
    if not node.connected or not node.health or node.health.state != "idle":
        return [f"Node {role} needs a healthy owned idle connection"]
    reasons = []
    if not set(ARGUMENTS) <= set(node.artifact_availability()["commands"]):
        reasons.append("Exact artifact commands are required for the error controls")
    if not {"audio.capture", "audio.play"} <= set(node.audio_availability()["commands"]):
        reasons.append("Finite capture and playback are required for the recovery controls")
    return reasons


def chunk(identifier, data, offset=0):
    return {
        "artifact_id": identifier,
        "offset": offset,
        "data_b64": base64.b64encode(data).decode("ascii"),
        "crc32": f"{zlib.crc32(data):08x}",
    }


async def case(host, binding, emit):
    adapter, audio = host.adapter, host.audio
    node, role = adapter.current(binding), binding["role"]
    owned = set()
    unexpected_operations = set()
    jobs, refusals = {}, {}
    cancel_latency_ms = None

    async def request(name, args=None):
        return await adapter.request(binding, name, args, on_record=emit)

    async def refused(label, expected, name, args):
        try:
            reply = await request(name, args)
        except ValueError as exc:
            actual = str(exc).split(":", 1)[0]
        else:
            actual = None
            if name == "audio.play" and reply.get("operation_id"):
                unexpected_operations.add(reply["operation_id"])
        record_refusal(label, expected, actual)

    def record_refusal(label, expected, actual):
        refusals[label] = {"expected": expected, "observed": actual}
        emit({"audio_refusal": label, **refusals[label]})
        if actual != expected:
            raise ValueError(f"{label} did not return {expected}")

    async def probe(label, expected, identifier):
        reply = await node.exercise_audio_rejection(label, identifier, emit)
        adapter.current(binding)
        if label == "oversized_capture" and reply.ok and reply.result.get("operation_id"):
            unexpected_operations.add(reply.result["operation_id"])
        record_refusal(label, expected, reply.error.code if not reply.ok else None)

    async def inventory():
        return (await request("artifact.list"))["artifacts"]

    async def operation(label, action, *, cancel=False, **options):
        nonlocal cancel_latency_ms
        started = await audio.start(role, action, **options)
        identifier, task = started["id"], audio.task
        jobs[label] = identifier
        if action == "capture":
            owned.add(started["artifact_id"])
        try:
            emit({"local_audio_jobs": dict(jobs)})
            if cancel:
                async with asyncio.timeout(4):
                    while not task.done() and audio.record and audio.record["operation_id"] is None:
                        await asyncio.sleep(0.005)
                active_id = (audio.record or {}).get("operation_id")
                if not active_id or task.done():
                    raise ValueError("Capture ended before the controlled cancellation")
                requested_at = monotonic_ns()
                await audio.stop(identifier)
                cancel_latency_ms = (monotonic_ns() - requested_at) / 1_000_000
                terminal = next(
                    (
                        event
                        for event in node.operation_results
                        if event["operation_id"] == active_id
                    ),
                    None,
                )
                emit({"cancelled_capture_result": terminal, "cancel_latency_ms": cancel_latency_ms})
                if not terminal or terminal["status"] != "cancelled":
                    raise ValueError("The board did not report an actual cancelled capture")
            else:
                await asyncio.shield(task)
        finally:
            if not task.done():
                await audio.stop(identifier)
        saved = audio.get(identifier)
        if saved["status"] != ("cancelled" if cancel else "completed") or not (
            saved.get("cleanup_details") or {}
        ).get("confirmed"):
            raise ValueError(f"{label} did not finish with confirmed cleanup")
        emit({"audio_job": label, "status": saved["status"], "operation_id": saved["operation_id"]})
        return saved

    async def begin(format_name, digest):
        identifier = str(uuid4())
        owned.add(identifier)
        await request(
            "artifact.begin",
            {
                "artifact_id": identifier,
                "format": format_name,
                "sha256": digest,
                "length_bytes": len(pcm),
                "kind": "source",
            },
        )
        return identifier

    pcm = bytes(RECOVERY_SAMPLES * 2)
    before = await inventory()
    baseline = await request("status.get")
    limits = node.artifact_availability()["limits"]
    reserved = baseline["memory"]["buffers"]["artifacts_reserved"]
    if (
        len(before) >= limits["node_artifact_slots"]
        or reserved + 2 * MAX_SAMPLES > limits["node_total_artifact_bytes"]
        or limits["max_artifact_bytes"] < 2 * MAX_SAMPLES
    ):
        raise ValueError("The negative controls need one free file slot and 48,000 capture bytes")
    clean, cleanup_error = False, None
    try:
        oversized = str(uuid4())
        owned.add(oversized)
        await probe("oversized_capture", "INVALID_ARGUMENT", oversized)
        binary = await begin("known_data", hashlib.sha256(pcm).hexdigest())
        await request("artifact.put", chunk(binary, pcm))
        await request("artifact.commit", {"artifact_id": binary})
        await refused("non_pcm_format", "INVALID_ARGUMENT", "audio.play", {"artifact_id": binary})
        await request("artifact.delete", {"artifact_id": binary})
        invalid = await begin("pcm_s16le_8000_mono", "0" * 64)
        staged = await inventory()
        await refused("uncommitted_pcm", "INVALID_STATE", "audio.play", {"artifact_id": invalid})
        await probe("bad_chunk_crc", "CHECKSUM_MISMATCH", invalid)
        await refused(
            "wrong_chunk_offset", "OFFSET_MISMATCH", "artifact.put", chunk(invalid, pcm[:2], 1)
        )
        if await inventory() != staged:
            raise ValueError("A rejected chunk or playback modified the staged inventory")
        await request("artifact.put", chunk(invalid, pcm))
        await refused(
            "wrong_final_hash", "CHECKSUM_MISMATCH", "artifact.commit", {"artifact_id": invalid}
        )
        await refused("failed_pcm", "INVALID_STATE", "audio.play", {"artifact_id": invalid})
        await request("artifact.delete", {"artifact_id": invalid})
        untouched = await request("status.get")
        if untouched["state"] != "idle" or untouched["operation_id"] is not None:
            raise ValueError("A rejected request started audio work")
        cancelled = await operation(
            "controlled_cancel", "capture", cancel=True, sample_count=MAX_SAMPLES
        )
        if any(row["artifact_id"] == cancelled["artifact_id"] for row in await inventory()):
            raise ValueError("The cancelled capture still occupies a file slot")
        recovered = await operation("recovery_capture", "capture", sample_count=RECOVERY_SAMPLES)
        artifact_id = recovered["artifact_id"]
        await operation("recovery_playback", "play", artifact_id=artifact_id)
        if recovered["clip"]["raw_bytes"] != 2 * RECOVERY_SAMPLES:
            raise ValueError("Recovery capture did not retain the expected PCM bytes")
        audio.wav(recovered["id"])
    finally:
        try:
            if unexpected_operations:
                status = await request("status.get")
                if status["operation_id"] in unexpected_operations:
                    await request("operation.stop", {"operation_id": status["operation_id"]})
            for row in await inventory():
                if row["artifact_id"] in owned:
                    await request("artifact.delete", {"artifact_id": row["artifact_id"]})
            status = await request("status.get")
            clean = (
                (await inventory()) == before
                and status["state"] == "idle"
                and status["operation_id"] is None
                and status["memory"]["buffers"]["artifacts_reserved"]
                == baseline["memory"]["buffers"]["artifacts_reserved"]
            )
        except (OSError, ValueError, TimeoutError) as exc:
            cleanup_error = str(exc)
        emit({"local_audio_cleanup_confirmed": clean, "local_audio_cleanup_error": cleanup_error})
    if not clean:
        raise ValueError("Audio validation could not confirm restored artifact inventory and idle")
    return {
        "refusals": refusals,
        "jobs": jobs,
        "recovery_samples": RECOVERY_SAMPLES,
        "cancelled_artifact_removed": True,
        "cancel_latency_ms": cancel_latency_ms,
        "capture_wav": f"/api/audio/operations/{recovered['id']}/wav",
    }
