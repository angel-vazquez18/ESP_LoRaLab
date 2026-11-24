"""Optional finite PTT workflow over the same public API/serial/audio owners."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from test_artifact_transfers import finished
from test_node_audio_host import AutoAudio
from test_node_control_native import NativeSerial
from test_node_control_native import native_library as native_library

from lora_testbed.app import create_app


def test_ptt_api_waits_for_fresh_press_then_verifies_capture_without_rf(native_library, tmp_path):
    pressed = False
    audio = AutoAudio()
    serial = NativeSerial(
        native_library,
        audio=audio.port,
        ptt=lambda _: pressed,
        radio=native_library.native_radio_create(),
    )
    with TestClient(create_app(data_dir=tmp_path)) as client:
        host = client.app.state.host
        host.physical["A"].opener = lambda _: serial
        client.portal.call(host.physical["A"].connect, "isolated-ptt-fixture")
        response = client.post("/api/nodes/A/audio/ptt", json={"sample_count": 160})
        assert response.status_code == 202, response.text
        record = response.json()
        assert record["trigger"] == "host_armed_ptt"

        async def ready():
            async with asyncio.timeout(5):
                while host.audio.get(record["id"])["operation_id"] is None:
                    await asyncio.sleep(0.01)
                await asyncio.sleep(0.1)

        client.portal.call(ready)
        assert audio.starts == 0
        assert client.get("/api/state").json()["bench_busy"]
        assert host.physical["A"].active_operation
        assert (
            client.post("/api/nodes/A/audio/capture", json={"sample_count": 160}).status_code == 409
        )
        pressed = True
        result = client.portal.call(finished, host.audio, record["id"])
        assert result["status"] == "completed", result["error"]
        assert result["node_result"]["result"]["trigger"] == "host_armed_ptt"
        assert result["clip"]["sample_count"] == 160
        assert not host.radio.snapshot()["runs"] and audio.starts == 1
        assert client.get(f"/api/audio/operations/{record['id']}/wav").status_code == 200
        assert not client.get("/api/state").json()["bench_busy"]


def test_ptt_stop_retires_armed_capture_and_requires_fresh_arm_release(native_library, tmp_path):
    pressed = True
    audio = AutoAudio()
    serial = NativeSerial(native_library, audio=audio.port, ptt=lambda _: pressed)
    with TestClient(create_app(data_dir=tmp_path)) as client:
        host = client.app.state.host
        host.physical["A"].opener = lambda _: serial
        client.portal.call(host.physical["A"].connect, "isolated-held-ptt")
        started = client.post("/api/nodes/A/audio/ptt", json={"sample_count": 160})
        assert started.status_code == 202
        first = started.json()["id"]

        async def wait_armed(identifier):
            async with asyncio.timeout(5):
                while host.audio.get(identifier)["operation_id"] is None:
                    await asyncio.sleep(0.01)
                await asyncio.sleep(0.1)

        client.portal.call(wait_armed, first)
        assert audio.starts == 0
        stopped = client.post(f"/api/audio/operations/{first}/stop")
        assert stopped.status_code == 200 and stopped.json()["status"] == "cancelled"
        assert not host.busy and not stopped.json()["clip"]
        second = client.post("/api/nodes/A/audio/ptt", json={"sample_count": 160}).json()["id"]
        client.portal.call(wait_armed, second)
        assert audio.starts == 0
        pressed = False
        client.portal.call(asyncio.sleep, 0.12)
        pressed = True
        record = client.portal.call(finished, host.audio, second)
        assert record["status"] == "completed" and audio.starts == 1


def test_missing_ptt_blocks_before_arm_and_cli_uses_shared_api(
    native_library, tmp_path, monkeypatch
):
    from typer.testing import CliRunner

    from lora_testbed import cli

    audio = AutoAudio()
    serial = NativeSerial(native_library, audio=audio.port)
    with TestClient(create_app(data_dir=tmp_path)) as client:
        host = client.app.state.host
        host.physical["A"].opener = lambda _: serial
        client.portal.call(host.physical["A"].connect, "isolated-no-ptt")
        response = client.post("/api/nodes/A/audio/ptt", json={"sample_count": 160})
        assert response.status_code == 400
        assert audio.starts == 0 and not host.busy
        assert not host.audio.snapshot()["operations"]
        assert not host.physical["A"].snapshot()["ptt_support"]["commands"]
    calls = []
    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: calls.append((args, kwargs)))
    command = ["audio-ptt", "b", "--samples", "160"]
    assert CliRunner().invoke(cli.app, command).exit_code == 0
    assert calls[0][0] == ("/api/nodes/B/audio/ptt", {"sample_count": 160})
    assert CliRunner().invoke(cli.app, ["audio-ptt", "b", "--samples", "24001"]).exit_code != 0


@pytest.mark.parametrize("phase", ["identity", "health"])
def test_mismatched_ptt_fingerprint_blocks_arm_without_hiding_other_audio(
    native_library, tmp_path, phase
):
    class ChangedProfile(NativeSerial):
        def read(self, count):
            wire = super().read(count)
            if not wire:
                return wire
            record = json.loads(wire)
            result = record.get("result") or {}
            caps = result.get("capabilities" if phase == "identity" else "capability_availability")
            if caps and caps.get("resource_limits", {}).get("ptt_io"):
                caps["resource_limits"]["ptt_io"]["schema_sha256"] = "0" * 64
            if phase == "health" and record.get("name") == "health":
                record["data"]["capability_availability"]["resource_limits"]["ptt_io"][
                    "schema_sha256"
                ] = "0" * 64
            return json.dumps(record, separators=(",", ":")).encode() + b"\n"

    audio = AutoAudio()
    serial = ChangedProfile(native_library, audio=audio.port, ptt=lambda _: False)
    with TestClient(create_app(data_dir=tmp_path)) as client:
        host = client.app.state.host
        host.physical["A"].opener = lambda _: serial
        client.portal.call(host.physical["A"].connect, "isolated-mismatched-ptt")
        response = client.post("/api/nodes/A/audio/ptt", json={"sample_count": 160})
        assert response.status_code == 400 and "PTT" in response.text
        assert audio.starts == 0 and not host.busy
        assert "audio.capture" in host.physical["A"].snapshot()["audio_support"]["commands"]
