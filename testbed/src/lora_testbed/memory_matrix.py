"""Case plans and named observer evidence for idle and known-data memory usage."""

import asyncio

from . import content_series, memory_observation_v2

GROUPS = {
    "MEM-01": {
        "C1": ("idle_baseline",),
        "C2": ("known_data",),
        "C3": ("capture", "encode", "reassembly", "decode", "playback", "integrated_voice"),
        "C4": ("allocation_above_limit",),
        "C5": ("cancel_and_recover", "failure_and_recover"),
    },
}
FIXED_SIZES = (64, 160, 321, 1200, 48000)
BLOCKERS = {
    "C3": "The instrumented audio workload matrix is unavailable",
    "C4": "A device-side resource rejection fixture is required",
    "C5": "A controlled cancellation/failure workload and declared recovery band are required",
}


def cases(request, groups, limit):
    for group in groups:
        for variant in GROUPS["MEM-01"][group]:
            roles = request.directions if group in ("C2", "C4") else request.roles
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
                            "driver": {"C1": "memory_idle", "C2": "memory_link"}.get(
                                group, "memory_unavailable"
                            ),
                            "role": role,
                            "observation_ms": request.memory_window_ms,
                        }
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


async def wait_for_idle_observation(adapter, binding, observation_id, duration_ms):
    async with asyncio.timeout(duration_ms / 1000 + 5):
        while True:
            status = await adapter.request(binding, "memory.status")
            if status["observation_id"] != observation_id:
                raise ValueError("The bound memory observation changed")
            if not status["active"]:
                return
            await asyncio.sleep(min(1, duration_ms / 3000))


def summary(record, duration_ms, linked_run_id=None):
    assessment = record["assessments"]["memory"]
    events = [event["data"] for event in record["evidence"]["memory"]["events"]]
    status = record["evidence"]["memory"]["status"]
    phases = assessment["stages"]
    ready = assessment["assessment"] == "consistent" and not status["active"]

    def idle(event):
        return event["stage"] == "idle" and event["workload_id"] is None

    if linked_run_id is None:
        clean_window = bool(events and all(idle(event) for event in events))
        complete_span = status["stop_reason"] == "deadline"
        idle_span = (
            status["stopped_us"] - status["started_us"]
            if clean_window and not status["active"]
            else None
        )
    else:
        work = [i for i, event in enumerate(events) if event["workload_id"] == linked_run_id]
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
