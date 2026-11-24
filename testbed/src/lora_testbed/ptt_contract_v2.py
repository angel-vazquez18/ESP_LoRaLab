"""Optional host-armed finite capture; no autonomous button/RF operation."""

import hashlib
import json
from functools import lru_cache
from typing import Literal

from . import audio_contract_v2, control_v2
from .artifact_contract_v2 import SHA256
from .models import StrictModel

PROFILE = "ptt_capture_v1"
DEBOUNCE_US = 50000
ARGUMENTS = {"ptt.arm": audio_contract_v2.Capture}


class Availability(StrictModel):
    profile: Literal["ptt_capture_v1"]
    schema_sha256: SHA256
    commands: list[Literal["ptt.arm"]]


POLICY = {
    "gpio": 47,
    "internal_pullup": True,
    "active_level": 0,
    "debounce_us": DEBOUNCE_US,
    "release_after_arm_required": True,
    "action": "one_finite_capture",
    "max_samples": 24000,
    "deadline_us": 30000000,
}


def schema():
    return {
        "scope": "host_armed_finite_capture",
        "profile": PROFILE,
        "policy": POLICY,
        "arguments": {key: value.model_json_schema() for key, value in ARGUMENTS.items()},
        "accepted": control_v2.AcceptedOperation.model_json_schema(),
        "capability": Availability.model_json_schema(),
        "availability": Availability.model_json_schema(),
    }


@lru_cache(maxsize=1)
def schema_digest():
    return hashlib.sha256(
        json.dumps(schema(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def require_capability(identity, health):
    audio_contract_v2.require_capability(identity, health, "audio.capture")
    if identity is None or health is None:
        raise ValueError("PTT identity/current health is unavailable")
    limits = Availability.model_validate(identity.resource_limits.get("ptt_io"))
    current = Availability.model_validate(health.resource_limits.get("ptt_io"))
    if any(
        value.schema_sha256 != schema_digest() or value.commands != ["ptt.arm"]
        for value in (limits, current)
    ):
        raise ValueError("Exact configured PTT capability is unavailable")
    return limits
