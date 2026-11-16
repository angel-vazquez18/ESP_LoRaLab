"""Finite local PCM I/O supplement; independent of RF and control schemas."""

import hashlib
import json
from functools import lru_cache
from typing import Literal

from pydantic import Field

from . import control_v2
from .artifact_contract_v2 import SHA256, ArtifactReference
from .models import StrictModel

PROFILE = "audio_io_v1"
MAX_SAMPLES = 24000
SAMPLE_RATE = 8000


class Play(ArtifactReference):
    pass


class Capture(ArtifactReference):
    sample_count: int = Field(ge=1, le=MAX_SAMPLES)


ARGUMENTS = {"audio.play": Play, "audio.capture": Capture}


class Capabilities(StrictModel):
    profile: Literal["audio_io_v1"]
    schema_sha256: SHA256
    commands: list[Literal["audio.play", "audio.capture"]] = Field(min_length=1, max_length=2)
    format: Literal["pcm_s16le_8000_mono"]
    sample_rate_hz: Literal[8000]
    max_samples: Literal[24000]
    output_gain_numerator: Literal[1]
    output_gain_denominator: Literal[8]
    hardware_gain_db: Literal[6]
    output_gpio: list[int] = Field(min_length=3, max_length=3)
    input_gpio: list[int] = Field(min_length=3, max_length=3)
    input_slot: Literal["left_24_msb_in_32"]
    input_conversion: Literal["signed_high_16_bits_no_gain"]
    warmup_samples: Literal[4800]
    underflow_detection: Literal["dma_callback_lateness"]


def schema():
    return {
        "scope": "finite_local_audio",
        "profile": PROFILE,
        "arguments": {k: v.model_json_schema() for k, v in ARGUMENTS.items()},
        "accepted": control_v2.AcceptedOperation.model_json_schema(),
        "capability": Capabilities.model_json_schema(),
    }


@lru_cache(maxsize=1)
def schema_digest():
    return hashlib.sha256(
        json.dumps(schema(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def require_capability(identity, health, name):
    if name not in ARGUMENTS:
        raise ValueError("Unknown finite audio command")
    for caps in (identity, health):
        if caps is None:
            raise ValueError("Audio identity/current health is unavailable")
        limits = Capabilities.model_validate(caps.resource_limits.get("audio_io"))
        flag = "audio_capture" if name == "audio.capture" else "audio_playback"
        if (
            limits.schema_sha256 != schema_digest()
            or name not in limits.commands
            or not getattr(caps, flag)
        ):
            raise ValueError("Exact configured audio capability is unavailable")
    return limits
