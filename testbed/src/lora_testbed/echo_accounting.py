"""Reconcile echo evidence before reporting requester-local timing distributions."""

import hashlib
import json
import math
from statistics import median

from .experiments_v2 import known_data
from .rf_events_v2 import EchoData


class _Excluded(ValueError):
    def __init__(self, reason, detail=None):
        self.reason, self.detail = reason, detail
        super().__init__(reason)


def _distribution(samples):
    ordered = sorted(sample["rtt_us"] for sample in samples)
    return {
        "n": len(ordered),
        "median_us": median(ordered) if ordered else None,
        "p95_us": ordered[math.ceil(0.95 * len(ordered)) - 1] if ordered else None,
        "minimum_us": ordered[0] if ordered else None,
        "maximum_us": ordered[-1] if ordered else None,
    }


def assess(record):
    samples, exclusions = [], []
    rejected = [
        {"role": event["role"], **event["data"]}
        for event in record.get("events", [])
        if event.get("name") == "rx.rejected"
    ]

    def exclude(reason, detail=None):
        raise _Excluded(reason, detail)

    try:
        source, peer = record["sender"], record["receiver"]
        if record["plan"]["spec"]["source"] != "echo":
            exclude("not_echo")
        if record["status"] != "completed":
            exclude("execution_" + record["status"], record.get("error"))
        if record.get("saved_integrity_error"):
            exclude("saved_evidence_unverified", record["saved_integrity_error"])
        if record.get("evidence_error"):
            exclude("incomplete_telemetry", record["evidence_error"])
        if not record.get("cleanup", {}).get("confirmed"):
            exclude("cleanup_unconfirmed")
        events = record["events"]
        for event in events:
            identity = record["identities"][event["role"]]
            if (event.get("device_id"), event.get("boot_id"), event.get("run_id")) != (
                identity["device_id"],
                identity["boot_id"],
                record["id"],
            ):
                exclude("clock_or_run_mismatch")
        for role in (source, peer):
            summary = record["summaries"][role]
            if summary.get("telemetry_drops") or summary.get("validity_reasons"):
                exclude("incomplete_telemetry")

        def rows(role, name):
            return [
                event["data"] for event in events if event["role"] == role and event["name"] == name
            ]

        def one(role, name):
            found = rows(role, name)
            if len(found) != 1:
                exclude("missing_or_multiple_" + name.replace(".", "_"))
            return found[0]

        result = EchoData.model_validate(one(source, "echo.result")).model_dump()
        summary = EchoData.model_validate(record["summaries"][source]["echo"]).model_dump()
        if result != summary or result["session_id"] != record["session_id"]:
            exclude("result_summary_mismatch")
        if not result["valid"]:
            exclude(result["reason"])
        spec = record["plan"]["spec"]
        expected = known_data(spec["source_seed"], 1, spec["message_bytes"])
        if (
            bytes.fromhex(result["reply_hex"] or "") != expected
            or result["payload_bytes"] != len(expected)
            or result["payload_sha256"] != hashlib.sha256(expected).hexdigest()
            or not record.get("verification", {}).get("bytes_equal")
        ):
            exclude("content_mismatch")
        request_tx, reply_tx = one(source, "tx.attempt"), one(peer, "tx.attempt")
        request_rx, reply_rx = one(peer, "rx.accepted"), one(source, "rx.accepted")
        frame_size = 40 + len(expected) + (16 if spec["security"] == "aes128_gcm" else 0)
        for role, tx, rx, origin, sequence, kind in (
            (peer, request_tx, request_rx, source, result["request_frame_seq"], "echo_request"),
            (source, reply_tx, reply_rx, peer, result["reply_frame_seq"], "echo_reply"),
        ):
            if (
                tx["session_id"] != record["session_id"]
                or tx["frame_seq"] != sequence
                or tx["message_id"] != 1
                or tx["fragment_index"] != 0
                or tx["frame_type"] != kind
                or tx["frame_bytes"] != frame_size
                or tx["status"] != "completed"
                or tx["attempt_index"] != 1
                or tx["tx_command_us"] is None
                or tx["tx_done_us"] is None
                or tx["tx_done_us"] < tx["tx_command_us"]
                or rx["session_id"] != record["session_id"]
                or rx["frame_seq"] != sequence
                or rx["source_role"] != origin
                or rx["message_id"] != 1
                or rx["fragment_index"] != 0
                or rx["payload_bytes"] != len(expected)
            ):
                exclude("unmatched_request_or_reply")
            observed = [
                row
                for row in rows(role, "rx.frame")
                if (
                    row["session_id"] == record["session_id"]
                    and row["frame_seq"] == sequence
                    and row["source_role"] == origin
                    and row["frame_type"] == kind
                    and row["message_id"] == 1
                    and row["fragment_index"] == 0
                    and row["frame_bytes"] == frame_size
                    and row["crc_ok"]
                    and row["rx_done_us"] <= rx["accepted_us"]
                )
            ]
            if not observed:
                exclude("missing_receive_observation")
        if (
            result["tx_command_us"] != request_tx["tx_command_us"]
            or result["reply_accepted_us"] != reply_rx["accepted_us"]
            or reply_rx["accepted_us"] < request_tx["tx_done_us"]
            or reply_tx["tx_command_us"] < request_rx["accepted_us"]
        ):
            exclude("local_timestamp_mismatch")
        host = record.get("host_transaction") or {}
        samples.append(
            {
                "run_id": record["id"],
                "requester": source,
                "device_id": record["identities"][source]["device_id"],
                "boot_id": record["identities"][source]["boot_id"],
                **result,
                "host_transaction_ns": host.get("elapsed_ns"),
            }
        )
    except (ValueError, KeyError, TypeError) as exc:
        reason = exc.reason if isinstance(exc, _Excluded) else "malformed_evidence"
        detail = exc.detail if isinstance(exc, _Excluded) else str(exc)[:240]
        exclusions.append(
            {
                "run_id": record.get("id"),
                "reason": reason or "malformed_evidence",
                "detail": detail or None,
            }
        )
    return {
        **_distribution(samples),
        "samples": samples,
        "exclusions": exclusions,
        "rejections": rejected[:128],
        "rejection_count": len(rejected),
        "rejections_truncated": len(rejected) > 128,
        "clock_scope": "requester_device_and_boot",
        "phase": "confirmed_request_tx_command_to_verified_reply_acceptance",
        "hardware_qualified": False,
    }


def distributions(records):
    seen, groups = set(), {}
    for record in records:
        if len(seen) >= 1000:
            raise ValueError("Select at most 1000 echo runs")
        if record["id"] in seen:
            raise ValueError("Select distinct runs; duplicate run ID")
        seen.add(record["id"])
        source, peer = record["sender"], record["receiver"]
        spec = record["plan"]["spec"]
        cohort = {
            "requester": source,
            "responder": peer,
            "requester_identity": {
                key: record["identities"][source][key] for key in ("device_id", "boot_id")
            },
            "responder_identity": {
                key: record["identities"][peer][key] for key in ("device_id", "boot_id")
            },
            "radio": record["plan"]["radio"],
            "link": record["plan"]["link"],
            "security": spec["security"],
            "message_bytes": spec["message_bytes"],
            "source_seed": spec["source_seed"],
            "timeout_ms": spec.get("max_duration_ms"),
            "execution_schema_sha256": record.get("execution_schema_sha256"),
        }
        key = json.dumps(cohort, sort_keys=True, separators=(",", ":"))
        group = groups.setdefault(
            key,
            {
                "cohort": cohort,
                "samples": [],
                "exclusions": [],
                "rejections": [],
                "rejection_count": 0,
            },
        )
        result = assess(record)
        for name in ("samples", "exclusions"):
            group[name].extend(result[name])
        group["rejections"].extend(
            {"run_id": record["id"], **row}
            for row in result["rejections"][: max(0, 128 - len(group["rejections"]))]
        )
        group["rejection_count"] += result["rejection_count"]
    for group in groups.values():
        group.update(_distribution(group["samples"]))
        group["rejections_truncated"] = group["rejection_count"] > len(group["rejections"])
    return {
        "groups": list(groups.values()),
        "selected_runs": len(seen),
        "hardware_qualified": False,
    }
