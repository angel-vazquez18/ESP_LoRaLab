"""File-transfer vocabulary and validation; this module does not store node files."""

import base64
import binascii
import hashlib
import json
import zlib
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator

from . import control_v2, v2
from .models import StrictModel

PROFILE = "artifact_transfer_v1"
MAX_ARTIFACT_BYTES = 131072
TOTAL_ARTIFACT_BYTES = 262144
ARTIFACT_SLOTS = 4
CHUNK_BYTES = 1024

ArtifactID = control_v2.UUID
SHA256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
CRC32 = Annotated[str, Field(pattern=r"^[0-9a-f]{8}$")]
Offset = Annotated[int, Field(ge=0, le=MAX_ARTIFACT_BYTES)]
ArtifactFormat = Literal["known_data", "pcm_s16le_8000_mono"]
ArtifactName = Literal[
    "artifact.begin",
    "artifact.put",
    "artifact.commit",
    "artifact.list",
    "artifact.get",
    "artifact.delete",
]


def decoded_chunk(data_b64: str, crc32: str) -> bytes:
    try:
        data = base64.b64decode(data_b64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Chunk must use standard Base64") from exc
    if base64.b64encode(data).decode("ascii") != data_b64:
        raise ValueError("Chunk must use canonical Base64")
    if len(data) > CHUNK_BYTES:
        raise ValueError("Decoded chunk exceeds 1024 bytes")
    if f"{zlib.crc32(data):08x}" != crc32:
        raise ValueError("Chunk CRC-32 mismatch")
    return data


class Empty(StrictModel):
    pass


class ArtifactReference(StrictModel):
    artifact_id: ArtifactID


class Begin(ArtifactReference):
    kind: Literal["source", "recovered"]
    length_bytes: int = Field(ge=1, le=MAX_ARTIFACT_BYTES)
    sha256: SHA256
    format: ArtifactFormat

    @model_validator(mode="after")
    def pcm_length(self):
        if self.format == "pcm_s16le_8000_mono" and (
            self.length_bytes % 2 or self.length_bytes > 48000
        ):
            raise ValueError("PCM needs 1–24000 complete signed-16-bit samples")
        return self


class Put(ArtifactReference):
    offset: Offset
    data_b64: str = Field(min_length=1, max_length=1368)
    crc32: CRC32

    @model_validator(mode="after")
    def valid_chunk(self):
        data = decoded_chunk(self.data_b64, self.crc32)
        if not data or self.offset + len(data) > MAX_ARTIFACT_BYTES:
            raise ValueError("Chunk is empty or exceeds the artifact address range")
        return self


class Get(ArtifactReference):
    offset: Offset
    length_bytes: int = Field(ge=1, le=CHUNK_BYTES)


ARGUMENTS = {
    "artifact.begin": Begin,
    "artifact.put": Put,
    "artifact.commit": ArtifactReference,
    "artifact.list": Empty,
    "artifact.get": Get,
    "artifact.delete": ArtifactReference,
}


class Command(control_v2.Command):
    name: ArtifactName
    target_boot_id: control_v2.BootID

    @model_validator(mode="after")
    def artifact_arguments(self):
        self.args = ARGUMENTS[self.name].model_validate(self.args).model_dump()
        return self


class BeginResult(ArtifactReference):
    next_offset: int = Field(ge=0, le=0)


class PutResult(ArtifactReference):
    next_offset: int = Field(ge=1, le=MAX_ARTIFACT_BYTES)


class Manifest(Begin):
    state: Literal["uploading", "failed", "committed"]
    next_offset: Offset
    in_use: bool
    codec: None
    sample_rate_hz: Annotated[int, Field(ge=8000, le=8000)] | None
    sample_count: int | None = Field(ge=1, le=24000)
    frame_count: None
    source_artifact_id: ArtifactID | None

    @model_validator(mode="after")
    def consistent_manifest(self):
        if self.next_offset > self.length_bytes:
            raise ValueError("Received bytes exceed declared length")
        if self.state == "committed" and self.next_offset != self.length_bytes:
            raise ValueError("Committed artifact must have its complete length")
        if self.in_use and self.state != "committed":
            raise ValueError("Uncommitted artifact cannot be in use")
        if self.format == "pcm_s16le_8000_mono":
            if self.sample_rate_hz != 8000 or self.sample_count != self.length_bytes // 2:
                raise ValueError("PCM metadata does not match the declared bytes")
        elif self.sample_rate_hz is not None or self.sample_count is not None:
            raise ValueError("Known data has no audio sample metadata")
        return self


class CommitResult(Manifest):
    state: Literal["committed"]


class ListResult(StrictModel):
    artifacts: list[Manifest] = Field(max_length=ARTIFACT_SLOTS)

    @model_validator(mode="after")
    def unique_slots_and_budget(self):
        if len({a.artifact_id for a in self.artifacts}) != len(self.artifacts):
            raise ValueError("Duplicate artifact ID in list")
        if sum(a.length_bytes for a in self.artifacts) > TOTAL_ARTIFACT_BYTES:
            raise ValueError("Artifact list exceeds total reserved-byte budget")
        return self


class GetResult(ArtifactReference):
    offset: Offset
    length_bytes: int = Field(ge=0, le=CHUNK_BYTES)
    data_b64: str = Field(max_length=1368)
    crc32: CRC32
    eof: bool

    @model_validator(mode="after")
    def consistent_chunk(self):
        data = decoded_chunk(self.data_b64, self.crc32)
        if len(data) != self.length_bytes or self.offset + len(data) > MAX_ARTIFACT_BYTES:
            raise ValueError("Returned chunk length is inconsistent")
        if not data and not self.eof:
            raise ValueError("Empty read must be EOF")
        return self


class DeleteResult(ArtifactReference):
    deleted: Literal[True]

    @field_validator("deleted", mode="before")
    @classmethod
    def boolean_deleted(cls, value):
        if type(value) is not bool:
            raise ValueError("deleted must be a JSON boolean")
        return value


RESULTS = {
    "artifact.begin": BeginResult,
    "artifact.put": PutResult,
    "artifact.commit": CommitResult,
    "artifact.list": ListResult,
    "artifact.get": GetResult,
    "artifact.delete": DeleteResult,
}


class Capabilities(StrictModel):
    profile: Literal["artifact_transfer_v1"]
    schema_sha256: SHA256
    commands: list[ArtifactName] = Field(min_length=1, max_length=6)
    max_artifact_bytes: int = Field(ge=1, le=MAX_ARTIFACT_BYTES)
    node_total_artifact_bytes: int = Field(ge=1, le=TOTAL_ARTIFACT_BYTES)
    node_artifact_slots: int = Field(ge=1, le=ARTIFACT_SLOTS)
    artifact_chunk_bytes: int = Field(ge=1, le=CHUNK_BYTES)

    @model_validator(mode="after")
    def consistent_limits(self):
        if len(set(self.commands)) != len(self.commands):
            raise ValueError("Duplicate supported command")
        if (
            not self.artifact_chunk_bytes
            <= self.max_artifact_bytes
            <= self.node_total_artifact_bytes
        ):
            raise ValueError("Artifact limits are inconsistent")
        return self


def validate_arguments(name: str, args: dict, limits: Capabilities):
    value = ARGUMENTS[name].model_validate(args)
    if isinstance(value, Begin) and value.length_bytes > limits.max_artifact_bytes:
        raise ValueError("Artifact exceeds the node's advertised file limit")
    if isinstance(value, Put):
        length = len(decoded_chunk(value.data_b64, value.crc32))
        if length > limits.artifact_chunk_bytes:
            raise ValueError("Chunk exceeds the node's advertised chunk limit")
        if value.offset + length > limits.max_artifact_bytes:
            raise ValueError("Chunk exceeds the node's advertised file limit")
    if isinstance(value, Get) and value.offset > limits.max_artifact_bytes:
        raise ValueError("Read offset exceeds the node's advertised file limit")
    if isinstance(value, Get) and value.length_bytes > limits.artifact_chunk_bytes:
        raise ValueError("Read exceeds the node's advertised chunk limit")
    return value


def validate_result(name: str, args: dict[str, Any], result: dict, limits: Capabilities):
    value = RESULTS[name].model_validate(result)
    if isinstance(value, ListResult):
        if len(value.artifacts) > limits.node_artifact_slots:
            raise ValueError("Returned list exceeds advertised slot count")
        if sum(a.length_bytes for a in value.artifacts) > limits.node_total_artifact_bytes:
            raise ValueError("Returned list exceeds advertised byte budget")
        manifests = value.artifacts
    else:
        if value.artifact_id != args["artifact_id"]:
            raise ValueError("Reply artifact ID does not match request")
        manifests = [value] if isinstance(value, Manifest) else []
    if any(a.length_bytes > limits.max_artifact_bytes for a in manifests):
        raise ValueError("Returned manifest exceeds advertised file limit")
    if isinstance(value, PutResult):
        expected = args["offset"] + len(decoded_chunk(args["data_b64"], args["crc32"]))
        if value.next_offset != expected:
            raise ValueError("Upload reply has the wrong next offset")
    if isinstance(value, GetResult) and (
        value.offset != args["offset"] or value.length_bytes > args["length_bytes"]
    ):
        raise ValueError("Read reply does not match requested range")
    return value


def schema():
    return {
        "contract_version": v2.CONTRACT_VERSION,
        "scope": "artifact_transfer_contract",
        "profile": PROFILE,
        "command": Command.model_json_schema(),
        "command_arguments": {name: model.model_json_schema() for name, model in ARGUMENTS.items()},
        "command_results": {name: model.model_json_schema() for name, model in RESULTS.items()},
        "capability": Capabilities.model_json_schema(),
    }


@lru_cache(maxsize=1)
def schema_digest():
    return hashlib.sha256(
        json.dumps(schema(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
