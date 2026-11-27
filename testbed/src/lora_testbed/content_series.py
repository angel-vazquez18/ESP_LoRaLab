"""Known-data workload matrices for boundary sizes and matched protection modes."""

from collections import Counter

from .experiments_v2 import KnownDataPlan, KnownDataSpec, Link, Radio, preview
from .radio_runs import RadioRunRequest

BOUNDARIES = (1, 159, 160, 161, 319, 320, 321, 1200, 48000)
GROUPS = {
    "PKT-01": {"C1": "fragment_boundaries", "C2": "advertised_limits", "C3": "oversize"},
    "SEC-01": {"C1": "paired_single_frame", "C2": "paired_fragmented", "C3": "negative"},
}


def cases(request, groups, message_limit):
    if request.catalog_id == "PKT-01":
        edge_sizes = tuple(
            n for n in (message_limit - 1, message_limit) if n > 0 and n not in BOUNDARIES
        )
        variants = {
            "C1": tuple((f"bytes_{n}", n, request.rf_security) for n in BOUNDARIES),
            "C2": tuple((f"bytes_{n}", n, request.rf_security) for n in edge_sizes),
            "C3": (("above_advertised_limit", message_limit + 1, request.rf_security),),
        }
    else:
        modes = ("none", "aes128_gcm")
        variants = {
            "C1": tuple((f"bytes_{n}_{mode}", n, mode) for n in (16, 64, 160) for mode in modes),
            "C2": tuple((f"fragmented_{mode}", 321, mode) for mode in modes),
            "C3": (("wrong_key", 64, "aes128_gcm"), ("peer_profile_mismatch", 64, "aes128_gcm")),
        }
    for group in groups:
        for variant, size, mode in variants[group]:
            if request.subset_sizes is not None and size not in request.subset_sizes:
                continue
            for direction in request.directions:
                for repetition in range(1, request.repetitions + 1):
                    case = {
                        "group": group,
                        "variant": variant,
                        "repetition": repetition,
                        "driver": (
                            "content_series"
                            if group != "C3"
                            else "resource_refusal"
                            if request.catalog_id == "PKT-01"
                            else "content_negative"
                        ),
                        "role": direction,
                        "direction": direction,
                        "message_bytes": size,
                        "message_count": request.messages_per_case if group != "C3" else 1,
                        "security": mode,
                        "fragment_count": (size + 159) // 160,
                        "final_fragment_bytes": (size - 1) % 160 + 1,
                        "planning_message_limit": message_limit,
                    }
                    if group != "C3":
                        child = run_request(request, case, 0)
                        case["child_budget"] = preview(child.plan())["timing"]["budget"]
                    yield case


def run_request(matrix, case, ordinal):
    seed = (matrix.seed + (case["repetition"] - 1) * 100 + ordinal) % 2**32
    link = Link(fragment_payload_bytes=160, ack_mode="none", max_retries=0)
    radio = Radio(tx_power_dbm=2)
    size, mode, direction = case["message_bytes"], case["security"], case["direction"]
    estimate = preview(
        KnownDataPlan(
            radio=radio,
            link=link,
            spec=KnownDataSpec(
                direction=direction,
                message_bytes=size,
                message_count=1,
                security=mode,
                source_seed=seed,
            ),
        )
    )["timing"]["required_max_duration_ms"]
    return RadioRunRequest(
        direction=direction,
        security=mode,
        message_bytes=size,
        source_seed=seed,
        timeout_ms=max(10000, estimate + 5000),
        radio=radio,
        link=link,
    )


def matched_auth_rejection(record):
    sender, receiver = record["sender"], record["receiver"]
    if (
        record["status"] != "completed"
        or record["verification"] is not None
        or not record["security"].get("controlled_receiver_key_mismatch")
        or not record["cleanup"]["confirmed"]
        or record["summaries"][receiver]["delivered_messages"] != 0
    ):
        return False
    sent = [
        r["data"]
        for r in record["events"]
        if r["role"] == sender
        and r["name"] == "tx.attempt"
        and r["data"]["status"] == "completed"
        and r["data"]["frame_type"] == "data"
    ]
    if len(sent) != 1 or not sent[0].get("wire_sha256"):
        return False
    target = sent[0]
    arrivals = [
        r["data"]
        for r in record["events"]
        if r["role"] == receiver
        and r["name"] == "rx.frame"
        and r["data"]["crc_ok"]
        and r["data"]["frame_type"] == "data"
        and all(
            r["data"][key] == target[key]
            for key in ("session_id", "frame_seq", "message_id", "fragment_index", "wire_sha256")
        )
    ]
    return len(arrivals) == 1 and any(
        r["role"] == receiver
        and r["name"] == "rx.rejected"
        and r["data"]["reason"] == "authentication_failed"
        and r["data"]["stage"] == "authentication"
        and r["data"]["rx_done_us"] == arrivals[0]["rx_done_us"]
        and all(
            r["data"][key] == target[key]
            for key in ("session_id", "frame_seq", "message_id", "fragment_index")
        )
        for r in record["events"]
    )


def protection_observation(record):
    spec = record["plan"]["spec"]
    frames = sorted(
        (
            row["data"]
            for row in record["events"]
            if row["role"] == record["sender"]
            and row["name"] == "tx.attempt"
            and row["data"]["frame_type"] == "data"
            and row["data"]["status"] == "completed"
        ),
        key=lambda row: row["fragment_index"],
    )
    return {
        "security": spec["security"],
        "source_seed": spec["source_seed"],
        "physical_bindings": record["physical_bindings"],
        "frame_bytes": [row["frame_bytes"] for row in frames],
    }


def matched_protection_observations(unprotected, protected, payload_bytes):
    if not unprotected or not protected:
        return False
    source, target = unprotected["protection_observation"], protected["protection_observation"]
    plain_sizes, secure_sizes = source["frame_bytes"], target["frame_bytes"]
    verified_hash = (unprotected.get("verification") or {}).get("sha256")
    settings = []
    for case in (unprotected, protected):
        verification, accounting = case.get("verification") or {}, case.get("accounting") or {}
        if (
            case["status"] != "completed"
            or not case["cleanup_confirmed"]
            or verification.get("bytes_equal") is not True
            or verification["sha256"] != verified_hash
            or verification["length_bytes"] != payload_bytes
            or accounting.get("evidence_complete") is not True
            or accounting["data_attempts"] != accounting["data_originals"]
            or accounting["verified_delivered_bytes"] != payload_bytes
            or set(case["applied_settings"]) != {"A", "B"}
        ):
            return False
        settings.append(
            [(v["radio"], v["link"]) for _, v in sorted(case["applied_settings"].items())]
        )
    return (
        unprotected["session_id"] != protected["session_id"]
        and [source["security"], target["security"]] == ["none", "aes128_gcm"]
        and source["physical_bindings"] == target["physical_bindings"]
        and source["source_seed"] == target["source_seed"]
        and settings[0] == settings[1]
        and len(plain_sizes) == unprotected["accounting"]["data_originals"]
        and len(secure_sizes) == protected["accounting"]["data_originals"]
        and secure_sizes == [length + 16 for length in plain_sizes]
    )


def metric_totals(matched, mode_index, *, timed):
    data = [pair[mode_index] for pair in matched]
    wire = sum(sum(row["protection_observation"]["frame_bytes"]) for row in data)
    delivered = sum(row["accounting"]["verified_delivered_bytes"] for row in data)
    total_frames = sum(row["accounting"]["data_originals"] for row in data)
    accepted_frames = sum(row["accounting"]["accepted_fragments"] for row in data)
    duration = (
        sum(row["accounting"]["sender_transfer_window"]["duration_us"] for row in data)
        if timed
        else None
    )
    return {
        "wire_bytes": wire,
        "framing_bytes": wire - delivered,
        "delivered_bytes": delivered,
        "unique_original_delivery_ratio": accepted_frames / total_frames,
        "sender_transfer_duration_us": duration,
        "goodput_bps": delivered * 8_000_000 / duration if duration else None,
    }


def compare_protection(cases, observations):
    groups = {}
    for case in cases:
        if case["driver"] == "content_series":
            key = (case["group"], case["direction"], case["message_bytes"], case["repetition"])
            groups.setdefault(key, {})[case["security"]] = case
    rows = []
    for (group, direction, size, repetition), modes in groups.items():
        expected = next(iter(modes.values()))["message_count"]
        archives = [
            observations(modes[security]["id"]) if security in modes else {}
            for security in ("none", "aes128_gcm")
        ]
        skipped = Counter()
        matched = []
        for ordinal in range(1, expected + 1):
            plain, secure = (archive.get(ordinal) for archive in archives)
            if matched_protection_observations(plain, secure, size):
                matched.append((plain, secure))
            else:
                skipped[
                    "missing_observation" if not plain or not secure else "mismatched_pair"
                ] += 1
        timed = sum(
            all(
                type(row["accounting"]["sender_transfer_window"]["duration_us"]) is int
                and row["accounting"]["sender_transfer_window"]["duration_us"] > 0
                for row in pair
            )
            for pair in matched
        )
        row = {
            "group": group,
            "direction": direction,
            "message_bytes": size,
            "repetition": repetition,
            "expected_pairs": expected,
            "matched_pairs": len(matched),
            "timed_pairs": timed,
            "unmatched": dict(skipped),
            "status": "complete" if timed == len(matched) == expected else "inconclusive",
        }
        if len(matched) == expected:
            plain, secure = (metric_totals(matched, n, timed=timed == expected) for n in (0, 1))
            row.update(
                unprotected=plain,
                protected=secure,
                overhead_bytes=secure["wire_bytes"] - plain["wire_bytes"],
            )
        rows.append(row)
    return rows
