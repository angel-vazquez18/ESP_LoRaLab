"""Secure voice orchestration reuses actual physical services behind isolated ports."""

import asyncio
import contextlib

import pytest
from test_artifact_transfers import finished
from test_multi_fragment_radio import Pair
from test_node_audio_host import AutoAudio
from test_node_control_native import NativeSerial
from test_node_control_native import native_library as native_library

from lora_testbed.host import Host


def test_common_radio_runner_transfers_committed_encoded_bytes_with_post_rf_readback(
    native_library, tmp_path
):
    async def scenario():
        from lora_testbed.radio_runs import EncodedRadioRunRequest

        host = Host(tmp_path)
        pair = Pair(host, native_library)
        bridge = None
        try:
            await pair.connect()
            uploaded = await host.artifact_action(
                "start_upload", "A", b"\x00\x08" * 24000, format="pcm_s16le_8000_mono"
            )
            uploaded = await finished(host.artifacts, uploaded["id"])
            local = await host.audio_action("A", "codec", artifact_id=uploaded["artifact_id"])
            local = await finished(host.audio, local["id"])
            assert local["verified_roundtrip"]
            encoded = local["codec_artifacts"]["encoded"]["manifest"]
            for node in host.physical.values():
                await node.request("status.get")
            bridge = asyncio.create_task(pair.bridge())
            started = await host.start_radio(
                EncodedRadioRunRequest(
                    source_artifact_id=encoded["artifact_id"],
                    sample_count=encoded["sample_count"],
                    message_bytes=encoded["length_bytes"],
                    expected_sha256=encoded["sha256"],
                )
            )
            async with asyncio.timeout(15):
                while host.radio.busy:
                    if bridge.done():
                        await bridge
                    await asyncio.sleep(0.01)
            result = host.radio.get(started["id"])
            assert result["status"] == "completed", result.get("error")
            assert result["plan"]["spec"]["source"] == "encoded_source"
            assert (
                result["verification"]["bytes_equal"]
                and result["verification"]["sha256"] == encoded["sha256"]
            )
            assert result["prepared"]["A"]["artifact_id"] == encoded["artifact_id"]
            assert host.radio.content(
                result["id"], "source"
            ).read_bytes() == host.audio.codec_content(local["id"], "encoded")
            assert (
                host.radio.content(result["id"], "recovered").read_bytes()
                == host.radio.content(result["id"], "source").read_bytes()
            )
            for transfer_id in result["transfers"].values():
                assert (
                    host.artifacts.get(transfer_id)["created_at"] >= result["rf_window_closed_at"]
                )
            assert result["cleanup"]["confirmed"]
            assert not result["hardware_qualified"]
        finally:
            if bridge:
                bridge.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bridge
            await host.close()

    asyncio.run(scenario())


def test_receiver_decode_job_preserves_encoded_input_and_publishes_a_separate_pcm(
    native_library, tmp_path
):
    from test_node_audio_host import audio_bench

    async def scenario():
        async with audio_bench(native_library, tmp_path) as (host, serial):
            captured = await host.audio_action("A", "capture", sample_count=129)
            captured = await finished(host.audio, captured["id"])
            local = await host.audio_action("A", "codec", artifact_id=captured["artifact_id"])
            local = await finished(host.audio, local["id"])
            encoded = local["codec_artifacts"]["encoded"]["manifest"]
            job = await host.audio_action("A", "decode", artifact_id=encoded["artifact_id"])
            result = await finished(host.audio, job["id"])
            assert result["status"] == "completed" and result["verified_codec_stage"]
            assert not result["verified_roundtrip"] and result["node_result"] is None
            assert result["codec_artifacts"]["encoded"]["manifest"] == encoded
            assert result["artifact_id"] != encoded["artifact_id"]
            assert len(host.audio.codec_content(result["id"], "decoded")) == 258
            assert result["planned_output_ids"]["decoded"] == result["artifact_id"]
            assert serial.audio.starts == 1

    asyncio.run(scenario())


class AudioRadioSerial(NativeSerial):
    def __init__(self, lib, playback=True, **kwargs):
        self.audio = AutoAudio()
        self.audio.port.playback = playback
        super().__init__(lib, audio=self.audio.port, **kwargs)


class AudioPair(Pair):
    def __init__(self, *args, missing_playback=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.missing_playback = missing_playback

    async def connect(self):
        for role, device in (("A", "esp-001122334455"), ("B", "esp-66778899aabb")):
            serial = AudioRadioSerial(
                self.lib,
                radio=self.lib.native_radio_create(),
                device=device,
                playback=role != self.missing_playback,
            )
            self.serials[role] = serial
            self.host.physical[role].opener = lambda _, port=serial: port
            await self.host.physical[role].connect("isolated-voice-" + role)


def test_reference_voice_pipeline_uses_common_protection_and_two_labelled_comparisons(
    native_library, tmp_path
):
    from lora_testbed.audio import inspect_wav, pcm_wav, save_wav

    async def scenario():
        from lora_testbed.voice_runs import VoiceRunRequest

        host = Host(tmp_path)
        pair = AudioPair(host, native_library)
        bridge = None
        try:
            await pair.connect()
            pcm = b"\x00\x08" * 24000
            wav = pcm_wav(pcm, 24000)
            reference = inspect_wav(wav, "reference.wav")
            save_wav(tmp_path, reference, wav)
            host.store.save_reference(reference)
            bridge = asyncio.create_task(pair.bridge())
            started = await host.start_voice(
                VoiceRunRequest(source="reference", reference_id=reference["id"])
            )
            result = await finished(host.voice, started["id"])
            assert result["status"] == "completed", result.get("error")
            assert result["delivery_verified"] and result["playback_completed"]
            assert (
                not result["hardware_qualified"] and result["listening"]["heard"] == "not_checked"
            )
            assert host.voice.content(result["id"], "source") == pcm
            assert len(host.voice.content(result["id"], "encoded")) == 1200
            assert host.voice.content(result["id"], "recovered") == host.voice.content(
                result["id"], "encoded"
            )
            assert len(host.voice.content(result["id"], "decoded")) == 48000
            assert result["comparisons"]["equal_encoded_bytes"]["message_bytes"] == 1200
            assert result["comparisons"]["standard_64_bytes"]["message_bytes"] == 64
            ids = [
                result["radio_run_id"],
                *(value["radio_run_id"] for value in result["comparisons"].values()),
            ]
            children = [host.radio.get(identifier) for identifier in ids]
            assert all(
                child["status"] == "completed" and child["security"]["profile"] == "aes128_gcm"
                for child in children
            )
            assert len({child["security"]["key_set_id"] for child in children}) == 3
            for child in children:
                for transfer in child["transfers"].values():
                    assert (
                        host.artifacts.get(transfer)["created_at"] >= child["rf_window_closed_at"]
                    )
            assert result["cleanup"]["confirmed"] and not host.busy
            for node in host.physical.values():
                assert (await node.request("artifact.list"))["artifacts"] == []
        finally:
            if bridge:
                bridge.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bridge
            await host.close()

    asyncio.run(scenario())


def test_microphone_voice_runs_in_reverse_and_preserves_capture_evidence(native_library, tmp_path):
    async def scenario():
        from lora_testbed.voice_runs import VoiceRunRequest

        host = Host(tmp_path)
        pair = AudioPair(host, native_library)
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            started = await host.start_voice(
                VoiceRunRequest(source="microphone", direction="B_TO_A", include_comparisons=False)
            )
            result = await finished(host.voice, started["id"])
            assert result["status"] == "completed", result.get("error")
            assert (
                result["sender"] == "B" and result["receiver"] == "A" and not result["comparisons"]
            )
            capture = host.audio.get(result["jobs"]["source_audio"])
            assert capture["clip"]["sample_count"] == 24000 and capture["node_artifacts_retired"]
            assert host.voice.content(result["id"], "source") == pair.serials["B"].audio.pcm
            assert result["delivery_verified"] and result["playback_completed"]
            assert result["cleanup"]["confirmed"] and not host.busy
        finally:
            if bridge:
                bridge.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bridge
            await host.close()

    asyncio.run(scenario())


def test_missing_receiver_speaker_blocks_voice_before_source_work(native_library, tmp_path):
    async def scenario():
        from lora_testbed.voice_runs import VoiceRunRequest

        host = Host(tmp_path)
        pair = AudioPair(host, native_library, missing_playback="B")
        try:
            await pair.connect()
            with pytest.raises(ValueError, match="play"):
                await host.start_voice(VoiceRunRequest(source="microphone"))
            assert not host.voice.snapshot()["runs"] and not host.audio.snapshot()["operations"]
            assert not host.radio.snapshot()["runs"] and not host.busy
        finally:
            await host.close()

    asyncio.run(scenario())


def test_failed_microphone_start_preserves_failure_and_releases_bench_for_next_clip(
    native_library, tmp_path
):
    async def scenario():
        from lora_testbed.voice_runs import VoiceRunRequest

        host = Host(tmp_path)
        pair = AudioPair(host, native_library)
        bridge = None
        try:
            await pair.connect()
            pair.serials["A"].audio.fail_start = True
            request = VoiceRunRequest(
                source="microphone", sample_count=160, include_comparisons=False
            )
            started = await host.start_voice(request)
            result = await finished(host.voice, started["id"])
            assert result["status"] == "failed" and not result["delivery_verified"]
            assert not result["playback_completed"] and pair.serials["B"].audio.starts == 0
            assert result["cleanup"]["confirmed"] and not host.busy
            pair.serials["A"].audio.fail_start = False
            bridge = asyncio.create_task(pair.bridge())
            following = await host.start_voice(request)
            assert (await finished(host.voice, following["id"]))["status"] == "completed"
        finally:
            if bridge:
                bridge.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bridge
            await host.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("reason", ["cancel", "incomplete"])
def test_failed_or_cancelled_rf_never_plays_partial_voice_and_following_clip_succeeds(
    native_library, tmp_path, reason
):
    async def scenario():
        from lora_testbed.voice_runs import VoiceRunRequest

        host = Host(tmp_path)
        pair = AudioPair(host, native_library, drop="data")
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            request = VoiceRunRequest(
                source="microphone", sample_count=160, include_comparisons=False, timeout_ms=15000
            )
            started = await host.start_voice(request)
            if reason == "cancel":
                async with asyncio.timeout(5):
                    while host.voice.get(started["id"])["radio_run_id"] is None:
                        await asyncio.sleep(0.002)
                result = await host.voice.stop(started["id"])
                assert result["status"] == "cancelled"
            else:
                async with asyncio.timeout(request.timeout_ms / 1000 + 10):
                    await host.voice.task
                result = host.voice.get(started["id"])
                assert result["status"] == "failed"
            assert not result["delivery_verified"] and not result["playback_completed"]
            assert pair.serials["B"].audio.starts == 0
            assert result["cleanup"]["confirmed"] and not host.busy
            assert len(host.voice.content(result["id"], "source")) == 320
            with pytest.raises(ValueError):
                host.voice.content(result["id"], "recovered")
            pair.drop = None
            following = await host.start_voice(request)
            assert (await finished(host.voice, following["id"]))["status"] == "completed"
        finally:
            if bridge:
                bridge.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bridge
            await host.close()

    asyncio.run(scenario())


def test_cancelled_stop_caller_does_not_release_voice_ownership_before_cleanup(
    native_library, tmp_path
):
    import json
    import threading

    async def scenario():
        from lora_testbed.voice_runs import VoiceRunRequest

        host = Host(tmp_path)
        pair = AudioPair(host, native_library)
        entered, release = threading.Event(), threading.Event()
        try:
            await pair.connect()
            pair.serials["A"].audio.hold = True
            serial = pair.serials["A"]
            original = serial.write

            def write(wire):
                if json.loads(wire).get("name") == "operation.stop":
                    entered.set()
                    release.wait(2)
                return original(wire)

            serial.write = write
            started = await host.start_voice(
                VoiceRunRequest(source="microphone", sample_count=160, include_comparisons=False)
            )
            async with asyncio.timeout(3):
                while not pair.serials["A"].audio.starts:
                    await asyncio.sleep(0.002)
            stopping = asyncio.create_task(host.voice.stop(started["id"]))
            assert await asyncio.to_thread(entered.wait, 2)
            stopping.cancel()
            with pytest.raises(asyncio.CancelledError):
                await stopping
            assert host.voice.busy and host.busy
            release.set()
            result = await finished(host.voice, started["id"])
            assert result["status"] == "cancelled" and result["cleanup"]["confirmed"]
            assert not host.busy
        finally:
            release.set()
            await host.close()

    asyncio.run(scenario())


def test_voice_api_runs_reference_downloads_verified_stages_and_records_listening(
    native_library, tmp_path
):
    from fastapi.testclient import TestClient

    from lora_testbed.app import create_app
    from lora_testbed.audio import pcm_wav

    with TestClient(create_app(data_dir=tmp_path)) as client:
        host = client.app.state.host
        pair = AudioPair(host, native_library)

        async def connect():
            await pair.connect()
            return asyncio.create_task(pair.bridge())

        bridge = client.portal.call(connect)
        try:
            pcm = b"\x00\x08" * 160
            reference = client.post(
                "/api/audio/references?name=voice.wav",
                content=pcm_wav(pcm, 160),
                headers={"Content-Type": "audio/wav"},
            )
            assert reference.status_code == 201
            body = {
                "source": "reference",
                "reference_id": reference.json()["id"],
                "include_comparisons": False,
            }
            ready = client.post("/api/voice/preflight", json=body)
            assert ready.status_code == 200 and ready.json()["ready"]
            started = client.post("/api/voice/runs", json=body)
            assert started.status_code == 202, started.text
            record = client.portal.call(finished, host.voice, started.json()["id"])
            assert record["status"] == "completed", record.get("error")
            prefix = f"/api/voice/runs/{record['id']}"
            assert client.get(prefix).json()["playback_completed"]
            assert client.get(f"{prefix}/artifacts/source").content == pcm
            encoded = client.get(f"{prefix}/artifacts/encoded")
            assert encoded.status_code == 200 and len(encoded.content) == 8
            assert client.get(f"{prefix}/artifacts/recovered").content == encoded.content
            assert len(client.get(f"{prefix}/artifacts/decoded").content) == 320
            assert client.get(f"{prefix}/artifacts/decoded?as_wav=true").status_code == 200
            assert client.get(f"{prefix}/artifacts/encoded?as_wav=true").status_code == 400
            noted = client.post(
                f"{prefix}/listening",
                json={"heard": "not_checked", "notes": "software fixture only"},
            )
            assert (
                noted.status_code == 200
                and noted.json()["listening"]["notes"] == "software fixture only"
            )
            assert not noted.json()["hardware_qualified"]
            assert client.get("/api/state").json()["voice_runs"]["active_id"] is None
            path = host.radio.content(record["radio_run_id"], "recovered")
            path.write_bytes(b"corrupt")
            assert client.get(f"{prefix}/artifacts/recovered").status_code == 400
        finally:

            async def stop_bridge():
                bridge.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bridge

            client.portal.call(stop_bridge)


def test_voice_cli_uses_shared_api_and_preserves_existing_downloads(monkeypatch, tmp_path):
    import io

    from typer.testing import CliRunner

    from lora_testbed import cli

    calls, urls = [], []
    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: calls.append((args, kwargs)))
    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "voice-start",
            "--source",
            "reference",
            "--reference-id",
            "ref",
            "--direction",
            "B_TO_A",
            "--no-comparisons",
        ],
    )
    assert result.exit_code == 0, result.output
    path, body = calls[-1][0]
    assert path == "/api/voice/runs" and body["security"] == "aes128_gcm"
    assert (
        body["reference_id"] == "ref"
        and body["direction"] == "B_TO_A"
        and not body["include_comparisons"]
    )
    assert runner.invoke(cli.app, ["voice-start", "--check"]).exit_code == 0
    assert calls[-1][0][0] == "/api/voice/preflight"
    assert runner.invoke(cli.app, ["voice-start", "--samples", "24001"]).exit_code != 0
    assert runner.invoke(cli.app, ["voice-stop", "job"]).exit_code == 0
    assert calls[-1][0] == ("/api/voice/runs/job/stop", {})

    def response(url, **kwargs):
        urls.append(url)
        return io.BytesIO(b"verified PCM wrapper")

    monkeypatch.setattr(cli, "urlopen", response)
    target = tmp_path / "decoded.wav"
    command = ["voice-save", "job", "decoded", str(target), "--wav"]
    assert runner.invoke(cli.app, command).exit_code == 0
    assert urls[-1].endswith("/api/voice/runs/job/artifacts/decoded?as_wav=true")
    assert target.read_bytes() == b"verified PCM wrapper"
    assert runner.invoke(cli.app, command).exit_code == 1
    assert target.read_bytes() == b"verified PCM wrapper"
    assert (
        runner.invoke(
            cli.app, ["voice-save", "job", "encoded", str(tmp_path / "bad.wav"), "--wav"]
        ).exit_code
        != 0
    )


def test_shutdown_interrupts_active_voice_and_restart_does_not_resume(native_library, tmp_path):
    async def scenario():
        from lora_testbed.voice_runs import VoiceRunRequest

        host = Host(tmp_path)
        pair = AudioPair(host, native_library)
        closed = False
        try:
            await pair.connect()
            pair.serials["A"].audio.hold = True
            started = await host.start_voice(
                VoiceRunRequest(source="microphone", sample_count=160, include_comparisons=False)
            )
            async with asyncio.timeout(3):
                while not pair.serials["A"].audio.starts:
                    await asyncio.sleep(0.002)
            await host.close()
            closed = True
            restarted = Host(tmp_path)
            try:
                record = restarted.voice.get(started["id"])
                assert record["status"] == "interrupted" and record["cleanup"]["confirmed"]
                assert not record["delivery_verified"] and not record["playback_completed"]
                assert not restarted.busy and restarted.voice.snapshot()["active_id"] is None
                assert all(not node.connected for node in restarted.physical.values())
            finally:
                await restarted.close()
        finally:
            if not closed:
                await host.close()

    asyncio.run(scenario())
