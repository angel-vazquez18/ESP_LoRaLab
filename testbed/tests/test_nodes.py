import asyncio
import json
import queue
from copy import deepcopy
from uuid import uuid4

import pytest

from lora_testbed import v2
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
