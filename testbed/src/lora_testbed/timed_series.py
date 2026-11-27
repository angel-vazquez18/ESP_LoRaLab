"""Matrix inputs and observed timing statistics for echo and local crypto."""

from math import ceil
from statistics import fmean, median

from . import crypto_benchmark_v2
from .radio_runs import EchoMissingReplyCheck, EchoRadioRunRequest

GROUPS = {
    "TIME-01": {"C1": "matched_echoes", "C2": "controlled_missing_reply"},
    "SEC-04": {"C1": "operation_timing"},
}


def cases(request, groups):
    if request.catalog_id == "SEC-04":
        for role in request.roles:
            for size in (16, 64, 160, 199):
                for repetition in range(1, request.repetitions + 1):
                    yield {
                        "group": "C1",
                        "variant": f"bytes_{size}",
                        "repetition": repetition,
                        "driver": "local_crypto",
                        "role": role,
                        "message_bytes": size,
                        "iterations": request.diagnostic_iterations,
                    }
        return
    for group in groups:
        choices = (
            ((64, "none"),)
            if group == "C2"
            else tuple((size, mode) for size in (16, 64, 160) for mode in ("none", "aes128_gcm"))
        )
        for size, mode in choices:
            for direction in request.directions:
                for repetition in range(1, request.repetitions + 1):
                    yield {
                        "group": group,
                        "variant": f"bytes_{size}_{mode}" if group == "C1" else "missing_reply",
                        "repetition": repetition,
                        "driver": "echo_batch" if group == "C1" else "echo_timeout_fixture",
                        "role": direction,
                        "direction": direction,
                        "message_bytes": size,
                        "security": mode,
                        "message_count": request.messages_per_case if group == "C1" else 1,
                    }


def echo_request(matrix, case):
    return EchoRadioRunRequest(
        direction=case["direction"],
        security=case["security"],
        message_bytes=case["message_bytes"],
        source_seed=(matrix.seed + case["repetition"] - 1) % 2**32,
    )


def echo_timeout_request(matrix, case):
    return EchoMissingReplyCheck(**echo_request(matrix, case).model_dump())


def controlled_timeout_report(record):
    requester, responder = record["sender"], record["receiver"]
    control = record.get("echo_timeout_control") or {}
    timing = record.get("timing") or {}
    report = {
        "verified": False,
        "rtt_us": None,
        "requester": requester,
        "responder": responder,
        "reason": "controlled_timeout_evidence_incomplete",
    }
    if (
        record["status"] != "completed"
        or not record["cleanup"]["confirmed"]
        or timing.get("n") != 0
        or [row["reason"] for row in timing.get("exclusions", [])] != ["timeout"]
        or control.get("responder_stop", {}).get("state") != "idle"
        or control.get("responder_idle", {}).get("state") != "idle"
        or "requester_start" not in control
        or not record.get("wire_sha256")
    ):
        return report

    transmissions = [row for row in record["events"] if row["name"] == "tx.attempt"]
    results = [
        row for row in record["events"] if row["name"] == "echo.result" and row["role"] == requester
    ]
    if len(transmissions) != 1 or len(results) != 1:
        return report
    tx, result = transmissions[0], results[0]
    sent, outcome = tx["data"], result["data"]
    send_summary, receive_summary = record["summaries"][requester], record["summaries"][responder]
    deadline = control["requester_start"]["deadline_us"]
    wait_until = deadline - control["drain_us"]
    confirmed = (
        tx["role"] == requester
        and sent["frame_type"] == "echo_request"
        and sent["status"] == "completed"
        and sent["session_id"] == record["session_id"] == outcome["session_id"]
        and sent["frame_seq"] == outcome["request_frame_seq"]
        and sent["tx_command_us"] == outcome["tx_command_us"]
        and sent["tx_done_us"] is not None
        and sent["tx_done_us"] < wait_until <= result["uptime_us"] <= deadline
        and send_summary["stop_reason"] == "timeout"
        and outcome == send_summary["echo"]
        and receive_summary["stop_reason"] == "operator"
        and receive_summary["tx_attempts"] == 0
        and receive_summary["delivered_messages"] == 0
        and outcome["rtt_us"] is None
        and outcome["reply_frame_seq"] is None
    )
    return {
        **report,
        "verified": confirmed,
        "reason": "timeout" if confirmed else report["reason"],
        "tx_command_us": sent["tx_command_us"],
        "timeout_observed_us": result["uptime_us"],
        "reply_cutoff_us": wait_until,
        "requester_deadline_us": deadline,
        "request_frame_seq": sent["frame_seq"],
    }


def crypto_report(records):
    result = crypto_benchmark_v2.assess(records)
    if not result["complete"]:
        return {"complete": False, "reasons": result["reasons"]}
    terminal = next(
        event["data"]["result"] for event in records if event["name"] == "operation.result"
    )
    first = {
        event["data"]["path"]: event["data"]["samples"][0][1] - event["data"]["samples"][0][0]
        for event in records
        if event["name"] == "crypto.benchmark" and event["data"]["phase"] == "first_call"
    }
    payload = terminal["payload_bytes"]
    vectors = {}
    for path, samples in result["timed"].items():
        ordered = sorted(samples)
        vectors[path] = {
            "n": len(samples),
            "first_call_us": first[path],
            "checked_warmups": result["counts"][path]["warmup"],
            "median_us": median(samples),
            "p95_us": ordered[ceil(0.95 * len(samples)) - 1],
            "mean_us": fmean(samples),
            "min_us": ordered[0],
            "max_us": ordered[-1],
            "mean_us_per_payload_byte": fmean(samples) / payload,
            "median_at_timer_resolution": median(samples) <= terminal["timestamp_resolution_us"],
        }
    return {
        "complete": True,
        "checked_samples": result["checked_samples"],
        "distributions": vectors,
        "identification": {
            key: terminal[key]
            for key in (
                "payload_bytes",
                "implementation",
                "timer",
                "timestamp_resolution_us",
                "configured_cpu_frequency_mhz",
                "dynamic_frequency_enabled",
                "hardware_aes_configured",
                "vector_sha256",
                "first_call_scope",
                "copy_baseline",
            )
        },
    }


def crypto_blockers(node):
    if (
        not node.connected
        or node.wire_profile != "node_control"
        or node.identity is None
        or node.health is None
        or node.health.node_role != node.role
        or node.health.state != "idle"
        or node.snapshot()["connection_state"] != "connected"
    ):
        return [f"Node {node.role} needs a healthy owned main-control connection"]
    try:
        crypto_benchmark_v2.require_capability(
            node.identity.capabilities, node.health.capability_availability
        )
    except ValueError:
        return [f"Node {node.role} lacks the exact local crypto benchmark capability"]
    return []
