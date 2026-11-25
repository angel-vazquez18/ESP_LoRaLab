"""Fixed IF-01 C3 inputs and independent framing observations."""

import hashlib

from . import physical_wire_v2, v2

INVALID_LINES = {
    "oversized_record": (b"x" * v2.MAX_LINE_BYTES + b"\n", "rx_oversized"),
    "duplicate_key": (b'{"fixture":1,"fixture":2}\n', "rx_json_rejected"),
    "invalid_utf8": (b'{"fixture":"\xff"}\n', "rx_json_rejected"),
    "malformed_json": (b'{"fixture":}\n', "rx_json_rejected"),
}
STATUS_COUNTS = {"concatenated_records": 2, "representative_board_splits": 3}
VARIANTS = frozenset(
    (*INVALID_LINES, *STATUS_COUNTS, "split_every_boundary", "crlf_record", "maximum_size_record")
)
REJECTION_COUNTERS = (
    "rx_oversized",
    "rx_json_rejected",
    "rx_envelope_rejected",
    "rx_backpressure",
    "reply_drops",
)


def split_for_transport(line):
    return [line[i : i + 1024] for i in range(0, len(line), 1024)]


def batches(variant, lines):
    """Return bounded groups of status writes and the status records each should yield."""
    invalid = INVALID_LINES.get(variant)
    if invalid:
        return [(split_for_transport(invalid[0]) + lines, 1)]
    if variant == "crlf_record":
        return [([lines[0][:-1] + b"\r\n"], 1)]
    if variant == "maximum_size_record":
        line = lines[0]
        padded = line[:-1] + b" " * (v2.MAX_LINE_BYTES - len(line)) + b"\n"
        return [(split_for_transport(padded), 1)]
    if variant == "concatenated_records":
        return [([b"".join(lines)], 2)]
    if variant == "representative_board_splits":
        offsets = (1, len(lines[1]) // 2, len(lines[2]) - 1)
        return [([line[:at], line[at:]], 1) for line, at in zip(lines, offsets, strict=True)]
    return [(lines, 1)]


def exercise_decoder(reply):
    """Check the production receive decoder on every split of the observed reply."""
    wire = v2.encode(reply)
    count = 0
    for offset in range(1, len(wire)):
        decoder = v2.Decoder(adapter=physical_wire_v2.ADAPTER)
        first, first_errors = decoder.feed(wire[:offset])
        second, second_errors = decoder.feed(wire[offset:])
        if first or first_errors or second != [reply] or second_errors:
            break
        count += 1
    return {
        "scope": "host decoder fixture using the re-encoded observed reply",
        "reply_sha256": hashlib.sha256(wire).hexdigest(),
        "checked_boundaries": count,
        "expected_boundaries": len(wire) - 1,
    }


def assess_counters(variant, before, after):
    prior, latest = before["traffic"], after["traffic"]
    missing = [key for key in REJECTION_COUNTERS if key not in prior or key not in latest]
    if missing:
        return {"outcome": "inconclusive", "missing_counters": missing}
    expected_rejection = INVALID_LINES[variant][1] if variant in INVALID_LINES else None
    expected = {key: int(key == expected_rejection) for key in REJECTION_COUNTERS}
    observed = {key: latest[key] - prior[key] for key in REJECTION_COUNTERS}
    return {
        "outcome": "pass" if expected == observed else "fail",
        "expected_deltas": expected,
        "observed_deltas": observed,
    }
