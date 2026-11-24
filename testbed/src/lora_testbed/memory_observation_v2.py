"""Finite sampled memory evidence, independent from diagnostic and execution hashes."""

import hashlib
import json
from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator

from .artifact_contract_v2 import SHA256
from .control_v2 import UUID
from .models import StrictModel
from .v2 import Counter, Identifier, Memory

PROFILE = "stage_memory_observation_v1"
PERIOD_US = 100_000
MAX_BUFFERS = 16
POLICY = {
    "period_us": PERIOD_US,
    "max_duration_ms": 300000,
    "max_named_buffers": MAX_BUFFERS,
    "stage_samples_additional": True,
    "minimum_scope": "observed_snapshots_not_peak",
    "lifetime_scope": "first_and_last_observed_not_exact_allocation_time",
    "requested_bytes_exclude_allocator_overhead": True,
    "provider_library_driver_allocations_untracked": True,
    "heap_scopes_nonoverlap": ["internal_8bit", "psram_8bit"],
    "snapshot_atomic": False,
    "raw_addresses_exported": False,
}


class Start(StrictModel):
    duration_ms: int = Field(ge=1000, le=300000)


class Stop(StrictModel):
    observation_id: UUID


class Empty(StrictModel):
    pass


ARGUMENTS = {"memory.start": Start, "memory.stop": Stop, "memory.status": Empty}


class Minima(StrictModel):
    internal_free_bytes: Counter
    psram_free_bytes: Counter | None


class Started(StrictModel):
    observation_id: UUID
    deadline_us: Counter
    period_us: Literal[100000]


class Stopped(StrictModel):
    observation_id: UUID
    active: Literal[False]


class WorkloadMinimum(StrictModel):
    workload_id: UUID
    samples_taken: Counter
    minimum: Minima


class Status(StrictModel):
    active: bool
    observation_id: UUID | None
    started_us: Counter | None
    deadline_us: Counter | None
    stopped_us: Counter | None
    stop_reason: (
        Literal["stop", "deadline", "lease_expired", "disconnect", "released", "shutdown"] | None
    )
    deadline_overrun_us: Counter
    samples_taken: Counter
    samples_dropped: Counter
    missed_periods: Counter
    measurement_minimum: Minima | None
    workload_minimum: WorkloadMinimum | None


class KnownBuffer(StrictModel):
    name: str = Field(pattern=r"^[a-z_0-9]{1,23}$")
    region: Literal["internal", "psram", "unknown"]
    requested_bytes: int = Field(gt=0)
    first_observed_us: Counter
    generation: int = Field(ge=1)


class KnownSizes(StrictModel):
    internal: Counter
    psram: Counter
    unknown: Counter


class Sample(StrictModel):
    observation_id: UUID
    sample_index: Counter
    taken_us: Counter
    finished_us: Counter
    reason: Literal[
        "start",
        "periodic",
        "stop",
        "deadline",
        "lease_expired",
        "disconnect",
        "shutdown",
        "released",
        "stage_entry",
        "stage_exit",
    ]
    stage: str = Field(pattern=r"^[a-z_]{1,24}$")
    workload_id: UUID | None
    memory: Memory
    known_buffers: list[KnownBuffer] = Field(max_length=16)
    known_requested_bytes: KnownSizes
    aliases_omitted: Counter
    inventory_truncated: bool
    overlap_detected: bool
    untracked_allocations: Literal[True]
    measurement_minimum: Minima
    workload_minimum: WorkloadMinimum | None
    samples_dropped: Counter
    missed_periods: Counter

    @model_validator(mode="after")
    def named_requested_totals(self):
        if self.finished_us < self.taken_us:
            raise ValueError("Memory observation finishes before it begins")
        if len({buffer.name for buffer in self.known_buffers}) != len(self.known_buffers):
            raise ValueError("Repeated named buffer")
        for region in ("internal", "psram", "unknown"):
            if sum(
                buffer.requested_bytes for buffer in self.known_buffers if buffer.region == region
            ) != getattr(self.known_requested_bytes, region):
                raise ValueError("Named requested-byte totals disagree")
        return self


class Event(StrictModel):
    v: Literal[2]
    kind: Literal["event"]
    device_id: Identifier
    boot_id: Identifier
    node_role: Literal["A", "B"] | None
    event_seq: Counter
    uptime_us: Counter
    run_id: UUID | None
    name: Literal["memory.sample"]
    data: Sample


class CurrentDeclaration(StrictModel):
    schema_sha256: SHA256


class Declaration(CurrentDeclaration):
    profile: Literal["stage_memory_observation_v1"]
    schema_sha256: SHA256


RESULTS = {"memory.start": Started, "memory.stop": Stopped, "memory.status": Status}


def schema():
    return {
        "scope": "finite_sampled_memory_observation",
        "profile": PROFILE,
        "policy": POLICY,
        "arguments": {name: model.model_json_schema() for name, model in ARGUMENTS.items()},
        "results": {name: model.model_json_schema() for name, model in RESULTS.items()},
        "event": Event.model_json_schema(),
        "capability": Declaration.model_json_schema(),
        "availability": CurrentDeclaration.model_json_schema(),
    }


@lru_cache(maxsize=1)
def schema_digest():
    return hashlib.sha256(
        json.dumps(schema(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def require_capability(identity, health):
    if identity is None or health is None:
        raise ValueError("Memory observation identity and current health are required")
    declared = Declaration.model_validate(identity.resource_limits.get("memory_io"))
    current = CurrentDeclaration.model_validate(health.resource_limits.get("memory_io"))
    if declared.schema_sha256 != schema_digest() or current.schema_sha256 != schema_digest():
        raise ValueError("Exact memory observation profile is unavailable")
    return declared
