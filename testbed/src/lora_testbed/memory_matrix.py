"""Case plans and named observer evidence for idle and known-data memory usage."""

import asyncio
import hashlib
from uuid import uuid4

from . import artifact_contract_v2, content_series, memory_observation_v2
from .experiments_v2 import Link
from .fault_protocol_v2 import Injection
from .radio_runs import LabRadioRunRequest, PreparedCancellationCheck, RadioRunRequest
from .voice_runs import VoiceReassemblyRequest, VoiceRunRequest

GROUPS = {
    "MEM-01": {
        "C1": ("idle_baseline",),
        "C2": ("known_data",),
        "C3": ("capture", "encode", "reassembly", "decode", "playback", "integrated_voice"),
        "C4": ("allocation_above_limit",),
        "C5": ("cancel_and_recover", "failure_and_recover"),
    },
}
LOCAL_AUDIO = {"capture": "capture", "encode": "codec", "decode": "codec", "playback": "play"}
AUDIO_SAMPLES = 24000
PCM_FIXTURE = bytes(2 * AUDIO_SAMPLES)
PAIRED_AUDIO = frozenset(("reassembly", "integrated_voice"))
ENCODED_BYTES = 1200

FIXED_SIZES = (64, 160, 321, 1200, 48000)
RECOVERY_BAND_BYTES = {"internal": 8192, "psram": 4096}


def cases(request, groups, limit):
    for group in groups:
        for variant in GROUPS["MEM-01"][group]:
            paired = group == "C3" and variant in PAIRED_AUDIO
            roles = request.directions if group in ("C2", "C4", "C5") or paired else request.roles
            for role in roles:
                sizes = (None,)
                if group == "C2":
                    sizes = tuple(dict.fromkeys((*FIXED_SIZES, limit)))
                    if request.subset_sizes is not None:
                        sizes = tuple(n for n in sizes if n in request.subset_sizes)
                if group == "C4":
                    sizes = (limit + 1,)
                for size in sizes:
                    for repetition in range(1, request.repetitions + 1):
                        case = {
                            "group": group,
                            "variant": f"bytes_{size}" if group == "C2" else variant,
                            "repetition": repetition,
                            "driver": (
                                "memory_audio_local"
                                if group == "C3" and variant in LOCAL_AUDIO
                                else "memory_audio_pair"
                                if paired
                                else {
                                    "C1": "memory_idle",
                                    "C2": "memory_link",
                                    "C4": "resource_refusal",
                                    "C5": "memory_recovery",
                                }[group]
                            ),
                            "role": role,
                            "observation_ms": request.memory_window_ms,
                        }
                        if paired or group == "C5":
                            case["direction"] = role
                        if group == "C5":
                            case["recovery_band_bytes"] = RECOVERY_BAND_BYTES.copy()
                        if size is not None:
                            case.update(
                                message_bytes=size,
                                direction=role,
                                security="none",
                                planning_message_limit=limit,
                            )
                        yield case


def role_blockers(node, role):
    state = node.snapshot()
    if (
        state["connection_state"] != "connected"
        or not node.health
        or node.health.node_role != role
        or node.health.state != "idle"
    ):
        return [f"Node {role} needs a healthy owned idle connection"]
    if not state["memory_support"]["commands"]:
        return [f"Node {role} lacks the exact memory observation profile"]
    return []


def link_request(spec, case):
    return content_series.run_request(spec, case, 0)


def recovery_request(case):
    request = RadioRunRequest(direction=case["direction"], message_bytes=1200)
    if case["variant"] == "cancel_and_recover":
        return PreparedCancellationCheck(**request.model_dump())
    return LabRadioRunRequest(
        **request.model_dump(exclude={"link", "security"}),
        security="aes128_gcm",
        link=Link(ack_mode="stop_wait", max_retries=0),
        injection=Injection(
            injection_id=str(uuid4()),
            stage="rx_before_reassembly",
            action="drop",
            message_id=1,
            fragment_index=3,
            attempt_index=1,
            byte_offset=None,
            xor_mask=None,
            block_size=None,
        ),
        exhaust_attempts=True,
    )


def recovery_summary(record, duration_ms, linked_run_id, band, cleanup_uptime_us):
    report = summary(record, duration_ms, linked_run_id)
    events = [row["data"] for row in record["evidence"]["memory"]["events"]]
    tracked = [index for index, event in enumerate(events) if event["workload_id"] == linked_run_id]
    if not report["passed"] or not tracked or tracked[0] == 0 or cleanup_uptime_us is None:
        return {**report, "recovery": None}

    baseline = events[0]  # The observation starts before an RF session exists.
    idle = [event for event in events[tracked[-1] + 1 :] if event["taken_us"] >= cleanup_uptime_us]
    if not idle or idle[-1]["finished_us"] - idle[0]["taken_us"] < (
        duration_ms * 1000 - 2 * memory_observation_v2.PERIOD_US
    ):
        return {**report, "recovery": None}
    regions = {}
    within_band = True
    for region, tolerance in band.items():
        prior = baseline["memory"][region]
        after = [event["memory"][region] for event in idle]
        if prior is None and all(heap is None for heap in after):
            regions[region] = None
            continue
        if prior is None or any(heap is None for heap in after):
            return {**report, "recovery": None}
        fields = ("free_bytes", "largest_free_bytes")
        floor = {key: max(0, prior[key] - tolerance) for key in fields}
        observed = {key: min(heap[key] for heap in after) for key in fields}
        regions[region] = {"baseline": prior, "lower_bounds": floor, "observed_min": observed}
        within_band &= all(observed[key] >= floor[key] for key in fields)

    def inventory(event):
        return {
            (item["name"], item["region"], item["requested_bytes"])
            for item in event["known_buffers"]
        }

    buffers_restored = all(inventory(event) == inventory(baseline) for event in idle)
    failures_unchanged = all(
        event["memory"]["allocation_failures"] == baseline["memory"]["allocation_failures"]
        for event in idle
    )
    return {
        **report,
        "recovery": {
            "baseline_sample_index": baseline["sample_index"],
            "cleanup_confirmed_uptime_us": cleanup_uptime_us,
            "first_idle_sample_index": idle[0]["sample_index"],
            "last_idle_sample_index": idle[-1]["sample_index"],
            "declared_tolerance_bytes": band,
            "regions": regions,
            "heap_within_band": within_band,
            "named_buffers_restored": buffers_restored,
            "allocation_failures_unchanged": failures_unchanged,
            "passed": within_band and buffers_restored and failures_unchanged,
        },
    }


async def wait_for_idle_observation(adapter, binding, observation_id, duration_ms):
    async with asyncio.timeout(duration_ms / 1000 + 5):
        while True:
            status = await adapter.request(binding, "memory.status")
            if status["observation_id"] != observation_id:
                raise ValueError("The bound memory observation changed")
            if not status["active"]:
                return
            await asyncio.sleep(min(1, duration_ms / 3000))


def summary(record, duration_ms, linked_run_id=None, *, workload_ids=()):
    assessment = record["assessments"]["memory"]
    events = [event["data"] for event in record["evidence"]["memory"]["events"]]
    status = record["evidence"]["memory"]["status"]
    phases = assessment["stages"]
    ready = assessment["assessment"] == "consistent" and not status["active"]

    def idle(event):
        return event["stage"] == "idle" and event["workload_id"] is None

    tracked = set(workload_ids)
    if linked_run_id:
        tracked.add(linked_run_id)
    if not tracked:
        clean_window = bool(events and all(idle(event) for event in events))
        complete_span = status["stop_reason"] == "deadline"
        idle_span = (
            status["stopped_us"] - status["started_us"]
            if clean_window and not status["active"]
            else None
        )
    else:
        work = [i for i, event in enumerate(events) if event["workload_id"] in tracked]
        post = events[work[-1] + 1 :] if work else []
        pre = events[: work[0]] if work else []
        clean_window = bool(pre and post and idle(pre[0]) and all(idle(event) for event in post))
        complete_span = status["stop_reason"] == "stop"
        idle_span = post[-1]["finished_us"] - post[0]["taken_us"] if clean_window else None
    minimum_span = duration_ms * 1000 - 2 * memory_observation_v2.PERIOD_US
    enough_idle = idle_span is not None and idle_span >= minimum_span
    return {
        "assessment": assessment["assessment"],
        "reasons": assessment["reasons"],
        "passed": bool(ready and clean_window and complete_span and enough_idle),
        "observed_idle_us": idle_span,
        "observed": assessment["observed"],
        "sampled_stages": [stage["stage"] for stage in phases],
        "linked_run_id": linked_run_id,
        "observation_id": status["observation_id"],
        "stop_reason": status["stop_reason"],
        "evidence_id": record["id"],
        "evidence_sha256": record["evidence_sha256"],
        "evidence": f"/api/workload-assessments/{record['id']}/export",
    }


def local_audio_blockers(node, role, variant):
    blockers = role_blockers(node, role)
    action = LOCAL_AUDIO[variant]
    commands = set(node.artifact_availability()["commands"])
    required = {"artifact.list", "artifact.get", "artifact.delete"}
    if action != "capture":
        required.update(artifact_contract_v2.ARGUMENTS)
    if not required <= commands:
        blockers.append("The stage requires verified artifact storage and readback")
    if action == "codec":
        if not {"audio.encode", "audio.decode"} <= set(node.codec_availability()["commands"]):
            blockers.append("The stage requires Codec 2 encode and decode")
    elif f"audio.{action}" not in node.audio_availability()["commands"]:
        blockers.append(f"Node {role} lacks audio.{action}")
    return blockers


async def execute_local_audio(host, case, binding, emit):
    adapter, audio, transfers = host.adapter, host.audio, host.artifacts
    role = binding["role"]
    action = LOCAL_AUDIO[case["variant"]]
    before = (await adapter.request(binding, "artifact.list"))["artifacts"]
    preexisting = {entry["artifact_id"] for entry in before}
    owned = set()
    result = None
    uploaded = None
    clean = False
    cleanup_error = None
    try:
        if action != "capture":
            started = await transfers.start_upload(
                role, PCM_FIXTURE, format="pcm_s16le_8000_mono", name="mem01-silence.pcm"
            )
            uploaded = started["artifact_id"]
            owned.add(uploaded)
            task = transfers.task
            emit(
                {
                    "audio_input_transfer_id": started["id"],
                    "pcm_sha256": hashlib.sha256(PCM_FIXTURE).hexdigest(),
                }
            )
            try:
                await asyncio.shield(task)
            finally:
                if not task.done():
                    await transfers.cancel(started["id"])
            transfer = transfers.get(started["id"])
            if transfer["status"] != "completed":
                raise ValueError(f"Memory audio input did not verify: {transfer.get('error')}")
        started = await audio.start(role, action, artifact_id=uploaded, sample_count=AUDIO_SAMPLES)
        if action == "capture":
            owned.add(started["artifact_id"])
        task = audio.task
        emit({"audio_operation_id": started["id"]})
        try:
            await asyncio.shield(task)
        finally:
            if not task.done():
                await audio.stop(started["id"])
            result = audio.get(started["id"])
            owned.update(result.get("planned_output_ids", {}).values())
            emit(
                {
                    "audio_child_id": result["id"],
                    "audio_status": result["status"],
                    "workload_command_ids": result.get("workload_command_ids", {}),
                    "audio_cleanup": result.get("cleanup_details"),
                    "audio_error": result.get("error"),
                }
            )
        if result["status"] != "completed" or result["sample_count"] != AUDIO_SAMPLES:
            raise ValueError(f"Memory audio stage failed: {result.get('error')}")
    finally:
        try:
            live = (await adapter.request(binding, "artifact.list"))["artifacts"]
            for entry in live:
                identifier = entry["artifact_id"]
                if identifier in owned and identifier not in preexisting:
                    await adapter.request(binding, "artifact.delete", {"artifact_id": identifier})
            after = (await adapter.request(binding, "artifact.list"))["artifacts"]
            status = await adapter.request(binding, "status.get")
            clean = before == after and status["state"] == "idle"
        except (OSError, ValueError) as exc:
            cleanup_error = str(exc)
        emit({"audio_artifacts_restored": clean, "audio_artifact_cleanup_error": cleanup_error})
    if not clean:
        raise ValueError("Memory audio artifact cleanup is unconfirmed")
    return result


def audio_stage_memory(events, sequences):
    selected = set(sequences)
    observed = [row for row in events if row["event_seq"] in selected]
    if not observed:
        return None
    first = observed[0]
    baseline = next(
        (row for row in reversed(events) if row["event_seq"] < first["event_seq"]), None
    )
    measured = [row["data"] for row in observed]
    regions = {}
    for region in ("internal", "psram"):
        heaps = [row["memory"][region] for row in measured]
        previous = baseline["data"]["memory"][region] if baseline else None
        if any(heap is None for heap in heaps):
            regions[region] = None
            continue
        minimum = min(heap["free_bytes"] for heap in heaps)
        regions[region] = {
            "baseline_free_bytes": previous["free_bytes"] if previous else None,
            "sampled_min_free_bytes": minimum,
            "baseline_minus_stage_min_free_bytes": previous["free_bytes"] - minimum
            if previous
            else None,
            "sampled_min_largest_free_block_bytes": min(
                heap["largest_free_bytes"] for heap in heaps
            ),
            "sampled_max_known_requested_bytes": max(
                row["known_requested_bytes"][region] for row in measured
            ),
        }
    return {
        "sample_count": len(observed),
        "baseline_sample_sequence": baseline["event_seq"] if baseline else None,
        **regions,
    }


def local_audio_summary(record, duration_ms, child, variant):
    commands = child.get("workload_command_ids", {}) if child else {}
    report = summary(record, duration_ms, workload_ids=commands.values())
    expected = {"capture": "capture", "encode": "encode", "decode": "decode", "playback": "play"}[
        variant
    ]
    workload = commands.get(f"audio.{expected}")
    events = record["evidence"]["memory"]["events"]
    samples = (
        [
            row["event_seq"]
            for row in events
            if row["data"]["workload_id"] == workload and row["data"]["stage"] == expected
        ]
        if workload
        else []
    )
    return {
        **report,
        "audio_operation_id": child["id"] if child else None,
        "target_stage": expected,
        "target_workload_id": workload,
        "target_sample_sequences": samples,
        "target_stage_memory": audio_stage_memory(events, samples),
        "passed": bool(report["passed"] and samples),
    }


def paired_audio_request(case):
    model = VoiceReassemblyRequest if case["variant"] == "reassembly" else VoiceRunRequest
    return model(
        source="microphone",
        direction=case["direction"],
        sample_count=AUDIO_SAMPLES,
        include_comparisons=False,
    )


def paired_audio_summary(voice, audio, role, record, duration_ms, variant):
    radio_id = voice.get("radio_run_id") if voice else None
    jobs = {}
    if voice:
        for name, identifier in voice["jobs"].items():
            if name != "source_upload":
                child = audio.get(identifier)
                if child["role"] == role:
                    jobs.update(child.get("workload_command_ids", {}))
    report = summary(record, duration_ms, radio_id, workload_ids=jobs.values())
    events = record["evidence"]["memory"]["events"]
    audio_samples = {
        stage: [
            event["event_seq"]
            for event in events
            if event["data"]["workload_id"] == identifier and event["data"]["stage"] == stage
        ]
        for command, identifier in jobs.items()
        if (stage := command.removeprefix("audio.")) in {"capture", "encode", "decode", "play"}
    }
    receiver = voice and role == voice["receiver"]
    reassembly = (
        [
            event["event_seq"]
            for event in events
            if event["data"]["workload_id"] == radio_id
            and any(
                buf["name"] == "rf_reassembled" and buf["requested_bytes"] == ENCODED_BYTES
                for buf in event["data"]["known_buffers"]
            )
        ]
        if receiver and radio_id
        else []
    )
    required = ()
    if variant == "integrated_voice":
        required = ("decode", "play") if receiver else ("capture", "encode")
    passed = (
        report["passed"]
        and (not receiver or reassembly)
        and all(audio_samples.get(stage) for stage in required)
    )
    return {
        **report,
        "passed": bool(passed),
        "audio_stage_samples": audio_samples,
        "reassembly_sample_sequences": reassembly,
        "audio_stage_memory": {
            stage: audio_stage_memory(events, samples) for stage, samples in audio_samples.items()
        },
        "reassembly_memory": audio_stage_memory(events, reassembly),
    }
