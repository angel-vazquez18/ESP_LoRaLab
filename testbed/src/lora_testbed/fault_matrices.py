"""Plan repeatable cases around the existing matched-control lab trial service."""

from itertools import product
from uuid import uuid4

from .experiments_v2 import KnownDataPlan, KnownDataSpec, Link, Radio, preview
from .fault_protocol_v2 import Injection
from .radio_runs import LabRadioRunRequest, RadioRunRequest

GROUPS = {
    "SEC-02": {"C1": "ciphertext_bit", "C2": "tag_bit"},
    "SEC-03": {"C1": "immediate_replay", "C2": "old_window_replay"},
    "PKT-02": {"C1": "intact", "C2": "dropped", "C3": "exact_duplicate", "C4": "reversed_block"},
    "PKT-03": {"C1": "intact", "C2": "dropped", "C3": "suppressed_ack", "C4": "dropped_all"},
}
PACKET_FRAGMENT_SIZES = (16, 64, 160, 199)
ACTIONS = {
    "ciphertext_bit": ("tx_after_protect", "xor_byte"),
    "tag_bit": ("tx_after_protect", "xor_byte"),
    "immediate_replay": ("tx_retained", "replay"),
    "dropped": ("rx_before_reassembly", "drop"),
    "dropped_all": ("rx_before_reassembly", "drop"),
    "suppressed_ack": ("tx_before_radio", "drop_ack"),
    "exact_duplicate": ("tx_schedule", "duplicate"),
    "reversed_block": ("tx_schedule", "reverse_block"),
}


def cases(request, groups):
    if request.catalog_id == "PKT-03":
        yield from retry_cases(request, groups)
        return
    packet = request.catalog_id == "PKT-02"
    fragment_sizes = PACKET_FRAGMENT_SIZES if packet else (160,)
    for group, fragment_bytes, direction, repetition in product(
        groups, fragment_sizes, request.directions, range(1, request.repetitions + 1)
    ):
        variant = GROUPS[request.catalog_id][group]
        count = min(10, request.messages_per_case) if packet else 1
        yield {
            "group": group,
            "variant": f"{variant}_{fragment_bytes}" if packet else variant,
            "repetition": repetition,
            "driver": (
                "fault_window_unavailable" if variant == "old_window_replay" else "fault_series"
            ),
            "role": direction,
            "direction": direction,
            "message_bytes": 1200 if packet else 64,
            "message_count": count,
            "fragment_payload_bytes": fragment_bytes,
            "security": "aes128_gcm",
            "action": variant,
            "target_ordinal": min(3, count) if packet else 1,
            "session_scope": "one finite session per message with separate intact controls",
        }


def retry_cases(request, groups):
    count = min(10, request.messages_per_case)
    all_policies = (("none", 0), ("stop_wait", 0), ("stop_wait", 1), ("stop_wait", 2))
    for group, direction, repetition in product(
        groups, request.directions, range(1, request.repetitions + 1)
    ):
        variant = GROUPS["PKT-03"][group]
        policies = all_policies[2:] if variant == "suppressed_ack" else all_policies
        for policy, retries in policies:
            yield {
                "group": group,
                "variant": f"{variant}_{policy}_{retries}",
                "driver": "fault_series",
                "role": direction,
                "direction": direction,
                "repetition": repetition,
                "message_bytes": 321,
                "message_count": count,
                "fragment_payload_bytes": 160,
                "security": "aes128_gcm",
                "action": variant,
                "target_ordinal": min(3, count),
                "ack_mode": policy,
                "max_retries": retries,
                "session_scope": "one finite session per message with separate intact controls",
            }


def selected_request(spec, case, ordinal):
    capacity = case["fragment_payload_bytes"]
    size = case["message_bytes"]
    options = {
        "direction": case["direction"],
        "message_bytes": size,
        "security": case["security"],
        "source_seed": (spec.seed + 10 * (case["repetition"] - 1) + ordinal) % 2**32,
        "link": Link(
            fragment_payload_bytes=capacity,
            ack_mode=case.get("ack_mode", "none"),
            max_retries=case.get("max_retries", 0),
        ),
    }

    plan = KnownDataPlan(
        radio=Radio(tx_power_dbm=2),
        link=options["link"],
        spec=KnownDataSpec(
            direction=case["direction"], message_bytes=size, security=case["security"]
        ),
    )
    options["timeout_ms"] = max(5000, preview(plan)["timing"]["required_max_duration_ms"] + 3000)
    variant = case["action"]
    if variant not in ACTIONS or ordinal + 1 != case["target_ordinal"]:
        return RadioRunRequest(**options)
    stage, action = ACTIONS[variant]
    count = (size + capacity - 1) // capacity
    index = {
        "dropped": 1 if "ack_mode" in case else count // 2,
        "dropped_all": 1,
        "suppressed_ack": 1,
        "exact_duplicate": 1,
        "reversed_block": (count - 4) // 2,
    }.get(variant, 0)
    injection = Injection(
        injection_id=str(uuid4()),
        stage=stage,
        action=action,
        message_id=1,
        fragment_index=index,
        attempt_index=1,
        byte_offset={"ciphertext_bit": 40, "tag_bit": 40 + size}.get(variant),
        xor_mask=1 if action == "xor_byte" else None,
        block_size=4 if action == "reverse_block" else None,
    )
    # A rejected or deliberately incomplete transaction still uses a finite deadline.
    exhausting = case.get("ack_mode") == "stop_wait" and (
        variant == "dropped_all" or (variant == "dropped" and not case["max_retries"])
    )
    return LabRadioRunRequest(**options, injection=injection, exhaust_attempts=exhausting)
