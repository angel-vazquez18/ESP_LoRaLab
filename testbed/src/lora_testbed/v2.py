"""Strict diagnostic subset of contract 2.0.0; legacy RF runs remain v1."""

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import Field, TypeAdapter, model_validator

from .models import StrictModel

CONTRACT_VERSION = "2.0.0"
MAX_LINE_BYTES = 4096
Identifier = Annotated[str, Field(min_length=1, max_length=96)]
Counter = Annotated[int, Field(ge=0, le=2**53 - 1)]


class Capabilities(StrictModel):
    radio: bool = False
    audio_capture: bool = False
    audio_playback: bool = False
    codec2_3200: bool = False
    security_gcm: bool = False
    fragmentation: bool = False
    ack_retry: bool = False
    echo: bool = False
    clock_sync: bool = False
    memory_stats: bool = True
    fault_injection: bool = False
    radio_limits: dict = Field(default_factory=dict)
    resource_limits: dict = Field(default_factory=dict)
    timestamp_resolution_us: int = Field(default=1, gt=0)


class Heap(StrictModel):
    free_bytes: Counter
    minimum_free_bytes: Counter
    largest_free_bytes: Counter


class Memory(StrictModel):
    internal: Heap
    psram: Heap | None
    buffers: dict[str, Counter] = Field(default_factory=dict)
    allocation_failures: Counter = 0


class NodeError(StrictModel):
    code: Identifier
    message: str = Field(max_length=160)
    field: str | None = None
    retryable: bool = False


class Health(StrictModel):
    node_role: Literal["A", "B"] | None
    state: Literal[
        "idle", "preparing", "prepared", "armed", "running", "draining", "stopping", "faulted"
    ]
    run_id: str | None
    operation_id: str | None
    uptime_us: Counter
    reset_cause: str
    radio: dict | None
    link: dict | None
    config_revision: Counter
    capability_availability: Capabilities
    memory: Memory
    traffic: dict[str, Counter]
    security_ready: bool
    audio_state: str
    telemetry_drops: Counter
    last_error: NodeError | None
    last_rx: dict | None


class Hello(StrictModel):
    device_id: Identifier
    boot_id: Identifier
    board_model: str | None
    board_revision: str | None
    chip_model: str
    firmware_version: str
    firmware_commit: str | None
    firmware_build_id: str
    idf_version: str
    board_manifest_hash: str | None
    provenance: Literal["hardware", "simulated"]
    supported_wire_versions: list[int]
    contract_version: str
    schema_sha256: str
    capabilities: Capabilities
    claimed: bool
    state: str


class Command(StrictModel):
    v: Literal[2] = 2
    kind: Literal["command"] = "command"
    command_id: Identifier
    client_id: Identifier
    command_seq: int = Field(ge=1, le=2**32 - 1)
    target_boot_id: Identifier | None
    run_id: str | None = None
    name: str = Field(min_length=1, max_length=64)
    args: dict[str, Any] = Field(default_factory=dict)


class Reply(StrictModel):
    v: Literal[2] = 2
    kind: Literal["reply"] = "reply"
    command_id: Identifier
    command_seq: int = Field(ge=1, le=2**32 - 1)
    device_id: Identifier
    boot_id: Identifier
    uptime_us: Counter
    ok: bool
    result: dict | None
    error: NodeError | None

    @model_validator(mode="after")
    def consistent_outcome(self):
        if self.ok != (self.result is not None and self.error is None):
            raise ValueError("Reply outcome does not match result/error")
        if not self.ok and (self.result is not None or self.error is None):
            raise ValueError("Failure requires an error and null result")
        return self


class Event(StrictModel):
    v: Literal[2] = 2
    kind: Literal["event"] = "event"
    device_id: Identifier
    boot_id: Identifier
    node_role: Literal["A", "B"] | None
    event_seq: Counter
    uptime_us: Counter
    run_id: str | None
    name: Literal["health", "diagnostic"]
    data: dict

    @model_validator(mode="after")
    def validate_data(self):
        if self.name == "health":
            self.data = Health.model_validate(self.data).model_dump()
        elif set(self.data) != {"severity", "code", "message", "related_command_id"}:
            raise ValueError("Malformed diagnostic event")
        return self


WireRecord = Annotated[Command | Reply | Event, Field(discriminator="kind")]
ADAPTER = TypeAdapter(WireRecord)


def schema() -> dict:
    return {"contract_version": CONTRACT_VERSION, "scope": "diagnostic", **ADAPTER.json_schema()}


def schema_digest() -> str:
    return hashlib.sha256(
        json.dumps(schema(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def encode(record: Command | Reply | Event) -> bytes:
    wire = record.model_dump_json().encode() + b"\n"
    if len(wire) > MAX_LINE_BYTES:
        raise ValueError("Record exceeds 4096 bytes")
    return wire


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def depth(value) -> int:
    if isinstance(value, dict):
        return 1 + max((depth(item) for item in value.values()), default=0)
    if isinstance(value, list):
        return 1 + max((depth(item) for item in value), default=0)
    return 0


class Decoder:
    def __init__(self, adapter=ADAPTER):
        self.adapter = adapter
        self.buffer = bytearray()
        self.discarding = False

    def feed(self, chunk: bytes) -> tuple[list, list[str]]:
        records, errors = [], []
        for byte in chunk:
            if byte == 10:
                if not self.discarding and self.buffer:
                    try:
                        raw = json.loads(
                            self.buffer.decode("utf-8"),
                            object_pairs_hook=unique_object,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
                        )
                        if depth(raw) > 8:
                            raise ValueError("JSON nesting exceeds eight levels")
                        records.append(self.adapter.validate_python(raw))
                    except (ValueError, TypeError, RecursionError):
                        errors.append("invalid_record")
                self.buffer.clear()
                self.discarding = False
            elif not self.discarding:
                self.buffer.append(byte)
                if len(self.buffer) >= MAX_LINE_BYTES:
                    self.buffer.clear()
                    self.discarding = True
                    errors.append("line_too_long")
        return records, errors
