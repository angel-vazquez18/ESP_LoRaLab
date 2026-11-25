"""Check the single-node reference workflow without access to another node."""

import asyncio

from test_node_audio_host import AudioSerial
from test_node_control_native import native_library as native_library
from test_voice_matrix import add_reference

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
