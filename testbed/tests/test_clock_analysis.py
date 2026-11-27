"""Check one-way analysis bounds without assuming a live calibrated bench."""

import hashlib
import json
from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from lora_testbed.app import create_app
from lora_testbed.cli import app
from lora_testbed.clock_analysis import MAX_EVIDENCE_BYTES, ClockEvidence, assess


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


def append_pulses(evidence, count):
    for role, interval in (("a", 100010), ("b", 100000)):
        edges = evidence[role]["edges"]
        last = edges[-1]
        edges.extend(
            {"index": last["index"] + i, "local_us": last["local_us"] + i * interval}
            for i in range(1, count + 1)
        )


def test_rolling_fit_selects_latest_prior_update_in_each_sender_domain():
    evidence = reference_case()
    append_pulses(evidence, 3)
    late = deepcopy(evidence["observations"][1])
    for field, step in (("tx_command_us", 100000), ("rx_done_us", 100010)):
        late[field] += 3 * step
    early = deepcopy(evidence["observations"][0])
    early["tx_command_us"] -= 60_000
    evidence["observations"].extend([late, early])

    report = assess(ClockEvidence.model_validate(evidence))
    assert [window["last_pulse_index"] for window in report["mapping_updates"]] == [41, 42, 43, 44]
    assert report["mapping"]["first_pulse_index"] == 13
    assert [row["calibration_update_pulse_index"] for row in report["observations"]] == [
        41,
        41,
        44,
        None,
    ]
    assert [row["tx_command_to_rx_done_us"] for row in report["observations"]] == [
        10001,
        10001,
        10001,
        None,
    ]
    assert report["observations"][-1]["reason"] == "sample_precedes_calibration_update"


def test_invalid_recent_window_is_not_replaced_by_an_older_eligible_fit():
    evidence = reference_case()
    append_pulses(evidence, 1)
    evidence["a"]["edges"][-1]["local_us"] += 90
    evidence["capture_bounds"]["skew_us"] = 950
    late = deepcopy(evidence["observations"][0])
    late["tx_command_us"] += 100010
    late["rx_done_us"] += 100000
    late["application_accept_us"] += 100000
    evidence["observations"].append(late)

    report = assess(ClockEvidence.model_validate(evidence))
    assert not report["eligible"]
    assert [window["eligible"] for window in report["mapping_updates"]] == [True, False]
    assert report["observations"][0]["valid"]
    assert report["observations"][-1]["reason"] == "uncertainty_exceeds_limit"
    assert report["observations"][-1]["calibration_update_pulse_index"] == 42
    assert report["observations"][-1]["tx_command_to_rx_done_us"] is None


def test_discontinuous_capture_does_not_hide_a_missing_edge_with_a_rolling_fit():
    evidence = reference_case()
    append_pulses(evidence, 2)
    evidence["b"]["edges"][-2]["index"] += 1
    report = assess(ClockEvidence.model_validate(evidence))
    assert not report["eligible"] and not report["mapping_updates"]
    assert {row["reason"] for row in report["observations"]} == {
        "missing_duplicate_or_reordered_pulse"
    }


def test_cli_emits_offline_model_with_reproducible_input_hash(tmp_path):
    path = tmp_path / "pulses.json"
    path.write_text(json.dumps(reference_case()))
    result = CliRunner().invoke(app, ["clock-evaluate", str(path)])
    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["eligible"] and not output["hardware_validated"]
    assert len(output["input_sha256"]) == 64


def test_clock_import_api_and_cli_keep_exact_source_hash_and_results(tmp_path):
    evidence = reference_case()
    append_pulses(evidence, 2)
    invalid = deepcopy(evidence["observations"][0])
    invalid["frame_id"] = "reset"
    invalid["receiver_clock"]["boot_id"] = "boot-B-later"
    evidence["observations"].append(invalid)
    source = ("\n" + json.dumps(evidence, indent=2) + "\n").encode()
    path = tmp_path / "pulses.json"
    path.write_bytes(source)
    cli = CliRunner().invoke(app, ["clock-evaluate", str(path)])
    assert cli.exit_code == 0, cli.output
    with TestClient(create_app(tmp_path / "store")) as client:
        response = client.post(
            "/api/procedures/clock/evaluate",
            content=source,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200
        report = response.json()
        assert report == json.loads(cli.output)
        assert report["input_sha256"] == hashlib.sha256(source).hexdigest()
        assert [row["reason"] for row in report["observations"]] == [
            None,
            None,
            "device_boot_or_capture_changed",
        ]
        assert report["observations"][-1]["tx_command_to_rx_done_us"] is None
        assert not report["hardware_validated"] and not client.app.state.host.busy


def test_clock_import_rejects_bad_duplicate_and_oversized_inputs(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        url = "/api/procedures/clock/evaluate"
        assert client.post(url, content=b"invalid JSON").status_code == 422
        assert client.post(url, content=b'{"a":1,"a":2}').status_code == 422
        assert client.post(url, content=b" " * (MAX_EVIDENCE_BYTES + 1)).status_code == 413
        assert not client.app.state.host.busy
