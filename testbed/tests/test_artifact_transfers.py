"""Shared host/API file workflows with the actual native C node as serial peer."""

import asyncio
import base64
import hashlib
import json
import threading
import zlib
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_node_control_native import NativeNode, NativeSerial
from test_node_control_native import native_library as native_library

from lora_testbed.app import create_app
from lora_testbed.host import Host
from lora_testbed.storage import Store, utc_now


@asynccontextmanager
async def bench(lib, root, serial_type=NativeSerial):
    host = Host(root)
    serial = serial_type(lib)
    node = host.physical["A"]
    node.opener = lambda _: serial
    await node.connect("isolated-native-transfer")
    try:
        yield host, serial
    finally:
        await host.close()


async def finished(service, transfer_id):
    for _ in range(5000):
        value = service.get(transfer_id)
        if value["status"] != "running":
            return value
        await asyncio.sleep(0.002)
    raise AssertionError("Transfer did not finish")


@pytest.mark.parametrize("length", [1, 1024, 1025, 48000])
def test_upload_download_roundtrip_preserves_bytes_hash_identity_and_wire_evidence(
    native_library, tmp_path, length
):
    async def scenario():
        async with bench(native_library, tmp_path) as (host, serial):
            data = bytes(i * 37 % 256 for i in range(length))
            started = await host.artifact_action("start_upload", "A", data)
            assert host.busy
            upload = await finished(host.artifacts, started["id"])
            assert upload["status"] == "completed", upload
            assert host.artifacts.content(upload["id"]).read_bytes() == data
            assert upload["actual_sha256"] == hashlib.sha256(data).hexdigest()
            assert upload["identity"]["boot_id"] == serial.core.boot_id
            evidence = tmp_path / "node_artifacts" / f"{upload['id']}.ndjson"
            rows = [json.loads(line) for line in evidence.read_text().splitlines()]
            assert rows and rows[-1]["direction"] == "node_to_host"
            started = await host.artifact_action("start_download", "A", upload["artifact_id"])
            download = await finished(host.artifacts, started["id"])
            assert download["status"] == "completed"
            assert host.artifacts.content(download["id"]).read_bytes() == data
            await host.artifact_action("delete", "A", upload["artifact_id"])
            assert not serial.core.allocations and not host.busy

    asyncio.run(scenario())


class CorruptSerial(NativeSerial):
    mode = "sha"

    def read(self, count):
        wire = super().read(count)
        if wire:
            record = json.loads(wire)
            result = record.get("result") or {}
            if self.mode and result.get("data_b64"):
                data = bytearray(base64.b64decode(result["data_b64"]))
                data[0] ^= 1
                result["data_b64"] = base64.b64encode(data).decode()
                if self.mode == "sha":
                    result["crc32"] = f"{zlib.crc32(data):08x}"
                return json.dumps(record).encode() + b"\n"
        return wire


@pytest.mark.parametrize("mode", ["crc", "sha"])
def test_corrupt_readback_never_creates_successful_file_and_recovery_works(
    native_library, tmp_path, mode
):
    async def scenario():
        async with bench(native_library, tmp_path, CorruptSerial) as (host, serial):
            serial.mode = mode
            started = await host.artifact_action("start_upload", "A", b"abcdefgh")
            record = await finished(host.artifacts, started["id"])
            assert record["status"] == "failed" and record["error"]
            assert not list((tmp_path / "node_artifacts").glob("*.bin"))
            assert not serial.core.allocations
            assert record["wire_records"] > 0
            serial.mode = None
            valid = await host.artifact_action("start_upload", "A", b"abcdefgh")
            assert (await finished(host.artifacts, valid["id"]))["status"] == "completed"

    asyncio.run(scenario())


def test_cancel_after_reservation_preserves_evidence_and_restores_bench(native_library, tmp_path):
    async def scenario():
        async with bench(native_library, tmp_path) as (host, serial):
            entered = asyncio.Event()
            original = host.physical["A"].request

            async def wait_put(name, *args, **kwargs):
                if name == "artifact.put":
                    entered.set()
                    await asyncio.Event().wait()
                return await original(name, *args, **kwargs)

            host.physical["A"].request = wait_put
            started = await host.artifact_action("start_upload", "A", b"abcdefgh")
            await asyncio.wait_for(entered.wait(), 2)
            with pytest.raises(RuntimeError, match="owns the bench"):
                await host.memory_probe("A", 1, 512)
            record = await host.artifacts.cancel(started["id"])
            assert record["status"] == "cancelled" and record["wire_records"] > 0
            assert not serial.core.allocations and not host.busy
            host.physical["A"].request = original
            valid = await host.artifact_action("start_upload", "A", b"abcdefgh")
            assert (await finished(host.artifacts, valid["id"]))["status"] == "completed"

    asyncio.run(scenario())


def test_immediate_cancel_before_worker_start_is_idempotent(native_library, tmp_path):
    async def scenario():
        async with bench(native_library, tmp_path) as (host, serial):
            started = await host.artifact_action("start_upload", "A", b"abcdefgh")
            result = await host.artifacts.cancel(started["id"])
            assert result["status"] == "cancelled"
            assert not host.busy and not serial.core.allocations
            assert await host.artifacts.cancel(started["id"]) == result

    asyncio.run(scenario())


def test_disconnect_preserves_interrupted_record_and_fresh_boot_can_transfer(
    native_library, tmp_path
):
    async def scenario():
        async with bench(native_library, tmp_path) as (host, serial):
            node = host.physical["A"]
            original = node.request

            async def lose_link(name, *args, **kwargs):
                if name == "artifact.put":
                    serial.close()
                    node.fail("isolated link loss")
                    raise ValueError("isolated link loss")
                return await original(name, *args, **kwargs)

            node.request = lose_link
            started = await host.artifact_action("start_upload", "A", b"abcdefgh")
            record = await finished(host.artifacts, started["id"])
            assert record["status"] == "interrupted" and "unconfirmed" in record["cleanup"]
            assert not list((tmp_path / "node_artifacts").glob("*.bin"))
            node.request = original
            fresh = NativeSerial(native_library)
            fresh.core.close()
            fresh.core = NativeNode(native_library, realtime=True, boot=2)
            node.opener = lambda _: fresh
            await node.connect("isolated-native-transfer")
            valid = await host.artifact_action("start_upload", "A", b"abcdefgh")
            assert (await finished(host.artifacts, valid["id"]))["status"] == "completed"
            assert host.artifacts.get(started["id"])["status"] == "interrupted"

    asyncio.run(scenario())


def test_verified_host_file_tampering_is_detected(native_library, tmp_path):
    async def scenario():
        async with bench(native_library, tmp_path) as (host, _):
            job = await host.artifact_action("start_upload", "A", b"abcdefgh")
            record = await finished(host.artifacts, job["id"])
            host.artifacts.content(record["id"]).write_bytes(b"changed!")
            with pytest.raises(ValueError, match="length/hash"):
                host.artifacts.content(record["id"])

    asyncio.run(scenario())


def test_restart_marks_running_transfers_interrupted_without_resume(tmp_path):
    store = Store(tmp_path)
    identity = str(uuid4())
    store.save_transfer({"id": identity, "created_at": utc_now(), "status": "running"})
    store.close()
    store = Store(tmp_path)
    try:
        assert store.transfer(identity)["status"] == "interrupted"
        assert "unconfirmed" in store.transfer(identity)["cleanup"]
    finally:
        store.close()


def test_api_upload_download_content_and_list_share_real_backend(native_library, tmp_path):
    serial = NativeSerial(native_library)
    with TestClient(create_app(data_dir=tmp_path)) as client:
        host = client.app.state.host
        host.physical["A"].opener = lambda _: serial
        client.portal.call(host.physical["A"].connect, "isolated-native-transfer")
        started = client.post(
            "/api/nodes/A/artifacts", json={"data_b64": base64.b64encode(b"abcdefgh").decode()}
        )
        assert started.status_code == 202
        record = client.portal.call(finished, host.artifacts, started.json()["id"])
        assert record["status"] == "completed"
        assert client.get(f"/api/artifact-transfers/{record['id']}/content").content == b"abcdefgh"
        assert client.get("/api/nodes/A/artifacts").json()["artifacts"][0]["state"] == "committed"
        assert client.get("/api/state").json()["artifact_transfers"]["transfers"]
        assert client.delete(f"/api/nodes/A/artifacts/{record['artifact_id']}").json()["deleted"]


@pytest.mark.parametrize(
    "body",
    [
        {"data_b64": "YR=="},
        {"data_b64": ""},
        {"data_b64": "YQ==", "format": "wav"},
        {"data_b64": "YQ==", "extra": 1},
    ],
)
def test_api_invalid_uploads_fail_without_node_or_success_record(tmp_path, body):
    with TestClient(create_app(data_dir=tmp_path)) as client:
        assert client.post("/api/nodes/A/artifacts", json=body).status_code == 400
        assert client.get("/api/artifact-transfers").json()["transfers"] == []


def test_api_request_bytes_are_bounded(tmp_path):
    with TestClient(create_app(data_dir=tmp_path)) as client:
        assert client.post("/api/nodes/A/artifacts", content=b"x" * 196609).status_code == 400


class WrongHashSerial(NativeSerial):
    bad_hash = True

    def write(self, wire):
        original_length = len(wire)
        command = json.loads(wire)
        if self.bad_hash and command["name"] == "artifact.begin":
            command["args"]["sha256"] = "0" * 64
            wire = json.dumps(command).encode() + b"\n"
        super().write(wire)
        return original_length


def test_failed_final_commit_never_persists_accepted_bytes_and_can_recover(
    native_library, tmp_path
):
    async def scenario():
        async with bench(native_library, tmp_path, WrongHashSerial) as (host, serial):
            job = await host.artifact_action("start_upload", "A", b"abcdefgh")
            record = await finished(host.artifacts, job["id"])
            assert record["status"] == "failed" and "CHECKSUM_MISMATCH" in record["error"]
            assert not serial.core.allocations
            assert not list((tmp_path / "node_artifacts").glob("*.bin"))
            serial.bad_hash = False
            job = await host.artifact_action("start_upload", "A", b"abcdefgh")
            assert (await finished(host.artifacts, job["id"]))["status"] == "completed"

    asyncio.run(scenario())


def test_withdrawn_support_disconnects_to_release_unfinished_reservation(native_library, tmp_path):
    async def scenario():
        async with bench(native_library, tmp_path) as (host, serial):
            node = host.physical["A"]
            original = node.request

            async def withdraw(name, *args, **kwargs):
                if name == "artifact.put":
                    node.health.capability_availability.resource_limits.pop(
                        "artifact_transfer", None
                    )
                return await original(name, *args, **kwargs)

            node.request = withdraw
            job = await host.artifact_action("start_upload", "A", b"abcdefgh")
            record = await finished(host.artifacts, job["id"])
            assert record["status"] == "failed" and "MISSING_CAPABILITY" in record["error"]
            assert "disconnected" in record["cleanup"]
            assert not node.connected and not serial.core.allocations

    asyncio.run(scenario())


def test_evidence_quota_still_releases_bench_and_reservation(native_library, tmp_path, monkeypatch):
    import lora_testbed.artifact_transfers as module

    monkeypatch.setattr(module, "MAX_EVIDENCE_BYTES", 1)

    async def scenario():
        async with bench(native_library, tmp_path) as (host, serial):
            job = await host.artifact_action("start_upload", "A", b"abcdefgh")
            record = await finished(host.artifacts, job["id"])
            assert record["status"] == "failed" and "evidence limit" in record["error"]
            assert not host.busy and not serial.core.allocations
            assert not list((tmp_path / "node_artifacts").glob("*.bin"))

    asyncio.run(scenario())


def test_missing_command_blocks_workflow_before_serial_write(native_library, tmp_path):
    async def scenario():
        async with bench(native_library, tmp_path) as (host, serial):
            node = host.physical["A"]
            node.identity.capabilities.resource_limits["artifact_transfer"]["commands"].remove(
                "artifact.get"
            )
            before = node.sequence
            with pytest.raises(ValueError, match="MISSING_CAPABILITY"):
                await host.artifact_action("start_upload", "A", b"abcdefgh")
            assert node.sequence == before and not serial.core.allocations
            assert host.store.transfers() == []

    asyncio.run(scenario())


def test_cli_upload_and_delete_use_shared_http_endpoints(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from lora_testbed import cli

    calls = []
    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: calls.append((args, kwargs)))
    file = tmp_path / "sample.bin"
    file.write_bytes(b"abcdefgh")
    runner = CliRunner()
    assert runner.invoke(cli.app, ["artifact-upload", "a", str(file)]).exit_code == 0
    assert calls[0][0][0] == "/api/nodes/A/artifacts"
    assert base64.b64decode(calls[0][0][1]["data_b64"]) == b"abcdefgh"
    assert runner.invoke(cli.app, ["artifact-delete", "a", str(uuid4())]).exit_code == 0
    assert calls[-1][1]["method"] == "DELETE"


class BlockedWriteSerial(NativeSerial):
    def __init__(self, lib):
        super().__init__(lib)
        self.entered = threading.Event()
        self.release_write = threading.Event()
        self.writes = []

    def write(self, wire):
        command = json.loads(wire)
        self.writes.append(command["name"])
        if command["name"] == "artifact.put":
            self.entered.set()
            assert self.release_write.wait(3), "Fixture write barrier was not released"
        return super().write(wire)


def test_cancel_waits_for_serial_write_before_sending_cleanup(native_library, tmp_path):
    async def scenario():
        async with bench(native_library, tmp_path, BlockedWriteSerial) as (host, serial):
            job = await host.artifact_action("start_upload", "A", b"abcdefgh")
            assert await asyncio.to_thread(serial.entered.wait, 2)
            cancellation = asyncio.create_task(host.artifacts.cancel(job["id"]))
            await asyncio.sleep(0.03)
            assert not cancellation.done()
            assert "artifact.delete" not in serial.writes
            serial.release_write.set()
            result = await cancellation
            assert result["status"] == "cancelled"
            assert "artifact.delete" in serial.writes and not serial.core.allocations
            job = await host.artifact_action("start_upload", "A", b"abcdefgh")
            assert (await finished(host.artifacts, job["id"]))["status"] == "completed"

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["missing", "schema", "command"])
def test_inspector_readiness_uses_exact_current_capabilities(native_library, tmp_path, change):
    async def scenario():
        async with bench(native_library, tmp_path) as (host, _):
            node = host.physical["A"]
            assert len(node.snapshot()["artifact_support"]["commands"]) == 6
            resource = node.health.capability_availability.resource_limits
            if change == "missing":
                resource.pop("artifact_transfer")
            elif change == "schema":
                resource["artifact_transfer"]["schema_sha256"] = "0" * 64
            else:
                resource["artifact_transfer"]["commands"].remove("artifact.put")
            support = node.snapshot()["artifact_support"]
            assert "artifact.put" not in support["commands"]
            assert "artifact.put" in support["blocked"]
            if change != "command":
                assert not support["commands"]

    asyncio.run(scenario())
