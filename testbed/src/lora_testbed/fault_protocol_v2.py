"""Explicit laboratory-only protected DATA faults and bounded retained evidence."""

from typing import Literal

from pydantic import Field, model_validator

from .control_v2 import UUID
from .experiments_v2 import ContractModel


class Injection(ContractModel):
    injection_id: UUID
    stage: Literal[
        "tx_after_protect", "tx_retained", "rx_before_reassembly", "tx_before_radio", "tx_schedule"
    ]
    action: Literal["xor_byte", "replay", "drop", "drop_ack", "duplicate", "reverse_block"]
    message_id: int = Field(ge=1, le=2**32 - 1)
    fragment_index: int = Field(ge=0, le=4095)
    attempt_index: int = Field(ge=1, le=3)
    byte_offset: int | None = Field(ge=40, le=254)
    xor_mask: int | None = Field(ge=1, le=255)
    block_size: int | None = Field(ge=2, le=32)

    @model_validator(mode="after")
    def exact_stage(self):
        if self.action == "xor_byte":
            if (
                self.stage != "tx_after_protect"
                or self.byte_offset is None
                or self.xor_mask is None
            ):
                raise ValueError(
                    "Mutation requires the post-protection stage and an explicit byte/mask"
                )
        else:
            stage = {
                "replay": "tx_retained",
                "drop": "rx_before_reassembly",
                "drop_ack": "tx_before_radio",
                "duplicate": "tx_schedule",
                "reverse_block": "tx_schedule",
            }[self.action]
            if self.stage != stage or self.byte_offset is not None or self.xor_mask is not None:
                raise ValueError("Action requires its declared stage and null mutation selectors")
        if (self.block_size is not None) != (self.action == "reverse_block"):
            raise ValueError("Only a reverse block requires a block size")
        if self.stage == "tx_schedule" and self.attempt_index != 1:
            raise ValueError("A scheduling fault targets the original send")
        return self


class Set(ContractModel):
    injections: list[Injection] = Field(max_length=8)
    replace: bool

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [entry.injection_id for entry in self.injections]
        if len(ids) != len(set(ids)):
            raise ValueError("Injection IDs must be distinct")
        return self


class Fire(ContractModel):
    injection_id: UUID


class Query(ContractModel):
    offset: int = Field(default=0, ge=0, le=32)
    limit: Literal[4] = 4


class Configured(ContractModel):
    count: int = Field(ge=0, le=32)


class Entry(Injection):
    state: Literal["planned", "retained", "applied", "fired", "disabled", "missed"]
    target_frame_seq: int | None = Field(ge=1, le=2**32 - 1)
    frame_bytes: int | None = Field(ge=41, le=255)
    before_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    after_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    applied_us: int | None = Field(ge=0, le=2**53 - 1)
    target_arrived_us: int | None = Field(ge=0, le=2**53 - 1)

    @model_validator(mode="after")
    def actual_observation(self):
        if self.state in ("retained", "applied", "fired") and any(
            value is None
            for value in (
                self.target_frame_seq,
                self.frame_bytes,
                self.before_sha256,
                self.after_sha256,
            )
        ):
            raise ValueError("Observed fault state requires exact target and wire digests")
        if self.state in ("applied", "fired") and self.applied_us is None:
            raise ValueError("Applied fault requires a node-local application instant")
        if (
            self.state == "applied"
            and self.action in ("drop", "drop_ack")
            and (self.target_arrived_us is None or self.target_arrived_us > self.applied_us)
        ):
            raise ValueError("Receiver fault requires its observed arrival before application")
        if self.action not in ("drop", "drop_ack") and self.target_arrived_us is not None:
            raise ValueError("Transmitter fault cannot carry a receiver arrival")
        return self


class Report(Configured):
    session_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    offset: int = Field(ge=0, le=32)
    next_offset: int = Field(ge=0, le=32)
    eof: bool
    fire_window_open: bool
    entries: list[Entry] = Field(max_length=4)

    @model_validator(mode="after")
    def coherent_page(self):
        if self.next_offset != self.offset + len(self.entries) or self.eof != (
            self.next_offset >= self.count
        ):
            raise ValueError("Fault page does not match its count/offset")
        return self


class Fired(Fire):
    frame_seq: int = Field(ge=1, le=2**32 - 1)
    frame_bytes: int = Field(ge=57, le=255)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["submitted"]


class Applied(Entry):
    session_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    state: Literal["applied", "fired"]


class Transmission(Fire):
    session_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    frame_seq: int = Field(ge=1, le=2**32 - 1)
    message_id: int = Field(ge=1, le=2**32 - 1)
    fragment_index: int = Field(ge=0, le=4095)
    frame_bytes: int = Field(ge=41, le=255)
    tx_command_us: int | None = Field(ge=0, le=2**53 - 1)
    tx_done_us: int | None = Field(ge=0, le=2**53 - 1)
    status: Literal["completed", "failed"]
    wire_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def confirmed_times(self):
        if self.status == "completed" and (
            self.tx_command_us is None
            or self.tx_done_us is None
            or self.tx_done_us < self.tx_command_us
        ):
            raise ValueError("Confirmed injected transmission requires ordered radio timestamps")
        return self
