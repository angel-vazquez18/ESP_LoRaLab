"""Main-node control profile; the original diagnostic schema stays unchanged."""

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import Field, TypeAdapter, model_validator

from . import v2
from .models import StrictModel

UUID = Annotated[str, Field(pattern=r"^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$")]
BootID = Annotated[str, Field(pattern=r"^esp-[0-9a-f]{12}:[1-9][0-9]{0,9}$")]


class Command(v2.Command):
    v: Literal[2]
    kind: Literal["command"]
    command_id: UUID
    client_id: UUID
    command_seq: int = Field(ge=1, le=2**32 - 1)
    target_boot_id: BootID | None
    run_id: UUID | None
    name: str = Field(min_length=1, max_length=64)
    args: dict[str, Any]


class AcceptedOperation(StrictModel):
    operation_id: UUID
    state: Literal["accepted"]
    deadline_us: v2.Counter


class OperationResult(StrictModel):
    operation_id: str = Field(pattern=r"^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$")
    status: Literal["completed", "cancelled", "failed"]
    result: dict | None
    error: v2.NodeError | None

    @model_validator(mode="after")
    def consistent_outcome(self):
        if self.status == "failed":
            if self.result is not None or self.error is None:
                raise ValueError("Failed operation requires an error and null result")
        elif self.result is None or self.error is not None:
            raise ValueError("Completed/cancelled operation requires a result and null error")
        return self


class Event(StrictModel):
    v: Literal[2] = 2
    kind: Literal["event"] = "event"
    device_id: v2.Identifier
    boot_id: v2.Identifier
    node_role: Literal["A", "B"] | None
    event_seq: v2.Counter
    uptime_us: v2.Counter
    run_id: str | None
    name: Literal["health", "diagnostic", "operation.result"]
    data: dict

    @model_validator(mode="after")
    def validate_data(self):
        if self.name == "operation.result":
            self.data = OperationResult.model_validate(self.data).model_dump()
        else:
            v2.Event.model_validate(self.model_dump())
        return self


WireRecord = Annotated[Command | v2.Reply | Event, Field(discriminator="kind")]
ADAPTER = TypeAdapter(WireRecord)


def schema():
    return {
        "contract_version": v2.CONTRACT_VERSION,
        "scope": "node_control",
        **ADAPTER.json_schema(),
    }


def schema_digest():
    return hashlib.sha256(
        json.dumps(schema(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
