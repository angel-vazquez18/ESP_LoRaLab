"""Finite Codec 2 artifact transform supplement, separate from physical I2S/RF."""

import hashlib
import json
from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator

from . import control_v2
from .artifact_contract_v2 import SHA256, ArtifactID, ArtifactReference, CommitResult
from .models import StrictModel

PROFILE = "codec_io_v1"
SOURCE_COMMIT = "06d4c11e699b0351765f10398abb4f663a984f36"


class Encode(ArtifactReference):
    source_artifact_id: ArtifactID

    @model_validator(mode="after")
    def distinct_artifacts(self):
        if self.artifact_id == self.source_artifact_id:
            raise ValueError("Codec work requires a separate output artifact")
        return self


ARGUMENTS = {"audio.encode": Encode, "audio.decode": Encode}


class Capabilities(StrictModel):
    profile: Literal["codec_io_v1"]
    schema_sha256: SHA256
    commands: list[Literal["audio.encode", "audio.decode"]] = Field(min_length=2, max_length=2)
    codec: Literal["codec2_3200_v1"]
    decoder_phase_state: Literal["per_clip_seed1"]
    version: Literal["1.2.0"]
    source_commit: Literal["06d4c11e699b0351765f10398abb4f663a984f36"]
    library_ready: Literal[True]
    mode: Literal[3200]
    bytes_per_frame: Literal[8]
    build_options: Literal["mode3200_only;kiss_fft;float;O2;no_fast_math"]
    sample_rate_hz: Literal[8000]
    samples_per_frame: Literal[160]
    bits_per_frame: Literal[64]
    max_samples: Literal[24000]
    max_frames_per_step: Literal[1]
    operation_timeout_us: Literal[30000000]


class Availability(StrictModel):
    profile: Literal["codec_io_v1"]
    schema_sha256: SHA256
    commands: list[Literal["audio.encode", "audio.decode"]] = Field(min_length=2, max_length=2)


class Result(StrictModel):
    kind: Literal["audio_encode"]
    codec: Literal["codec2_3200_v1"]
    source_artifact_id: ArtifactID
    source_sha256: SHA256
    artifact_id: ArtifactID
    input_samples: int = Field(ge=1, le=24000)
    frame_count: int = Field(ge=1, le=150)
    frames_completed: int = Field(ge=0, le=150)
    encoded_bytes: int = Field(ge=0, le=1200)
    padded_samples: int = Field(ge=0, le=159)
    setup_us: int = Field(ge=0)
    conversion_us: int = Field(ge=0)
    codec_us: int = Field(ge=0)
    finalize_us: int = Field(ge=0)
    started_us: int = Field(ge=0)
    finished_us: int = Field(ge=0)
    duration_us: int = Field(ge=0)
    artifact: CommitResult | None
    stop_reason: str | None

    @model_validator(mode="after")
    def consistent_counts(self):
        if (
            self.frame_count != (self.input_samples + 159) // 160
            or self.frames_completed > self.frame_count
            or self.encoded_bytes != self.frames_completed * 8
            or self.padded_samples != self.frame_count * 160 - self.input_samples
        ):
            raise ValueError("Codec frame/sample counts are inconsistent")
        if self.finished_us - self.started_us != self.duration_us:
            raise ValueError("Codec duration differs from node-local endpoints")
        if self.artifact is not None and (
            self.frames_completed != self.frame_count
            or self.artifact.artifact_id != self.artifact_id
            or self.artifact.source_artifact_id != self.source_artifact_id
            or self.artifact.format != self.codec
            or self.artifact.length_bytes != self.encoded_bytes
            or self.artifact.sample_count != self.input_samples
        ):
            raise ValueError("Published encoded artifact differs from the completed transform")
        return self


class HeapSnapshot(StrictModel):
    free_bytes: int = Field(ge=0)
    minimum_free_bytes: int = Field(ge=0)
    largest_free_bytes: int = Field(ge=0)


class MemorySnapshot(StrictModel):
    internal: HeapSnapshot | None
    psram: HeapSnapshot | None
    allocation_failures: int = Field(ge=0)


class DecodeMemory(StrictModel):
    scope: Literal["platform_heap_snapshots_not_peak"]
    before: MemorySnapshot
    ready: MemorySnapshot
    after: MemorySnapshot


class DecodeResult(StrictModel):
    memory: DecodeMemory
    kind: Literal["audio_decode"]
    codec: Literal["codec2_3200_v1"]
    source_artifact_id: ArtifactID
    source_sha256: SHA256
    artifact_id: ArtifactID
    sample_count: int = Field(ge=1, le=24000)
    samples_completed: int = Field(ge=0, le=24000)
    frame_count: int = Field(ge=1, le=150)
    frames_completed: int = Field(ge=0, le=150)
    decoded_bytes: int = Field(ge=0, le=48000)
    trimmed_samples: int = Field(ge=0, le=159)
    setup_us: int = Field(ge=0)
    conversion_us: int = Field(ge=0)
    codec_us: int = Field(ge=0)
    finalize_us: int = Field(ge=0)
    started_us: int = Field(ge=0)
    finished_us: int = Field(ge=0)
    duration_us: int = Field(ge=0)
    artifact: CommitResult | None
    stop_reason: str | None

    @model_validator(mode="after")
    def consistent_counts(self):
        if (
            self.frame_count != (self.sample_count + 159) // 160
            or self.frames_completed > self.frame_count
            or self.samples_completed != min(self.sample_count, self.frames_completed * 160)
            or self.decoded_bytes != self.samples_completed * 2
            or self.trimmed_samples != self.frame_count * 160 - self.sample_count
            or self.finished_us - self.started_us != self.duration_us
            or self.artifact_id == self.source_artifact_id
        ):
            raise ValueError("Decoded counts, identities or duration are inconsistent")
        if self.artifact is not None and (
            self.frames_completed != self.frame_count
            or self.artifact.artifact_id != self.artifact_id
            or self.artifact.source_artifact_id != self.source_artifact_id
            or self.artifact.format != "pcm_s16le_8000_mono"
            or self.artifact.length_bytes != self.decoded_bytes
            or self.artifact.sample_count != self.sample_count
            or self.artifact.kind != "recovered"
        ):
            raise ValueError("Published PCM differs from the completed decode")
        return self


def schema():
    return {
        "scope": "finite_codec_artifacts",
        "profile": PROFILE,
        "arguments": {k: v.model_json_schema() for k, v in ARGUMENTS.items()},
        "accepted": control_v2.AcceptedOperation.model_json_schema(),
        "capability": Capabilities.model_json_schema(),
        "result": Result.model_json_schema(),
        "decode_result": DecodeResult.model_json_schema(),
        "availability": Availability.model_json_schema(),
    }


@lru_cache(maxsize=1)
def schema_digest():
    return hashlib.sha256(
        json.dumps(schema(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def require_capability(identity, health, name):
    if name not in ARGUMENTS:
        raise ValueError("Unknown finite codec command")
    if identity is None or health is None:
        raise ValueError("Codec identity/current health is unavailable")
    if not identity.codec2_3200 or not health.codec2_3200:
        raise ValueError("Codec 2 artifact transforms are unavailable")
    limits = Capabilities.model_validate(identity.resource_limits.get("codec_io"))
    current = Availability.model_validate(health.resource_limits.get("codec_io"))
    if (
        not identity.codec2_3200
        or not health.codec2_3200
        or limits.schema_sha256 != schema_digest()
        or current.schema_sha256 != schema_digest()
        or name not in limits.commands
        or name not in current.commands
    ):
        raise ValueError("Exact finite codec capability is unavailable")
    return limits
