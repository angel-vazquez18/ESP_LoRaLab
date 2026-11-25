"""Typed run protocol isolated from the installed diagnostic wire profile."""

import hashlib
import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, TypeAdapter, model_validator

from . import fault_protocol_v2 as fault
from . import rf_events_v2 as rf
from . import source_protocol_v2 as source_protocol
from . import v2
from .experiments_v2 import Budget, ContractModel, KnownDataPlan, KnownDataSpec, Link, Radio

EXECUTION_PROFILE = "finite_message_execution_v5"
ARM_WINDOW_US = 5_000_000
ExecutionName = Literal[
    "session.open",
    "session.close",
    "config.set",
    "run.prepare",
    "run.arm",
    "run.start",
    "run.stop",
    "run.summary",
    "run.source",
    "fault.set",
    "fault.fire",
    "fault.status",
]
BASE_EXECUTION_COMMANDS = (
    "session.open",
    "session.close",
    "config.set",
    "run.prepare",
    "run.arm",
    "run.start",
    "run.stop",
    "run.summary",
    "run.source",
)
LAB_FAULT_COMMANDS = ("fault.set", "fault.fire", "fault.status")
EXECUTION_COMMANDS = BASE_EXECUTION_COMMANDS + LAB_FAULT_COMMANDS
CLEANUP_COMMANDS = ("session.close", "run.stop", "run.summary", "run.source", "fault.status")


class Capabilities(ContractModel):
    profile: Literal["finite_message_execution_v5"]
    schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    commands: list[ExecutionName] | Literal["base", "lab"] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def unique_commands(self):
        if isinstance(self.commands, str):
            self.commands = list(
                BASE_EXECUTION_COMMANDS if self.commands == "base" else EXECUTION_COMMANDS
            )
        if len(self.commands) != len(set(self.commands)):
            raise ValueError("Duplicate execution command")
        return self


class Empty(ContractModel):
    pass


class Claim(ContractModel):
    node_role: Literal["A", "B"]


class Session(ContractModel):
    session_id: rf.SessionID
    peer_device_id: v2.Identifier
    peer_boot_id: v2.Identifier
    model_config = ConfigDict(hide_input_in_errors=True)
    security: Literal["none", "aes128_gcm"]
    tx_key_hex: str | None = Field(
        pattern=r"^[0-9a-f]{32}$", repr=False, json_schema_extra={"writeOnly": True}
    )
    rx_key_hex: str | None = Field(
        pattern=r"^[0-9a-f]{32}$", repr=False, json_schema_extra={"writeOnly": True}
    )

    @model_validator(mode="after")
    def source_keys(self):
        if self.security == "none":
            if self.tx_key_hex is not None or self.rx_key_hex is not None:
                raise ValueError("Unprotected sessions require null keys")
        elif (
            self.tx_key_hex is None or self.rx_key_hex is None or self.tx_key_hex == self.rx_key_hex
        ):
            raise ValueError("Protected sessions require distinct source keys")
        return self


class Configuration(ContractModel):
    radio: Radio
    link: Link


class EncodedSourceSpec(KnownDataSpec):
    catalog_id: Literal["VOICE-02"] = "VOICE-02"
    source: Literal["encoded_source"] = "encoded_source"
    message_count: Literal[1] = 1
    message_bytes: int = Field(ge=8, le=1200, multiple_of=8)
    source_seed: None = None
    source_artifact_id: rf.RunID
    sample_count: int = Field(ge=1, le=24000)
    security: Literal["aes128_gcm"] = "aes128_gcm"
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def exact_encoded_frames(self):
        if self.message_bytes != ((self.sample_count + 159) // 160) * 8:
            raise ValueError("Encoded message length differs from its complete mode-3200 frames")
        return self


class FixedRateSourceSpec(EncodedSourceSpec):
    catalog_id: Literal["VOICE-03"] = "VOICE-03"
    source: Literal["fixed_rate_encoded"] = "fixed_rate_encoded"
    message_count: Literal[20] = 20
    message_bytes: Literal[1200] = 1200
    sample_count: Literal[24000] = 24000
    source_duration_ms: Literal[60000] = 60000
    max_duration_ms: int = Field(default=90000, ge=60000, le=90000)


class EchoSpec(KnownDataSpec):
    catalog_id: Literal["TIME-01"] = "TIME-01"
    source: Literal["echo"] = "echo"
    message_count: Literal[1] = 1
    message_bytes: int = Field(default=64, ge=1, le=215)


class EchoPlan(KnownDataPlan):
    spec: EchoSpec = Field(default_factory=EchoSpec)

    @model_validator(mode="after")
    def single_unacknowledged_frame(self):
        if (
            self.link.ack_mode != "none"
            or self.link.max_retries
            or self.spec.message_bytes > self.link.fragment_payload_bytes
        ):
            raise ValueError("Echo requires one unacknowledged fragment without retries")
        return self


class Prepare(ContractModel):
    spec: KnownDataSpec | EncodedSourceSpec | FixedRateSourceSpec | EchoSpec
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
    "run.source": source_protocol.Query,
    "fault.set": fault.Set,
    "fault.fire": fault.Fire,
    "fault.status": fault.Query,
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
    role: Literal["sender", "receiver"]
    receiver_ready: bool
    arm_deadline_us: int = Field(ge=0)

    @model_validator(mode="after")
    def ready_role(self):
        if self.receiver_ready != (self.role == "receiver"):
            raise ValueError("Receiver readiness disagrees with the armed role")
        return self


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
    "run.source": source_protocol.Report,
    "fault.set": fault.Configured,
    "fault.fire": fault.Fired,
    "fault.status": fault.Report,
    "artifact.list": ArtifactList,
    "artifact.get": ArtifactChunk,
}


class Command(v2.Command, ContractModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    command_id: rf.RunID
    client_id: rf.RunID
    run_id: rf.RunID | None = None

    @model_validator(mode="after")
    def validate_arguments(self):
        model = ARGUMENTS.get(self.name)
        if model is None:
            raise ValueError("Unknown run-protocol command")
        self.args = model.model_validate(self.args).model_dump()
        if self.name.startswith(("session.", "run.", "fault.")) and self.run_id is None:
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
        "scope": "finite_message_execution",
        "command_sets": {"base": list(BASE_EXECUTION_COMMANDS), "lab": list(EXECUTION_COMMANDS)},
        "fixed_source_policy": source_protocol.POLICY,
        "lifecycle": {"arm_window_us": ARM_WINDOW_US, "sender_arm_required": True},
        "laboratory_faults": {
            "default_enabled": False,
            "command_entries": 8,
            "session_entries": 32,
            "retained_frames": 16,
            "status_page": 4,
            "scope": "protected_generated_data",
        },
        "wire": ADAPTER.json_schema(),
        "capability": Capabilities.model_json_schema(),
        "command_arguments": {name: model.model_json_schema() for name, model in ARGUMENTS.items()},
        "command_results": {name: model.model_json_schema() for name, model in RESULTS.items()},
    }


@lru_cache(maxsize=1)
def schema_digest():
    return hashlib.sha256(
        json.dumps(schema(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
