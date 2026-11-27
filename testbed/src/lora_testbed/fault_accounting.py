"""Correlate a controlled bench fault with retained, role-bound observations."""

import hashlib

from .radio_accounting import failed_ranges


def _data(run, role, name):
    return [row for row in run["events"] if row["role"] == role and row["name"] == name]


def _identity(data):
    return (
        data.get("session_id"),
        data.get("frame_seq"),
        data.get("message_id"),
        data.get("fragment_index"),
    )


def _refs(*rows):
    return [
        {"role": row["role"], "name": row["name"], "event_seq": row["event_seq"]} for row in rows
    ]


def verified_control(run):
    return (
        run["status"] == "completed"
        and bool((run.get("verification") or {}).get("bytes_equal"))
        and bool((run.get("accounting") or {}).get("evidence_complete"))
        and bool((run.get("cleanup") or {}).get("confirmed"))
        and not run.get("evidence_error")
    )


def matched_controls(before, run, after):
    """Require fresh, intact runs on the same connections with the same workload."""

    def settings(value):
        return {
            role: {key: applied[key] for key in ("radio", "link")}
            for role, applied in value["applied_settings"].items()
        }

    return (
        all(verified_control(control) and not control.get("lab") for control in (before, after))
        and len({before["session_id"], run["session_id"], after["session_id"]}) == 3
        and before["plan"] == run["plan"] == after["plan"]
        and before["physical_bindings"] == run["physical_bindings"] == after["physical_bindings"]
        and settings(before) == settings(run) == settings(after)
        and before["verification"]["sha256"] == after["verification"]["sha256"]
    )


def assess_exhaustion(run, targets, require):
    lab = run["lab"]
    sender, receiver = run["sender"], run["receiver"]
    report = lab.get("report") or {}
    planned_attempts = list(range(1, run["plan"]["link"]["max_retries"] + 2))
    target_ids = {target["injection_id"] for target in targets}
    applied = [
        event
        for event in _data(run, receiver, "fault.applied")
        if event["data"]["injection_id"] in target_ids
    ]
    if not require(
        "every_planned_drop_applied",
        lab["role"] == receiver
        and [target["attempt_index"] for target in targets] == planned_attempts
        and len(applied) == len(targets)
        and all(
            all(event["data"][key] == value for key, value in target.items())
            and event["data"]["session_id"] == run["session_id"]
            for event, target in zip(applied, targets, strict=True)
        )
        and report.get("session_id") == run["session_id"]
        and report.get("count") == len(targets)
        and report.get("eof")
        and report.get("entries")
        == [
            {key: value for key, value in event["data"].items() if key != "session_id"}
            for event in applied
        ],
        evidence=_refs(*applied),
    ):
        return

    first = applied[0]["data"]
    sequence, fragment = first["target_frame_seq"], first["fragment_index"]
    identity = (run["session_id"], sequence, first["message_id"], fragment)
    digest = first["before_sha256"]
    attempts = [
        event for event in _data(run, sender, "tx.attempt") if _identity(event["data"]) == identity
    ]
    received = [
        event for event in _data(run, receiver, "rx.frame") if _identity(event["data"]) == identity
    ]
    require(
        "all_attempts_reused_exact_protected_bytes",
        [event["data"]["attempt_index"] for event in attempts] == planned_attempts
        and all(
            event["data"]["status"] == "completed" and event["data"]["wire_sha256"] == digest
            for event in attempts
        ),
        evidence=_refs(*attempts),
    )
    require(
        "all_drops_match_distinct_crc_valid_arrivals",
        len(received) == len(targets)
        and len({event["data"]["rx_done_us"] for event in received}) == len(targets)
        and all(
            event["data"]["source_role"] == sender
            and event["data"]["crc_ok"]
            and event["data"]["wire_sha256"] == digest
            and drop["data"]["target_frame_seq"] == sequence
            and drop["data"]["before_sha256"] == drop["data"]["after_sha256"] == digest
            and drop["data"]["target_arrived_us"] == event["data"]["rx_done_us"]
            for event, drop in zip(received, applied, strict=True)
        ),
        evidence=_refs(*received, *applied),
    )
    responses = [
        event
        for event in _data(run, sender, "ack.result")
        if event["data"]["acked_frame_seq"] == sequence
    ]
    send_summary = run["summaries"][sender]
    receive_summary = run["summaries"][receiver]
    first_tx = send_summary["first_tx_command_us"]
    elapsed = responses[-1]["uptime_us"] - first_tx if responses and first_tx is not None else None
    require(
        "bounded_ack_exhaustion",
        [event["data"]["attempt_index"] for event in responses] == planned_attempts
        and all(event["data"]["status"] == "timeout" for event in responses)
        and send_summary["stop_reason"] == "timeout"
        and send_summary["failed_messages"] == 1
        and elapsed is not None
        and 0 < elapsed <= run["plan"]["spec"]["max_duration_ms"] * 1000,
        evidence=_refs(*responses),
    )
    accepted = _data(run, receiver, "rx.accepted")
    ranges = failed_ranges(run)
    require(
        "exhaustion_no_partial_delivery",
        receive_summary["delivered_messages"] == 0
        and receive_summary["useful_delivered_bytes"] == 0,
        outcome="fail",
    )
    require(
        "exhaustion_failed_message_and_missing_suffix",
        receive_summary["failed_messages"] == 1
        and [event["data"]["fragment_index"] for event in accepted] == list(range(fragment))
        and send_summary["original_packets"] == fragment + 1
        and bool(ranges and ranges.get("ranges_complete"))
        and ranges["missing_indexes"] == list(range(fragment, ranges["fragment_count"])),
        evidence=_refs(*accepted),
    )


def assess_incomplete_drop(run, expected, target, require):
    """Compare the missing report against actual TX and unique receiver insertion."""
    sender, receiver = run["sender"], run["receiver"]
    receive = run["summaries"][receiver]
    sending = run["summaries"][sender]
    capacity = run["plan"]["link"]["fragment_payload_bytes"]
    count = (len(expected) + capacity - 1) // capacity
    sent = _data(run, sender, "tx.attempt")
    inserted = _data(run, receiver, "rx.accepted")
    actual = {row["data"]["fragment_index"]: row["data"] for row in sent}
    wanted = set(range(count)) - {target}
    required = {row["data"]["fragment_index"]: row["data"] for row in inserted}
    observed = {
        (_identity(row["data"]), row["data"].get("wire_sha256"))
        for row in _data(run, receiver, "rx.frame")
        if row["data"]["crc_ok"]
        and row["data"]["frame_type"] == "data"
        and row["data"]["source_role"] == sender
    }
    messages = _data(run, receiver, "message.result")
    require(
        "no_partial_message_result",
        not any(event["data"]["status"] == "delivered" for event in messages),
        evidence=_refs(*messages),
        outcome="fail",
    )
    require(
        "bounded_incomplete_message",
        receive["stop_reason"] == "timeout"
        and receive["failed_messages"] == 1
        and len(messages) == 1
        and messages[0]["data"]["status"] == "failed"
        and messages[0]["data"]["complete_us"] is None
        and messages[0]["data"]["sha256"] is None,
        evidence=_refs(*messages),
    )
    require(
        "all_other_fragments_inserted_once",
        len(sent) == sending["original_packets"] == sending["tx_attempts"] == count
        and set(actual) == set(range(count))
        and len({frame["frame_seq"] for frame in actual.values()}) == count
        and all(
            frame["session_id"] == run["session_id"]
            and frame["message_id"] == run.get("message_id", 1)
            and frame["frame_type"] == "data"
            and frame["attempt_index"] == 1
            and frame["status"] == "completed"
            and frame["frame_bytes"]
            == 40
            + min(capacity, len(expected) - index * capacity)
            + (16 if run["plan"]["spec"]["security"] == "aes128_gcm" else 0)
            and (_identity(frame), frame.get("wire_sha256")) in observed
            for index, frame in actual.items()
        )
        and set(required) == wanted
        and len(inserted) == receive["accepted_fragments"] == len(wanted)
        and all(
            _identity(frame) == _identity(actual[index])
            and frame["source_role"] == sender
            and frame["payload_bytes"] == min(capacity, len(expected) - index * capacity)
            for index, frame in required.items()
        ),
        evidence=_refs(*sent, *inserted),
    )
    require(
        "intact_archived_source",
        (run.get("saved_files") or {}).get("source")
        == {"length_bytes": len(expected), "sha256": hashlib.sha256(expected).hexdigest()},
    )


def assess(run, expected):
    checks = []

    def require(code, condition, *, evidence=(), outcome="inconclusive"):
        checks.append(
            {"code": code, "outcome": "pass" if condition else outcome, "evidence": list(evidence)}
        )
        return condition

    def result():
        outcomes = {row["outcome"] for row in checks}
        verdict = (
            "fail"
            if "fail" in outcomes
            else "inconclusive"
            if "inconclusive" in outcomes
            else "pass"
        )
        return {"outcome": verdict, "checks": checks}

    if not require(
        "complete_bound_run",
        run["status"] == "completed"
        and not run.get("evidence_error")
        and (run.get("cleanup") or {}).get("confirmed")
        and len(run["summaries"]) == 2
        and all(not s["telemetry_drops"] for s in run["summaries"].values()),
    ):
        return result()

    lab = run["lab"]
    if targets := lab.get("exhaustion_targets"):
        assess_exhaustion(run, targets, require)
        return result()
    selected, role = lab["injection"], lab["role"]
    action = selected["action"]
    sender, receiver = run["sender"], run["receiver"]
    applied = [
        row
        for row in _data(run, role, "fault.applied")
        if row["data"]["injection_id"] == selected["injection_id"]
    ]
    report = lab.get("report") or {}
    if not require(
        "exact_applied_target",
        len(applied) == 1
        and applied[0]["data"]["session_id"] == run["session_id"]
        and all(applied[0]["data"][key] == value for key, value in selected.items())
        and report.get("session_id") == run["session_id"]
        and report.get("count") == 1
        and report.get("eof")
        and report.get("entries")
        == [{k: v for k, v in applied[0]["data"].items() if k != "session_id"}],
        evidence=_refs(*applied),
    ):
        return result()

    row = applied[0]["data"]
    target = (run["session_id"], row["target_frame_seq"], row["message_id"], row["fragment_index"])
    attempts = [e for e in _data(run, sender, "tx.attempt") if _identity(e["data"]) == target]
    source_attempt = row["attempt_index"] if role == sender else 1
    originals = [
        e
        for e in attempts
        if e["data"]["attempt_index"] == source_attempt and e["data"]["status"] == "completed"
    ]
    selected_sha = row["after_sha256"]
    require(
        "confirmed_target_transmission",
        len(originals) == 1 and originals[0]["data"]["wire_sha256"] == selected_sha,
        evidence=_refs(*attempts),
    )
    received = [
        e
        for e in _data(run, receiver, "rx.frame")
        if _identity(e["data"]) == target
        and e["data"]["source_role"] == sender
        and e["data"]["crc_ok"]
        and e["data"].get("wire_sha256") == selected_sha
    ]
    rejected = [e for e in _data(run, receiver, "rx.rejected") if _identity(e["data"]) == target]
    accepted = [e for e in _data(run, receiver, "rx.accepted") if _identity(e["data"]) == target]
    extra = action in ("replay", "duplicate")
    arrivals_needed = 2 if extra else 1
    require(
        "matching_crc_valid_arrival", len(received) >= arrivals_needed, evidence=_refs(*received)
    )
    if extra:
        sent = [
            e
            for e in _data(run, sender, "fault.tx")
            if e["data"]["injection_id"] == selected["injection_id"]
        ]
        require(
            "confirmed_exact_extra_transmission",
            len(sent) == 1
            and _identity(sent[0]["data"]) == target
            and sent[0]["data"]["status"] == "completed"
            and sent[0]["data"]["wire_sha256"] == selected_sha == row["before_sha256"],
            evidence=_refs(*sent),
        )
    if action in ("xor_byte", "replay", "duplicate") and len(received) >= arrivals_needed:
        expected_reasons = {
            "xor_byte": {"authentication_failed"},
            "replay": {"replay", "too_old"},
            "duplicate": {"replay", "duplicate"},
        }[action]
        arrival = received[arrivals_needed - 1]["data"]["rx_done_us"]
        stage = "authentication" if action == "xor_byte" else "replay"
        require(
            "expected_receiver_rejection",
            any(
                e["data"]["rx_done_us"] == arrival
                and e["data"]["stage"] == stage
                and e["data"]["reason"] in expected_reasons
                for e in rejected
            ),
            evidence=_refs(*rejected),
        )
        if action == "xor_byte":
            require(
                "changed_wire_digest",
                row["before_sha256"] != selected_sha,
                evidence=_refs(applied[0]),
                outcome="fail",
            )
    if action == "duplicate":
        first_arrival = received[0]["data"]["rx_done_us"] if received else None
        next_arrival = received[1]["data"]["rx_done_us"] if len(received) > 1 else None
        require(
            "exactly_one_rejected_duplicate_after_insertion",
            len(received) == 2
            and len(accepted) == 1
            and len(rejected) == 1
            and first_arrival <= accepted[0]["data"]["accepted_us"] < next_arrival
            and rejected[0]["data"]["rx_done_us"] == next_arrival,
            evidence=_refs(*received, *accepted, *rejected),
        )
    if action in ("drop", "drop_ack"):
        matching = [e for e in received if e["data"]["rx_done_us"] == row["target_arrived_us"]]
        require(
            "exact_receiver_opportunity",
            len(matching) == 1 and row["before_sha256"] == selected_sha,
            evidence=_refs(*matching),
        )
        later = [e for e in received if e["data"]["rx_done_us"] > row["target_arrived_us"]]
        if action == "drop":
            require(
                "drop_did_not_insert",
                all(e["data"]["accepted_us"] > row["applied_us"] for e in accepted)
                and (not accepted or bool(later)),
                evidence=_refs(*accepted),
                outcome="fail",
            )
        else:
            require(
                "ack_suppressed_after_insertion",
                len(accepted) == 1
                and matching
                and row["target_arrived_us"]
                <= accepted[0]["data"]["accepted_us"]
                <= row["applied_us"],
                evidence=_refs(*accepted),
            )
        policy = run["plan"]["link"]
        if policy["ack_mode"] == "stop_wait" and policy["max_retries"]:
            acked = [
                e
                for e in _data(run, sender, "ack.result")
                if e["data"]["acked_frame_seq"] == row["target_frame_seq"]
                and e["data"]["status"] == "received"
            ]
            require(
                "identical_bounded_retry_and_valid_ack",
                len(attempts) == 2
                and [e["data"]["attempt_index"] for e in attempts] == [1, 2]
                and all(
                    e["data"]["status"] == "completed" and e["data"]["wire_sha256"] == selected_sha
                    for e in attempts
                )
                and later
                and len(acked) == 1
                and acked[0]["data"]["attempt_index"] == 2
                and acked[0]["data"]["status"] == "received",
                evidence=_refs(*attempts, *acked),
            )
    if action == "reverse_block":
        start, size = row["fragment_index"], row["block_size"]
        capacity = run["plan"]["link"]["fragment_payload_bytes"]
        count = (len(expected) + capacity - 1) // capacity
        expected_order = [
            *range(start),
            *range(start + size - 1, start - 1, -1),
            *range(start + size, count),
        ]
        wires = _data(run, sender, "tx.attempt")
        arrival = [
            e
            for e in _data(run, receiver, "rx.frame")
            if e["data"]["frame_type"] == "data"
            and e["data"]["crc_ok"]
            and e["data"]["source_role"] == sender
        ]
        acceptance = _data(run, receiver, "rx.accepted")
        transmit_ids = [_identity(e["data"]) for e in wires]
        require(
            "complete_reversed_block",
            [e["data"]["fragment_index"] for e in wires] == expected_order
            and transmit_ids == [_identity(e["data"]) for e in arrival]
            and transmit_ids == [_identity(e["data"]) for e in acceptance]
            and all(
                e["data"]["attempt_index"] == 1 and e["data"]["status"] == "completed"
                for e in wires
            )
            and all(
                tx["data"].get("wire_sha256") is not None
                and tx["data"]["wire_sha256"] == rx["data"].get("wire_sha256")
                and rx["data"]["rx_done_us"] <= accepted_row["data"]["accepted_us"]
                for tx, rx, accepted_row in zip(wires, arrival, acceptance, strict=True)
            ),
            evidence=_refs(*wires, *arrival, *acceptance),
        )
    receive_summary = run["summaries"][receiver]
    send_summary = run["summaries"][sender]
    delivered = receive_summary["delivered_messages"]
    should_miss = action == "xor_byte" or (
        action == "drop" and not run["plan"]["link"]["max_retries"]
    )
    if should_miss:
        ranges = failed_ranges(run)
        require(
            "no_partial_delivery",
            delivered == 0 and receive_summary["useful_delivered_bytes"] == 0,
            outcome="fail",
        )
        require(
            "exact_missing_fragment",
            bool(ranges and ranges.get("ranges_complete"))
            and ranges["missing_indexes"] == [row["fragment_index"]]
            and send_summary["original_packets"] == ranges["fragment_count"],
        )
        if action == "drop" and run["plan"]["link"]["ack_mode"] == "none":
            assess_incomplete_drop(run, expected, row["fragment_index"], require)
    else:
        verification = run.get("verification") or {}
        require("single_application_delivery", delivered <= 1, outcome="fail")
        require(
            "verified_recovered_content",
            delivered == 1
            and verification.get("bytes_equal")
            and verification.get("sha256") == hashlib.sha256(expected).hexdigest(),
            outcome="inconclusive",
        )
        if extra:
            require(
                "duplicate_not_inserted_twice",
                len(accepted) <= 1,
                evidence=_refs(*accepted),
                outcome="fail",
            )
    return result()
