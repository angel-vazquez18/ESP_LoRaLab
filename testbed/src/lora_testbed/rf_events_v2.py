"""Staged typed RF event schema; not accepted by the diagnostic serial adapter."""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, TypeAdapter, model_validator

from .experiments_v2 import SHA256, Budget
from .experiments_v2 import ContractModel as StrictModel
from .v2 import CONTRACT_VERSION, Counter, Identifier, NodeError

Sequence = Annotated[int, Field(ge=1, le=2**32 - 1)]


def nonzero_session(value: str) -> str:
    if value == "0000000000000000":
        raise ValueError("Session identity must be nonzero")
    return value


SessionID = Annotated[
    str,
    Field(pattern=r"^[0-9a-f]{16}$", json_schema_extra={"not": {"const": "0000000000000000"}}),
    AfterValidator(nonzero_session),
]
RunID = Annotated[
    str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]
FrameType = Literal["data", "ack", "echo_request", "echo_reply"]


class StateData(StrictModel):
    state: Literal[
        "idle", "preparing", "prepared", "armed", "running", "draining", "stopping", "faulted"
    ]
    reason: str | None
    config_revision: Annotated[int, Field(ge=0, le=2**32 - 1)]


class PreparedData(StrictModel):
    config_revision: Annotated[int, Field(ge=0, le=2**32 - 1)]
    budget: Budget
    source_length_bytes: Annotated[int, Field(ge=1, le=65536)] | None
    source_sha256: SHA256 | None


class FrameIdentity(StrictModel):
    session_id: SessionID
    frame_seq: Sequence
    message_id: Sequence
    fragment_index: Annotated[int, Field(ge=0, le=4095)]


class AttemptData(FrameIdentity):
    attempt_index: Annotated[int, Field(ge=1, le=6)]
    frame_type: FrameType
    frame_bytes: Annotated[int, Field(ge=40, le=255)]
    tx_command_us: Counter | None
    tx_done_us: Counter | None
    status: Literal["completed", "failed"]

    @model_validator(mode="after")
    def timestamps(self):
        if self.status == "completed" and (self.tx_command_us is None or self.tx_done_us is None):
            raise ValueError("Completed transmissions require both timestamps")
        if (
            self.tx_command_us is not None
            and self.tx_done_us is not None
            and self.tx_done_us < self.tx_command_us
        ):
            raise ValueError("TX completion precedes its command")
        return self


class ReceivedData(StrictModel):
    session_id: SessionID | None
    source_role: Literal["A", "B"] | None
    frame_seq: Sequence | None
    message_id: Sequence | None
    fragment_index: Annotated[int, Field(ge=0, le=4095)] | None
    frame_type: FrameType | None
    frame_bytes: Annotated[int, Field(ge=0, le=255)]
    rx_done_us: Counter
    rssi_dbm: Annotated[float, Field(allow_inf_nan=False)]
    snr_db: Annotated[float, Field(allow_inf_nan=False)]
    crc_ok: bool


class AcceptedData(FrameIdentity):
    source_role: Literal["A", "B"]
    payload_bytes: Annotated[int, Field(ge=1, le=215)]
    accepted_us: Counter


class MessageData(StrictModel):
    message_id: Sequence
    status: Literal["delivered", "failed"]
    message_bytes: Annotated[int, Field(ge=1, le=65536)]
    sha256: SHA256 | None
    fragment_count: Annotated[int, Field(ge=1, le=4096)]
    missing_count: Annotated[int, Field(ge=0, le=4096)]
    missing_parts: Counter
    first_fragment_us: Counter | None
    complete_us: Counter | None

    @model_validator(mode="after")
    def delivery_evidence(self):
        if self.missing_count > self.fragment_count:
            raise ValueError("Missing count exceeds fragment count")
        if self.status == "delivered" and (
            self.sha256 is None
            or self.first_fragment_us is None
            or self.complete_us is None
            or self.missing_count
            or self.missing_parts
        ):
            raise ValueError("Delivery requires complete content and timing evidence")
        if (
            self.first_fragment_us is not None
            and self.complete_us is not None
            and self.complete_us < self.first_fragment_us
        ):
            raise ValueError("Message completion precedes first fragment")
        return self


class Envelope(StrictModel):
    v: Literal[2] = 2
    kind: Literal["event"] = "event"
    device_id: Identifier
    boot_id: Identifier
    node_role: Literal["A", "B"]
    event_seq: Annotated[int, Field(ge=1, le=2**53 - 1)]
    uptime_us: Counter
    run_id: RunID


class RunState(Envelope):
    name: Literal["run.state"]
    data: StateData


class RunPrepared(Envelope):
    name: Literal["run.prepared"]
    data: PreparedData


class Attempt(Envelope):
    name: Literal["tx.attempt"]
    data: AttemptData


class Received(Envelope):
    name: Literal["rx.frame"]
    data: ReceivedData


class Accepted(Envelope):
    name: Literal["rx.accepted"]
    data: AcceptedData


class MessageResult(Envelope):
    name: Literal["message.result"]
    data: MessageData


class RejectedData(StrictModel):
    session_id: SessionID | None
    source_role: Literal["A", "B"] | None
    frame_seq: Sequence | None
    message_id: Sequence | None
    fragment_index: Annotated[int, Field(ge=0, le=4095)] | None
    stage: Literal["framing", "session", "authentication", "replay", "reassembly"]
    reason: Identifier
    related_injection_id: RunID | None


class Rejected(Envelope):
    name: Literal["rx.rejected"]
    data: RejectedData


class MissingData(StrictModel):
    message_id: Sequence
    part_index: Counter
    part_count: Annotated[int, Field(ge=1)]
    ranges: list[list[int]] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_ranges(self):
        if self.part_index >= self.part_count:
            raise ValueError("Missing-range part index is out of bounds")
        previous = -1
        for pair in self.ranges:
            if len(pair) != 2 or not 0 <= pair[0] <= pair[1] <= 4095 or pair[0] <= previous:
                raise ValueError("Missing ranges must be ordered nonoverlapping index pairs")
            previous = pair[1]
        return self


class Missing(Envelope):
    name: Literal["message.missing"]
    data: MissingData


class SummaryData(StrictModel):
    role: Literal["sender", "receiver"]
    session_id: SessionID
    config_revision: Annotated[int, Field(ge=0, le=2**32 - 1)]
    intended_messages: Counter
    started_messages: Counter
    finished_messages: Counter
    original_packets: Counter
    tx_attempts: Counter
    radio_observations: Counter
    accepted_fragments: Counter
    duplicates: Counter
    delivered_messages: Counter
    failed_messages: Counter
    useful_source_bytes: Counter
    useful_delivered_bytes: Counter
    first_tx_command_us: Counter | None
    last_tx_done_us: Counter | None
    first_rx_us: Counter | None
    last_rx_us: Counter | None
    stop_reason: Literal[
        "completed", "operator", "host_shutdown", "peer_failure", "timeout", "error"
    ]
    telemetry_drops: Counter
    validity_reasons: list[str] = Field(max_length=16)


class Summary(Envelope):
    name: Literal["run.summary"]
    data: SummaryData


class OperationData(StrictModel):
    operation_id: RunID
    status: Literal["completed", "failed", "cancelled"]
    result: dict | None
    error: NodeError | None

    @model_validator(mode="after")
    def consistent_outcome(self):
        if self.status == "completed" and (self.result is None or self.error is not None):
            raise ValueError("Completed operation requires a result and no error")
        if self.status == "failed" and (self.error is None or self.result is not None):
            raise ValueError("Failed operation requires an error and no result")
        return self


class OperationResult(Envelope):
    name: Literal["operation.result"]
    data: OperationData


RFEvent = Annotated[
    RunState
    | RunPrepared
    | Attempt
    | Received
    | Accepted
    | Rejected
    | Missing
    | MessageResult
    | Summary
    | OperationResult,
    Field(discriminator="name"),
]
ADAPTER = TypeAdapter(RFEvent)


def schema() -> dict:
    return {
        "contract_version": CONTRACT_VERSION,
        "scope": "staged_known_data_events",
        **ADAPTER.json_schema(),
    }


def schema_digest() -> str:
    return hashlib.sha256(
        json.dumps(schema(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
