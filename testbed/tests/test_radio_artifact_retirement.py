"""Verified DATA run objects retire without consuming user files or failed evidence."""

import asyncio
import contextlib
import hashlib
import io
import json
import zipfile

import pytest
from test_multi_fragment_radio import Pair
from test_node_control_native import native_library as native_library

from lora_testbed.host import Host
from lora_testbed.radio_runs import RadioRunRequest


@pytest.mark.parametrize(
    "direction,security",
    [
        ("A_TO_B", "none"),
        ("B_TO_A", "none"),
        ("A_TO_B", "aes128_gcm"),
        ("B_TO_A", "aes128_gcm"),
    ],
)
def test_six_data_runs_preserve_existing_artifacts_and_saved_exports(
    tmp_path, native_library, direction, security
):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library)
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            originals = {}
            for role in "AB":
                upload = await host.artifacts.start_upload(role, b"keep this user source")
                await host.artifacts.task
                originals[role] = host.artifacts.get(upload["id"])["manifest"]["artifact_id"]
            for index in range(6):
                started = await host.start_radio(
                    RadioRunRequest(direction=direction, security=security, message_bytes=32)
                )
                async with asyncio.timeout(15):
                    await host.radio.task
                saved = host.radio.get(started["id"])
                assert saved["status"] == "completed", dict(
                    index=index + 1, error=saved.get("error")
                )
                assert (
                    saved["verification"]["bytes_equal"]
                    and saved["accounting"]["evidence_complete"]
                )
                assert saved["cleanup"]["confirmed"]
                for role in "AB":
                    listing = await host.physical[role].request("artifact.list")
                    assert [item["artifact_id"] for item in listing["artifacts"]] == [
                        originals[role]
                    ]
                assert (
                    host.radio.content(started["id"], "source").read_bytes()
                    == host.radio.content(started["id"], "recovered").read_bytes()
                )
                with zipfile.ZipFile(io.BytesIO(host.radio.export(started["id"]))) as archive:
                    assert all(
                        hashlib.sha256(archive.read(name)).hexdigest() == digest
                        for name, digest in json.loads(archive.read("sha256.json")).items()
                    )
        finally:
            if bridge:
                bridge.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bridge
            await host.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["readback", "retire"])
def test_failed_readback_or_retirement_preserves_evidence_and_closes_both_sessions(
    tmp_path, native_library, monkeypatch, failure
):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library)
        bridge = None
        original_retrieve, original_command = host.radio.retrieve, host.radio.command

        async def retrieve(record, role, kind):
            if failure == "readback" and kind == "recovered":
                raise ValueError("Injected DATA readback failure")
            return await original_retrieve(record, role, kind)

        async def command(record, role, name, *args, **kwargs):
            if failure == "retire" and role == "A" and name == "artifact.delete":
                raise ValueError("Injected DATA retirement failure")
            return await original_command(record, role, name, *args, **kwargs)

        monkeypatch.setattr(host.radio, "retrieve", retrieve)
        monkeypatch.setattr(host.radio, "command", command)
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            started = await host.start_radio(RadioRunRequest(message_bytes=32))
            async with asyncio.timeout(15):
                await host.radio.task
            saved = host.radio.get(started["id"])
            assert saved["status"] == "failed", saved
            assert all(detail["confirmed"] for detail in saved["cleanup"]["details"].values())
            if failure == "readback":
                assert saved["cleanup"]["confirmed"]
                for role in "AB":
                    assert (await host.physical[role].request("artifact.list"))["artifacts"]
            else:
                assert not saved["cleanup"]["confirmed"] and "retire" in saved["error"]
                assert (await host.physical["A"].request("artifact.list"))["artifacts"]
                assert (await host.physical["B"].request("artifact.list"))["artifacts"] == []
            assert not host.busy
        finally:
            if bridge:
                bridge.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bridge
            await host.close()

    asyncio.run(scenario())
