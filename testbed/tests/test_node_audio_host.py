"""Public host/API/CLI audio workflows with real C control and a test-only DMA seam."""

import asyncio
import base64
import ctypes as C
import io
import json
import struct
import threading
import time
import wave
import zlib
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from test_artifact_transfers import finished
from test_node_audio_native import AudioFixture
from test_node_control_native import AudioProgress, NativeNode, NativeSerial
from test_node_control_native import native_library as native_library

from lora_testbed import cli, node_audio
from lora_testbed.app import create_app
from lora_testbed.audio import inspect_pcm, pcm_wav
from lora_testbed.host import Host
from lora_testbed.storage import Store, utc_now


class AutoAudio(AudioFixture):
    def __init__(self):
        super().__init__()
        self.hold = False
        self.zero = False

    def start(self, context, source, samples, capture):
        okay = super().start(context, source, samples, capture)
        self.started = time.monotonic()
        if capture:
            values = [0] if self.zero else [-32768, 32767, -400, 400, 0]
            self.pcm = struct.pack(
                "<" + "h" * samples, *(values[i % len(values)] for i in range(samples))
            )
            C.memmove(source, self.pcm, len(self.pcm))
        return okay

    def poll(self, context, target):
        if not self.hold and time.monotonic() - self.started > 0.08:
            self.progress = AudioProgress(
                self.target, self.target + (4800 if self.capture else 0), 0, True, False
            )
        super().poll(context, target)


class AudioSerial(NativeSerial):
    def __init__(self, lib):
        super().__init__(lib)
        self.core.close()
        self.audio = AutoAudio()
        self.core = NativeNode(lib, realtime=True, audio=self.audio.port)
        self.corruption = None

    def read(self, count):
        data = super().read(count)
        if not data or not self.corruption:
            return data
        record = json.loads(data)
        result = record.get("result") or {}
        if result.get("data_b64"):
            raw = bytearray(base64.b64decode(result["data_b64"]))
            raw[0] ^= 1
            result["data_b64"] = base64.b64encode(raw).decode()
            if self.corruption == "sha":
                result["crc32"] = f"{zlib.crc32(raw):08x}"
        if (
            self.corruption == "count"
            and record.get("name") == "operation.result"
            and record["data"]["result"]
        ):
            record["data"]["result"]["samples_completed"] -= 1
        if self.corruption == "lost_result" and record.get("name") == "operation.result":
            return b""
        return json.dumps(record).encode() + b"\n"


@asynccontextmanager
async def audio_bench(lib, root):
    host = Host(root)
    serial = AudioSerial(lib)
    host.physical["A"].opener = lambda _: serial
    await host.physical["A"].connect("native-audio-fixture")
    try:
        yield host, serial
    finally:
        await host.close()


@pytest.mark.parametrize("samples", [1, 129, 24000])
def test_capture_retrieve_wav_preserves_exact_pcm_and_counts_gain_and_listening(
    native_library, tmp_path, samples
):
    async def scenario():
        async with audio_bench(native_library, tmp_path) as (host, serial):
            started = await host.audio_action("A", "capture", sample_count=samples)
            with pytest.raises(RuntimeError):
                await host.artifact_action("list", "A")
            record = await finished(host.audio, started["id"])
            assert record["status"] == "completed", record
            assert record["clip"]["sample_count"] == samples
            assert (
                not record["hardware_qualified"] and record["listening"]["heard"] == "not_checked"
            )
            assert record["configuration"]["output_gain_denominator"] == 8
            with wave.open(io.BytesIO(host.audio.wav(record["id"]))) as wav:
                assert (
                    wav.getframerate(),
                    wav.getsampwidth(),
                    wav.getnchannels(),
                    wav.getnframes(),
                ) == (8000, 2, 1, samples)
                assert wav.readframes(samples) == serial.audio.pcm
            record = host.audio.listening(record["id"], "not_checked", "fixture only")
            assert record["node_result"]["result"]["heard_verified"] is False
            assert not host.busy
            played = await host.audio_action("A", "play", artifact_id=record["artifact_id"])
            assert (await finished(host.audio, played["id"]))["stage"] == "driver_completed"
            retrieved = await host.audio_action("A", "retrieve", artifact_id=record["artifact_id"])
            assert (await finished(host.audio, retrieved["id"]))["clip"]["pcm_sha256"] == record[
                "clip"
            ]["pcm_sha256"]
            assert any(
                json.loads(x).get("direction") == "node_event"
                for x in (tmp_path / "node_audio" / f"{record['id']}.ndjson")
                .read_text()
                .splitlines()
            )

    asyncio.run(scenario())


@pytest.mark.parametrize("fault", ["crc", "sha", "count"])
def test_corrupt_or_short_audio_completion_never_becomes_a_verified_wav_and_recovers(
    native_library, tmp_path, fault
):
    async def scenario():
        async with audio_bench(native_library, tmp_path) as (host, serial):
            serial.corruption = fault
            r = await host.audio_action("A", "capture", sample_count=129)
            record = await finished(host.audio, r["id"])
            assert record["status"] == "failed" and record["error"] and record["clip"] is None, (
                record
            )
            with pytest.raises(ValueError):
                host.audio.wav(record["id"])
            assert not host.busy and record["cleanup_details"]["confirmed"]
            retained = record["retained_capture"]
            assert (
                retained["artifact_id"] == record["artifact_id"]
                and retained["state"] == "committed"
            )
            assert (await host.physical["A"].request("status.get"))["state"] == "idle"
            serial.corruption = None
            r = await host.audio_action("A", "capture", sample_count=129)
            assert (await finished(host.audio, r["id"]))["status"] == "completed"

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["before_start", "during_capture", "during_write"])
def test_stop_priority_cleanup_and_following_capture(native_library, tmp_path, phase):
    async def scenario():
        async with audio_bench(native_library, tmp_path) as (host, serial):
            serial.audio.hold = True
            entered = threading.Event()
            original = serial.write

            def write(wire):
                if phase == "during_write" and b"audio.capture" in wire:
                    entered.set()
                    time.sleep(0.08)  # Isolated physical-write latency fixture.
                return original(wire)

            if phase == "during_write":
                serial.write = write
            r = await host.audio_action("A", "capture")
            if phase == "during_write":
                while not entered.is_set():
                    await asyncio.sleep(0.002)
            if phase == "during_capture":
                while not serial.audio.starts:
                    await asyncio.sleep(0.002)
            with pytest.raises(RuntimeError):
                await host.audio_action("A", "play", artifact_id=r["artifact_id"])
            stopped = await host.audio.stop(r["id"])
            assert stopped["status"] == "cancelled" and not host.busy
            files = (await host.physical["A"].request("artifact.list"))["artifacts"]
            assert all(file["state"] == "committed" and not file["in_use"] for file in files)
            assert (
                not files or stopped["retained_capture"]["artifact_id"] == files[0]["artifact_id"]
            )
            serial.audio.hold = False
            valid = await host.audio_action("A", "capture", sample_count=8)
            assert (await finished(host.audio, valid["id"]))["status"] == "completed"

    asyncio.run(scenario())


def test_all_zero_pcm_is_byte_valid_but_explicitly_warns_signal_not_qualified(
    native_library, tmp_path
):
    async def scenario():
        async with audio_bench(native_library, tmp_path) as (host, serial):
            serial.audio.zero = True
            r = await host.audio_action("A", "capture", sample_count=128)
            r = await finished(host.audio, r["id"])
            assert r["status"] == "completed" and r["clip"]["all_zero"]
            assert (
                "unverified" in r["clip"]["signal_warning"] and not r["clip"]["hardware_qualified"]
            )

    asyncio.run(scenario())


@pytest.mark.parametrize("fault", ["lost_result", "disconnect", "capability"])
def test_missing_result_disconnect_and_live_capability_withdrawal_do_not_pass(
    native_library, tmp_path, monkeypatch, fault
):
    monkeypatch.setattr(node_audio, "OPERATION_WAIT_SECONDS", 0.2)

    async def scenario():
        async with audio_bench(native_library, tmp_path) as (host, serial):
            if fault == "capability":
                host.physical["A"].identity.capabilities.audio_capture = False
                with pytest.raises(ValueError):
                    await host.audio_action("A", "capture")
                assert not serial.audio.starts
                return
            serial.corruption = fault
            serial.audio.hold = fault == "disconnect"
            r = await host.audio_action("A", "capture", sample_count=8)
            if fault == "disconnect":
                while not serial.audio.starts:
                    await asyncio.sleep(0.002)
                host.physical["A"].fail("fixture USB loss")
            r = await finished(host.audio, r["id"])
            assert r["status"] in ("failed", "interrupted") and r["clip"] is None
            assert not host.busy

    asyncio.run(scenario())


@pytest.mark.parametrize("size", [0, 1, 47998, 48001])
def test_short_odd_or_missing_pcm_cannot_be_wrapped_as_expected_three_second_audio(size):
    with pytest.raises(ValueError):
        pcm_wav(b"\0" * size, 24000)


def test_pcm_metrics_waveform_clipping_and_wav_bytes_are_explicit():
    pcm = struct.pack("<5h", -32768, 32767, 0, 1, -1)
    m = inspect_pcm(pcm, 5)
    assert m["clipped_samples"] == 2 and m["peak_abs"] == 32768 and not m["near_silence"]
    with wave.open(io.BytesIO(pcm_wav(pcm, 5))) as f:
        assert f.readframes(5) == pcm


def test_audio_restart_marks_running_interrupted_and_retains_completed_records(tmp_path):
    store = Store(tmp_path)
    for status in ["running", "completed"]:
        store.save_audio({"id": status, "status": status, "created_at": utc_now()})
    store.close()
    store = Store(tmp_path)
    assert store.audio_operation("running")["status"] == "interrupted"
    assert store.audio_operation("completed")["status"] == "completed"
    store.close()


def test_audio_api_validates_bodies_wav_integrity_notes_and_unavailable_readiness(
    native_library, tmp_path
):
    serial = AudioSerial(native_library)
    with TestClient(create_app(data_dir=tmp_path)) as client:
        host = client.app.state.host
        host.physical["A"].opener = lambda _: serial
        client.portal.call(host.physical["A"].connect, "native-api-audio")
        assert client.get("/api/state").json()["nodes"][0]["audio_support"]["commands"] == [
            "audio.play",
            "audio.capture",
        ]
        assert (
            client.post("/api/nodes/A/audio/capture", json={"sample_count": True}).status_code
            == 422
        )
        assert (
            client.post("/api/nodes/A/audio/play", json={"artifact_id": "invalid"}).status_code
            == 422
        )
        r = client.post("/api/nodes/A/audio/capture", json={"sample_count": 129})
        assert r.status_code == 202
        r = client.portal.call(finished, host.audio, r.json()["id"])
        assert client.get(f"/api/audio/operations/{r['id']}/wav").status_code == 200
        notes = client.post(
            f"/api/audio/operations/{r['id']}/listening",
            json={"heard": "not_checked", "notes": "fixture"},
        )
        assert notes.json()["listening"]["heard"] == "not_checked"
        path = tmp_path / "node_audio" / f"{r['id']}.wav"
        path.write_bytes(b"corrupt")
        assert client.get(f"/api/audio/operations/{r['id']}/wav").status_code == 400
        client.portal.call(host.physical["A"].close)
        assert client.get("/api/state").json()["nodes"][0]["audio_support"]["commands"] == []


def test_audio_cli_uses_the_same_http_paths_and_count_bounds(monkeypatch):
    from typer.testing import CliRunner

    calls = []
    monkeypatch.setattr(cli, "request", lambda *a, **k: calls.append((a, k)))
    runner = CliRunner()
    assert runner.invoke(cli.app, ["audio-capture", "A", "--samples", "24000"]).exit_code == 0
    assert calls[-1][0] == ("/api/nodes/A/audio/capture", {"sample_count": 24000})
    assert runner.invoke(cli.app, ["audio-capture", "A", "--samples", "24001"]).exit_code != 0
    assert runner.invoke(cli.app, ["audio-stop", "job"]).exit_code == 0
    assert calls[-1][0][0] == "/api/audio/operations/job/stop"


def test_cancel_during_internal_retrieval_stops_transfer_and_releases_bench(
    native_library, tmp_path
):
    async def scenario():
        async with audio_bench(native_library, tmp_path) as (host, serial):
            entered = asyncio.Event()
            original = host.physical["A"].request

            async def request(name, *args, **kwargs):
                if name == "artifact.get":
                    entered.set()
                    await asyncio.Event().wait()
                return await original(name, *args, **kwargs)

            host.physical["A"].request = request
            r = await host.audio_action("A", "capture", sample_count=129)
            await asyncio.wait_for(entered.wait(), 3)
            r = await host.audio.stop(r["id"])
            assert r["status"] == "cancelled" and not host.busy
            assert r["retained_capture"]["state"] == "committed"
            assert r["cleanup_details"]["confirmed"]

    asyncio.run(scenario())


def test_shutdown_marks_audio_interrupted_and_restart_does_not_resume(native_library, tmp_path):
    async def scenario():
        host = Host(tmp_path)
        serial = AudioSerial(native_library)
        host.physical["A"].opener = lambda _: serial
        await host.physical["A"].connect("native-shutdown-audio")
        serial.audio.hold = True
        r = await host.audio_action("A", "capture")
        while not serial.audio.starts:
            await asyncio.sleep(0.002)
        await host.close()
        host = Host(tmp_path)
        try:
            assert host.audio.get(r["id"])["status"] == "interrupted"
            assert not host.busy and not host.physical["A"].connected
        finally:
            await host.close()

    asyncio.run(scenario())


def test_live_health_audio_withdrawal_disables_readiness_and_direct_command(
    native_library, tmp_path
):
    async def scenario():
        async with audio_bench(native_library, tmp_path) as (host, serial):
            node = host.physical["A"]
            node.health.capability_availability.audio_capture = False
            assert "audio.capture" not in node.snapshot()["audio_support"]["commands"]
            with pytest.raises(ValueError):
                await node.request(
                    "audio.capture",
                    {"artifact_id": "00000000-0000-0000-0000-000000000000", "sample_count": 8},
                )
            assert not serial.audio.starts

    asyncio.run(scenario())


def test_reconnect_starts_with_new_health_age_and_preserves_audio_findings(
    native_library, tmp_path
):
    async def scenario():
        async with audio_bench(native_library, tmp_path) as (host, serial):
            r = await host.audio_action("A", "capture", sample_count=8)
            r = await finished(host.audio, r["id"])
            node = host.physical["A"]
            await node.close()
            replacement = AudioSerial(native_library)
            node.opener = lambda _: replacement
            node.last_health = time.monotonic() - 100
            entered = asyncio.Event()
            release = asyncio.Event()
            original = node.request

            async def request(name, *args, **kwargs):
                if name == "hello":
                    entered.set()
                    await release.wait()
                return await original(name, *args, **kwargs)

            node.request = request
            connecting = asyncio.create_task(node.connect("native-reconnect-audio"))
            await asyncio.wait_for(entered.wait(), 2)
            assert node.snapshot()["connection_state"] == "connecting"
            assert node.snapshot()["audio_support"]["commands"] == []
            release.set()
            await connecting
            assert node.snapshot()["audio_support"]["commands"]
            assert host.audio.get(r["id"])["clip"]["sample_count"] == 8

    asyncio.run(scenario())
