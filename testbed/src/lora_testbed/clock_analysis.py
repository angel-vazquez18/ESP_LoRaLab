"""Validate saved paired pulses and project explicit one-way timing phases."""

from fractions import Fraction
from itertools import pairwise
from math import ceil
from typing import Literal

from pydantic import Field

from .control_v2 import UUID
from .experiments_v2 import SHA256
from .models import StrictModel
from .v2 import Counter, Identifier

EXPECTED_PULSES = 32
INTERVAL_US = 100_000
MAX_AGE_US = 2_000_000
MAX_UNCERTAINTY_US = 1000


class ClockIdentity(StrictModel):
    device_id: Identifier
    boot_id: Identifier
    capture_id: UUID


class Edge(StrictModel):
    index: Counter
    local_us: Counter


class Capture(StrictModel):
    identity: ClockIdentity
    quantum_us: int = Field(ge=1, le=1000)
    edges: list[Edge] = Field(max_length=64)


class CaptureBounds(StrictModel):
    evidence_sha256: SHA256
    skew_us: int = Field(ge=0, le=1_000_000)
    drift_ppm: int = Field(ge=0, le=100_000)


class Observation(StrictModel):
    frame_id: Identifier
    sender_role: Literal["A", "B"]
    sender_clock: ClockIdentity
    receiver_clock: ClockIdentity
    tx_command_us: Counter
    rx_done_us: Counter
    application_accept_us: Counter | None = None


class ClockEvidence(StrictModel):
    calibration_id: UUID
    a: Capture
    b: Capture
    pulse_interval_tolerance_us: int = Field(ge=1, lt=50_000)
    capture_bounds: CaptureBounds | None = None
    observations: list[Observation] = Field(default_factory=list, max_length=600)


def capture_problem(evidence):
    if evidence.a.identity.device_id == evidence.b.identity.device_id:
        return "capture_requires_distinct_devices"
    for capture in (evidence.a, evidence.b):
        if len(capture.edges) != EXPECTED_PULSES:
            return "incorrect_pulse_count"
        for left, right in pairwise(capture.edges):
            if right.index != left.index + 1:
                return "missing_duplicate_or_reordered_pulse"
            delta = right.local_us - left.local_us
            if abs(delta - INTERVAL_US) > evidence.pulse_interval_tolerance_us:
                return "pulse_interval_outside_declared_tolerance"
    if [edge.index for edge in evidence.a.edges] != [edge.index for edge in evidence.b.edges]:
        return "peer_pulse_indices_differ"
    return None


def fit(evidence):
    a, b = ([edge.local_us for edge in capture.edges] for capture in (evidence.a, evidence.b))
    n = EXPECTED_PULSES
    x = [value - b[0] for value in b]
    y = [value - a[0] for value in a]
    sum_x, sum_y = sum(x), sum(y)
    scale = Fraction(
        n * sum(s * t for s, t in zip(x, y, strict=True)) - sum_x * sum_y,
        n * sum(s * s for s in x) - sum_x * sum_x,
    )
    offset = Fraction(sum_y, n) - scale * Fraction(sum_x, n) + a[0] - scale * b[0]
    residual = ceil(
        max(abs(target - (scale * source + offset)) for source, target in zip(b, a, strict=True))
    )
    return scale, offset, residual


def project_observation(evidence, observation, scale, offset, base_uncertainty):
    sender, receiver = (
        (evidence.a.identity, evidence.b.identity)
        if observation.sender_role == "A"
        else (evidence.b.identity, evidence.a.identity)
    )
    if (observation.sender_clock, observation.receiver_clock) != (sender, receiver):
        return {"reason": "device_boot_or_capture_changed"}
    if (
        observation.application_accept_us is not None
        and observation.application_accept_us < observation.rx_done_us
    ):
        return {"reason": "application_acceptance_precedes_receive"}

    def mapped(role, value):
        return Fraction(value) if role == "A" else scale * value + offset

    receiver_role = "B" if observation.sender_role == "A" else "A"
    tx = mapped(observation.sender_role, observation.tx_command_us)
    rx = mapped(receiver_role, observation.rx_done_us)
    accept = (
        mapped(receiver_role, observation.application_accept_us)
        if observation.application_accept_us is not None
        else None
    )
    latest = evidence.a.edges[-1].local_us
    if tx < latest:
        return {"reason": "sample_precedes_calibration_update"}
    age_us = ceil(max(tx, rx, accept if accept is not None else rx) - latest)
    assert evidence.capture_bounds is not None
    uncertainty = base_uncertainty + ceil(
        Fraction(age_us * evidence.capture_bounds.drift_ppm, 1_000_000)
    )
    if age_us > MAX_AGE_US:
        return {"reason": "calibration_expired", "age_us": age_us}
    if uncertainty > MAX_UNCERTAINTY_US:
        return {"reason": "uncertainty_exceeds_limit", "uncertainty_us": uncertainty}
    if rx < tx:
        return {"reason": "mapped_receive_precedes_transmit", "uncertainty_us": uncertainty}
    return {
        "reason": None,
        "age_us": age_us,
        "uncertainty_us": uncertainty,
        "tx_command_to_rx_done_us": float(rx - tx),
        "tx_command_to_application_accept_us": float(accept - tx) if accept is not None else None,
    }


def assess(evidence):
    problem = capture_problem(evidence)
    mapping = None
    if problem is None:
        scale, offset, residual = fit(evidence)
        quantization = ceil(evidence.a.quantum_us + scale * evidence.b.quantum_us)
        bounds = evidence.capture_bounds
        uncertainty = residual + quantization + bounds.skew_us if bounds is not None else None
        mapping = {
            "scale": [scale.numerator, scale.denominator],
            "offset_us": [offset.numerator, offset.denominator],
            "residual_us": residual,
            "quantization_us": quantization,
            "capture_skew_us": bounds.skew_us if bounds else None,
            "base_uncertainty_us": uncertainty,
            "reference_update_us": evidence.a.edges[-1].local_us,
        }
        if bounds is None:
            problem = "missing_instrument_bounds"
        elif uncertainty > MAX_UNCERTAINTY_US:
            problem = "uncertainty_exceeds_limit"

    rows = []
    for obs in evidence.observations:
        result = (
            {"reason": problem}
            if problem
            else project_observation(evidence, obs, scale, offset, uncertainty)
        )
        rows.append(
            {
                "frame_id": obs.frame_id,
                "sender_role": obs.sender_role,
                "valid": result["reason"] is None,
                "tx_command_to_rx_done_us": None,
                "tx_command_to_application_accept_us": None,
                **result,
            }
        )
    return {
        "calibration_id": evidence.calibration_id,
        "scope": "offline assessment of supplied pulse and frame evidence",
        "hardware_validated": False,
        "capture_complete": mapping is not None,
        "eligible": problem is None,
        "reason": problem,
        "mapping": mapping,
        "observations": rows,
        "raw": evidence.model_dump(),
    }
