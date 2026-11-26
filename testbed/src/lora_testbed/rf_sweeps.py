"""Seeded one-factor RF settings and a bounded per-child measurement projection."""

import hashlib
from statistics import median

from .experiments_v2 import Radio, airtime_us, preview
from .radio_runs import SweepRadioRunRequest, TransmitterPowerRunRequest

FACTORS = {
    "RF-01": ("spreading_factor", (7, 8, 9, 10, 11, 12), 7),
    "RF-02": ("bandwidth_hz", (125000, 250000, 500000), 125000),
    "RF-03": ("coding_rate_denominator", (5, 6, 7, 8), 5),
    "RF-04": ("tx_power_dbm", (2, 5, 8, 11, 14, 17, 20), 2),
}
GROUPS = {
    identifier: {"C1": "before_control", "C2": "factor_sweep", "C3": "after_control"}
    for identifier in FACTORS
}


def cases(request, groups):
    field, values, baseline = FACTORS[request.catalog_id]
    for direction in request.directions:
        for repetition in range(1, request.repetitions + 1):
            order_key = f"{request.seed}:{request.catalog_id}:{repetition}:"
            randomized = sorted(
                values, key=lambda value: hashlib.sha256(f"{order_key}{value}".encode()).digest()
            )
            sequence = (
                ("C1", baseline),
                *[("C2", value) for value in randomized],
                ("C3", baseline),
            )
            for group, value in sequence:
                if group not in groups:
                    continue
                case = {
                    "group": group,
                    "variant": GROUPS[request.catalog_id][group],
                    "repetition": repetition,
                    "driver": "rf_sweep",
                    "factor": field,
                    "value": value,
                    "role": direction,
                    "direction": direction,
                    "message_bytes": 64,
                    "message_count": request.messages_per_case,
                }
                child = sweep_request(request, case, 0)
                timing = preview(child.plan())["timing"]
                yield {
                    **case,
                    "requested_settings": child.radio.model_dump(),
                    "child_budget": timing["budget"],
                    "required_child_window_ms": timing["required_max_duration_ms"],
                }


def sweep_request(matrix, case, ordinal):
    seed = (matrix.seed + (case["repetition"] - 1) * 100 + ordinal) % 2**32
    selected = Radio(**{case["factor"]: case["value"]})
    args = {
        "direction": case["direction"],
        "message_bytes": 64,
        "source_seed": seed,
        "timeout_ms": 30000,
        "security": matrix.rf_security,
        "radio": selected,
    }
    if matrix.catalog_id == "RF-04":
        return TransmitterPowerRunRequest(**args, receiver_power_dbm=2)
    return SweepRadioRunRequest(**args)


def observation(record):
    """Use exact serial-bound observations and node-local TX duration."""
    accounting = record.get("accounting") or {}
    if record["status"] != "completed" or not accounting.get("evidence_complete"):
        return None
    failed_delivery = accounting.get("observed_delivery_failure", False)
    if not failed_delivery and not (record.get("verification") or {}).get("bytes_equal"):
        return None
    sender, receiver = record["sender"], record["receiver"]
    observed = [
        event["data"]
        for event in record["events"]
        if event["role"] == sender
        and event["name"] == "tx.attempt"
        and event["data"]["status"] == "completed"
        and event["data"]["frame_type"] == "data"
    ]
    if len(observed) != 1:
        return None
    attempt = observed[0]
    received = [
        event["data"]
        for event in record["events"]
        if event["role"] == receiver
        and event["name"] == "rx.frame"
        and event["data"]["crc_ok"]
        and event["data"]["frame_type"] == "data"
        and (event["data"]["session_id"], event["data"]["frame_seq"])
        == (attempt["session_id"], attempt["frame_seq"])
    ]
    if len(received) > 1 or (not received and not failed_delivery):
        return None
    reported = record["applied_settings"][sender]["radio"]
    settings = Radio.model_validate({k: v for k, v in reported.items() if k != "ldro_enabled"})
    predicted = airtime_us(settings, attempt["frame_bytes"])
    duration = attempt["tx_done_us"] - attempt["tx_command_us"]
    return {
        "frame_bytes": attempt["frame_bytes"],
        "tx_command_to_done_us": duration,
        "predicted_airtime_us": predicted,
        "delivered_messages": accounting["delivered_messages"],
        "useful_delivered_bytes": record["summaries"][receiver]["useful_delivered_bytes"],
        "rssi_dbm": received[0]["rssi_dbm"] if received else None,
        "snr_db": received[0]["snr_db"] if received else None,
    }


def report(rows, requested):
    complete = len(rows) == requested
    delivered = sum(row["delivered_messages"] for row in rows)
    seconds = sum(row["tx_command_to_done_us"] for row in rows) / 1_000_000
    useful_bytes = sum(row["useful_delivered_bytes"] for row in rows)
    signal = [row for row in rows if row["rssi_dbm"] is not None]
    return {
        "sample_count": len(rows),
        "requested_messages": requested,
        "complete_observation_cohort": complete,
        "delivered_messages": delivered,
        "observed_non_deliveries": len(rows) - delivered,
        "unresolved_messages": requested - len(rows),
        "unique_original_delivery_ratio": delivered / requested if complete else None,
        "useful_bits_per_active_tx_second": 8 * useful_bytes / seconds
        if complete and seconds
        else None,
        "signal_sample_count": len(signal),
        "measured_airtime_basis": "sender-local transmit command to completion",
        "rssi_dbm_median": median(row["rssi_dbm"] for row in signal) if signal else None,
        "snr_db_median": median(row["snr_db"] for row in signal) if signal else None,
        "tx_command_to_done_us_median": median(row["tx_command_to_done_us"] for row in rows)
        if rows
        else None,
        "predicted_airtime_us_median": median(row["predicted_airtime_us"] for row in rows)
        if rows
        else None,
    }
