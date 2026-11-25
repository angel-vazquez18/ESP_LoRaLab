"""Check one-way analysis bounds without assuming a live calibrated bench."""

import json
from copy import deepcopy
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from lora_testbed.cli import app
from lora_testbed.clock_analysis import ClockEvidence, assess


def reference_case():
    a = {
        "device_id": "esp-A",
        "boot_id": "boot-A",
        "capture_id": str(uuid4()),
    }
    b = {
        "device_id": "esp-B",
        "boot_id": "boot-B",
        "capture_id": str(uuid4()),
    }
    base_a, base_b = 10_000_000, 15_000_000
    last_a, last_b = base_a + 31 * 100010, base_b + 31 * 100000
    return {
        "calibration_id": str(uuid4()),
        "a": {
            "identity": a,
            "quantum_us": 1,
            "edges": [{"index": i + 10, "local_us": base_a + i * 100010} for i in range(32)],
        },
        "b": {
            "identity": b,
            "quantum_us": 1,
            "edges": [{"index": i + 10, "local_us": base_b + i * 100000} for i in range(32)],
        },
        "pulse_interval_tolerance_us": 100,
        "capture_bounds": {"evidence_sha256": "1" * 64, "skew_us": 30, "drift_ppm": 50},
        "observations": [
            {
                "frame_id": "A-1",
                "sender_role": "A",
                "sender_clock": deepcopy(a),
                "receiver_clock": deepcopy(b),
                "tx_command_us": last_a + 50005,
                "rx_done_us": last_b + 60000,
                "application_accept_us": last_b + 70000,
            },
            {
                "frame_id": "B-1",
                "sender_role": "B",
                "sender_clock": deepcopy(b),
                "receiver_clock": deepcopy(a),
                "tx_command_us": last_b + 50000,
                "rx_done_us": last_a + 60006,
            },
        ],
    }


def test_recovers_exact_scale_and_two_receiver_phases_without_qualification():
    report = assess(ClockEvidence.model_validate(reference_case()))
    assert report["eligible"] and not report["hardware_validated"]
    assert report["mapping"]["scale"] == [10001, 10000]
    assert report["mapping"]["residual_us"] == 0
    assert report["mapping"]["base_uncertainty_us"] == 33
    first, second = report["observations"]
    assert first["valid"] and first["tx_command_to_rx_done_us"] == 10001
    assert first["tx_command_to_application_accept_us"] == 20002
    assert first["uncertainty_us"] == 37
    assert second["valid"] and second["tx_command_to_rx_done_us"] == 10001
    assert second["tx_command_to_application_accept_us"] is None


@pytest.mark.parametrize(
    "change,expected",
    [
        (lambda source: source["b"]["edges"].pop(9), "incorrect_pulse_count"),
        (
            lambda source: source["b"]["edges"].append(source["b"]["edges"][-1]),
            "incorrect_pulse_count",
        ),
        (
            lambda source: source["b"]["edges"][9].update(index=12),
            "missing_duplicate_or_reordered_pulse",
        ),
        (
            lambda source: source["b"]["edges"][9].update(local_us=0),
            "pulse_interval_outside_declared_tolerance",
        ),
        (lambda source: source.pop("capture_bounds"), "missing_instrument_bounds"),
        (lambda source: source["capture_bounds"].update(skew_us=2000), "uncertainty_exceeds_limit"),
    ],
)
def test_incomplete_capture_or_bounds_disable_all_projection(change, expected):
    evidence = reference_case()
    change(evidence)
    report = assess(ClockEvidence.model_validate(evidence))
    assert not report["eligible"] and report["reason"] == expected
    assert all(
        not row["valid"] and row["tx_command_to_rx_done_us"] is None
        for row in report["observations"]
    )


def test_reset_expiry_and_growth_beyond_uncertainty_invalidate_only_the_affected_samples():
    source = reference_case()
    original = source["observations"][0]
    rebooted = deepcopy(original)
    rebooted["frame_id"] = "reset"
    rebooted["receiver_clock"]["boot_id"] = "boot-B-2"
    late = deepcopy(original)
    late.update(frame_id="expired", rx_done_us=late["rx_done_us"] + 2_000_000)
    late.pop("application_accept_us")
    uncertainty = deepcopy(original)
    uncertainty.update(
        frame_id="uncertainty",
        rx_done_us=uncertainty["rx_done_us"] + 1_500_000,
    )
    uncertainty.pop("application_accept_us")
    source["capture_bounds"]["drift_ppm"] = 1000
    source["observations"].extend([rebooted, late, uncertainty])
    report = assess(ClockEvidence.model_validate(source))
    assert [result["reason"] for result in report["observations"]] == [
        None,
        None,
        "device_boot_or_capture_changed",
        "calibration_expired",
        "uncertainty_exceeds_limit",
    ]


def test_cli_emits_offline_model_with_reproducible_input_hash(tmp_path):
    path = tmp_path / "pulses.json"
    path.write_text(json.dumps(reference_case()))
    result = CliRunner().invoke(app, ["clock-evaluate", str(path)])
    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["eligible"] and not output["hardware_validated"]
    assert len(output["input_sha256"]) == 64
