"""Shared host workflows across two real C nodes and an isolated SPI/IRQ bridge."""

import asyncio
import contextlib
import ctypes as C
import threading
from time import monotonic

import pytest
from test_node_control_native import NativeSerial
from test_node_control_native import native_library as native_library
from test_radio_runs import FaultSerial

from lora_testbed.experiments_v2 import Link
from lora_testbed.host import Host
from lora_testbed.radio_runs import RadioRunRequest


class Pair:
    def __init__(self, host, lib, drop=None, event_loss=None):
        self.host, self.lib, self.drop = host, lib, drop
        self.event_loss = event_loss
        self.serials = {}
        self.frames = []
        self.dropped = False
        lib.native_radio_generation.argtypes = [C.c_void_p]
        lib.native_radio_generation.restype = C.c_uint
        lib.native_radio_listening.argtypes = [C.c_void_p]
        lib.native_radio_listening.restype = C.c_bool
        lib.native_radio_transmitting.argtypes = [C.c_void_p]
        lib.native_radio_transmitting.restype = C.c_bool

    async def connect(self):
        for role, device in [("A", "esp-001122334455"), ("B", "esp-66778899aabb")]:
            options = {"radio": self.lib.native_radio_create(), "device": device}
            peer = (
                FaultSerial(self.lib, drop_event=self.event_loss[1], **options)
                if self.event_loss and self.event_loss[0] == role
                else NativeSerial(self.lib, **options)
            )
            self.serials[role] = peer
            self.host.physical[role].opener = lambda _, p=peer: p
            await self.host.physical[role].connect("fixture-only-" + role)

    def hardware_loop(self, stop):
        generations = {role: 0 for role in "AB"}
        in_flight = []
        while not stop.is_set():
            for role, peer in self.serials.items():
                with peer.lock:
                    if peer.closed:
                        continue
                    peer._pump()  # Model autonomous firmware, independent of host polling.
                    radio = peer.core.radio
                    generation = self.lib.native_radio_generation(radio)
                    if generation == generations[role]:
                        continue
                    output = C.create_string_buffer(255)
                    n = self.lib.native_radio_sent(radio, output)
                generations[role] = generation
                wire = output.raw[:n]
                self.frames.append((role, wire))
                # This scheduling allowance is not an RF propagation/airtime model.
                in_flight.append((monotonic() + 0.02, role, generation, wire))
            now = monotonic()
            ready = [item for item in in_flight if item[0] <= now]
            in_flight = [item for item in in_flight if item[0] > now]
            for _, role, generation, wire in ready:
                source = self.serials[role]
                target = self.serials["B" if role == "A" else "A"]
                with self.serials["A"].lock, self.serials["B"].lock:
                    if source.closed or target.closed:
                        continue
                    radio = source.core.radio
                    if (
                        not self.lib.native_radio_transmitting(radio)
                        or self.lib.native_radio_generation(radio) != generation
                    ):
                        continue
                    kind = "data" if wire[3] == 1 else "ack"
                    lost = not self.dropped and self.drop == kind
                    if lost:
                        self.dropped = True
                    if not lost and self.lib.native_radio_listening(target.core.radio):
                        self.lib.native_radio_inject(target.core.radio, wire, len(wire), 2)
                    self.lib.native_radio_tx_done(radio)
            stop.wait(0.001)

    async def bridge(self):
        stop = threading.Event()
        worker = asyncio.create_task(asyncio.to_thread(self.hardware_loop, stop))
        try:
            await asyncio.shield(worker)
        finally:
            stop.set()
            await asyncio.shield(worker)


@pytest.mark.parametrize(
    ("direction", "length"), [("A_TO_B", 321), ("B_TO_A", 161), ("A_TO_B", 65536)]
)
def test_full_host_multi_fragment_readback_and_originals(
    tmp_path, native_library, direction, length
):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library)
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            run = await host.start_radio(
                RadioRunRequest(
                    direction=direction,
                    message_bytes=length,
                    timeout_ms=900000,
                    link=Link(guard_us=0),
                )
            )
            async with asyncio.timeout(35):
                while host.radio.busy:
                    if bridge.done():
                        await bridge
                    await asyncio.sleep(0.01)
            result = host.radio.get(run["id"])
            assert result["status"] == "completed", result.get("error")
            assert (
                result["verification"]["bytes_equal"]
                and result["verification"]["length_bytes"] == length
            )
            tx = result["summaries"][result["sender"]]
            rx = result["summaries"][result["receiver"]]
            count = (length + 159) // 160
            assert tx["original_packets"] == count and tx["tx_attempts"] == count
            assert rx["accepted_fragments"] == count and rx["delivered_messages"] == 1
            assert result["accounting"]["data_originals"] == count
            assert result["accounting"]["data_attempts"] == count
            assert result["accounting"]["unique_original_delivery_ratio"] == 1
            assert not result["hardware_qualified"]
        finally:
            if bridge:
                bridge.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bridge
            await host.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("drop", ["data", "ack"])
def test_actual_node_retries_reconcile_exact_bytes_and_once_only_delivery(
    tmp_path, native_library, drop
):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library, drop=drop)
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            run = await host.start_radio(
                RadioRunRequest(
                    direction="B_TO_A",
                    message_bytes=321,
                    timeout_ms=120000,
                    link=Link(ack_mode="stop_wait", max_retries=2, guard_us=0),
                )
            )
            async with asyncio.timeout(15):
                while host.radio.busy:
                    if bridge.done():
                        await bridge
                    await asyncio.sleep(0.01)
            result = host.radio.get(run["id"])
            assert result["status"] == "completed", result.get("error")
            assert result["verification"]["bytes_equal"]
            accounting = result["accounting"]
            assert accounting["data_originals"] == 3 and accounting["data_attempts"] == 4
            assert accounting["data_retries"] == 1 and accounting["accepted_fragments"] == 3
            assert (
                accounting["delivered_messages"] == 1
                and accounting["unique_original_delivery_ratio"] == 1
            )
            assert accounting["receiver_duplicates"] == (1 if drop == "ack" else 0)
            originals = [wire for _, wire in pair.frames if wire[3] == 1 and wire[24:26] == b"\0\0"]
            assert len(originals) == 2 and originals[0] == originals[1]
            assert result["cleanup"]["confirmed"]
        finally:
            if bridge:
                bridge.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bridge
            await host.close()

    asyncio.run(scenario())


def test_missing_fragment_observation_retains_verified_bytes_and_incomplete_assessment(
    tmp_path, native_library
):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library, event_loss=("A", "rx.accepted"))
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            run = await host.start_radio(
                RadioRunRequest(
                    direction="B_TO_A", message_bytes=321, timeout_ms=120000, link=Link(guard_us=0)
                )
            )
            async with asyncio.timeout(15):
                while host.radio.busy:
                    if bridge.done():
                        await bridge
                    await asyncio.sleep(0.01)
            record = host.radio.get(run["id"])
            assert record["status"] == "failed" and record["verification"]["bytes_equal"]
            assert record["accounting"]["evidence_complete"] is False
            assert "do not infer RF loss" in record["error"]
        finally:
            if bridge:
                bridge.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bridge
            await host.close()

    asyncio.run(scenario())


def test_failed_message_retains_complete_missing_parts_without_inventing_bytes(
    tmp_path, native_library
):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library, drop="data")
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            run = await host.start_radio(
                RadioRunRequest(message_bytes=321, timeout_ms=10000, link=Link(guard_us=0))
            )
            async with asyncio.timeout(15):
                while host.radio.busy:
                    if bridge.done():
                        await bridge
                    await asyncio.sleep(0.01)
            record = host.radio.get(run["id"])
            assert record["status"] == "failed" and record["verification"] is None
            missing = record["missing_evidence"]
            assert missing["ranges_complete"] and missing["missing_indexes"] == [0]
            assert missing["fragment_count"] == 3 and missing["accepted_fragments"] == 2
            assert "recovered" not in record["available_content"]
            assert record["cleanup"]["confirmed"]
        finally:
            if bridge:
                bridge.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bridge
            await host.close()

    asyncio.run(scenario())


def test_absent_missing_range_part_never_fills_in_loss_indexes(tmp_path, native_library):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library, drop="data", event_loss=("B", "message.missing"))
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            run = await host.start_radio(
                RadioRunRequest(message_bytes=321, timeout_ms=10000, link=Link(guard_us=0))
            )
            async with asyncio.timeout(15):
                while host.radio.busy:
                    if bridge.done():
                        await bridge
                    await asyncio.sleep(0.01)
            record = host.radio.get(run["id"])
            assert record["status"] == "failed"
            assert record["missing_evidence"]["ranges_complete"] is False
            assert "missing_indexes" not in record["missing_evidence"]
        finally:
            if bridge:
                bridge.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bridge
            await host.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("live_updates", [False, True])
def test_single_reliable_message_while_dashboard_reads_snapshots(
    tmp_path, native_library, live_updates
):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library, drop="ack")
        bridge = updates = None
        durations = []

        async def snapshots():
            from time import perf_counter

            while host.radio.busy:
                begin = perf_counter()
                host.snapshot()
                durations.append(perf_counter() - begin)
                await asyncio.sleep(0.3)

        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            run = await host.start_radio(
                RadioRunRequest(
                    message_bytes=64,
                    timeout_ms=10000,
                    link=Link(ack_mode="stop_wait", max_retries=2),
                )
            )
            if live_updates:
                updates = asyncio.create_task(snapshots())
            async with asyncio.timeout(15):
                while host.radio.busy:
                    if bridge.done():
                        await bridge
                    await asyncio.sleep(0.01)
            result = host.radio.get(run["id"])
            assert result["status"] == "completed", (result["error"], durations)
        finally:
            for task in (bridge, updates):
                if task:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
            await host.close()

    asyncio.run(scenario())


def test_device_fixture_continues_through_host_pause_shorter_than_lease(tmp_path, native_library):
    async def scenario():
        import time

        host = Host(tmp_path)
        pair = Pair(host, native_library, drop="ack")
        bridge = None
        paused = False
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            run = await host.start_radio(
                RadioRunRequest(
                    message_bytes=64,
                    timeout_ms=10000,
                    link=Link(ack_mode="stop_wait", max_retries=2),
                )
            )
            async with asyncio.timeout(15):
                while host.radio.busy:
                    if pair.frames and not paused:
                        # Deliberately stall only the host loop; physical nodes remain autonomous.
                        time.sleep(3.5)
                        paused = True
                    if bridge.done():
                        await bridge
                    await asyncio.sleep(0.01)
            record = host.radio.get(run["id"])
            assert record["status"] == "completed", record.get("error")
        finally:
            if bridge:
                bridge.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bridge
            await host.close()

    asyncio.run(scenario())
