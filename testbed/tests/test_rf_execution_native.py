"""Finite node lifecycle against real C control and a test-only radio boundary."""

import asyncio
import base64
import ctypes as C
import hashlib
import json
from uuid import uuid4

import pytest
from test_node_control_native import NativeNode, NativeSerial
from test_node_control_native import native_library as native_library

from lora_testbed import run_protocol_v2
from lora_testbed.experiments_v2 import KnownDataPlan, KnownDataSpec, known_data, preview
from lora_testbed.frames_v2 import data_frame
from lora_testbed.nodes import NodeSession


def setup(node, *, sender=False, length=160):
    node.claim()
    run = str(uuid4())
    assert node.request(
        "session.open",
        {
            "session_id": "0102030405060708",
            "peer_device_id": "esp-aabbccddeeff",
            "peer_boot_id": "esp-aabbccddeeff:1",
            "security": "none",
            "tx_key_hex": None,
            "rx_key_hex": None,
        },
        run_id=run,
    )["ok"]
    config = node.request("config.set", {"radio": {}, "link": {}})
    assert config["ok"]
    plan = KnownDataPlan(
        spec=KnownDataSpec(
            message_count=1,
            message_bytes=length,
            direction="A_TO_B" if sender else "B_TO_A",
            max_duration_ms=3000,
        )
    )
    budget = preview(plan)["timing"]["budget"]
    accepted = node.request(
        "run.prepare", {"spec": plan.spec.model_dump(), "budget": budget}, run_id=run
    )
    assert accepted["ok"], accepted
    node.tick()
    events = node.drain()
    assert any(e.get("name") == "run.prepared" for e in events)
    assert any(
        e.get("name") == "operation.result" and e["data"]["status"] == "completed" for e in events
    )
    return run, config["result"]["config_revision"], events


@pytest.mark.parametrize("length", [1, 159, 160])
def test_receiver_validates_actual_bytes_and_publishes_committed_readback(native_library, length):
    radio = native_library.native_radio_create()
    node = NativeNode(native_library, radio=radio)
    try:
        run, revision, _ = setup(node, length=length)
        ready = node.request("run.arm", {"config_revision": revision}, run_id=run)
        assert ready["ok"] and ready["result"]["receiver_ready"]
        payload = known_data(743, 1, length)
        wire = data_frame("0102030405060708", 1, 1, 0, 1, length, "B", "A", payload)
        native_library.native_radio_inject(radio, wire, len(wire), 2)
        node.tick()
        events = node.drain()
        delivered = [e for e in events if e.get("name") == "message.result"]
        assert (
            len(delivered) == 1
            and delivered[0]["data"]["sha256"] == hashlib.sha256(payload).hexdigest()
        )
        summary = node.request("run.summary", run_id=run)["result"]
        run_protocol_v2.RESULTS["run.summary"].model_validate(summary)
        assert summary["delivered_messages"] == 1 and summary["useful_delivered_bytes"] == length
        manifests = node.request("artifact.list")["result"]["artifacts"]
        assert len(manifests) == 1 and manifests[0]["kind"] == "recovered"
        assert (
            manifests[0]["state"] == "committed"
            and manifests[0]["sha256"] == hashlib.sha256(payload).hexdigest()
        )
        chunk = node.request(
            "artifact.get",
            {"artifact_id": manifests[0]["artifact_id"], "offset": 0, "length_bytes": 1024},
        )["result"]
        assert base64.b64decode(chunk["data_b64"]) == payload and chunk["eof"]
    finally:
        node.close()


def test_sender_retains_exact_source_and_attributed_completion(native_library):
    radio = native_library.native_radio_create()
    node = NativeNode(native_library, radio=radio)
    try:
        run, revision, _ = setup(node, sender=True)
        request = node.command("run.start", {"config_revision": revision}, run_id=run)
        accepted = node.send(request)[0]
        assert accepted["ok"]
        frame = C.create_string_buffer(255)
        length = native_library.native_radio_sent(radio, frame)
        assert frame.raw[:length] == data_frame(
            "0102030405060708", 1, 1, 0, 1, 160, "A", "B", known_data(743, 1, 160)
        )
        assert node.send(request)[0] == accepted
        native_library.native_radio_tx_done(radio)
        node.tick()
        events = node.drain()
        attempts = [e for e in events if e.get("name") == "tx.attempt"]
        assert len(attempts) == 1 and attempts[0]["data"]["status"] == "completed"
        summary = node.request("run.summary", run_id=run)["result"]
        assert summary["original_packets"] == 1 and summary["tx_attempts"] == 1
        assert summary["last_tx_done_us"] >= summary["first_tx_command_us"]
    finally:
        node.close()


def test_wrong_frames_do_not_publish_and_receiver_recovers(native_library):
    radio = native_library.native_radio_create()
    node = NativeNode(native_library, radio=radio)
    try:
        run, revision, _ = setup(node)
        assert (
            node.request("run.arm", {"config_revision": revision + 1}, run_id=run)["error"]["code"]
            == "INVALID_STATE"
        )
        assert node.request("run.arm", {"config_revision": revision}, run_id=run)["ok"]
        wire = data_frame("0102030405060708", 1, 1, 0, 1, 160, "B", "A", known_data(743, 1, 160))
        malformed = [
            (wire, 0x42),
            (wire[:8] + b"\x01" * 8 + wire[16:], 2),
            (wire[:-1] + bytes([wire[-1] ^ 1]), 2),
            (wire[:-1], 2),
        ]
        for bad, irq in malformed:
            native_library.native_radio_inject(radio, bad, len(bad), irq)
            node.tick()
            events = node.drain()
            assert not any(e.get("name") == "message.result" for e in events)
            assert any(e.get("name") == "rx.rejected" for e in events)
        native_library.native_radio_inject(radio, wire, len(wire), 2)
        node.tick()
        assert sum(e.get("name") == "message.result" for e in node.drain()) == 1
        assert node.request("run.summary", run_id=run)["result"]["delivered_messages"] == 1
    finally:
        node.close()


@pytest.mark.parametrize("cleanup", ["stop", "lease", "disconnect"])
def test_rf_cleanup_never_resumes_prepared_session(native_library, cleanup):
    radio = native_library.native_radio_create()
    node = NativeNode(native_library, radio=radio)
    try:
        run, revision, _ = setup(node)
        assert node.request("run.arm", {"config_revision": revision}, run_id=run)["ok"]
        assert node.request("config.set", {"radio": {}, "link": {}})["error"]["code"] == "BUSY"
        assert node.request("control.release")["error"]["code"] == "INVALID_STATE"
        if cleanup == "stop":
            assert node.request("run.stop", {"reason": "operator"}, run_id=run)["ok"]
        elif cleanup == "lease":
            node.tick(5_000_001)
        else:
            native_library.node_control_link(node.node, False)
            native_library.node_control_link(node.node, True)
        node.drain()
        if cleanup != "stop":
            node.claim()
        assert node.request("status.get")["result"]["state"] == "idle"
        assert not node.request("run.arm", {"config_revision": revision}, run_id=run)["ok"]
        assert not any(
            m["state"] == "uploading" for m in node.request("artifact.list")["result"]["artifacts"]
        )
    finally:
        node.close()


def test_rf_prepare_json_failures_do_not_reserve_or_start_work(native_library):
    from lora_testbed.experiments_v2 import KnownDataSpec

    for failure in range(200):
        radio = native_library.native_radio_create()
        node = NativeNode(native_library, radio=radio)
        try:
            node.claim()
            run = str(uuid4())
            assert node.request(
                "session.open",
                {
                    "session_id": "0102030405060708",
                    "peer_device_id": "esp-aabbccddeeff",
                    "peer_boot_id": "esp-aabbccddeeff:1",
                    "security": "none",
                    "tx_key_hex": None,
                    "rx_key_hex": None,
                },
                run_id=run,
            )["ok"]
            assert node.request("config.set", {"radio": {}, "link": {}})["ok"]
            plan = KnownDataPlan(spec=KnownDataSpec(message_count=1, max_duration_ms=3000))
            command = node.command(
                "run.prepare",
                {"spec": plan.spec.model_dump(), "budget": preview(plan)["timing"]["budget"]},
                run_id=run,
            )
            native_library.native_allocator_fail_after(failure)
            node.feed(json.dumps(command).encode() + b"\n")
            native_library.native_allocator_fail_after(-1)
            replies = [r for r in node.drain() if r["kind"] == "reply"]
            if not replies or not replies[0]["ok"]:
                assert node.request("artifact.list")["result"]["artifacts"] == []
            assert native_library.native_allocations_live() == 0
        finally:
            native_library.native_allocator_fail_after(-1)
            node.close()


def test_host_negotiates_and_collects_real_core_rf_events(native_library):
    async def scenario():
        radio = native_library.native_radio_create()
        serial = NativeSerial(native_library, radio=radio)
        events = []
        node = NodeSession("A", lambda _, event: events.append(event), lambda _: serial)
        await node.connect("isolated-rf-core")
        run = str(uuid4())
        try:
            await node.request(
                "session.open",
                {
                    "session_id": "0102030405060708",
                    "peer_device_id": "esp-aabbccddeeff",
                    "peer_boot_id": "esp-aabbccddeeff:1",
                    "security": "none",
                    "tx_key_hex": None,
                    "rx_key_hex": None,
                },
                run_id=run,
            )
            config = await node.request("config.set", {"radio": {}, "link": {}})
            plan = KnownDataPlan(spec=KnownDataSpec(message_count=1, max_duration_ms=3000))
            prepared = await node.request(
                "run.prepare",
                {"spec": plan.spec.model_dump(), "budget": preview(plan)["timing"]["budget"]},
                run_id=run,
            )
            for _ in range(100):
                if any(
                    r["operation_id"] == prepared["operation_id"] for r in node.operation_results
                ):
                    break
                await asyncio.sleep(0.005)
            assert any(e["name"] == "run.prepared" for e in events)
            await node.request(
                "run.start", {"config_revision": config["config_revision"]}, run_id=run
            )
            native_library.native_radio_tx_done(radio)
            for _ in range(100):
                if any(e["name"] == "tx.attempt" for e in events):
                    break
                await asyncio.sleep(0.005)
            summary = await node.request("run.summary", run_id=run)
            assert summary["tx_attempts"] == 1 and summary["stop_reason"] == "completed"
            assert node.framing_errors == 0 and node.connected
        finally:
            await node.close()
        assert serial.closed

    asyncio.run(scenario())
