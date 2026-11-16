import asyncio
import json
import queue
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

from lora_testbed import artifact_contract_v2 as artifacts
from lora_testbed import control_v2, v2
from lora_testbed.nodes import NodeSession


def health():
    return {
        "node_role": "A",
        "state": "idle",
        "run_id": None,
        "operation_id": None,
        "uptime_us": 1000000,
        "reset_cause": "power_on",
        "radio": None,
        "link": None,
        "config_revision": 0,
        "capability_availability": v2.Capabilities().model_dump(),
        "memory": {
            "internal": {
                "free_bytes": 200000,
                "minimum_free_bytes": 190000,
                "largest_free_bytes": 180000,
            },
            "psram": None,
            "buffers": {},
            "allocation_failures": 0,
        },
        "traffic": {},
        "security_ready": False,
        "audio_state": "not_supported",
        "telemetry_drops": 0,
        "last_error": None,
        "last_rx": None,
    }


class FirmwarePeer:
    """In-memory serial peer; tests cross the real session/framing interface."""

    def __init__(self):
        self.queue = queue.Queue()
        self.writes = []
        self.closed = False
        self.status_override = {}
        self.role = "A"
        self.uptime_us = 1000000
        self.drop_once = False
        self.identity = {
            "device_id": "esp-001122334455",
            "boot_id": "esp-001122334455:1",
            "board_model": None,
            "board_revision": None,
            "chip_model": "ESP32-S3",
            "firmware_version": "test",
            "firmware_commit": None,
            "firmware_build_id": "test-build",
            "idf_version": "v6.0.2",
            "board_manifest_hash": None,
            "provenance": "hardware",
            "supported_wire_versions": [2],
            "contract_version": "2.0.0",
            "schema_sha256": v2.schema_digest(),
            "capabilities": v2.Capabilities().model_dump(),
            "claimed": False,
            "state": "idle",
        }

    def write(self, wire):
        self.writes.append(wire)
        cmd = v2.Command.model_validate(json.loads(wire))
        if cmd.name == "control.claim":
            self.role = cmd.args["node_role"]
        self.uptime_us += 100000
        status = {
            **health(),
            "node_role": self.role,
            "uptime_us": self.uptime_us,
            **self.status_override,
        }
        result = (
            self.identity
            if cmd.name == "hello"
            else status
            if cmd.name == "status.get"
            else {"state": "idle"}
        )
        reply = v2.Reply(
            command_id=cmd.command_id,
            command_seq=cmd.command_seq,
            device_id=self.identity["device_id"],
            boot_id=self.identity["boot_id"],
            uptime_us=1000000,
            ok=True,
            result=result,
            error=None,
        )
        if self.drop_once:
            self.drop_once = False
        else:
            self.queue.put(v2.encode(reply))
        return len(wire)

    def read(self, count):
        try:
            return self.queue.get(timeout=0.02)
        except queue.Empty:
            return b""

    def close(self):
        self.closed = True

    def emit(self, seq, boot=None):
        self.queue.put(
            v2.encode(
                v2.Event(
                    device_id=self.identity["device_id"],
                    boot_id=boot or self.identity["boot_id"],
                    node_role="A",
                    event_seq=seq,
                    uptime_us=1000000 + seq,
                    run_id=None,
                    name="health",
                    data=health(),
                )
            )
        )


def test_v2_strict_framing_and_recovery():
    cmd = v2.Command(
        command_id=str(uuid4()),
        client_id=str(uuid4()),
        command_seq=1,
        target_boot_id=None,
        name="hello",
    )
    wire = v2.encode(cmd)
    decoder = v2.Decoder()
    assert decoder.feed(wire[:10]) == ([], [])
    assert decoder.feed(wire[10:]) == ([cmd], [])
    duplicate = wire.replace(b'"v":2', b'"v":2,"v":2')
    deep = deepcopy(cmd.model_dump())
    deep["args"] = {"nested": [[[[[[[[[0]]]]]]]]]}
    malformed = [duplicate, b'{"x":NaN}\n', b"\xff\n", json.dumps(deep).encode() + b"\n"]
    for bad in malformed:
        records, errors = decoder.feed(bad + wire)
        assert records == [cmd] and errors == ["invalid_record"]
    records, errors = decoder.feed(b"x" * 10000 + b"\n" + wire)
    assert records == [cmd] and errors == ["line_too_long"]
    assert decoder.buffer == b""


def test_hardware_session_retry_health_gaps_and_reset():
    async def scenario():
        peer = FirmwarePeer()
        peer.queue.put(b"ROM boot text\n")
        observations = []
        session = NodeSession("A", lambda role, event: observations.append(event), lambda _: peer)
        await session.connect("test-port")
        assert session.snapshot()["connected"]
        assert session.startup_records == 1 and session.framing_errors == 0
        assert session.health.memory.internal.free_bytes == 200000
        peer.drop_once = True
        await session.request("control.keepalive", timeout=0.03)
        assert peer.writes[-1] == peer.writes[-2]  # Resolve an ambiguous write, no new command ID.
        peer.emit(1)
        peer.emit(1)
        peer.emit(4)
        await asyncio.sleep(0.08)
        assert len(observations) == 2 and session.event_gaps == 2
        assert len(session.samples) == 2
        peer.emit(5, boot="esp-001122334455:2")
        await asyncio.sleep(0.05)
        assert not session.connected
        assert "reset" in session.error
        await session.close()
        assert peer.closed and session.tasks == []

    asyncio.run(scenario())


def test_incompatible_firmware_releases_port():
    async def scenario():
        peer = FirmwarePeer()
        peer.identity["schema_sha256"] = "incompatible"
        session = NodeSession("A", lambda *_: None, lambda _: peer)
        with pytest.raises(ValueError, match="schema mismatch"):
            await session.connect("test-port")
        assert peer.closed and not session.connected and not session.tasks

    asyncio.run(scenario())


class ArtifactPeer(FirmwarePeer):
    """Protocol replies only; this isolated peer implements no file storage."""

    def __init__(self, advertised=True):
        super().__init__()
        self.identity["schema_sha256"] = control_v2.schema_digest()
        self.examples = json.loads(
            (
                Path(__file__).resolve().parents[2] / "contracts/v2/artifact_examples.json"
            ).read_text()
        )
        self.override_result = None
        if advertised:
            self.identity["capabilities"]["resource_limits"]["artifact_transfer"] = deepcopy(
                self.examples["capability_example"]
            )

    def write(self, wire):
        command = v2.Command.model_validate(json.loads(wire))
        if command.name not in artifacts.ARGUMENTS:
            self.status_override["capability_availability"] = deepcopy(
                self.identity["capabilities"]
            )
            return super().write(wire)
        self.writes.append(wire)
        if self.drop_once:
            self.drop_once = False
            return len(wire)
        result = deepcopy(
            next(e["result"] for e in self.examples["valid"] if e["name"] == command.name)
        )
        if self.override_result:
            result.update(self.override_result)
        self.queue.put(
            v2.encode(
                v2.Reply(
                    command_id=command.command_id,
                    command_seq=command.command_seq,
                    device_id=self.identity["device_id"],
                    boot_id=self.identity["boot_id"],
                    uptime_us=self.uptime_us,
                    ok=True,
                    result=result,
                    error=None,
                )
            )
        )
        return len(wire)


def test_missing_artifact_support_blocks_without_serial_write_or_sequence_change():
    async def scenario():
        for peer in (FirmwarePeer(), ArtifactPeer(advertised=False)):
            session = NodeSession("A", lambda *_: None, lambda _, active_peer=peer: active_peer)
            await session.connect("test-port")
            try:
                original_writes, sequence = len(peer.writes), session.sequence
                for name in artifacts.ARGUMENTS:
                    with pytest.raises(ValueError, match="MISSING_CAPABILITY"):
                        await session.request(name)
                assert len(peer.writes) == original_writes and session.sequence == sequence
            finally:
                await session.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "update",
    [
        {"schema_sha256": "0" * 64},
        {"profile": "unknown"},
        {"artifact_chunk_bytes": True},
        {"commands": ["artifact.list", "artifact.list"]},
    ],
)
def test_invalid_artifact_advertisement_cannot_enable_writes(update):
    async def scenario():
        peer = ArtifactPeer()
        peer.identity["capabilities"]["resource_limits"]["artifact_transfer"].update(update)
        session = NodeSession("A", lambda *_: None, lambda _: peer)
        await session.connect("test-port")
        try:
            count = len(peer.writes)
            with pytest.raises(ValueError, match="UNSUPPORTED_VERSION"):
                await session.request("artifact.list")
            assert len(peer.writes) == count
        finally:
            await session.close()

    asyncio.run(scenario())


def test_session_checks_advertised_command_subset_and_lower_limits():
    async def scenario():
        peer = ArtifactPeer()
        descriptor = peer.identity["capabilities"]["resource_limits"]["artifact_transfer"]
        descriptor.update(commands=["artifact.list", "artifact.put"], artifact_chunk_bytes=4)
        session = NodeSession("A", lambda *_: None, lambda _: peer)
        await session.connect("test-port")
        try:
            count = len(peer.writes)
            with pytest.raises(ValueError, match="MISSING_CAPABILITY"):
                await session.request(
                    "artifact.get",
                    {
                        "artifact_id": "33333333-3333-4333-8333-333333333333",
                        "offset": 0,
                        "length_bytes": 1,
                    },
                )
            args = next(e["args"] for e in peer.examples["valid"] if e["name"] == "artifact.put")
            with pytest.raises(ValueError, match="advertised chunk limit"):
                await session.request("artifact.put", args)
            assert len(peer.writes) == count
            assert len((await session.request("artifact.list"))["artifacts"]) == 1
        finally:
            await session.close()

    asyncio.run(scenario())


def test_supported_session_validates_messages_and_can_recover_from_bad_replies():
    async def scenario():
        peer = ArtifactPeer()
        session = NodeSession("A", lambda *_: None, lambda _: peer)
        await session.connect("test-port")
        try:
            assert session.wire_profile == "node_control"
            for example in peer.examples["valid"]:
                assert await session.request(example["name"], example["args"]) == example["result"]
            get = next(e for e in peer.examples["valid"] if e["name"] == "artifact.get")
            peer.override_result = {"artifact_id": "44444444-4444-4444-8444-444444444444"}
            with pytest.raises(ValueError, match="artifact ID"):
                await session.request("artifact.get", get["args"])
            peer.override_result = {"crc32": "00000000"}
            with pytest.raises(ValueError, match="CRC-32"):
                await session.request("artifact.get", get["args"])
            peer.override_result = None
            assert await session.request("artifact.get", get["args"]) == get["result"]
        finally:
            await session.close()

    asyncio.run(scenario())


def test_live_health_can_withdraw_artifact_support_or_lower_its_limits():
    async def scenario():
        peer = ArtifactPeer()
        session = NodeSession("A", lambda *_: None, lambda _: peer)
        await session.connect("test-port")
        try:
            current = session.health.capability_availability.resource_limits
            descriptor = current.pop("artifact_transfer")
            count = len(peer.writes)
            with pytest.raises(ValueError, match="MISSING_CAPABILITY"):
                await session.request("artifact.list")
            assert len(peer.writes) == count
            current["artifact_transfer"] = {**descriptor, "artifact_chunk_bytes": 4}
            args = next(e["args"] for e in peer.examples["valid"] if e["name"] == "artifact.put")
            with pytest.raises(ValueError, match="advertised chunk limit"):
                await session.request("artifact.put", args)
            assert len(peer.writes) == count
            current["artifact_transfer"] = descriptor
            assert len((await session.request("artifact.list"))["artifacts"]) == 1
        finally:
            await session.close()

    asyncio.run(scenario())


def test_artifact_read_retries_use_fresh_identity_but_mutations_reuse_exact_wire():
    async def scenario():
        peer = ArtifactPeer()
        session = NodeSession("A", lambda *_: None, lambda _: peer)
        await session.connect("test-port")
        try:
            for name, same_wire in (("artifact.get", False), ("artifact.put", True)):
                example = next(e for e in peer.examples["valid"] if e["name"] == name)
                peer.drop_once = True
                assert (
                    await session.request(name, example["args"], timeout=0.03) == example["result"]
                )
                assert (peer.writes[-1] == peer.writes[-2]) is same_wire
                first, second = (json.loads(w) for w in peer.writes[-2:])
                if not same_wire:
                    assert first["command_id"] != second["command_id"]
                    assert second["command_seq"] == first["command_seq"] + 1
        finally:
            await session.close()

    asyncio.run(scenario())
