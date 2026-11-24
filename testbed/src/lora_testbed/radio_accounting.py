"""Reconcile observed DATA/ACK identities without treating telemetry gaps as RF loss."""

import hashlib


def reconcile(record, expected):
    sender, receiver = record["sender"], record["receiver"]
    link = record["plan"]["link"]
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
        if row["frame_type"] != "data" or row["frame_bytes"] != 40 + size:
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
            or row["frame_bytes"] != 40
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
    for row in ack_rx:
        bound(row)
        if (
            row["source_role"] != receiver
            or row["frame_bytes"] != 40
            or identity(row) not in ack_identities
        ):
            invalid("ACK receive observation lacks its transmission")
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
