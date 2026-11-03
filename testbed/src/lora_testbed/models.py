"""Validated host configuration and version-one node wire records."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RadioConfig(StrictModel):
    frequency_hz: int = Field(default=915_000_000, ge=900_000_000, le=930_000_000)
    bandwidth_hz: Literal[125000, 250000, 500000] = 125000
    spreading_factor: int = Field(default=7, ge=7, le=12)
    coding_rate_denominator: int = Field(default=5, ge=5, le=8)
    tx_power_dbm: int = Field(default=14, ge=2, le=20)


class RunSpec(StrictModel):
    catalog_id: str = "IF-02"
    name: str = Field(default="Known-data link check", min_length=1, max_length=100)
    direction: Literal["A_TO_B", "B_TO_A"] = "A_TO_B"
    packet_count: int = Field(default=100, ge=1, le=1000)
    payload_bytes: int = Field(default=64, ge=1, le=200)
    interval_ms: int = Field(default=50, ge=10, le=1000)
    loss_rate: float = Field(default=0.05, ge=0, le=1)
    duplicate_rate: float = Field(default=0.02, ge=0, le=1)
    seed: int = Field(default=743, ge=0, le=2**32 - 1)
    radio: RadioConfig = Field(default_factory=RadioConfig)

    @model_validator(mode="after")
    def bounded_duration(self):
        if self.packet_count * self.interval_ms > 120_000:
            raise ValueError("A simulated run must finish within 120 seconds")
        return self


class Command(StrictModel):
    v: Literal[1] = 1
    kind: Literal["command"] = "command"
    command_id: str = Field(min_length=1, max_length=64)
    name: Literal["hello", "configure", "arm", "start", "stop"]
    run_id: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)


class Reply(StrictModel):
    v: Literal[1] = 1
    kind: Literal["reply"] = "reply"
    command_id: str
    node_id: str
    boot_id: str
    ok: bool
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class PacketData(StrictModel):
    origin_node: Literal["A", "B"]
    packet_seq: int = Field(ge=0, le=2**32 - 1)
    payload_bytes: int = Field(ge=1, le=255)


class ReceivedData(PacketData):
    rssi_dbm: float = Field(allow_inf_nan=False)
    snr_db: float = Field(allow_inf_nan=False)


class SummaryData(StrictModel):
    role: Literal["sender"]
    measurement_window_us: int = Field(gt=0)


class NodeEvent(StrictModel):
    v: Literal[1] = 1
    kind: Literal["event"] = "event"
    node_id: Literal["A", "B"]
    boot_id: str
    event_seq: int = Field(ge=1)
    run_id: str
    uptime_us: int = Field(ge=0)
    name: Literal["tx_done", "rx_valid", "run_summary"]
    data: dict[str, Any]

    @model_validator(mode="after")
    def validate_payload(self):
        model = {"tx_done": PacketData, "rx_valid": ReceivedData, "run_summary": SummaryData}
        self.data = model[self.name].model_validate(self.data).model_dump()
        return self
