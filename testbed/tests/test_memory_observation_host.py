"""Memory control and evidence use the ordinary physical session interface."""

import asyncio
import json

import pytest
from test_node_control_native import NativeSerial
from test_node_control_native import native_library as native_library

from lora_testbed.nodes import NodeSession


def test_host_gates_memory_control_and_retains_typed_observations(native_library):
    async def scenario():
        serial = NativeSerial(native_library)
        events = []
        node = NodeSession("A", lambda _, record: events.append(record), lambda _: serial)
        try:
            await node.connect("isolated-memory-observer")
            support = node.snapshot()["memory_support"]
            assert set(support["commands"]) == {"memory.start", "memory.stop", "memory.status"}
            started = await node.request("memory.start", {"duration_ms": 1000})
            async with asyncio.timeout(3):
                while (
                    len([record for record in events if record.get("name") == "memory.sample"]) < 2
                ):
                    await asyncio.sleep(0.01)
            state = node.snapshot()["memory_observation"]
            assert (
                state["fresh"]
                and state["last_sample"]["observation_id"] == started["observation_id"]
            )
            stopped = await node.request(
                "memory.stop", {"observation_id": started["observation_id"]}
            )
            assert stopped["active"] is False
            assert node.framing_errors == 0
            await node.close()
            assert node.snapshot()["memory_observation"]["fresh"] is False
            assert not node.snapshot()["memory_support"]["commands"]
        finally:
            await node.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("scope", ["identity", "current", "missing"])
def test_incompatible_memory_declaration_blocks_before_serial_mutation(native_library, scope):
    class ChangedDeclaration(NativeSerial):
        def __init__(self):
            super().__init__(native_library)
            self.names = []

        def write(self, wire):
            self.names.append(json.loads(wire)["name"])
            return super().write(wire)

        def read(self, count):
            wire = super().read(count)
            if not wire:
                return wire
            record = json.loads(wire)
            container = record.get("result") or record.get("data") or {}
            key = "capabilities" if scope != "current" else "capability_availability"
            caps = container.get(key)
            if caps is not None:
                if scope == "missing":
                    caps["resource_limits"].pop("memory_io", None)
                elif "memory_io" in caps["resource_limits"]:
                    caps["resource_limits"]["memory_io"]["schema_sha256"] = "0" * 64
            return json.dumps(record, separators=(",", ":")).encode() + b"\n"

    async def scenario():
        serial = ChangedDeclaration()
        node = NodeSession("A", lambda *_: None, lambda _: serial)
        try:
            await node.connect("isolated-incompatible-memory")
            assert not node.snapshot()["memory_support"]["commands"]
            with pytest.raises(ValueError):
                await node.request("memory.start", {"duration_ms": 1000})
            assert "memory.start" not in serial.names
        finally:
            await node.close()

    asyncio.run(scenario())


def test_reconnect_preserves_historical_events_but_does_not_resume_observation(native_library):
    async def scenario():
        events = []
        peers = [NativeSerial(native_library, boot=1), NativeSerial(native_library, boot=2)]
        node = NodeSession("A", lambda _, record: events.append(record), lambda _: peers.pop(0))
        try:
            await node.connect("isolated-memory-first-boot")
            await node.request("memory.start", {"duration_ms": 1000})
            async with asyncio.timeout(2):
                while not node.snapshot()["memory_observation"]["last_sample"]:
                    await asyncio.sleep(0.01)
            before = len(events)
            await node.close()
            await node.connect("isolated-memory-new-boot")
            assert node.identity.boot_id.endswith(":2")
            assert node.snapshot()["memory_observation"]["last_sample"] is None
            status = await node.request("memory.status")
            assert not status["active"] and status["observation_id"] is None
            assert len(events) >= before
        finally:
            await node.close()
            for peer in peers:
                peer.close()

    asyncio.run(scenario())
