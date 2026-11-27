"""Passive optional OLED worker observations; readiness is not pixel validation."""

import hashlib
import json
from functools import lru_cache
from typing import Literal

from .artifact_contract_v2 import SHA256
from .models import StrictModel

PROFILE = "oled_status_v1"


class Status(StrictModel):
    profile: Literal["oled_status_v1"]
    schema_sha256: SHA256
    state: Literal["starting", "ready", "setup_failed", "io_failed", "allocation_failed"]
    physical_qualified: Literal[False]


def schema():
    return {
        "scope": "passive_oled_worker_observation",
        "profile": PROFILE,
        "status": Status.model_json_schema(),
        "policy": {
            "controller": "SSD1315",
            "width": 128,
            "height": 64,
            "frame_bytes": 1024,
            "max_frame_writes": 10,
            "io_timeout_ms": 5,
            "worker_period_ms": 250,
            "pending_views": 1,
            "ready_basis": "complete_i2c_frame_acknowledgment_not_observed_pixels",
            "failure_policy": "stop_worker_no_automatic_retry_keep_vext_on",
        },
    }


@lru_cache(maxsize=1)
def schema_digest():
    return hashlib.sha256(
        json.dumps(schema(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
