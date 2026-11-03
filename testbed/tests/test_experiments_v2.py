import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from lora_testbed import rf_events_v2, v2
from lora_testbed.app import create_app
from lora_testbed.experiments_v2 import KnownDataPlan, Radio, airtime_us, known_data, preview

ROOT = Path(__file__).resolve().parents[2]


def test_known_data_matches_public_cross_language_vector():
    vector = json.loads((ROOT / "contracts/v2/conformance_vectors.json").read_text())["known_data"]
    actual = known_data(vector["seed"], vector["message_id"], vector["message_bytes"])
    assert actual.hex() == vector["payload_hex"]
    assert hashlib.sha256(actual).hexdigest() == vector["sha256"]
    assert known_data(743, 1, 1) == actual[:1]
    assert known_data(743, 1, 33) == actual[:33]
    assert known_data(743, 2, 64) != actual
    for args in [(True, 1, 64), (-1, 1, 64), (0, 0, 64), (0, 1, 65537)]:
        with pytest.raises(ValueError):
            known_data(*args)


@pytest.mark.parametrize(
    ("sf", "length", "expected"), [(7, 120, 199936), (7, 216, 343296), (12, 216, 7872512)]
)
def test_airtime_against_independent_reference_vectors(sf, length, expected):
    assert airtime_us(Radio(spreading_factor=sf), length) == expected


def test_exact_fragment_boundaries_security_overhead_and_budget():
    default = preview(KnownDataPlan())
    assert default["fragmentation"]["last_fragment_frame_bytes"] == 104
    assert default["fragmentation"]["total_useful_bytes"] == 6400
    assert default["timing"]["worst_case_duration_us"] == 26_895_600
    protected = preview(KnownDataPlan.model_validate({"spec": {"security": "aes128_gcm"}}))
    assert protected["fragmentation"]["last_fragment_frame_bytes"] == 120
    assert protected["timing"]["worst_case_duration_us"] == 28_943_600
    for size, count, last in [(159, 1, 159), (160, 1, 160), (161, 2, 1), (320, 2, 160)]:
        item = preview(KnownDataPlan.model_validate({"spec": {"message_bytes": size}}))
        assert item["fragmentation"]["fragments_per_message"] == count
        assert item["fragmentation"]["last_fragment_payload_bytes"] == last
        assert ("fragmentation" in item["required_capabilities"]) == (count > 1)
    assert preview(KnownDataPlan()) == default


def test_ack_retry_budget_and_explicit_duration_failure():
    plan = KnownDataPlan.model_validate(
        {
            "link": {"ack_mode": "stop_wait"},
            "spec": {
                "message_count": 1,
                "message_bytes": 160,
                "security": "aes128_gcm",
                "max_duration_ms": 1000,
            },
        }
    )
    result = preview(plan)
    assert plan.link.max_retries == 2
    assert result["fragmentation"]["maximum_attempts"] == 3
    timing = result["timing"]
    assert timing["ack_airtime_us"] == 107776
    assert timing["budget"]["ack_timeout_us"] == 207776
    assert timing["worst_case_duration_us"] == 3_793_216
    assert timing["fits_selected_duration"] is False
    assert result["plan"]["spec"]["message_count"] == 1
    assert result["plan"]["spec"]["max_duration_ms"] == 1000
    huge = preview(
        KnownDataPlan.model_validate(
            {"radio": {"spreading_factor": 12}, "spec": {"message_bytes": 65536}}
        )
    )
    assert huge["timing"]["requires_linked_split"] is True
    assert huge["timing"]["recommended_max_duration_ms"] is None
    assert huge["fragmentation"]["original_packets"] == 41000


def test_duration_boundary_includes_full_millisecond_rounding_and_headroom():
    for duration, fits in [(27895, False), (27896, True)]:
        result = preview(KnownDataPlan.model_validate({"spec": {"max_duration_ms": duration}}))
        assert result["timing"]["required_max_duration_ms"] == 27896
        assert result["timing"]["fits_selected_duration"] is fits


@pytest.mark.parametrize(
    "body",
    [
        {"loss_rate": 0.5},
        {"radio": {"frequency_hz": 915000001}},
        {"radio": {"header_mode": "implicit"}},
        {"radio": {"crc_enabled": 1}},
        {"radio": {"sync_word": 5156.0}},
        {"spec": {"playback": 0}},
        {"spec": {"instrumentation": {"packet_events": 1}}},
        {"spec": {"message_count": True}},
        {"spec": {"sample_count": 24000}},
        {"spec": {"message_count": 0}},
        {"spec": {"source": "node_microphone"}},
        {"spec": {"message_bytes": 65537}},
        {"spec": {"instrumentation": {"crypto_samples": True}}},
        {"link": {"max_retries": 2}},
        {"link": {"fragment_payload_bytes": 200}, "spec": {"security": "aes128_gcm"}},
    ],
)
def test_invalid_or_simulation_only_settings_are_rejected(body):
    with pytest.raises(ValidationError):
        KnownDataPlan.model_validate(body)


def attempt_event():
    return {
        "v": 2,
        "kind": "event",
        "device_id": "esp-test",
        "boot_id": "esp-test:1",
        "node_role": "A",
        "event_seq": 1,
        "uptime_us": 200000,
        "run_id": "11111111-1111-4111-8111-111111111111",
        "name": "tx.attempt",
        "data": {
            "session_id": "0102030405060708",
            "frame_seq": 1,
            "message_id": 1,
            "fragment_index": 0,
            "attempt_index": 1,
            "frame_type": "data",
            "frame_bytes": 104,
            "tx_command_us": 100,
            "tx_done_us": 179556,
            "status": "completed",
        },
    }


def test_staged_events_validate_evidence_without_changing_diagnostic_wire():
    event = attempt_event()
    assert rf_events_v2.ADAPTER.validate_python(event).data.frame_bytes == 104
    for key, value in [
        ("session_id", "0000000000000000"),
        ("frame_seq", 0),
        ("tx_done_us", 99),
        ("tx_done_us", None),
    ]:
        bad = deepcopy(event)
        bad["data"][key] = value
        with pytest.raises(ValidationError):
            rf_events_v2.ADAPTER.validate_python(bad)
    with pytest.raises(ValidationError):
        v2.ADAPTER.validate_python(event)
    delivery = {
        **event,
        "name": "message.result",
        "data": {
            "message_id": 1,
            "status": "delivered",
            "message_bytes": 64,
            "sha256": None,
            "fragment_count": 1,
            "missing_count": 0,
            "missing_parts": 0,
            "first_fragment_us": 100,
            "complete_us": 200,
        },
    }
    with pytest.raises(ValidationError):
        rf_events_v2.ADAPTER.validate_python(delivery)
    delivery["data"]["sha256"] = "a" * 64
    assert rf_events_v2.ADAPTER.validate_python(delivery).data.status == "delivered"


def test_previews_are_read_only_and_diagnostic_compatibility_is_preserved(tmp_path):
    header = (ROOT / "firmware/diagnostic/main/contract_schema.h").read_text()
    assert v2.schema_digest() in header
    with TestClient(create_app(tmp_path)) as client:
        before = client.get("/api/state").json()
        assert client.get("/api/protocol/v2").json()["schema_sha256"] == v2.schema_digest()
        metadata = client.get("/api/protocol/v2/known-data").json()
        assert metadata["execution_available"] is False
        assert metadata["event_schema_sha256"] == rf_events_v2.schema_digest()
        response = client.post("/api/experiments/v2/known-data/preview", json={})
        assert response.status_code == 200
        result = response.json()
        assert result["execution_available"] is result["hardware_validated"] is False
        assert result["first_message_sha256"] == (
            "23ba5aff34305fd81aea721044b5f208bbd49b1f6b87f4a73598046d8672de82"
        )
        assert (
            client.post(
                "/api/experiments/v2/known-data/preview",
                json={
                    "link": {"max_retries": 1},
                },
            ).status_code
            == 422
        )
        assert client.get("/api/state").json() == before
        client.post("/api/bench/mode", json={"mode": "hardware"})
        assert client.post("/api/runs", json={}).status_code == 400
