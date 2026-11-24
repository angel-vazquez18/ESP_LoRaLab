"""Bounded public-vector local measurements, independent of RF/session capabilities."""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .control_v2 import UUID, AcceptedOperation
from .models import StrictModel
from .paths import REPOSITORY_ROOT
from .v2 import Counter, Identifier

PROFILE = "local_crypto_benchmark_v1"
PATHS = ("encrypt", "decrypt", "invalid_tag", "copy")
PHASES = ("first_call", "warmup", "timed")


class Request(StrictModel):
    iterations: int = Field(default=1000, ge=1, le=10000)
    payload_bytes: Literal[16, 64, 160, 199] = 160


class Arguments(Request):
    kind: Literal["crypto_benchmark"] = "crypto_benchmark"


class Declaration(StrictModel):
    profile: Literal["local_crypto_benchmark_v1"]
    schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    vector_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    max_iterations: Literal[10000]
    warmup_operations: Literal[50]
    page_samples: Literal[16]


class Page(StrictModel):
    operation_id: UUID
    path: Literal["encrypt", "decrypt", "invalid_tag", "copy"]
    phase: Literal["first_call", "warmup", "timed"]
    first_index: int = Field(ge=0, le=9999)
    page_index: int = Field(ge=0, le=99999)
    payload_bytes: Literal[16, 64, 160, 199]
    # [call_start_us, call_end_us, checked]. The clock domain is the event's boot.
    samples: list[Annotated[tuple[Counter, Counter, bool], Field(strict=False)]] = Field(
        min_length=1, max_length=16
    )

    @model_validator(mode="after")
    def ordered_times(self):
        if any(end < start for start, end, _ in self.samples):
            raise ValueError("Crypto call ends before it starts")
        return self


class Event(StrictModel):
    v: Literal[2] = 2
    kind: Literal["event"] = "event"
    device_id: Identifier
    boot_id: Identifier
    node_role: Literal["A", "B"] | None
    event_seq: Counter
    uptime_us: Counter
    run_id: UUID | None
    name: Literal["crypto.benchmark"]
    data: Page


class Counts(StrictModel):
    first_call: int = Field(ge=0, le=1)
    warmup: int = Field(ge=0, le=50)
    timed: int = Field(ge=0, le=10000)


class Result(StrictModel):
    kind: Literal["crypto_benchmark"]
    profile: Literal["local_crypto_benchmark_v1"]
    schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    vector_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_bytes: Literal[16, 64, 160, 199]
    iterations_requested: int = Field(ge=1, le=10000)
    pages_emitted: int = Field(ge=0, le=100000)
    samples_lost: Counter
    checked_complete: bool
    checked_counts: dict[Literal["encrypt", "decrypt", "invalid_tag", "copy"], Counts]
    implementation: Literal["PSA_GCM_MbedTLS_4.1.0_TFPSA_1.1.0"]
    timer: Literal["platform_monotonic_us"]
    timestamp_resolution_us: Literal[1]
    configured_cpu_frequency_mhz: int = Field(ge=0, le=1000)
    dynamic_frequency_enabled: bool
    hardware_aes_configured: bool
    buffer_policy: Literal["fixed_nonoverlap_215B_output_16_sample_page"]
    measurement: Literal["one_shot_PSA_call_including_provider_internal_work"]
    first_call_scope: Literal["first_per_path_in_this_batch_not_cold_boot"]
    copy_baseline: Literal["memcpy_payload_plus_16_tag_bytes_no_authentication"]
    public_vector_material_only: Literal[True]
    duration_us: Counter
    stop_reason: str | None


def vector_digest():
    return hashlib.sha256(
        (REPOSITORY_ROOT / "contracts/v2/crypto_benchmark_vectors.json").read_bytes()
    ).hexdigest()


def assess(records):
    """Return distributions only for complete, independently reconciled raw evidence."""
    result = {"complete": False, "checked_samples": 0, "timed": {}, "reasons": []}
    try:
        terminals = [r for r in records if r.get("name") == "operation.result"]
        if len(terminals) != 1:
            raise ValueError("Exactly one terminal record is required")
        terminal = terminals[0]
        data = terminal["data"]
        summary = Result.model_validate(data["result"])
        result["counts"] = {k: v.model_dump() for k, v in summary.checked_counts.items()}
        if summary.schema_sha256 != schema_digest() or summary.vector_sha256 != vector_digest():
            raise ValueError("Benchmark schema or public vector fingerprint differs")
        if data["status"] != "completed" or not summary.checked_complete or summary.samples_lost:
            raise ValueError("Benchmark is partial, failed, cancelled or reports lost samples")
        pages = [Event.model_validate(r) for r in records if r.get("name") == "crypto.benchmark"]
        if len(pages) != summary.pages_emitted:
            raise ValueError("Sample page count differs from the node terminal record")
        counts = {path: {phase: 0 for phase in PHASES} for path in PATHS}
        timed = {path: [] for path in PATHS}
        previous_end, previous_rank = -1, -1
        for index, event in enumerate(pages):
            page = event.data
            if any(
                getattr(event, key) != terminal[key]
                for key in ("device_id", "boot_id", "node_role", "run_id")
            ):
                raise ValueError("Sample page belongs to another node, boot, role or run")
            if (
                page.operation_id != data["operation_id"]
                or page.payload_bytes != summary.payload_bytes
            ):
                raise ValueError("Sample page belongs to another operation or payload size")
            rank = PATHS.index(page.path) * 3 + PHASES.index(page.phase)
            if (
                page.page_index != index
                or page.first_index != counts[page.path][page.phase]
                or rank < previous_rank
            ):
                raise ValueError("Sample page is missing, duplicated or out of order")
            previous_rank = rank
            for start, end, checked in page.samples:
                if not checked or start < previous_end:
                    raise ValueError("Unchecked output or overlapping/regressing sample clock")
                previous_end = end
                counts[page.path][page.phase] += 1
                result["checked_samples"] += 1
                if page.phase == "timed":
                    timed[page.path].append(end - start)
        expected = {"first_call": 1, "warmup": 50, "timed": summary.iterations_requested}
        if set(summary.checked_counts) != set(PATHS) or any(
            counts[path] != expected or counts[path] != summary.checked_counts[path].model_dump()
            for path in PATHS
        ):
            raise ValueError("First-call/warm-up/timed counts are incomplete or inconsistent")
        result.update(complete=True, timed=timed, counts=counts)
    except (ValueError, KeyError, TypeError) as exc:
        result["reasons"].append(str(exc))
    return result


def schema():
    return {
        "scope": "local_crypto_benchmark",
        "profile": PROFILE,
        "arguments": Arguments.model_json_schema(),
        "accepted": AcceptedOperation.model_json_schema(),
        "declaration": Declaration.model_json_schema(),
        "event": Event.model_json_schema(),
        "result": Result.model_json_schema(),
    }


def schema_digest():
    return hashlib.sha256(
        json.dumps(schema(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def require_capability(identity, health):
    for caps in (identity, health):
        if caps is None:
            raise ValueError("Local benchmark requires current node identity and health")
        declaration = Declaration.model_validate(caps.resource_limits.get("crypto_benchmark"))
        if (
            declaration.vector_sha256 != vector_digest()
            or declaration.schema_sha256 != schema_digest()
            or "crypto_benchmark" not in caps.resource_limits.get("diag_kinds", [])
        ):
            raise ValueError("Exact local crypto benchmark capability is unavailable")
    return declaration
