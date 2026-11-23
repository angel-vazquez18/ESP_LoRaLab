"""Local codec provenance through shared host/API/CLI and real portable nodes."""

import asyncio
import hashlib
import io
import json
import subprocess
import wave

import pytest
from native_codec2 import build_codec2
from test_artifact_transfers import finished
from test_node_audio_host import audio_bench
from test_node_control_native import native_library as native_library


def test_local_roundtrip_retains_three_independently_verified_files_and_stage_times(
    native_library, tmp_path
):
    async def scenario():
        async with audio_bench(native_library, tmp_path) as (host, serial):
            captured = await host.audio_action("A", "capture", sample_count=24000)
            captured = await finished(host.audio, captured["id"])
            assert captured["status"] == "completed"
            started = await host.audio_action("A", "codec", artifact_id=captured["artifact_id"])
            result = await finished(host.audio, started["id"])
            assert result["status"] == "completed", result
            assert result["verified_roundtrip"] and not result["hardware_qualified"]
            files = result["codec_artifacts"]
            assert set(files) == {"source", "encoded", "decoded"}
            assert len({file["manifest"]["artifact_id"] for file in files.values()}) == 3
            contents = {stage: host.audio.codec_content(result["id"], stage) for stage in files}
            assert contents["source"] == serial.audio.pcm
            reference, expected = tmp_path / "reference.pcm", tmp_path / "reference.codec2"
            reference.write_bytes(contents["source"])
            subprocess.run(
                [str(build_codec2().parent / "codec2_probe"), str(reference), str(expected)],
                check=True,
                capture_output=True,
                timeout=10,
            )
            assert contents["encoded"] == expected.read_bytes()
            for phase in ("encode", "decode"):
                stage = result["codec_operations"][phase]["result"]
                assert stage["frames_completed"] == stage["frame_count"] == 150
                assert stage["duration_us"] == stage["finished_us"] - stage["started_us"]
            assert {stage: len(data) for stage, data in contents.items()} == {
                "source": 48000,
                "encoded": 1200,
                "decoded": 48000,
            }
            for stage, data in contents.items():
                assert hashlib.sha256(data).hexdigest() == files[stage]["manifest"]["sha256"]
                assert files[stage]["verified"]
            assert result["source_audio_operation_id"] == captured["id"]
            assert (
                result["codec_operations"]["encode"]["result"]["source_artifact_id"]
                == files["source"]["manifest"]["artifact_id"]
            )
            assert (
                result["codec_operations"]["decode"]["result"]["source_artifact_id"]
                == files["encoded"]["manifest"]["artifact_id"]
            )
            assert result["codec_operations"]["decode"]["result"]["samples_completed"] == 24000
            assert result["assessment"]["lossless_pcm_comparison"] == "not_applicable_lossy_codec"
            with wave.open(io.BytesIO(host.audio.wav(result["id"]))) as wav:
                assert wav.getnframes() == 24000 and wav.readframes(24000) == contents["decoded"]
            assert serial.audio.starts == 1, "The codec workflow must not start playback"
            assert not host.busy

    asyncio.run(scenario())


def test_codec_api_returns_verified_files_and_links_only_matching_completed_playback(
    native_library, tmp_path
):
    from fastapi.testclient import TestClient
    from test_node_audio_host import AudioSerial

    from lora_testbed.app import create_app

    serial = AudioSerial(native_library)
    with TestClient(create_app(data_dir=tmp_path)) as client:
        host = client.app.state.host
        host.physical["A"].opener = lambda _: serial
        client.portal.call(host.physical["A"].connect, "native-codec-api")
        captured = client.post("/api/nodes/A/audio/capture", json={"sample_count": 129})
        captured = client.portal.call(finished, host.audio, captured.json()["id"])
        started = client.post(
            "/api/nodes/A/audio/codec", json={"artifact_id": captured["artifact_id"]}
        )
        assert started.status_code == 202, started.text
        result = client.portal.call(finished, host.audio, started.json()["id"])
        assert result["status"] == "completed", result
        shared = client.get("/api/state").json()["audio_operations"]["operations"]
        current = next(value for value in shared if value["id"] == result["id"])
        assert current["node_result"] is None, (
            "Codec children must not masquerade as an audio DMA result"
        )
        prefix = f"/api/audio/operations/{result['id']}"
        for stage, size in (("source", 258), ("encoded", 8), ("decoded", 258)):
            response = client.get(f"{prefix}/artifacts/{stage}")
            assert response.status_code == 200 and len(response.content) == size
        assert client.get(f"{prefix}/artifacts/source?as_wav=true").status_code == 200
        assert client.get(f"{prefix}/artifacts/encoded?as_wav=true").status_code == 400
        assert client.get(f"{prefix}/artifacts/unknown").status_code == 422
        played = client.post("/api/nodes/A/audio/play", json={"artifact_id": result["artifact_id"]})
        played = client.portal.call(finished, host.audio, played.json()["id"])
        client.post(
            f"/api/audio/operations/{played['id']}/listening",
            json={"heard": "not_checked", "notes": "software fixture"},
        )
        linked = client.post(
            f"{prefix}/playback", json={"operation_id": played["id"], "stage": "decoded"}
        )
        assert linked.status_code == 200, linked.text
        observation = linked.json()["playback_observations"][0]
        assert observation["operation_id"] == played["id"] and observation["stage"] == "decoded"
        assert observation["listening"]["notes"] == "software fixture"
        assert not linked.json()["hardware_qualified"]
        assert (
            client.post(
                f"{prefix}/playback", json={"operation_id": played["id"], "stage": "source"}
            ).status_code
            == 400
        )
        assert (
            client.post(f"{prefix}/playback", json={"operation_id": captured["id"]}).status_code
            == 400
        )
        transfer_id = result["codec_artifacts"]["encoded"]["transfer_id"]
        path = client.portal.call(host.artifacts.content, transfer_id)
        path.write_bytes(b"corrupt")
        assert client.get(f"{prefix}/artifacts/encoded").status_code == 400


def test_codec_cli_uses_shared_http_and_saves_without_overwriting(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from lora_testbed import cli

    calls = []
    monkeypatch.setattr(cli, "request", lambda *a, **k: calls.append((a, k)))
    runner = CliRunner()
    assert runner.invoke(cli.app, ["audio-codec", "b", "source"]).exit_code == 0
    assert calls[-1][0] == ("/api/nodes/B/audio/codec", {"artifact_id": "source"})
    assert (
        runner.invoke(
            cli.app, ["audio-link-playback", "codec", "play", "--stage", "source"]
        ).exit_code
        == 0
    )
    assert calls[-1][0] == (
        "/api/audio/operations/codec/playback",
        {"operation_id": "play", "stage": "source"},
    )
    assert (
        runner.invoke(
            cli.app, ["audio-link-playback", "codec", "play", "--stage", "encoded"]
        ).exit_code
        != 0
    )
    urls = []

    def response(url, **kwargs):
        urls.append(url)
        return io.BytesIO(b"verified-response")

    monkeypatch.setattr(cli, "urlopen", response)
    path = tmp_path / "source.wav"
    args = ["audio-codec-save", "codec", "source", str(path), "--wav"]
    assert runner.invoke(cli.app, args).exit_code == 0
    assert urls[-1].endswith("/api/audio/operations/codec/artifacts/source?as_wav=true")
    assert path.read_bytes() == b"verified-response"
    assert runner.invoke(cli.app, args).exit_code == 1
    assert path.read_bytes() == b"verified-response"


async def wait_stage(service, identifier, phase):
    async with asyncio.timeout(8):
        while True:
            record = service.get(identifier)
            if phase in record.get("codec_operations", {}):
                return record
            if record["status"] != "running":
                raise AssertionError(record)
            await asyncio.sleep(0.002)


@pytest.mark.parametrize("phase", ["encode", "decode"])
def test_cancel_during_codec_keeps_partial_node_result_and_verified_source(
    native_library, tmp_path, phase
):
    async def scenario():
        async with audio_bench(native_library, tmp_path) as (host, serial):
            captured = await host.audio_action("A", "capture")
            captured = await finished(host.audio, captured["id"])
            started = await host.audio_action("A", "codec", artifact_id=captured["artifact_id"])
            await wait_stage(host.audio, started["id"], phase)
            result = await host.audio.stop(started["id"])
            assert result["status"] == "cancelled" and not result["verified_roundtrip"]
            assert result["codec_artifacts"]["source"]["verified"]
            partial = result["codec_operations"][phase]
            assert partial["status"] == "cancelled" and partial["result"]["frames_completed"] < 150
            assert host.audio.codec_content(result["id"], "source") == serial.audio.pcm
            assert not host.busy
            assert (await host.physical["A"].request("status.get"))["state"] == "idle"
            following = await host.audio_action("A", "codec", artifact_id=captured["artifact_id"])
            assert (await finished(host.audio, following["id"]))["verified_roundtrip"]

    asyncio.run(scenario())


@pytest.mark.parametrize("fault", ["crc", "sha"])
def test_codec_transfer_failure_preserves_verified_source_and_does_not_claim_roundtrip(
    native_library, tmp_path, fault
):
    async def scenario():
        async with audio_bench(native_library, tmp_path) as (host, serial):
            captured = await host.audio_action("A", "capture", sample_count=129)
            captured = await finished(host.audio, captured["id"])
            original_write = serial.write
            inject = True

            def write(wire):
                if inject and json.loads(wire).get("name") == "audio.encode":
                    serial.corruption = fault
                return original_write(wire)

            serial.write = write  # Fault only at the external serial boundary.
            started = await host.audio_action("A", "codec", artifact_id=captured["artifact_id"])
            result = await finished(host.audio, started["id"])
            assert result["status"] == "failed" and not result["verified_roundtrip"]
            assert result["codec_artifacts"]["source"]["verified"]
            assert result["codec_operations"]["encode"]["status"] == "completed"
            failed = result["codec_artifacts"]["encoded"]
            assert (
                not failed["verified"]
                and host.artifacts.get(failed["transfer_id"])["status"] == "failed"
            )
            assert host.audio.codec_content(result["id"], "source") == serial.audio.pcm
            with pytest.raises(ValueError):
                host.audio.codec_content(result["id"], "encoded")
            with pytest.raises(ValueError):
                host.audio.wav(result["id"])
            assert not host.busy
            inject = False
            serial.corruption = None
            following = await host.audio_action("A", "codec", artifact_id=captured["artifact_id"])
            assert (await finished(host.audio, following["id"]))["verified_roundtrip"]

    asyncio.run(scenario())


def test_codec_artifact_ids_cannot_alias_and_existing_source_is_preserved(
    native_library, tmp_path, monkeypatch
):
    from uuid import UUID

    from lora_testbed import node_audio

    async def scenario():
        async with audio_bench(native_library, tmp_path) as (host, serial):
            captured = await host.audio_action("A", "capture", sample_count=129)
            captured = await finished(host.audio, captured["id"])
            original_uuid = node_audio.uuid4
            monkeypatch.setattr(node_audio, "uuid4", lambda: UUID(captured["artifact_id"]))
            started = await host.audio_action("A", "codec", artifact_id=captured["artifact_id"])
            result = await finished(host.audio, started["id"])
            assert result["status"] == "failed" and "distinct" in result["error"]
            assert not result["verified_roundtrip"] and not result["codec_operations"]
            monkeypatch.setattr(node_audio, "uuid4", original_uuid)
            files = (await host.physical["A"].request("artifact.list"))["artifacts"]
            assert [file["artifact_id"] for file in files] == [captured["artifact_id"]]
            assert not host.busy

    asyncio.run(scenario())


def test_reused_artifact_id_does_not_link_an_older_recording_with_different_bytes(
    native_library, tmp_path, monkeypatch
):
    from uuid import UUID

    from lora_testbed import artifact_transfers

    async def scenario():
        async with audio_bench(native_library, tmp_path) as (host, serial):
            captured = await host.audio_action("A", "capture", sample_count=129)
            captured = await finished(host.audio, captured["id"])
            identifier = captured["artifact_id"]
            await host.artifact_action("delete", "A", identifier)
            with monkeypatch.context() as scoped:
                scoped.setattr(artifact_transfers, "uuid4", lambda: UUID(identifier))
                transfer = await host.artifact_action(
                    "start_upload", "A", b"\x00\x08" * 129, format="pcm_s16le_8000_mono"
                )
                assert (await finished(host.artifacts, transfer["id"]))["status"] == "completed"
            started = await host.audio_action("A", "codec", artifact_id=identifier)
            result = await finished(host.audio, started["id"])
            assert result["status"] == "completed"
            assert result["source_audio_operation_id"] is None
            assert host.audio.codec_content(result["id"], "source") == b"\x00\x08" * 129

    asyncio.run(scenario())


def test_playback_link_rejects_reused_decoded_id_with_changed_pcm(
    native_library, tmp_path, monkeypatch
):
    from uuid import UUID

    from lora_testbed import artifact_transfers

    async def scenario():
        async with audio_bench(native_library, tmp_path) as (host, serial):
            captured = await host.audio_action("A", "capture", sample_count=129)
            captured = await finished(host.audio, captured["id"])
            started = await host.audio_action("A", "codec", artifact_id=captured["artifact_id"])
            result = await finished(host.audio, started["id"])
            identifier = result["artifact_id"]
            await host.artifact_action("delete", "A", identifier)
            with monkeypatch.context() as scoped:
                scoped.setattr(artifact_transfers, "uuid4", lambda: UUID(identifier))
                transfer = await host.artifact_action(
                    "start_upload", "A", b"\x00\x08" * 129, format="pcm_s16le_8000_mono"
                )
                assert (await finished(host.artifacts, transfer["id"]))["status"] == "completed"
            played = await host.audio_action("A", "play", artifact_id=identifier)
            played = await finished(host.audio, played["id"])
            assert played["status"] == "completed"
            with pytest.raises(ValueError, match="content"):
                host.audio.link_playback(result["id"], played["id"])

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["encode", "decode"])
def test_codec_allocation_failure_retains_prior_files_and_fresh_work_recovers(
    native_library, tmp_path, phase
):
    async def scenario():
        async with audio_bench(native_library, tmp_path) as (host, serial):
            captured = await host.audio_action("A", "capture", sample_count=129)
            captured = await finished(host.audio, captured["id"])
            original_write = serial.write

            def write(wire):
                if json.loads(wire).get("name") == f"audio.{phase}":
                    serial.core.allocation_fails = True
                return original_write(wire)

            serial.write = write
            started = await host.audio_action("A", "codec", artifact_id=captured["artifact_id"])
            result = await finished(host.audio, started["id"])
            assert result["status"] == "failed" and "ALLOCATION_FAILED" in result["error"]
            assert (
                not result["verified_roundtrip"] and result["codec_artifacts"]["source"]["verified"]
            )
            if phase == "decode":
                assert result["codec_artifacts"]["encoded"]["verified"]
            serial.core.allocation_fails = False
            serial.write = original_write
            assert not host.busy
            following = await host.audio_action("A", "codec", artifact_id=captured["artifact_id"])
            assert (await finished(host.audio, following["id"]))["verified_roundtrip"]

    asyncio.run(scenario())


def test_unavailable_codec_rejects_before_starting_a_job(native_library, tmp_path):
    from test_node_control_native import NativeSerial

    from lora_testbed.host import Host

    async def scenario():
        host = Host(tmp_path)
        serial = NativeSerial(native_library, codec2_mode=0)
        host.physical["A"].opener = lambda _: serial
        try:
            await host.physical["A"].connect("isolated-codec-unavailable")
            transfer = await host.artifact_action(
                "start_upload", "A", b"\x00\x08" * 129, format="pcm_s16le_8000_mono"
            )
            transfer = await finished(host.artifacts, transfer["id"])
            with pytest.raises(ValueError, match="unavailable"):
                await host.audio_action("A", "codec", artifact_id=transfer["artifact_id"])
            assert not host.audio.snapshot()["operations"] and not host.busy
        finally:
            await host.close()

    asyncio.run(scenario())
