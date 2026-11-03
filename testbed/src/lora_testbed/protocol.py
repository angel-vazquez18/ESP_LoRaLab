"""Bounded NDJSON framing retained for historical v1 protocol compatibility checks."""

import json

from pydantic import ValidationError

from .models import Command, NodeEvent, Reply

MAX_LINE_BYTES = 4096  # Includes terminating LF; negotiated protocol ceiling.
WireRecord = Command | Reply | NodeEvent


def encode(record: WireRecord) -> bytes:
    payload = record.model_dump_json().encode("utf-8") + b"\n"
    if len(payload) > MAX_LINE_BYTES:
        raise ValueError("Record exceeds the protocol line limit")
    return payload


class Decoder:
    """Recover at the next LF after malformed or oversized records.

    Each feed returns valid records and diagnostics. Callers must preserve
    diagnostics; framing faults must never silently become apparent RF loss.
    """

    def __init__(self):
        self.buffer = bytearray()
        self.discarding = False

    def feed(self, chunk: bytes) -> tuple[list[WireRecord], list[str]]:
        records: list[WireRecord] = []
        errors: list[str] = []
        for value in chunk:
            if value == 10:
                if self.discarding:
                    self.discarding = False
                    self.buffer.clear()
                    continue
                line = bytes(self.buffer).rstrip(b"\r")
                self.buffer.clear()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                    model = {"command": Command, "reply": Reply, "event": NodeEvent}[raw["kind"]]
                    records.append(model.model_validate(raw))
                except (ValueError, KeyError, TypeError, ValidationError):
                    errors.append("invalid_record")
            elif not self.discarding:
                self.buffer.append(value)
                if len(self.buffer) >= MAX_LINE_BYTES:
                    self.buffer.clear()
                    self.discarding = True
                    errors.append("line_too_long")
        return records, errors
