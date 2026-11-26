"""Plan and inspect the bounded, linked bench-recovery campaign."""

from itertools import product
from resource import RUSAGE_SELF, getrusage
from sys import platform

from .campaign_plans import (
    BATCH_CASES,
    BATCH_SECONDS,
    CampaignSpec,
    MemoryCase,
    RadioCase,
    Template,
)
from .radio_runs import RadioRunRequest

STABILITY_SECONDS = 3600
LOAD_PERIOD_SECONDS = 60
HEALTH_GAP_US = 2_000_000

GROUPS = {
    "OPS-01": {
        "C1": ("usb_unplug",),
        "C2": ("reset",),
        "C3": ("restart_active", "restart_paused"),
        "C4": ("invalid_configuration", "command_timeout"),
        "C5": ("telemetry_gap",),
        "C6": ("idle_observation", "loaded_observation"),
        "C7": ("linked_campaign",),
    },
}
BLOCKERS = {
    "C1": "The attended USB interruption case is unavailable",
    "C2": "The attended board reset case is unavailable",
    "C3": "A supervised host restart fixture is required",
    "C5": "A controlled telemetry omission fixture is required",
}


def cases(request, groups):
    for group in groups:
        if group == "C7":
            yield {
                "group": group,
                "variant": "linked_campaign",
                "repetition": 1,
                "driver": "ops_campaign",
                "role": "A ↔ B",
                "planned_campaign_cases": 10 * min(request.messages_per_case, 10),
                "campaign_repetitions": min(request.messages_per_case, 10),
            }
            continue
        for variant, direction, repetition in product(
            GROUPS["OPS-01"][group],
            request.directions,
            range(1, 2 if group == "C6" else request.repetitions + 1),
        ):
            yield {
                "group": group,
                "variant": variant,
                "repetition": repetition,
                "driver": {"C4": "ops_control_recovery", "C6": "ops_stability"}.get(
                    group, "ops_unavailable"
                ),
                "role": direction,
                "direction": direction,
                **(
                    {
                        "observation_s": request.ops_observation_s,
                        "firmware_health_hz": 1,
                        "radio_load_period_s": LOAD_PERIOD_SECONDS
                        if variant == "loaded_observation"
                        else None,
                    }
                    if group == "C6"
                    else {}
                ),
            }


def known_data_request(case, seed, ordinal=0):
    return RadioRunRequest(direction=case["direction"], source_seed=(seed + ordinal) % 2**32)


def stability_role_blockers(nodes):
    blockers = []
    for role in ("A", "B"):
        node = nodes[role]
        if (
            node.wire_profile != "node_control"
            or node.identity is None
            or node.snapshot()["connection_state"] != "connected"
            or node.health is None
            or node.health.node_role != role
            or node.health.state != "idle"
            or node.rf_run_id
        ):
            blockers.append(f"Node {role} needs compatible, owned and idle health telemetry")
    if not blockers and nodes["A"].identity.device_id == nodes["B"].identity.device_id:
        blockers.append("Stability observation requires two distinct devices")
    return blockers


def idle_status(status):
    return (
        status["state"] == "idle"
        and status["run_id"] is None
        and status["operation_id"] is None
        and not status["security_ready"]
    )


def observed_host_resources(nodes):
    reported_peak = getrusage(RUSAGE_SELF).ru_maxrss
    return {
        "host_peak_rss_bytes": reported_peak if platform == "darwin" else 1024 * reported_peak,
        "live_health_buffers": {
            role: {"size": len(node.samples), "capacity": node.samples.maxlen}
            for role, node in nodes.items()
        },
    }


class HealthWindow:
    def __init__(self, binding, node, status):
        self.binding = binding
        self.start_us = self.last_us = status["uptime_us"]
        self.allocation_failures = status["memory"]["allocation_failures"]
        self.last_event_seq = node.event_seq
        self.start_faults = self.faults(node, status)
        self.samples = 0
        self.max_gap_us = 0
        self.minimum_internal_free = status["memory"]["internal"]["free_bytes"]
        self.non_idle_samples = 0
        self.reasons = set()

    @staticmethod
    def faults(node, status):
        return {
            "event_gaps": node.event_gaps,
            "framing_errors": node.framing_errors,
            "node_telemetry_drops": status["telemetry_drops"],
        }

    def observe(self, event):
        if (event["device_id"], event["boot_id"], event["node_role"]) != (
            self.binding["device_id"],
            self.binding["boot_id"],
            self.binding["role"],
        ):
            self.reasons.add("Health event belongs to a different device, boot or role")
            return
        status = event["data"]
        uptime = status["uptime_us"]
        if uptime <= self.last_us or event["event_seq"] <= self.last_event_seq:
            self.reasons.add("Health event uptime or sequence did not advance")
            return
        self.samples += 1
        self.max_gap_us = max(self.max_gap_us, uptime - self.last_us)
        self.last_us = uptime
        self.last_event_seq = event["event_seq"]
        self.minimum_internal_free = min(
            self.minimum_internal_free, status["memory"]["internal"]["free_bytes"]
        )
        self.non_idle_samples += status["state"] != "idle"
        if status["memory"]["allocation_failures"] != self.allocation_failures:
            self.reasons.add("Node reported allocation failures during observation")
        if status["telemetry_drops"] != self.start_faults["node_telemetry_drops"]:
            self.reasons.add("Node reported telemetry drops during observation")

    def finish(self, node, status, *, loaded):
        final_faults = self.faults(node, status)
        if self.start_faults != final_faults:
            self.reasons.add("Serial framing or telemetry counters changed")
        after = status["uptime_us"]
        max_gap = max(self.max_gap_us, after - self.last_us)
        if not self.samples or after < self.last_us or max_gap >= HEALTH_GAP_US:
            self.reasons.add("A periodic health observation is missing or out of order")
        if status["memory"]["allocation_failures"] != self.allocation_failures:
            self.reasons.add("Node reported allocation failures during observation")
        if not loaded and self.non_idle_samples:
            self.reasons.add("Node reported activity during the idle case")
        return {
            "samples": self.samples,
            "max_gap_us": max_gap,
            "start_uptime_us": self.start_us,
            "end_uptime_us": after,
            "minimum_internal_free_bytes": self.minimum_internal_free,
            "non_idle_samples": self.non_idle_samples,
            "baseline_counters": self.start_faults,
            "final_counters": final_faults,
            "reasons": sorted(self.reasons),
        }


def campaign_request(matrix, case):
    local = [
        Template(
            label=f"Memory smoke check {role}",
            case=MemoryCase(kind="memory_probe", role=role, iterations=1, payload_bytes=4096),
        )
        for role in ("A", "B")
    ]
    transfers = [
        Template(
            label=f"Known data {size} bytes",
            case=RadioCase(
                kind="known_data",
                request=RadioRunRequest(
                    message_bytes=size, source_seed=(matrix.seed + offset * 10) % 2**32
                ),
            ),
        )
        for offset, size in enumerate((32, 64, 160, 321))
    ]
    return CampaignSpec(
        name="OPS-01 C7 linked bench campaign",
        templates=[*local, *transfers],
        repetitions=case["campaign_repetitions"],
        order="randomized",
        order_seed=matrix.seed,
    )


def verified_batches(plan, expected):
    cases = [case["id"] for case in plan["cases"]]
    if len(cases) != expected or len(set(cases)) != expected:
        return False
    batches = plan["batches"]
    if [identifier for batch in batches for identifier in batch["case_ids"]] != cases:
        return False
    return all(
        batch["parent_plan_id"] == plan["id"]
        and batch["case_count"] == len(batch["case_ids"]) <= BATCH_CASES
        and batch["duration_bound_s"] <= BATCH_SECONDS
        and batch["previous_batch_id"] == (batches[i - 1]["id"] if i else None)
        and batch["next_batch_id"] == (batches[i + 1]["id"] if i + 1 < len(batches) else None)
        for i, batch in enumerate(batches)
    )


def ready_blockers(matrix, case, planner):
    if planner is None:
        return ["The campaign capability preview is unavailable"]
    plan = planner.preview(campaign_request(matrix, case))
    return list(
        dict.fromkeys(
            blocker
            for entry in plan["cases"]
            for blocker in entry["hardware_preflight"]["blockers"]
        )
    )
