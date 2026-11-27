"""Check that listening ratings bind to inspected audio and retain valid clock scope."""

import json
from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from lora_testbed import cli
from lora_testbed.app import create_app
from lora_testbed.voice_quality import Review, review


def inspection(identifier):
    return {
        "record": {
            "id": identifier,
            "status": "completed",
            "request": {"source": "reference", "direction": "A_TO_B", "radio": {}, "link": {}},
            "playback_completed": True,
            "listening": {"heard": "not_checked"},
        },
        "files": {
            "source": {
                "available": True,
                "sha256": "1" * 64,
                "pcm": {"waveform": [{"min": -0.1, "max": 0.1}]},
            },
            "decoded": {
                "available": True,
                "sha256": "2" * 64,
                "pcm": {"waveform": [{"min": -0.2, "max": 0.2}]},
            },
        },
        "stages": [
            {
                "name": "encode",
                "status": "completed",
                "timing": {"basis": "node_monotonic_us", "duration_us": 10, "role": "A"},
            },
        ],
        "encoded_integrity": {"verified": True},
        "one_way_latency": {"valid": False, "value_us": None, "reason": "No calibration"},
    }


def test_voice_review_matches_each_rating_to_an_exact_clip_and_listener():
    key = str(uuid4())
    requested = Review(run_ids=[key])
    plan = review(requested, inspection)
    assert len(plan["presentation_order"]) == 2
    assert {clip["waveform"][0]["max"] for clip in plan["clip_key"].values()} == {0.1, 0.2}
    [distribution] = plan["stage_distributions"]
    assert distribution["n"] == 1 and distribution["median_us"] == distribution["p95_us"] == 10
    assert distribution["samples"][0]["run_id"] == key
    assert plan["presentation_order"] == review(requested, inspection)["presentation_order"]
    given = [
        {
            "listener_id": "listener-2",
            "clip_code": clip["code"],
            "audio_sha256": clip["sha256"],
            "score": 4 if clip["kind"] == "decoded" else 5,
        }
        for clip in plan["clip_key"].values()
    ]
    output = review(Review.model_validate({**requested.model_dump(), "ratings": given}), inspection)
    [run] = output["runs"]
    assert run["paired_listeners"] == ["listener-2"]
    assert run["ratings"]["decoded"]["score_counts"] == {"4": 1}
    assert run["ratings"]["source"]["score_counts"] == {"5": 1}
    assert run["named_stage_timing"][0]["duration_us"] == 10
    assert not run["one_way_latency"]["valid"] and not output["hardware_validated"]

    altered = deepcopy(given)
    altered[0]["audio_sha256"] = "3" * 64
    with pytest.raises(ValueError, match="changed artifact hash"):
        review(Review.model_validate({**requested.model_dump(), "ratings": altered}), inspection)


def test_voice_api_excludes_a_run_with_missing_encoded_verification(tmp_path, monkeypatch):
    key = str(uuid4())
    damaged = inspection(key)
    damaged["encoded_integrity"]["verified"] = False
    with TestClient(create_app(tmp_path)) as ui:
        monkeypatch.setattr(ui.app.state.host.voice, "inspect", lambda _: damaged)
        response = ui.post("/api/voice/review", json={"run_ids": [key]})
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["presentation_order"] == []
        assert report["exclusions"][0]["run_id"] == key
        assert not report["hardware_validated"]


def test_voice_review_cli_uses_shared_endpoint(tmp_path, monkeypatch):
    args = {"run_ids": [str(uuid4())]}
    source = tmp_path / "review.json"
    source.write_text(json.dumps(args))
    calls = []
    monkeypatch.setattr(cli, "request", lambda path, body: calls.append((path, body)))
    result = CliRunner().invoke(cli.app, ["voice-review", str(source)])
    assert result.exit_code == 0, result.output
    assert calls == [("/api/voice/review", args)]
