"""Seeded one-factor RF settings and a bounded per-child measurement projection."""

import csv
import hashlib
import io
from math import isfinite
from statistics import median

from .experiments_v2 import Radio, airtime_us, preview
from .radio_runs import (
    EchoRadioRunRequest,
    SweepRadioRunRequest,
    TransmitterPowerEchoRunRequest,
    TransmitterPowerRunRequest,
)

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


DEFAULT_ECHO_SERIES = {"RF-02", "RF-03", "RF-04"}


def echo_count(request):
    if request.rf_echoes_per_case is not None:
        return request.rf_echoes_per_case
    if request.catalog_id in DEFAULT_ECHO_SERIES and request.messages_per_case == 100:
        return 100
    return 0


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
                    "echo_count": echo_count(request),
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


def echo_request(matrix, case):
    data = sweep_request(matrix, case, 0)
    options = data.model_dump()
    if isinstance(data, TransmitterPowerRunRequest):
        return TransmitterPowerEchoRunRequest(**options)
    return EchoRadioRunRequest(**options)


def matched_echo(data, echo):
    def applied(record):
        return {
            role: {key: values[key] for key in ("radio", "link")}
            for role, values in record["applied_settings"].items()
        }

    return (
        data["sender"] == echo["sender"]
        and data["identities"] == echo["identities"]
        and data["plan"]["spec"]["security"] == echo["plan"]["spec"]["security"]
        and applied(data) == applied(echo)
    )


def echo_report(distribution, requested):
    [group] = distribution["groups"] if len(distribution["groups"]) == 1 else [None]
    verified = group["n"] if group else 0
    timeouts = sum(row["reason"] == "timeout" for row in group["exclusions"]) if group else 0
    return {
        "requested": requested,
        "verified": verified,
        "timeouts": timeouts,
        "unresolved": requested - verified - timeouts,
        "median_us": group["median_us"] if group else None,
        "p95_us": group["p95_us"] if group else None,
        "clock_scope": "requester_device_and_boot",
    }


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
        "accepted_fragment_bytes": accounting.get("accepted_fragment_bytes"),
        "sender_transfer_window": accounting.get("sender_transfer_window"),
        "whole_transaction_ns": (record.get("host_transaction") or {}).get("elapsed_ns"),
        "rssi_dbm": received[0]["rssi_dbm"] if received else None,
        "snr_db": received[0]["snr_db"] if received else None,
    }


def report(rows, requested):
    complete = len(rows) == requested
    delivered = sum(row["delivered_messages"] for row in rows)
    seconds = sum(row["tx_command_to_done_us"] for row in rows) / 1_000_000
    useful_bytes = sum(row["useful_delivered_bytes"] for row in rows)
    windows = [(row.get("sender_transfer_window") or {}).get("duration_us") for row in rows]
    accepted = [row.get("accepted_fragment_bytes") for row in rows]
    full_timing = complete and all(value is not None and value > 0 for value in windows)
    total_us = sum(windows) if full_timing else None
    host_times = [row.get("whole_transaction_ns") for row in rows]
    signal = [row for row in rows if row["rssi_dbm"] is not None]
    return {
        "sample_count": len(rows),
        "requested_messages": requested,
        "complete_observation_cohort": complete,
        "delivered_messages": delivered,
        "observed_non_deliveries": len(rows) - delivered,
        "unresolved_messages": requested - len(rows),
        "unique_original_delivery_ratio": delivered / requested if complete else None,
        "complete_message_ratio": delivered / requested if complete else None,
        "summed_sender_transfer_us": total_us,
        "accepted_fragment_bps": 8_000_000 * sum(accepted) / total_us
        if total_us and all(n is not None for n in accepted)
        else None,
        "goodput_bps": 8_000_000 * useful_bytes / total_us if total_us else None,
        "whole_transaction_ns_median": median(host_times)
        if complete and all(value is not None and value > 0 for value in host_times)
        else None,
        "transfer_rate_unavailable_reason": None
        if full_timing
        else "One or more finite child transfer windows are unverified",
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


COMPARISON_METRICS = {
    "delivery_percent": ("Delivery (%)", "unique_original_delivery_ratio", 100),
    "accepted_fragment_bps": ("Accepted fragment rate (bit/s)", "accepted_fragment_bps", 1),
    "goodput_bps": ("Verified application goodput (bit/s)", "goodput_bps", 1),
    "host_transaction_ms": ("Host transaction (ms)", "whole_transaction_ns_median", 1 / 1_000_000),
    "useful_bits_per_tx_second": (
        "Useful bitrate during TX (bit/s)",
        "useful_bits_per_active_tx_second",
        1,
    ),
    "rssi_dbm": ("RSSI (dBm)", "rssi_dbm_median", 1),
    "snr_db": ("SNR (dB)", "snr_db_median", 1),
    "tx_duration_us": ("Observed TX duration (µs)", "tx_command_to_done_us_median", 1),
    "airtime_us": ("Modeled airtime (µs)", "predicted_airtime_us_median", 1),
}


RTT_METRICS = {
    "rtt_median_us": ("Median RTT (µs)", "median_us", 1),
    "rtt_p95_us": ("p95 RTT (µs)", "p95_us", 1),
}


def case_measurements(case, metrics):
    measurements = case.get("measurements") or {}
    complete = case["status"] == "completed" and measurements.get("complete_observation_cohort")
    values = {}
    timing = measurements.get("matched_rtt") or {}
    for metric, (_, field, ratio) in metrics.items():
        if metric in RTT_METRICS:
            value = timing.get(field) if timing.get("unresolved") == 0 else None
        else:
            value = measurements.get(field) if complete else None
        values[metric] = value * ratio if type(value) in (int, float) and isfinite(value) else None
    return {
        "case_id": case["id"],
        "repetition": case["repetition"],
        "status": case["status"],
        "observations": measurements.get("sample_count", 0),
        "planned_messages": case["message_count"],
        "rtt_requested": case.get("echo_count", 0),
        "rtt_verified": timing.get("verified", 0),
        "rtt_timeouts": timing.get("timeouts", 0),
        "values": values,
    }


def compare_saved_cases(run):
    include_rtt = any(case.get("echo_count") for case in run["cases"])
    metrics = {**COMPARISON_METRICS, **RTT_METRICS} if include_rtt else COMPARISON_METRICS
    cohorts, controls = {}, {}
    for case in run["cases"]:
        direction = case["direction"]
        if case["group"] == "C2":
            cohorts.setdefault((direction, case["value"]), []).append(
                case_measurements(case, metrics)
            )
        else:
            controls.setdefault((direction, case["repetition"]), {})[case["group"]] = case
    comparisons = []
    for (direction, setting), trials in sorted(cohorts.items()):
        bands = {}
        for key in metrics:
            values = [trial["values"][key] for trial in trials if trial["values"][key] is not None]
            bands[key] = (
                {
                    "count": len(values),
                    "min": min(values),
                    "median": median(values),
                    "max": max(values),
                }
                if values
                else None
            )
        comparisons.append(
            {
                "direction": direction,
                "value": setting,
                "repetitions": trials,
                "ranges": bands,
            }
        )
    baselines = []
    for (direction, repetition), phases in sorted(controls.items()):
        before, after = (phases.get(group) for group in ("C1", "C3"))
        first = case_measurements(before, metrics) if before else None
        last = case_measurements(after, metrics) if after else None
        matched = (
            bool(first and last)
            and before["value"] == after["value"]
            and before["requested_settings"] == after["requested_settings"]
            and first["planned_messages"] == last["planned_messages"]
            and first["rtt_requested"] == last["rtt_requested"]
        )
        changes = {}
        for key in metrics:
            initial = first["values"][key] if first else None
            final = last["values"][key] if last else None
            changes[key] = {
                "before": initial,
                "after": final,
                "delta": final - initial
                if matched and initial is not None and final is not None
                else None,
            }
        baselines.append(
            {
                "direction": direction,
                "repetition": repetition,
                "settings_matched": matched,
                "before_case_id": first["case_id"] if first else None,
                "after_case_id": last["case_id"] if last else None,
                "changes": changes,
            }
        )
    return {
        "factor": FACTORS[run["catalog_id"]][0],
        "security": run["request"]["rf_security"],
        "metrics": {key: info[0] for key, info in metrics.items()},
        "rtt_metrics": list(RTT_METRICS) if include_rtt else [],
        "settings": comparisons,
        "baselines": baselines,
    }


def comparison_csv(report):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "direction",
            "factor",
            "setting",
            "security",
            "repetition",
            "case_id",
            "status",
            "observations",
            "planned_messages",
            "rtt_requested",
            "rtt_verified",
            "rtt_timeouts",
            *report["metrics"],
        ],
    )
    writer.writeheader()
    for setting in report["settings"]:
        for trial in setting["repetitions"]:
            writer.writerow(
                {
                    "direction": setting["direction"],
                    "factor": report["factor"],
                    "setting": setting["value"],
                    "security": report["security"],
                    **{key: value for key, value in trial.items() if key != "values"},
                    **trial["values"],
                }
            )
    return output.getvalue()
