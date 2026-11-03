import io
import wave

import pytest
from fastapi.testclient import TestClient

from lora_testbed.app import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as instance:
        yield instance


def wav_bytes(channels=1, sample_rate=8000, samples=24000):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(b"\x00\x01" * samples * channels)
    return output.getvalue()


def test_reference_audio_validation_persistence_and_retrieval(client):
    content = wav_bytes()
    response = client.post("/api/audio/references?name=reference.wav", content=content)
    assert response.status_code == 201
    reference = response.json()
    assert reference["raw_bytes"] == 48000
    assert reference["duration_s"] == 3
    assert len(reference["peaks"]) <= 128
    assert client.get(f"/api/audio/references/{reference['id']}/wav").content == content
    assert len(client.get("/api/state").json()["references"]) == 1
    assert client.post("/api/audio/references", content=wav_bytes(channels=2)).status_code == 400
    assert client.post("/api/audio/references", content=wav_bytes(samples=24001)).status_code == 400
    assert client.post("/api/audio/references", content=b"not a wave").status_code == 400
    assert client.post("/api/audio/references", content=content[:-20]).status_code == 400
    assert client.post("/api/audio/references", content=b"x" * 1_048_577).status_code == 413
