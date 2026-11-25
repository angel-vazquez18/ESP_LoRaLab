"""Plan and inspect the bounded, linked bench-recovery campaign."""

from itertools import product

from .campaign_plans import (
    BATCH_CASES,
    BATCH_SECONDS,
    CampaignSpec,
    MemoryCase,
    RadioCase,
    Template,
)
from .radio_runs import RadioRunRequest

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
    "C4": "The invalid configuration/timeout recovery fixture is unavailable",
    "C5": "A controlled telemetry omission fixture is required",
    "C6": "The one-hour stability and loaded observation runner is unavailable",
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
                "driver": "ops_unavailable",
                "role": direction,
                "direction": direction,
                "observation_s": 3600 if group == "C6" else None,
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
