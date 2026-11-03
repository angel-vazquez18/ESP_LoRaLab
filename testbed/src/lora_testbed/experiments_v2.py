"""Known-data preparation for contract v2, independent of serial-port ownership.

These are calculated previews, not applied hardware settings or RF measurements.
The diagnostic wire schema remains unchanged while the run adapter is developed.
"""

import hashlib
import json
import struct
from typing import Annotated, Literal, get_args, get_origin

from pydantic import Field, model_validator

from .models import StrictModel

U32 = Annotated[int, Field(ge=0, le=2**32 - 1)]
SHA256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
MODEL_VERSION = "sx126x_lora_v1"


class ContractModel(StrictModel):
    @model_validator(mode="before")
    @classmethod
    def exact_literal_types(cls, value):
        # Pydantic Literal otherwise accepts 1 for True and 2.0 for integer 2,
        # even with strict=True. Wire constants must retain their JSON types.
        if isinstance(value, dict):
            for name, field in cls.model_fields.items():
                if name in value and get_origin(field.annotation) is Literal:
                    if not any(
                        type(value[name]) is type(item) and value[name] == item
                        for item in get_args(field.annotation)
                    ):
                        raise ValueError(f"Invalid value or JSON type for {name}")
        return value


class Radio(ContractModel):
    frequency_hz: int = Field(default=915_000_000, ge=902_000_000, le=928_000_000)
    bandwidth_hz: Literal[125000, 250000, 500000] = 125000
    spreading_factor: int = Field(default=7, ge=7, le=12)
    coding_rate_denominator: int = Field(default=5, ge=5, le=8)
    tx_power_dbm: int = Field(default=14, ge=2, le=20)
    preamble_symbols: int = Field(default=8, ge=8, le=32)
    header_mode: Literal["explicit"] = "explicit"
    crc_enabled: Literal[True] = True
    iq_inverted: Literal[False] = False
    sync_word: Literal[5156] = 5156
    ldro_mode: Literal["auto"] = "auto"

    @model_validator(mode="after")
    def frequency_step(self):
        if self.frequency_hz % 1000:
            raise ValueError("Frequency must use 1000 Hz steps")
        return self


class Link(ContractModel):
    fragment_payload_bytes: int = Field(default=160, ge=16, le=215)
    ack_mode: Literal["none", "stop_wait"] = "none"
    max_retries: int = Field(default=0, ge=0, le=5)
    guard_us: int = Field(default=50000, ge=0, le=1_000_000)
    ack_turnaround_us: Literal[20000] = 20000
    ack_margin_us: Literal[80000] = 80000

    @model_validator(mode="before")
    @classmethod
    def reliable_default(cls, value):
        if isinstance(value, dict) and value.get("ack_mode") == "stop_wait":
            return {"max_retries": 2, **value}
        return value

    @model_validator(mode="after")
    def retries_require_ack(self):
        if self.ack_mode == "none" and self.max_retries:
            raise ValueError("ACK-disabled runs must use zero retries")
        return self


class Instrumentation(ContractModel):
    packet_events: Literal[True] = True
    crypto_samples: bool = False
    memory_10hz: bool = False
    clock_samples: bool = False


class KnownDataSpec(ContractModel):
    catalog_id: Literal["IF-02"] = "IF-02"
    direction: Literal["A_TO_B", "B_TO_A"] = "A_TO_B"
    source: Literal["known_data"] = "known_data"
    message_count: int = Field(default=100, ge=1, le=10000)
    message_bytes: int = Field(default=64, ge=1, le=65536)
    source_seed: U32 = 743
    source_artifact_id: None = None
    sample_count: None = None
    security: Literal["none", "aes128_gcm"] = "none"
    max_duration_ms: int = Field(default=120000, ge=1000, le=3600000)
    source_duration_ms: None = None
    instrumentation: Instrumentation = Field(default_factory=Instrumentation)
    expected_sha256: None = None
    playback: Literal[False] = False

    @model_validator(mode="after")
    def crypto_profile(self):
        if self.instrumentation.crypto_samples and self.security != "aes128_gcm":
            raise ValueError("Crypto samples require the protected profile")
        return self


class KnownDataPlan(ContractModel):
    radio: Radio = Field(default_factory=Radio)
    link: Link = Field(default_factory=Link)
    spec: KnownDataSpec = Field(default_factory=KnownDataSpec)

    @model_validator(mode="after")
    def fragment_capacity(self):
        capacity = 199 if self.spec.security == "aes128_gcm" else 215
        if self.link.fragment_payload_bytes > capacity:
            raise ValueError(f"Useful fragment capacity is {capacity} bytes for this profile")
        return self


class Budget(ContractModel):
    ack_timeout_us: int = Field(ge=0)
    reassembly_timeout_us: int = Field(ge=0)
    drain_us: int = Field(ge=0)
    capture_budget_us: Literal[0] = 0
    processing_budget_us: int = Field(ge=0)
    playback_budget_us: Literal[0] = 0
    fault_budget_us: Literal[0] = 0
    model_version: Literal["sx126x_lora_v1"] = MODEL_VERSION


def known_data(seed: int, message_id: int, length: int) -> bytes:
    """Independent SHA-256 block recipe, with bounded allocation and no PRNG."""
    if (
        type(seed) is not int
        or not 0 <= seed <= 2**32 - 1
        or type(message_id) is not int
        or not 1 <= message_id <= 2**32 - 1
        or type(length) is not int
        or not 1 <= length <= 65536
    ):
        raise ValueError("Invalid known-data seed, message identity or length")
    prefix = b"lora-testbed-v2" + struct.pack(">II", seed, message_id)
    return b"".join(
        hashlib.sha256(prefix + struct.pack(">I", block)).digest()
        for block in range((length + 31) // 32)
    )[:length]


def ceil_div(numerator: int, denominator: int) -> int:
    return (numerator + denominator - 1) // denominator


def ldro_enabled(radio: Radio) -> bool:
    return (1 << radio.spreading_factor) * 1000 >= 16 * radio.bandwidth_hz


def airtime_us(radio: Radio, frame_bytes: int) -> int:
    """Exact quarter-symbol arithmetic for the v2 explicit-header SF7-12 domain."""
    if type(frame_bytes) is not int or not 1 <= frame_bytes <= 255:
        raise ValueError("Radio frame length must be 1 through 255 bytes")
    sf = radio.spreading_factor
    de = int(ldro_enabled(radio))
    payload_symbols = 8 + max(
        ceil_div(8 * frame_bytes - 4 * sf + 28 + 16, 4 * (sf - 2 * de))
        * radio.coding_rate_denominator,
        0,
    )
    quarter_symbols = 4 * (radio.preamble_symbols + payload_symbols) + 17
    return ceil_div(quarter_symbols * (1 << sf) * 1_000_000, 4 * radio.bandwidth_hz)


def preview(plan: KnownDataPlan) -> dict:
    """Prepare bounded calculations without connecting nodes or creating a run."""
    spec, radio, link = plan.spec, plan.radio, plan.link
    tag_bytes = 16 if spec.security == "aes128_gcm" else 0
    fragments = ceil_div(spec.message_bytes, link.fragment_payload_bytes)
    last_bytes = spec.message_bytes - (fragments - 1) * link.fragment_payload_bytes
    full_frame_bytes = 40 + link.fragment_payload_bytes + tag_bytes
    last_frame_bytes = 40 + last_bytes + tag_bytes
    last_airtime = airtime_us(radio, last_frame_bytes)
    full_airtime = airtime_us(radio, full_frame_bytes) if fragments > 1 else last_airtime
    data_us_per_message = (fragments - 1) * full_airtime + last_airtime
    packets = fragments * spec.message_count
    reliable = link.ack_mode == "stop_wait"
    attempts_per_packet = 1 + link.max_retries
    attempts = packets * attempts_per_packet
    ack_airtime = airtime_us(radio, 40 + tag_bytes) if reliable else 0
    ack_timeout = link.ack_turnaround_us + ack_airtime + link.ack_margin_us if reliable else 0
    drain = max(2_000_000, ack_timeout + link.guard_us)
    # Provisional contract allowances; not measured CPU or hardware performance.
    processing = 10000 * (spec.message_count + attempts)
    worst_rf = data_us_per_message * spec.message_count * attempts_per_packet
    worst_wait = attempts * ack_timeout
    guards = max(0, attempts - 1) * link.guard_us
    worst_total = worst_rf + worst_wait + guards + processing + drain
    per_message = (
        data_us_per_message * attempts_per_packet
        + fragments * attempts_per_packet * ack_timeout
        + max(0, fragments * attempts_per_packet - 1) * link.guard_us
        + 10000 * (1 + fragments * attempts_per_packet)
        + 2_000_000
    )
    nominal = (
        data_us_per_message * spec.message_count
        + packets * (link.ack_turnaround_us + ack_airtime if reliable else 0)
        + max(0, packets - 1) * link.guard_us
        + 10000 * (spec.message_count + packets)
        + drain
    )
    required_ms = ceil_div(worst_total, 1000) + 1000
    suggested_ms = max(120000, required_ms)
    fits = required_ms <= spec.max_duration_ms
    budget = Budget(
        ack_timeout_us=ack_timeout,
        reassembly_timeout_us=per_message,
        drain_us=drain,
        processing_budget_us=processing,
    )
    required = ["radio"]
    if fragments > 1:
        required.append("fragmentation")
    if tag_bytes or spec.instrumentation.crypto_samples:
        required.append("security_gcm")
    if reliable:
        required.append("ack_retry")
    if spec.instrumentation.memory_10hz:
        required.append("memory_stats")
    if spec.instrumentation.clock_samples:
        required.append("clock_sync")
    canonical = json.dumps(plan.model_dump(), sort_keys=True, separators=(",", ":")).encode()
    return {
        "scope": "known_data_calculated_preview",
        "execution_available": False,
        "hardware_validated": False,
        "execution_blocker": "The v2 run adapter and RF firmware are not implemented",
        "plan": plan.model_dump(),
        "plan_sha256": hashlib.sha256(canonical).hexdigest(),
        "required_capabilities": required,
        "source_role": "A" if spec.direction == "A_TO_B" else "B",
        "destination_role": "B" if spec.direction == "A_TO_B" else "A",
        "source_recipe": "sha256_blocks_be32_v2",
        "first_message_sha256": hashlib.sha256(
            known_data(spec.source_seed, 1, spec.message_bytes)
        ).hexdigest(),
        "fragmentation": {
            "fragments_per_message": fragments,
            "full_fragments_per_message": fragments - 1,
            "full_fragment_frame_bytes": full_frame_bytes if fragments > 1 else None,
            "last_fragment_payload_bytes": last_bytes,
            "last_fragment_frame_bytes": last_frame_bytes,
            "header_bytes": 40,
            "tag_bytes": tag_bytes,
            "original_packets": packets,
            "maximum_attempts": attempts,
            "total_useful_bytes": spec.message_count * spec.message_bytes,
        },
        "timing": {
            "model_version": MODEL_VERSION,
            "predicted_ldro_enabled": ldro_enabled(radio),
            "maximum_data_frame_airtime_us": max(full_airtime, last_airtime),
            "ack_airtime_us": ack_airtime,
            "nominal_duration_us": nominal,
            "worst_case_duration_us": worst_total,
            "fits_selected_duration": fits,
            "required_max_duration_ms": required_ms,
            "recommended_max_duration_ms": suggested_ms if suggested_ms <= 3_600_000 else None,
            "requires_linked_split": suggested_ms > 3_600_000,
            "duration_blocker": None
            if fits
            else "Worst-case budget plus 1000 ms headroom exceeds max_duration_ms",
            "budget": budget.model_dump(),
            "assumptions": [
                "Requested modem settings; applied radio settings are not yet verified",
                "Processing allowance: 10000 us per message plus 10000 us per maximum attempt",
                "No controlled injections, codec, capture or playback in this preview",
                "Worst case includes every permitted ACK timeout and inter-attempt guard",
                "Airtime predictions do not predict delivery, RSSI/SNR or measured goodput",
            ],
        },
    }
