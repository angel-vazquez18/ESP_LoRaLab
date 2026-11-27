"""Finite VOICE-03 source evidence; repeated encoded bytes, not a live microphone."""

from typing import Literal

from pydantic import Field, model_validator

from .experiments_v2 import ContractModel

POLICY = {
    "frame_bytes": 8,
    "period_us": 20000,
    "source_duration_us": 60000000,
    "message_bytes": 1200,
    "queue_bytes_including_active_and_partial": 4800,
    "audit_period_us": 200000,
    "maximum_drain_us": 30000000,
    "assessment_interval_us": [3000000, 60000000],
    "first_frame_elapsed_us": 0,
    "reassembly": "global_duration_plus_receiver_arm_allowance",
    "overflow": "drop_new_whole_message",
    "late_wakes": "record_actual_time_no_post_cutoff_catchup",
}


class Status(ContractModel):
    started_us: int = Field(ge=0)
    production_end_us: int = Field(ge=0)
    drain_deadline_us: int = Field(ge=0)
    phase: int = Field(ge=0, le=4)
    frames_produced: int = Field(ge=0, le=3000)
    frames_missed: int = Field(ge=0, le=3000)
    frames_cancelled: int = Field(ge=0, le=3000)
    produced_bytes: int = Field(ge=0, le=24000)
    admitted_bytes: int = Field(ge=0, le=24000)
    overflow_dropped_bytes: int = Field(ge=0, le=24000)
    admitted_messages: int = Field(ge=0, le=20)
    dropped_messages: int = Field(ge=0, le=20)
    taken_messages: int = Field(ge=0, le=20)
    sent_messages: int = Field(ge=0, le=20)
    failed_messages: int = Field(ge=0, le=20)
    sent_bytes: int = Field(ge=0, le=24000)
    failed_bytes: int = Field(ge=0, le=24000)
    consumer_discarded_bytes: int = Field(ge=0, le=24000)
    queue_discarded_messages: int = Field(ge=0, le=20)
    queue_discarded_bytes: int = Field(ge=0, le=24000)
    partial_discarded_bytes: int = Field(ge=0, le=24000)
    ready_messages: int = Field(ge=0, le=4)
    partial_bytes: int = Field(ge=0, le=1200)
    active_bytes: int = Field(ge=0, le=1200)
    occupancy_bytes: int = Field(ge=0, le=4800)
    peak_occupancy_bytes: int = Field(ge=0, le=4800)
    late_frames: int = Field(ge=0, le=3000)
    max_lateness_us: int = Field(ge=0, le=60000000)
    trace_frames: int = Field(ge=0, le=3000)
    admitted_message_mask: int = Field(ge=0, le=1048575)
    overflow_message_mask: int = Field(ge=0, le=1048575)
    sent_message_mask: int = Field(ge=0, le=1048575)
    failed_message_mask: int = Field(ge=0, le=1048575)
    discarded_message_mask: int = Field(ge=0, le=1048575)
    drain_cutoff: bool
    consistent: bool
    cancel_requested: bool


class Frame(ContractModel):
    index: int = Field(ge=0, lt=3000)
    planned_elapsed_us: int = Field(ge=0, lt=60000000)
    actual_elapsed_us: int | None = Field(ge=0, lt=60000000)
    produced: bool


class Sample(ContractModel):
    index: int = Field(ge=0, lt=451)
    planned_elapsed_us: int = Field(ge=0, le=90000000)
    actual_elapsed_us: int = Field(ge=0, le=2**32 - 1)
    missed_intervals: int = Field(ge=0)
    status: Status


class Query(ContractModel):
    view: Literal["status", "frames", "samples"] = "status"
    offset: int = Field(default=0, ge=0, le=3000)
    limit: int = Field(default=1, ge=1, le=16)

    @model_validator(mode="after")
    def bounded_samples(self):
        if self.view == "samples" and self.limit != 1:
            raise ValueError("Sample pages contain one snapshot to preserve the 4 KiB record limit")
        return self


class Report(ContractModel):
    status: Status | None
    delivered_message_ids: list[int] = Field(max_length=20)
    archive_artifact_id: str | None
    archive_sha256: str | None
    view: Literal["status", "frames", "samples"]
    offset: int = Field(ge=0, le=3000)
    next_offset: int = Field(ge=0, le=3000)
    eof: bool
    frames: list[Frame] = Field(max_length=16)
    samples: list[Sample] = Field(max_length=1)
