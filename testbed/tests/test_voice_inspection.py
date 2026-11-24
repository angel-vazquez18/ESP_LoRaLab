"""Public dashboard inspection with native codec/radio nodes and isolated I/O."""

import asyncio
import contextlib

import pytest
from fastapi.testclient import TestClient
from test_artifact_transfers import finished
from test_node_control_native import native_library as native_library
from test_voice_workflows import AudioPair

from lora_testbed.app import create_app


def test_voice_inspection_preserves_files_stage_clocks_and_listening_after_reload(
    native_library, tmp_path
):
    with TestClient(create_app(data_dir=tmp_path)) as client:
        host = client.app.state.host
        pair = AudioPair(host, native_library)

        async def connect():
            await pair.connect()
            return asyncio.create_task(pair.bridge())

        bridge = client.portal.call(connect)
        try:
            started = client.post(
                "/api/voice/runs",
                json={"source": "microphone", "sample_count": 160, "include_comparisons": False},
            )
            assert started.status_code == 202
            result = client.portal.call(finished, host.voice, started.json()["id"])
            assert result["status"] == "completed", result["error"]
            path = f"/api/voice/runs/{result['id']}/inspection"
            response = client.get(path)
            assert response.status_code == 200, response.text
            view = response.json()
            assert view["record"]["id"] == result["id"]
            assert view["files"]["source"]["length_bytes"] == 320
            assert len(view["files"]["source"]["pcm"]["waveform"]) > 0
            assert view["files"]["encoded"]["length_bytes"] == 8
            assert view["files"]["encoded"]["sha256"] == view["files"]["recovered"]["sha256"]
            assert view["files"]["decoded"]["pcm"]["sample_count"] == 160
            assert view["encoded_integrity"]["verified"]
            assert (
                view["files"]["encoded"]["manifest"]["artifact_id"]
                != (view["files"]["recovered"]["manifest"]["artifact_id"])
            )
            stages = {row["name"]: row for row in view["stages"]}
            assert stages["encode"]["timing"]["basis"] == "node_monotonic_us"
            assert stages["encode"]["timing"]["role"] == "A"
            assert stages["capture"]["timing"]["basis"] == "node_monotonic_us"
            assert stages["playback"]["timing"]["duration_us"] >= 0
            assert stages["playback"]["timing"]["started_us"] is None
            assert stages["receiver_decode"]["timing"]["role"] == "B"
            assert (
                stages["encode"]["timing"]["boot_id"]
                != stages["receiver_decode"]["timing"]["boot_id"]
            )
            assert view["one_way_latency"]["value_us"] is None
            assert not view["one_way_latency"]["valid"]
            assert "calibration" in view["one_way_latency"]["reason"]
            client.post(
                f"/api/voice/runs/{result['id']}/listening",
                json={"heard": "not_checked", "notes": "isolated browser fixture"},
            ).raise_for_status()
            reloaded = client.get(path).json()
            assert reloaded["record"]["listening"]["notes"] == "isolated browser fixture"
            assert not reloaded["record"]["hardware_qualified"]
            host.radio.content(result["radio_run_id"], "recovered").write_bytes(b"changed")
            changed = client.get(path).json()
            assert not changed["files"]["recovered"]["available"]
            assert "integrity" in changed["files"]["recovered"]["error"]
            assert not changed["encoded_integrity"]["verified"]
            assert changed["record"]["delivery_verified"]  # Historical observation is unchanged.
        finally:

            async def stop_bridge():
                bridge.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bridge

            client.portal.call(stop_bridge)


@pytest.mark.parametrize("action", ["cancel", "incomplete"])
def test_incomplete_voice_inspection_keeps_receiver_outputs_unavailable(
    native_library, tmp_path, action
):
    with TestClient(create_app(data_dir=tmp_path)) as client:
        host = client.app.state.host
        pair = AudioPair(host, native_library, drop="data")

        async def connect():
            await pair.connect()
            return asyncio.create_task(pair.bridge())

        bridge = client.portal.call(connect)
        try:
            started = client.post(
                "/api/voice/runs",
                json={
                    "source": "microphone",
                    "sample_count": 160,
                    "include_comparisons": False,
                    "timeout_ms": 15000,
                },
            ).json()
            if action == "cancel":

                async def wait_for_radio():
                    async with asyncio.timeout(5):
                        while not host.voice.get(started["id"])["radio_run_id"]:
                            await asyncio.sleep(0.002)

                client.portal.call(wait_for_radio)
                stopped = client.post(f"/api/voice/runs/{started['id']}/stop")
                assert stopped.status_code == 200
                assert stopped.json()["status"] == "cancelled"
            else:
                assert client.portal.call(finished, host.voice, started["id"])["status"] == "failed"
            response = client.get(f"/api/voice/runs/{started['id']}/inspection")
            assert response.status_code == 200, response.text
            view = response.json()
            assert not view["record"]["delivery_verified"]
            assert not view["record"]["playback_completed"]
            assert not view["encoded_integrity"]["verified"]
            assert view["files"]["source"]["available"]
            assert not view["files"]["recovered"]["available"]
            assert not view["files"]["decoded"]["available"]
            assert not view["one_way_latency"]["valid"]
            assert all(
                stage["status"] == "not_started"
                for stage in view["stages"]
                if stage["name"] in ("receiver_decode", "playback")
            )
        finally:

            async def stop_bridge():
                bridge.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bridge

            client.portal.call(stop_bridge)
