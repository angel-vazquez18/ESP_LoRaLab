"""Qualification packet consistency tests; synthetic records never qualify hardware."""

import importlib.util
import json
import struct
from uuid import uuid4

import pytest

from lora_testbed.paths import REPOSITORY_ROOT

spec = importlib.util.spec_from_file_location(
    "audio_qualification", REPOSITORY_ROOT / "scripts/audio_qualification.py"
)
q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(q)


def record(pcm, identifier="esp-fixture"):
    return {
        "id": str(uuid4()),
        "status": "completed",
        "action": "capture",
        "sample_count": 24000,
        "identity": {
            "device_id": identifier,
            "provenance": "hardware",
            "firmware_build_id": "a" * 64,
        },
        "clip": {"pcm_sha256": q.digest(pcm), "raw_bytes": 48000, "clipped_samples": 0},
        "node_result": {
            "status": "completed",
            "result": {
                "samples_requested": 24000,
                "samples_completed": 24000,
                "dma_completed": True,
                "underflows": 0,
                "overflows": 0,
                "artifact": {"sha256": q.digest(pcm)},
            },
        },
    }


def synthetic_packet(tmp_path):
    directory = tmp_path / "packet"
    d = q.prepare(directory, "esp-fixture")
    d.update(
        operator="synthetic fixture",
        observed_at="fixture timestamp",
        printed_revision="fixture",
        wiring_independently_checked=True,
        microphone_response_notes="synthetic notes, no physical evidence",
    )
    d["listening"] = {
        "reference_heard": True,
        "captured_heard": True,
        "distortion_notes": "synthetic only",
    }
    pcm = q.reference()
    for kind in ("speech", "quiet"):
        (directory / f"{kind}.wav").write_bytes(q.pcm_wav(pcm))
        q.save_json(directory / f"{kind}.json", record(pcm))
        d["captures"][kind] = {
            "wav": f"{kind}.wav",
            "record": f"{kind}.json",
            "pcm_sha256": q.digest(pcm),
        }
    for name in ("sample_clock", "rail"):
        d["instruments"][name] = {
            "available": False,
            "measurement": None,
            "limitation": "synthetic missing instrument",
        }
    (directory / "fixture-evidence.json").write_text('{"fixture_only":true}')
    d["recovery"] = {
        "invalid_upload_rejected": True,
        "invalid_upload_evidence": "fixture-evidence.json",
        "cancel_then_valid": True,
        "cancel_evidence": "fixture-evidence.json",
        "usb_issue_21_evidence": "fixture-evidence.json",
    }
    q.save_json(directory / "observations.json", d)
    return directory, d


def test_reference_has_exact_bytes_quiet_limit_fade_and_wav_preserves_samples(tmp_path):
    directory = tmp_path / "packet"
    d = q.prepare(directory, "esp-fixture")
    pcm = (directory / "quiet-reference.pcm").read_bytes()
    values = struct.unpack("<24000h", pcm)
    assert len(pcm) == 48000 and values[0] == values[-1] == 0
    assert 0 < max(abs(v) for v in values) <= 1000
    assert q.read_pcm((directory / "quiet-reference.wav").read_bytes()) == pcm
    assert q.digest(pcm) == d["reference"]["pcm_sha256"]
    assert q.assess(directory)["status"] == "pending"
    with pytest.raises(FileExistsError):
        q.prepare(directory)


@pytest.mark.parametrize(
    "field",
    ["operator", "printed_revision", "microphone_response_notes", "wiring_independently_checked"],
)
def test_missing_observation_cannot_become_ready_for_human_review(tmp_path, field):
    directory, d = synthetic_packet(tmp_path)
    d[field] = None
    q.save_json(directory / "observations.json", d)
    r = q.assess(directory)
    assert r["status"] == "pending" and not r["automatic_hardware_qualification"]


@pytest.mark.parametrize(
    "fault",
    [
        "zero_speech",
        "clipping",
        "wav_corruption",
        "hash",
        "different_build",
        "dma",
        "count",
        "truncated",
    ],
)
def test_invalid_physical_packet_content_is_failed_even_with_completed_jobs(tmp_path, fault):
    directory, d = synthetic_packet(tmp_path)
    if fault in ("zero_speech", "clipping"):
        pcm = b"\0" * 48000 if fault == "zero_speech" else struct.pack("<h", 32767) * 24000
        (directory / "speech.wav").write_bytes(q.pcm_wav(pcm))
        q.save_json(directory / "speech.json", record(pcm))
        d["captures"]["speech"]["pcm_sha256"] = q.digest(pcm)
    elif fault == "truncated":
        p = directory / "speech.wav"
        p.write_bytes(p.read_bytes()[:-2])
    elif fault == "wav_corruption":
        (directory / "speech.wav").write_bytes(b"broken")
    elif fault == "hash":
        d["captures"]["speech"]["pcm_sha256"] = "0" * 64
    else:
        p = directory / "speech.json"
        r = json.loads(p.read_text())
        if fault == "different_build":
            r["identity"]["firmware_build_id"] = "b" * 64
        elif fault == "count":
            r["sample_count"] = 23999
        else:
            r["node_result"]["result"]["dma_completed"] = False
        q.save_json(p, r)
    q.save_json(directory / "observations.json", d)
    assert q.assess(directory)["status"] == "failed"


def test_configured_clock_is_not_accepted_as_a_measurement_without_an_instrument_trace(tmp_path):
    directory, d = synthetic_packet(tmp_path)
    d["instruments"]["sample_clock"] = {
        "available": True,
        "measurement": "configured 8000 Hz",
        "limitation": None,
    }
    q.save_json(directory / "observations.json", d)
    assert q.assess(directory)["status"] == "pending"
    d["instruments"]["sample_clock"]["measurement"] = {
        "instrument": "fixture",
        "method": "fixture",
        "observed": "fixture",
        "trace": "fixture-evidence.json",
    }
    q.save_json(directory / "observations.json", d)
    r = q.assess(directory)
    assert (
        r["status"] == "ready_for_human_review" and r["automatic_hardware_qualification"] is False
    )


@pytest.mark.parametrize(
    "field", ["invalid_upload_evidence", "cancel_evidence", "usb_issue_21_evidence"]
)
def test_missing_recovery_evidence_keeps_packet_pending(tmp_path, field):
    directory, d = synthetic_packet(tmp_path)
    d["recovery"][field] = None
    q.save_json(directory / "observations.json", d)
    assert q.assess(directory)["status"] == "pending"


def test_collect_is_read_only_bounded_and_checks_device_hash_before_saving(tmp_path, monkeypatch):
    directory = tmp_path / "packet"
    q.prepare(directory, "esp-fixture")
    pcm = q.reference()
    r = record(pcm)
    calls = []

    def fetch(base, suffix, limit):
        calls.append((suffix, limit))
        return q.pcm_wav(pcm) if suffix.endswith("/wav") else json.dumps(r).encode()

    monkeypatch.setattr(q, "fetch", fetch)
    entry = q.collect(directory, "speech", r["id"], "http://127.0.0.1:8000")
    assert entry["pcm_sha256"] == q.digest(pcm) and len(calls) == 2
    assert q.read_pcm((directory / "speech.wav").read_bytes()) == pcm
    with pytest.raises(ValueError, match="already exists"):
        q.collect(directory, "speech", r["id"], "http://127.0.0.1:8000")


@pytest.mark.parametrize(
    "base", ["https://example.com", "http://example.com", "http://user:password@localhost:8000"]
)
def test_collection_refuses_remote_or_credential_bearing_backends(base):
    with pytest.raises(ValueError, match="loopback"):
        q.fetch(base, "/api/state", 100)


def test_packet_paths_and_file_reads_are_bounded(tmp_path):
    with pytest.raises(ValueError):
        q.local_file(tmp_path, "../outside.wav")
    p = tmp_path / "oversized"
    p.write_bytes(b"x" * 100)
    with pytest.raises(ValueError):
        q.read_file(p, 99)
