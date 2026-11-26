"""Reconcile observed DATA/ACK identities without treating telemetry gaps as RF loss."""

import hashlib


def transfer_rates(record, transmissions, accepted_bytes, delivered_bytes):
    sender = record["sender"]
    summary = record["summaries"][sender]
    first, last = summary["first_tx_command_us"], summary["last_tx_done_us"]
    complete = [row for row in transmissions if row["status"] == "completed"]
    valid = (
        bool(complete)
        and first is not None
        and last is not None
        and first < last
        and all(
            row["tx_command_us"] is not None and row["tx_done_us"] is not None for row in complete
        )
        and min(row["tx_command_us"] for row in complete) == first
        and max(row["tx_done_us"] for row in complete) == last
    )
    interval_us = last - first if valid else None
    drain_us = next(
        (
            row["data"]["budget"]["drain_us"]
            for row in record["events"]
            if row["role"] == sender and row["name"] == "run.prepared"
        ),
        None,
    )
    return {
        "sender_transfer_window": {
            "basis": "sender first DATA TX command through final DATA TX done",
            "first_tx_command_us": first,
            "last_tx_done_us": last,
            "duration_us": interval_us,
            "configured_drain_us": drain_us,
            "unavailable_reason": None
            if valid
            else "Sender window is zero or differs from DATA observations",
        },
        "accepted_fragment_bytes": accepted_bytes,
        "verified_delivered_bytes": delivered_bytes,
        "accepted_fragment_bps": 8_000_000 * accepted_bytes / interval_us if valid else None,
        "goodput_bps": 8_000_000 * delivered_bytes / interval_us if valid else None,
    }


def reconcile(record, expected):
    sender, receiver = record["sender"], record["receiver"]
    link = record["plan"]["link"]
    protected = record["plan"]["spec"].get("security", "none") == "aes128_gcm"
    tag_bytes = 16 if protected else 0
    capacity = link["fragment_payload_bytes"]
    count = (len(expected) + capacity - 1) // capacity

    def rows(role, name):
        return [e["data"] for e in record["events"] if e["role"] == role and e["name"] == name]

    def invalid(reason):
        raise ValueError(
            f"Radio evidence is incomplete or inconsistent: {reason}; do not infer RF loss"
        )

    def identity(row):
        return row["frame_seq"], row["message_id"], row["fragment_index"]

    def bound(row):
        if row.get("session_id") != record["session_id"] or row.get("message_id") != 1:
            invalid("unmatched session/message")
        i = row["fragment_index"]
        if not 0 <= i < count:
            invalid("fragment index outside the message")
        return i, min(capacity, len(expected) - i * capacity)

    transmissions = rows(sender, "tx.attempt")
    originals = {}
    sequences = {}
    groups = {}
    for row in transmissions:
        i, size = bound(row)
        if row["frame_type"] != "data" or row["frame_bytes"] != 40 + size + tag_bytes:
            invalid("DATA type or final body length")
        sequence = row["frame_seq"]
        if i in sequences and sequences[i] != sequence:
            invalid("multiple originals for one fragment")
        if sequence in groups and groups[sequence][0]["fragment_index"] != i:
            invalid("one sequence names multiple fragments")
        sequences[i] = sequence
        groups.setdefault(sequence, []).append(row)
        if row["status"] == "completed":
            originals[i] = sequence
    if len(originals) != count:
        invalid("missing confirmed DATA originals")
    for attempts in groups.values():
        indexes = sorted(row["attempt_index"] for row in attempts)
        if indexes != list(range(1, len(indexes) + 1)) or len(indexes) > 1 + link["max_retries"]:
            invalid("missing, duplicate or excessive attempt indexes")
    accepted = rows(receiver, "rx.accepted")
    unique = {}
    for row in accepted:
        i, size = bound(row)
        if (
            row["source_role"] != sender
            or row["payload_bytes"] != size
            or row["frame_seq"] != originals[i]
        ):
            invalid("accepted fragment does not match a confirmed original")
        if i in unique:
            invalid("duplicate insertion recorded as new acceptance")
        unique[i] = identity(row)
    if len(unique) != count:
        invalid("missing accepted fragment records")
    observations = rows(receiver, "rx.frame")
    observed = {
        identity(row)
        for row in observations
        if row["crc_ok"]
        and row["frame_type"] == "data"
        and row["session_id"] == record["session_id"]
        and row["source_role"] == sender
        and row["message_id"] == 1
    }
    if not set(unique.values()) <= observed:
        invalid("missing DATA receive observations")
    messages = rows(receiver, "message.result")
    if (
        len(messages) != 1
        or messages[0]["status"] != "delivered"
        or messages[0]["message_id"] != 1
        or messages[0]["sha256"] != hashlib.sha256(expected).hexdigest()
        or messages[0]["message_bytes"] != len(expected)
        or messages[0]["fragment_count"] != count
        or messages[0]["missing_count"]
        or messages[0]["missing_parts"]
        or rows(receiver, "message.missing")
    ):
        invalid("message delivery does not reconcile with exact recovered bytes")
    ack_tx = rows(receiver, "tx.attempt")
    for row in ack_tx:
        bound(row)
        if (
            row["frame_type"] != "ack"
            or row["frame_bytes"] != 40 + tag_bytes
            or row["attempt_index"] != 1
            or row["status"] != "completed"
        ):
            invalid("ACK traffic is not a completed distinct frame")
    ack_identities = {identity(row) for row in ack_tx}
    if len(ack_identities) != len(ack_tx):
        invalid("ACK sequence reused")
    ack_rx = [
        row for row in rows(sender, "rx.frame") if row["crc_ok"] and row["frame_type"] == "ack"
    ]
    accepted_ack_rows = [row for row in rows(sender, "ack.result") if row["status"] == "received"]
    if protected or accepted_ack_rows:
        if len({row["acked_frame_seq"] for row in accepted_ack_rows}) != len(accepted_ack_rows):
            invalid("multiple ACK acceptances for one DATA original")
        accepted_ack_sequences = set()
        for row in accepted_ack_rows:
            original = row["acked_frame_seq"]
            attempts = groups.get(original, [])
            if not attempts or row["attempt_index"] not in {a["attempt_index"] for a in attempts}:
                invalid("accepted ACK lacks its outstanding DATA attempt")
            if row["ack_frame_seq"] in accepted_ack_sequences:
                invalid("accepted ACK sequence reused")
            accepted_ack_sequences.add(row["ack_frame_seq"])
        raw_sequences = {row["frame_seq"] for row in ack_rx}
        if not accepted_ack_sequences <= raw_sequences:
            invalid("accepted ACK lacks its raw RF observation")
        ack_rx = [row for row in ack_rx if row["frame_seq"] in accepted_ack_sequences]
    for row in ack_rx:
        bound(row)
        if (
            row["source_role"] != receiver
            or row["frame_bytes"] != 40 + tag_bytes
            or identity(row) not in ack_identities
        ):
            invalid("accepted ACK lacks its peer transmission")
    reliable = link["ack_mode"] == "stop_wait"
    if (reliable and len(ack_rx) != count) or (not reliable and (ack_tx or ack_rx)):
        invalid("ACK observations do not reconcile with selected policy")
    tx, rx = record["summaries"][sender], record["summaries"][receiver]
    if (
        tx["original_packets"] != count
        or tx["tx_attempts"] != len(transmissions)
        or rx["original_packets"]
        or rx["tx_attempts"] != len(ack_tx)
        or rx["accepted_fragments"] != count
        or rx["delivered_messages"] != 1
        or rx["useful_delivered_bytes"] != len(expected)
        or tx["useful_source_bytes"] != len(expected)
        or rx["radio_observations"] != len(observations)
        or tx["radio_observations"] != len(rows(sender, "rx.frame"))
    ):
        invalid("node totals differ from retained frame/message evidence")
    return {
        "evidence_complete": True,
        "data_originals": count,
        "data_attempts": len(transmissions),
        "data_retries": sum(len(group) - 1 for group in groups.values()),
        "accepted_fragments": len(unique),
        "delivered_messages": 1,
        "ack_transmissions": len(ack_tx),
        "valid_ack_observations": len(ack_rx),
        "unique_original_delivery_ratio": len(unique) / len(originals),
        "receiver_duplicates": rx["duplicates"],
        **transfer_rates(
            record, transmissions, sum(row["payload_bytes"] for row in accepted), len(expected)
        ),
    }


def reconcile_sweep_loss(record, source):
    """Verify observed non-delivery of one confirmed unacknowledged DATA frame."""
    sender, receiver = record["sender"], record["receiver"]
    sent, received = record["summaries"][sender], record["summaries"][receiver]

    def events(role, name):
        return [e["data"] for e in record["events"] if e["role"] == role and e["name"] == name]

    attempts = events(sender, "tx.attempt")
    if len(attempts) != 1:
        raise ValueError("RF sweep loss needs exactly one observed transmission")
    [frame] = attempts
    tag_bytes = 16 if record["plan"]["spec"]["security"] == "aes128_gcm" else 0
    missing = failed_ranges(record)
    if (
        sent["stop_reason"] != "completed"
        or received["stop_reason"] != "timeout"
        or any(summary["telemetry_drops"] for summary in (sent, received))
        or sent["original_packets"] != 1
        or sent["tx_attempts"] != 1
        or sent["useful_source_bytes"] != len(source)
        or received["radio_observations"] != len(events(receiver, "rx.frame"))
        or received["failed_messages"] != 1
        or received["delivered_messages"]
        or received["accepted_fragments"]
        or received["useful_delivered_bytes"]
        or events(receiver, "rx.accepted")
        or events(receiver, "tx.attempt")
        or frame["session_id"] != record["session_id"]
        or frame["message_id"] != 1
        or frame["fragment_index"] != 0
        or frame["frame_type"] != "data"
        or frame["attempt_index"] != 1
        or frame["status"] != "completed"
        or frame["frame_bytes"] != 40 + len(source) + tag_bytes
        or frame["tx_command_us"] != sent["first_tx_command_us"]
        or frame["tx_done_us"] != sent["last_tx_done_us"]
        or not missing
        or not missing["ranges_complete"]
        or missing["missing_indexes"] != [0]
    ):
        raise ValueError("RF sweep evidence does not reconcile a bounded non-delivery")
    return {
        "evidence_complete": True,
        "observed_delivery_failure": True,
        "data_originals": 1,
        "data_attempts": 1,
        "data_retries": 0,
        "accepted_fragments": 0,
        "delivered_messages": 0,
        "unique_original_delivery_ratio": 0.0,
        "receiver_duplicates": received["duplicates"],
        "ack_transmissions": 0,
        "valid_ack_observations": 0,
        **transfer_rates(record, attempts, 0, 0),
        "source_sha256": hashlib.sha256(source).hexdigest(),
    }


def failed_ranges(record):
    """Describe only retained failed-message ranges; absence never fills in RF loss."""
    receiver = record["receiver"]
    results = [
        event["data"]
        for event in record["events"]
        if event["role"] == receiver
        and event["name"] == "message.result"
        and event["data"]["status"] == "failed"
    ]
    if not results:
        if record["summaries"].get(receiver, {}).get("failed_messages", 0):
            return {
                "ranges_complete": False,
                "reason": "No failed-message range report was retained",
            }
        return None

    def incomplete(reason):
        return {"ranges_complete": False, "reason": reason}

    if len(results) != 1:
        return incomplete("Multiple failed-message results conflict")
    result = results[0]
    size = record["plan"]["spec"]["message_bytes"]
    capacity = record["plan"]["link"]["fragment_payload_bytes"]
    count = (size + capacity - 1) // capacity
    if (
        result["message_id"] != 1
        or result["fragment_count"] != count
        or result["message_bytes"] != size
    ):
        return incomplete("Failed-message metadata does not match the prepared message")
    parts = sorted(
        [
            event["data"]
            for event in record["events"]
            if event["role"] == receiver and event["name"] == "message.missing"
        ],
        key=lambda p: p["part_index"],
    )
    if len(parts) != result["missing_parts"] or [p["part_index"] for p in parts] != list(
        range(len(parts))
    ):
        return incomplete("Missing-range parts are absent or duplicated")
    indexes = []
    for part in parts:
        if part["message_id"] != 1 or part["part_count"] != result["missing_parts"]:
            return incomplete("Missing-range part metadata conflicts")
        for start, end in part["ranges"]:
            if start < 0 or end >= count or start > end or (indexes and start <= indexes[-1]):
                return incomplete("Missing-range indexes overlap or exceed the message")
            indexes.extend(range(start, end + 1))
    accepted = record["summaries"].get(receiver, {}).get("accepted_fragments")
    if (
        len(indexes) != result["missing_count"]
        or accepted is None
        or accepted + len(indexes) != count
    ):
        return incomplete("Missing indexes do not reconcile with receiver totals")
    return {
        "ranges_complete": True,
        "fragment_count": count,
        "missing_indexes": indexes,
        "accepted_fragments": accepted,
        "part_count": len(parts),
        "scope": "receiver insertion result; not a classification of RF versus other loss",
    }
