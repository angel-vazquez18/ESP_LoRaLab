"""Check the single-node reference workflow without access to another node."""

import asyncio
import hashlib
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from test_node_audio_host import AudioSerial
from test_node_control_native import native_library as native_library
from test_voice_matrix import add_reference

from lora_testbed.app import create_app
from lora_testbed.host import Host
from lora_testbed.integration_matrices import MatrixRequest


def test_local_reference_roundtrip_preserves_preexisting_device_files(native_library, tmp_path):
    async def scenario():
        host = Host(tmp_path)
        node = host.physical["B"]
        peer = AudioSerial(native_library)
        node.opener = lambda _: peer
        try:
            await node.connect("fixture-only-B")
            old = await host.artifacts.start_upload("B", b"existing data", name="existing.bin")
            await host.artifacts.task
            assert host.artifacts.get(old["id"])["status"] == "completed"
            before = (await node.request("artifact.list"))["artifacts"]
            reference_id = add_reference(host, tmp_path, 24000)
            spec = MatrixRequest(
                catalog_id="VOICE-01",
                groups=["C3"],
                roles=["B"],
                voice_reference_ids=[reference_id],
                repetitions=1,
            )
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(35):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert saved["status"] == "completed" and saved["assessment"] == "pass", saved
            assert set(saved["physical_bindings"]) == {"B"}
            assert not saved["hardware_validated"]
            [case] = saved["cases"]
            evidence = case["measurements"]
            assert evidence["physical_listening"] == "pending"
            assert evidence["codec_manifests"]["encoded"]["length_bytes"] == 1200
            assert evidence["codec_manifests"]["source"]["length_bytes"] == 48000
            assert evidence["codec_manifests"]["decoded"]["length_bytes"] == 48000
            assert (await node.request("artifact.list"))["artifacts"] == before
            assert len(host.audio.codec_content(case["audio_jobs"]["codec"], "decoded")) == 48000
            assert case["cleanup_verified"]
            assert not host.busy
        finally:
            await host.close()

    asyncio.run(scenario())


def test_negative_local_audio_matrix_rejects_corrupt_input_and_proves_recovery(
    native_library, tmp_path
):
    async def scenario():
        host = Host(tmp_path)
        node = host.physical["B"]
        peer = AudioSerial(native_library)
        node.opener = lambda _: peer
        try:
            spec = MatrixRequest(catalog_id="VOICE-01", groups=["C4"], roles=["B"], repetitions=1)
            initial = host.procedures.matrix_preview(spec, host.radio, host.voice)
            assert initial["case_count"] == 3 and initial["ready_case_count"] == 0
            await node.connect("fixture-only-B")
            existing = await host.artifacts.start_upload("B", b"keep this", name="existing.bin")
            await host.artifacts.task
            assert host.artifacts.get(existing["id"])["status"] == "completed"
            baseline = (await node.request("artifact.list"))["artifacts"]
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(20):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert saved["assessment"] == "pass", saved
            assert not saved["full_procedure_passed"] and not saved["hardware_validated"]
            expected = {
                "oversized_capture": "INVALID_ARGUMENT",
                "non_pcm_format": "INVALID_ARGUMENT",
                "uncommitted_pcm": "INVALID_STATE",
                "bad_chunk_crc": "CHECKSUM_MISMATCH",
                "wrong_chunk_offset": "OFFSET_MISMATCH",
                "wrong_final_hash": "CHECKSUM_MISMATCH",
                "failed_pcm": "INVALID_STATE",
            }
            for case in saved["cases"]:
                assert case["cleanup_verified"]
                report = case["measurements"]
                assert report["refusals"] == {
                    label: {"expected": code, "observed": code} for label, code in expected.items()
                }
                assert 0 < report["cancel_latency_ms"] < 15_000
                jobs = report["jobs"]
                assert host.audio.get(jobs["controlled_cancel"])["status"] == "cancelled"
                recovered = host.audio.get(jobs["recovery_capture"])
                pcm = host.audio.wav(recovered["id"])[44:]
                assert len(pcm) == 320
                assert hashlib.sha256(pcm).hexdigest() == recovered["clip"]["pcm_sha256"]
                played = host.audio.get(jobs["recovery_playback"])
                assert played["artifact_id"] == recovered["artifact_id"]
                assert played["node_result"]["result"]["samples_completed"] == 160
            assert peer.audio.starts == 9
            assert (await node.request("artifact.list"))["artifacts"] == baseline
            assert not host.busy
        finally:
            await host.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("group", "heard", "outcome"),
    [
        ("C1", "heard", "pass"),
        ("C1", "not_heard", "fail"),
        ("C1", "not_checked", "inconclusive"),
        ("C2", "heard", "pass"),
    ],
)
def test_saved_microphone_playback_review_separates_listening_from_dma(
    native_library, tmp_path, group, heard, outcome
):
    async def scenario():
        app = create_app(tmp_path)
        async with app.router.lifespan_context(app):
            host = app.state.host
            node = host.physical["B"]
            node.opener = lambda _: AudioSerial(native_library)
            await node.connect("fixture-only-B")
            capture = await host.audio_action("B", "capture")
            async with asyncio.timeout(12):
                await host.audio.task
            capture = host.audio.get(capture["id"])
            assert capture["status"] == "completed", capture["error"]
            selected = capture["artifact_id"]
            reference = {
                "group": group,
                "role": "B",
                "utterance": 1,
                "repetition": 1,
                "capture": capture["id"],
            }
            if group == "C2":
                codec = await host.audio_action("B", "codec", artifact_id=selected)
                async with asyncio.timeout(16):
                    await host.audio.task
                codec = host.audio.get(codec["id"])
                assert codec["verified_roundtrip"], codec["error"]
                reference["codec"] = codec["id"]
                selected = codec["codec_artifacts"]["decoded"]["manifest"]["artifact_id"]
            play = await host.audio_action("B", "play", artifact_id=selected)
            async with asyncio.timeout(6):
                await host.audio.task
            play = host.audio.get(play["id"])
            assert play["status"] == "completed", play["error"]
            if heard != "not_checked":
                host.audio.listening(play["id"], heard, "Isolated fixture listening record")
            reference["playback"] = play["id"]
            await node.close()

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://127.0.0.1"
            ) as ui:
                path = "/api/procedures/matrix"
                request = {
                    "catalog_id": "VOICE-01",
                    "groups": [group],
                    "roles": ["B"],
                    "repetitions": 1,
                }
                initial = (await ui.post(f"{path}/preview", json=request)).json()
                assert initial["case_count"] == 3 and initial["ready_case_count"] == 0
                request["local_voice_evidence"] = [{**reference, "playback": str(uuid4())}]
                unknown = (await ui.post(f"{path}/preview", json=request)).json()
                assert unknown["ready_case_count"] == 0
                request["local_voice_evidence"] = [reference]
                accepted = await ui.post(path, json=request)
                assert accepted.status_code == 202, accepted.json()
                async with asyncio.timeout(5):
                    await host.procedures.task
                result = host.procedures.get(accepted.json()["id"])
                [case] = [row for row in result["cases"] if row["status"] == "completed"]
                assert case["assessment"] == outcome and case["cleanup_verified"], case
                assert not result["physical_bindings"] and not result["hardware_validated"]
                report = case["measurements"]
                assert report["clip"]["raw_bytes"] == 48000 and report["clip"]["duration_s"] == 3
                assert report["listening"]["heard"] == heard
                assert report["jobs"]["play"] == play["id"]
                path_to_original = report["capture_wav"]
                assert (await ui.get(path_to_original)).content[:4] == b"RIFF"
                if group == "C2":
                    assert len((await ui.get(report["encoded_artifact"])).content) == 1200
                    assert (await ui.get(report["decoded_wav"])).content[:4] == b"RIFF"
                    (host.audio.directory / f"{capture['id']}.wav").write_bytes(b"damaged")
                    accepted = await ui.post(path, json=request)
                    assert accepted.status_code == 202
                    async with asyncio.timeout(5):
                        await host.procedures.task
                    result = host.procedures.get(accepted.json()["id"])
                    assert "integrity verification" in result["cases"][0]["reason"]

    asyncio.run(scenario())
