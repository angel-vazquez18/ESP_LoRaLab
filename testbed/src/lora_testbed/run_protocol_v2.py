"""Typed run protocol isolated from the installed diagnostic wire profile."""

import hashlib
import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, model_validator

from . import rf_events_v2 as rf
from . import v2
from .experiments_v2 import Budget, ContractModel, KnownDataSpec, Link, Radio


class Empty(ContractModel):
    pass


class Claim(ContractModel):
    node_role: Literal["A", "B"]


class Session(ContractModel):
    session_id: rf.SessionID
    peer_device_id: v2.Identifier
    peer_boot_id: v2.Identifier
    security: Literal["none"]
    tx_key_hex: None
    rx_key_hex: None


class Configuration(ContractModel):
    radio: Radio
    link: Link


class Prepare(ContractModel):
    spec: KnownDataSpec
    budget: Budget


class Revision(ContractModel):
    config_revision: int = Field(ge=0, le=2**32 - 1)


class Stop(ContractModel):
    reason: Literal["operator", "host_shutdown", "peer_failure"]


class ArtifactGet(ContractModel):
    artifact_id: rf.RunID
    offset: int = Field(ge=0, le=65536)
    length_bytes: int = Field(ge=1, le=1024)


ARGUMENTS = {
    "hello": Empty,
    "control.claim": Claim,
    "control.keepalive": Empty,
    "control.release": Empty,
    "status.get": Empty,
    "session.open": Session,
    "session.close": Empty,
    "config.set": Configuration,
    "run.prepare": Prepare,
    "run.arm": Revision,
    "run.start": Revision,
    "run.stop": Stop,
    "run.summary": Empty,
    "artifact.list": Empty,
    "artifact.get": ArtifactGet,
}


class Idle(ContractModel):
    state: Literal["idle"]


class Lease(ContractModel):
    lease_expires_us: int = Field(ge=0)


class Claimed(Idle, Lease):
    config_revision: int = Field(ge=0, le=2**32 - 1)


class SessionOpened(Idle):
    session_id: rf.SessionID


class AppliedRadio(Radio):
    ldro_enabled: bool


class AppliedConfiguration(ContractModel):
    radio: AppliedRadio
    link: Link
    config_revision: int = Field(ge=0, le=2**32 - 1)


class Accepted(ContractModel):
    operation_id: rf.RunID
    state: Literal["accepted"]
    deadline_us: int = Field(ge=0)


class Armed(ContractModel):
    receiver_ready: Literal[True]


class ArtifactManifest(ContractModel):
    artifact_id: rf.RunID
    kind: Literal["source", "recovered"]
    message_id: int = Field(ge=1, le=2**32 - 1)
    length_bytes: int = Field(ge=1, le=65536)
    sha256: str = Field(pattern="^[a-f0-9]{64}$")
    format: Literal["known_data"]


class ArtifactList(ContractModel):
    artifacts: list[ArtifactManifest] = Field(max_length=2)


class ArtifactChunk(ContractModel):
    artifact_id: rf.RunID
    offset: int = Field(ge=0, le=65536)
    length_bytes: int = Field(ge=0, le=1024)
    data_b64: str = Field(max_length=1368)
    crc32: str = Field(pattern="^[a-f0-9]{8}$")
    eof: bool


RESULTS = {
    "hello": v2.Hello,
    "control.claim": Claimed,
    "control.keepalive": Lease,
    "control.release": Idle,
    "status.get": v2.Health,
    "session.open": SessionOpened,
    "session.close": Idle,
    "config.set": AppliedConfiguration,
    "run.prepare": Accepted,
    "run.arm": Armed,
    "run.start": Accepted,
    "run.stop": Idle,
    "run.summary": rf.SummaryData,
    "artifact.list": ArtifactList,
    "artifact.get": ArtifactChunk,
}


class Command(v2.Command, ContractModel):
    command_id: rf.RunID
    client_id: rf.RunID
    run_id: rf.RunID | None = None

    @model_validator(mode="after")
    def validate_arguments(self):
        model = ARGUMENTS.get(self.name)
        if model is None:
            raise ValueError("Unknown run-protocol command")
        self.args = model.model_validate(self.args).model_dump()
        if self.name.startswith(("session.", "run.")) and self.run_id is None:
            raise ValueError("Session and run commands require run_id")
        if self.name != "hello" and self.target_boot_id is None:
            raise ValueError("Command requires target_boot_id")
        return self


class Reply(v2.Reply, ContractModel):
    pass


class HealthEvent(v2.Event, ContractModel):
    pass


WireRecord = Command | Reply | Annotated[rf.RFEvent | HealthEvent, Field(discriminator="name")]
ADAPTER = TypeAdapter(WireRecord)


def schema():
    return {
        "contract_version": v2.CONTRACT_VERSION,
        "scope": "virtual_known_data_execution",
        "wire": ADAPTER.json_schema(),
        "command_arguments": {name: model.model_json_schema() for name, model in ARGUMENTS.items()},
        "command_results": {name: model.model_json_schema() for name, model in RESULTS.items()},
    }


@lru_cache(maxsize=1)
def schema_digest():
    return hashlib.sha256(
        json.dumps(schema(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
