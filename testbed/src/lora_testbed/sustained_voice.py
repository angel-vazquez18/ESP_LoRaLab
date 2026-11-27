"""Fixed-rate voice procedure cases and bound source/archive assessments."""

from itertools import product

from .experiments_v2 import Link, Radio
from .voice_runs import SustainedVoiceRequest

GROUPS = {
    "VOICE-03": {
        "C1": "wide_band_unacknowledged",
        "C2": "wide_band_stop_and_wait",
        "C3": "slow_profile_overload_check",
    }
}


def cases(request, groups):
    for group, direction, repetition in product(
        groups, request.directions, range(1, request.repetitions + 1)
    ):
        yield {
            "group": group,
            "variant": GROUPS["VOICE-03"][group],
            "repetition": repetition,
            "driver": "sustained_voice",
            "role": direction,
            "direction": direction,
            "reference_id": next(iter(request.voice_reference_ids or ()), None),
            "message_bytes": 1200,
            "message_count": 20,
            "producer_duration_ms": 60_000,
            "drain_cap_ms": 30_000,
            "source_frame_rate_hz": 50,
            "queue_observation_hz": 5,
            "queue_max_bytes": 4800,
            "radio": Radio(
                bandwidth_hz=125_000 if group == "C3" else 500_000,
                spreading_factor=12 if group == "C3" else 7,
                tx_power_dbm=2,
            ).model_dump(),
            "link": Link(
                ack_mode="stop_wait" if group == "C2" else "none",
                max_retries=2 if group == "C2" else 0,
            ).model_dump(),
        }


def request_for(case):
    return SustainedVoiceRequest(
        direction=case["direction"],
        reference_id=case["reference_id"],
        radio=Radio.model_validate(case["radio"]),
        link=Link.model_validate(case["link"]),
    )


def blockers(voice, case):
    if not case["reference_id"]:
        return ["Select one saved three-second reference"]
    if voice is None:
        return ["Voice preflight is unavailable"]
    return voice.preflight(request_for(case))["blockers"]
