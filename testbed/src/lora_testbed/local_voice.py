"""Exercise reference PCM and review retained attended one-node audio runs."""

import asyncio
import hashlib
from itertools import product

from .artifact_contract_v2 import ARGUMENTS
from .voice_matrix import EXPECTED_ENCODED_BYTES, EXPECTED_SAMPLES
from .voice_runs import VoiceRunRequest

GROUPS = {
    "VOICE-01": {
        "C1": "capture_and_playback",
        "C2": "capture_codec_and_playback",
        "C3": "reference_codec_and_playback",
        "C4": "invalid_artifact_or_cancel",
    }
}


def cases(request, groups):
    saved = {
        (item.group, item.role, item.utterance, item.repetition): item
        for item in request.local_voice_evidence or ()
    }
    for group in groups:
        references = request.voice_reference_ids if group == "C3" else None
        clips = references or [None] * 3
        for (ordinal, reference), role, repetition in product(
            enumerate(clips, start=1), request.roles, range(1, request.repetitions + 1)
        ):
            yield {
                "group": group,
                "variant": f"{GROUPS['VOICE-01'][group]}_{ordinal}",
                "repetition": repetition,
                "driver": {
                    "C1": "local_voice_capture_review",
                    "C2": "local_voice_capture_review",
                    "C3": "local_voice_reference",
                    "C4": "local_audio_negative",
                }[group],
                "role": role,
                "reference_id": reference,
                "sample_count": EXPECTED_SAMPLES,
                **(
                    {"capture_evidence": entry.model_dump()}
                    if (entry := saved.get((group, role, ordinal, repetition)))
                    else {}
                ),
            }


def request_for(case):
    return VoiceRunRequest(source="reference", reference_id=case["reference_id"])


def blockers(voice, case):
    if case["driver"] == "local_voice_capture_review":
        reference = case.get("capture_evidence")
        if not reference:
            return ["Attach the saved microphone capture and local playback operations"]
        if voice is None:
            return ["Saved local audio evidence is unavailable"]
        try:
            for stage in ("capture", "codec", "playback"):
                if identifier := reference.get(stage):
                    if voice.audio.get(identifier)["status"] != "completed":
                        return [f"The saved {stage} operation is incomplete"]
        except ValueError as exc:
            return [str(exc)]
        return []
    if not case["reference_id"]:
        return ["Select a saved three-second reference"]
    if voice is None:
        return ["Local audio preflight is unavailable"]
    node = voice.nodes[case["role"]]
    if not node.connected or not node.health or node.health.state != "idle":
        return [f"Node {case['role']} needs a healthy owned idle connection"]
    reasons = []
    if not set(ARGUMENTS) <= set(node.artifact_availability()["commands"]):
        reasons.append("Exact artifact transfer and evidence readback are required")
    if not {"audio.encode", "audio.decode"} <= set(node.codec_availability()["commands"]):
        reasons.append("Exact Codec 2 encode/decode capabilities are required")
    if "audio.play" not in node.audio_availability()["commands"]:
        reasons.append("Local PCM playback is unavailable")
    try:
        reference, _ = voice.reference(request_for(case))
        if reference["sample_count"] != EXPECTED_SAMPLES:
            reasons.append("The selected reference must contain exactly 24,000 samples")
    except ValueError as exc:
        reasons.append(str(exc))
    return reasons


def review_capture(audio, case):
    reference = case["capture_evidence"]
    capture, playback = (audio.get(reference[stage]) for stage in ("capture", "playback"))
    codec = audio.get(reference["codec"]) if reference["codec"] else None
    jobs = [capture, codec, playback] if codec else [capture, playback]
    if (
        [job["action"] for job in jobs]
        != (["capture", "codec", "play"] if codec else ["capture", "play"])
        or any(
            job["role"] != case["role"]
            or job["status"] != "completed"
            or job["physical_binding"] != capture["physical_binding"]
            or job["sample_count"] != EXPECTED_SAMPLES
            or not (job.get("cleanup_details") or {}).get("confirmed")
            for job in jobs
        )
        or any(a["finished_at"] > b["created_at"] for a, b in zip(jobs, jobs[1:], strict=False))
    ):
        raise ValueError("The stages must be ordered completed audio operations on the same node")
    clip = capture.get("clip") or {}
    captured_manifest = (capture["node_result"]["result"] or {}).get("artifact") or {}
    if (
        clip.get("raw_bytes") != EXPECTED_SAMPLES * 2
        or clip.get("pcm_sha256") != captured_manifest.get("sha256")
        or clip.get("sample_rate_hz") != 8000
    ):
        raise ValueError("The original microphone clip did not verify")
    audio.wav(capture["id"])
    expected_playback = captured_manifest
    manifests = None
    if codec:
        manifests = {stage: entry["manifest"] for stage, entry in codec["codec_artifacts"].items()}
        if (
            not codec["verified_roundtrip"]
            or manifests.get("source") != captured_manifest
            or (manifests.get("encoded") or {}).get("length_bytes") != EXPECTED_ENCODED_BYTES
            or (manifests.get("decoded") or {}).get("length_bytes") != EXPECTED_SAMPLES * 2
            or any(
                (codec["codec_operations"][action].get("result") or {}).get("frames_completed")
                != 150
                for action in ("encode", "decode")
            )
        ):
            raise ValueError(
                "The codec result does not match the captured PCM or 150 expected frames"
            )
        for stage in ("source", "encoded", "decoded"):
            audio.codec_content(codec["id"], stage)
        expected_playback = manifests["decoded"]
    if playback["source_manifest"] != expected_playback:
        raise ValueError("The playback source does not match the selected saved PCM")
    heard = playback["listening"]["heard"]
    if clip["near_silence"]:
        outcome, reason = "inconclusive", "The microphone recording is near silence"
    elif heard == "heard":
        outcome, reason = "pass", None
    elif heard == "not_heard":
        outcome, reason = "fail", "The operator heard no playback"
    else:
        outcome, reason = "inconclusive", "Record the operator listening result for playback"
    return {
        "outcome": outcome,
        "reason": reason,
        "jobs": {job["action"]: job["id"] for job in jobs},
        "physical_binding": capture["physical_binding"],
        "capture_configuration": capture["configuration"],
        "clip": {key: value for key, value in clip.items() if key != "waveform"},
        "capture_wav": f"/api/audio/operations/{capture['id']}/wav",
        "decoded_wav": f"/api/audio/operations/{codec['id']}/artifacts/decoded?as_wav=true"
        if codec
        else None,
        "encoded_artifact": f"/api/audio/operations/{codec['id']}/artifacts/encoded"
        if codec
        else None,
        "codec_manifests": manifests,
        "codec_configuration": codec["codec_configuration"] if codec else None,
        "listening": playback["listening"],
    }


async def execute(host, case, binding, emit):
    adapter = host.adapter
    role = case["role"]
    adapter.current(binding)
    reference, pcm = host.voice.reference(request_for(case))
    if reference["sample_count"] != EXPECTED_SAMPLES:
        raise ValueError("Reference length changed")
    before = (await adapter.request(binding, "artifact.list"))["artifacts"]
    previous_ids = {entry["artifact_id"] for entry in before}
    owned = set()
    jobs = {}

    async def settle(stage, service, started, stop):
        identifier = started["id"]
        task = service.task
        try:
            jobs[stage] = identifier
            emit({"local_audio_jobs": dict(jobs)})
            await asyncio.shield(task)
        finally:
            if not task.done():
                await stop(identifier)
            result = service.get(identifier)
            if stage == "source_upload":
                owned.add(result["artifact_id"])
            owned.update(result.get("planned_output_ids", {}).values())
            emit(
                {
                    "local_audio_stage": stage,
                    "status": result["status"],
                    "job_id": identifier,
                    "error": result.get("error"),
                }
            )
        if result["status"] != "completed":
            raise ValueError(f"{stage} did not complete: {result.get('error')}")
        return result

    try:
        started = await host.artifacts.start_upload(
            role, pcm, format="pcm_s16le_8000_mono", name=reference["name"]
        )
        uploaded = await settle("source_upload", host.artifacts, started, host.artifacts.cancel)
        started = await host.audio.start(role, "codec", artifact_id=uploaded["artifact_id"])
        codec = await settle("codec", host.audio, started, host.audio.stop)
        files = codec["codec_artifacts"]
        if not (
            codec["verified_roundtrip"]
            and files["source"]["manifest"]["sha256"] == hashlib.sha256(pcm).hexdigest()
            and files["encoded"]["manifest"]["length_bytes"] == EXPECTED_ENCODED_BYTES
            and files["decoded"]["manifest"]["length_bytes"] == len(pcm)
        ):
            raise ValueError("The reference codec artifacts did not verify")
        started = await host.audio.start(
            role, "play", artifact_id=files["decoded"]["manifest"]["artifact_id"]
        )
        played = await settle("playback", host.audio, started, host.audio.stop)
        host.audio.link_playback(codec["id"], played["id"])
    finally:
        clean = False
        error = None
        try:
            current = (await adapter.request(binding, "artifact.list"))["artifacts"]
            for manifest in current:
                identifier = manifest["artifact_id"]
                if identifier in owned and identifier not in previous_ids:
                    await adapter.request(binding, "artifact.delete", {"artifact_id": identifier})
            status = await adapter.request(binding, "status.get")
            after = (await adapter.request(binding, "artifact.list"))["artifacts"]
            clean = status["state"] == "idle" and after == before
        except Exception as exc:
            error = str(exc) or type(exc).__name__
        emit({"local_audio_cleanup_confirmed": clean, "local_audio_cleanup_error": error})
    if not clean:
        raise ValueError("Local audio cleanup is unconfirmed")
    return {
        "jobs": jobs,
        "reference_id": reference["id"],
        "codec_manifests": {stage: value["manifest"] for stage, value in files.items()},
        "physical_listening": "pending",
        "codec_inspection": f"/api/audio/operations/{codec['id']}",
    }
