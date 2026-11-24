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
from lora_testbed.experiments_v2 import KnownDataPlan, KnownDataSpec, Link, known_data, preview
from lora_testbed.frames_v2 import data_frame
from lora_testbed.nodes import NodeSession


def setup(node, *, sender=False, length=160, link=None, duration=3000):
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
    config = node.request("config.set", {"radio": {}, "link": link.model_dump() if link else {}})
    assert config["ok"]
    plan = KnownDataPlan(
        link=link or Link(),
        spec=KnownDataSpec(
            message_count=1,
            message_bytes=length,
            direction="A_TO_B" if sender else "B_TO_A",
            max_duration_ms=duration,
        ),
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
        assert node.request("run.arm", {"config_revision": revision}, run_id=run)["ok"]
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
                "run.arm", {"config_revision": config["config_revision"]}, run_id=run
            )
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


def test_receiver_reconstructs_reordered_fragments_with_exact_readback(native_library):
    radio = native_library.native_radio_create()
    node = NativeNode(native_library, radio=radio)
    try:
        run, revision, _ = setup(node, length=321)
        assert node.request("run.arm", {"config_revision": revision}, run_id=run)["ok"]
        source = known_data(743, 1, 321)
        for index in (2, 0, 0, 1):
            payload = source[index * 160 : (index + 1) * 160]
            wire = data_frame("0102030405060708", index + 1, 1, index, 3, 321, "B", "A", payload)
            native_library.native_radio_inject(radio, wire, len(wire), 2)
            node.tick()
            node.drain()
        summary = node.request("run.summary", run_id=run)["result"]
        assert summary["accepted_fragments"] == 3 and summary["duplicates"] == 1
        assert summary["delivered_messages"] == 1 and summary["useful_delivered_bytes"] == 321
        files = node.request("artifact.list")["result"]["artifacts"]
        assert len(files) == 1 and files[0]["state"] == "committed"
        part = node.request(
            "artifact.get",
            {"artifact_id": files[0]["artifact_id"], "offset": 0, "length_bytes": 1024},
        )["result"]
        assert base64.b64decode(part["data_b64"]) == source
        assert files[0]["sha256"] == hashlib.sha256(source).hexdigest()
    finally:
        node.close()


def test_sender_emits_exact_original_fragments_with_guard_and_separate_counts(native_library):
    radio = native_library.native_radio_create()
    node = NativeNode(native_library, radio=radio)
    try:
        run, revision, _ = setup(node, sender=True, length=321)
        assert node.request("run.arm", {"config_revision": revision}, run_id=run)["ok"]
        assert node.request("run.start", {"config_revision": revision}, run_id=run)["ok"]
        source = known_data(743, 1, 321)
        attempts = []
        for index, size in enumerate((160, 160, 1)):
            frame = C.create_string_buffer(255)
            count = native_library.native_radio_sent(radio, frame)
            assert frame.raw[:count] == data_frame(
                "0102030405060708",
                index + 1,
                1,
                index,
                3,
                321,
                "A",
                "B",
                source[index * 160 : index * 160 + size],
            )
            native_library.native_radio_tx_done(radio)
            node.tick()
            attempts.extend(e["data"] for e in node.drain() if e.get("name") == "tx.attempt")
            summary = node.request("run.summary", run_id=run)["result"]
            assert summary["original_packets"] == index + 1 and summary["tx_attempts"] == index + 1
            if index < 2:
                assert summary["finished_messages"] == 0
                node.tick(50000)
                node.drain()
        assert summary["finished_messages"] == 1
        assert [a["fragment_index"] for a in attempts] == [0, 1, 2]
        assert [a["frame_bytes"] for a in attempts] == [200, 200, 41]
    finally:
        node.close()


def test_receiver_schedules_fresh_acks_for_identical_retry_and_delivers_once(native_library):
    radio = native_library.native_radio_create()
    node = NativeNode(native_library, radio=radio)
    try:
        link = Link(ack_mode="stop_wait", max_retries=2, guard_us=0)
        run, revision, _ = setup(node, length=64, link=link, duration=10000)
        assert node.request("run.arm", {"config_revision": revision}, run_id=run)["ok"]
        source = known_data(743, 1, 64)
        plain = data_frame("0102030405060708", 1, 1, 0, 1, 64, "B", "A", source)
        wire = plain[:4] + b"\x02" + plain[5:]
        acknowledgments = []
        deliveries = []
        for attempt in (1, 2):
            native_library.native_radio_inject(radio, wire, len(wire), 2)
            node.tick()
            deliveries.extend(e for e in node.drain() if e.get("name") == "message.result")
            node.tick(20000)
            frame = C.create_string_buffer(255)
            n = native_library.native_radio_sent(radio, frame)
            assert n == 40 and frame.raw[3:7] == b"\x02\0\x01\x02"
            assert int.from_bytes(frame.raw[16:20], "big") == attempt
            assert int.from_bytes(frame.raw[34:38], "big") == 1
            acknowledgments.append(frame.raw[:n])
            native_library.native_radio_tx_done(radio)
            node.tick()
            node.drain()
        summary = node.request("run.summary", run_id=run)["result"]
        assert len(deliveries) == 1 and summary["delivered_messages"] == 1
        assert summary["accepted_fragments"] == 1 and summary["duplicates"] == 1
        assert summary["original_packets"] == 0 and summary["tx_attempts"] == 2
        node.tick(2500000)
        assert node.request("status.get")["result"]["state"] == "idle"
    finally:
        node.close()


def test_sender_waits_for_exact_ack_before_finishing_original(native_library):
    import struct

    radio = native_library.native_radio_create()
    node = NativeNode(native_library, radio=radio)
    try:
        link = Link(ack_mode="stop_wait", max_retries=2, guard_us=0)
        run, revision, _ = setup(node, sender=True, length=64, link=link, duration=10000)
        assert node.request("run.arm", {"config_revision": revision}, run_id=run)["ok"]
        assert node.request("run.start", {"config_revision": revision}, run_id=run)["ok"]
        frame = C.create_string_buffer(255)
        assert native_library.native_radio_sent(radio, frame) == 104
        assert frame.raw[4] == 2
        native_library.native_radio_tx_done(radio)
        node.tick()
        events = node.drain()
        assert not any(e.get("name") == "run.summary" for e in events)
        ack = struct.pack(
            ">2sBBBBBBQIIHHIHIH",
            b"LT",
            2,
            2,
            0,
            2,
            1,
            0,
            0x0102030405060708,
            1,
            1,
            0,
            1,
            64,
            0,
            1,
            0,
        )
        native_library.native_radio_inject(radio, ack, len(ack), 2)
        node.tick()
        events = node.drain()
        assert any(e.get("name") == "rx.frame" and e["data"]["frame_type"] == "ack" for e in events)
        summary = node.request("run.summary", run_id=run)["result"]
        assert summary["finished_messages"] == 1 and summary["stop_reason"] == "completed"
        assert summary["original_packets"] == 1 and summary["tx_attempts"] == 1
    finally:
        node.close()


def test_incomplete_receiver_reports_exact_missing_indexes_without_partial_artifact(native_library):
    radio = native_library.native_radio_create()
    node = NativeNode(native_library, radio=radio)
    try:
        run, revision, _ = setup(node, length=321, duration=10000)
        assert node.request("run.arm", {"config_revision": revision}, run_id=run)["ok"]
        source = known_data(743, 1, 321)
        for index in (0, 2):
            wire = data_frame(
                "0102030405060708",
                index + 1,
                1,
                index,
                3,
                321,
                "B",
                "A",
                source[index * 160 : (index + 1) * 160],
            )
            native_library.native_radio_inject(radio, wire, len(wire), 2)
            node.tick()
            node.drain()
        events = []
        for _ in range(8):
            assert node.request("control.keepalive")["ok"]
            node.tick(1_000_000)
            events.extend(node.drain())
        for _ in range(5):
            node.tick()
            events.extend(node.drain())
        missing = [e["data"] for e in events if e.get("name") == "message.missing"]
        result = [e["data"] for e in events if e.get("name") == "message.result"]
        assert len(missing) == 1 and missing[0]["ranges"] == [[1, 1]]
        assert missing[0]["part_index"] == 0 and missing[0]["part_count"] == 1
        assert len(result) == 1 and result[0]["status"] == "failed"
        assert result[0]["missing_count"] == 1 and result[0]["missing_parts"] == 1
        assert result[0]["sha256"] is None
        assert node.request("artifact.list")["result"]["artifacts"] == []
        assert node.request("status.get")["result"]["state"] == "idle"
    finally:
        node.close()


def test_maximum_fragment_bitmap_emits_bounded_missing_range_pages(native_library):
    radio = native_library.native_radio_create()
    node = NativeNode(native_library, radio=radio)
    try:
        link = Link(fragment_payload_bytes=16, guard_us=0)
        run, revision, _ = setup(node, length=65536, link=link, duration=900000)
        assert node.request("run.arm", {"config_revision": revision}, run_id=run)["ok"]
        source = known_data(743, 1, 65536)
        for index in range(0, 4096, 2):
            wire = data_frame(
                "0102030405060708",
                index + 1,
                1,
                index,
                4096,
                65536,
                "B",
                "A",
                source[index * 16 : (index + 1) * 16],
            )
            native_library.native_radio_inject(radio, wire, len(wire), 2)
            node.tick()
            node.drain()
        lifetime = preview(
            KnownDataPlan(
                link=link,
                spec=KnownDataSpec(message_count=1, message_bytes=65536, max_duration_ms=900000),
            )
        )["timing"]["budget"]["reassembly_timeout_us"]
        events = []
        remaining = lifetime + 5_000_001
        while remaining:
            assert node.request("control.keepalive")["ok"]
            step = min(remaining, 1000000)
            node.tick(step)
            events.extend(node.drain())
            remaining -= step
        for _ in range(40):
            node.tick()
            events.extend(node.drain())
        parts = [e["data"] for e in events if e.get("name") == "message.missing"]
        assert len(parts) == 32 and [p["part_index"] for p in parts] == list(range(32))
        assert all(p["part_count"] == 32 and len(p["ranges"]) <= 64 for p in parts)
        indexes = [i for p in parts for start, end in p["ranges"] for i in range(start, end + 1)]
        assert indexes == list(range(1, 4096, 2))
        failed = [e["data"] for e in events if e.get("name") == "message.result"]
        assert (
            len(failed) == 1
            and failed[0]["missing_count"] == 2048
            and failed[0]["missing_parts"] == 32
        )
        assert node.request("artifact.list")["result"]["artifacts"] == []
        assert node.request("status.get")["result"]["state"] == "idle"
    finally:
        node.close()


@pytest.mark.parametrize("cleanup", ["stop", "lease", "disconnect"])
def test_ack_wait_cleanup_reaches_real_sender_and_never_resumes_attempts(native_library, cleanup):
    native_library.native_radio_generation.argtypes = [C.c_void_p]
    native_library.native_radio_generation.restype = C.c_uint
    radio = native_library.native_radio_create()
    node = NativeNode(native_library, radio=radio)
    try:
        link = Link(ack_mode="stop_wait", max_retries=2, guard_us=0)
        run, revision, _ = setup(node, sender=True, length=321, link=link, duration=10000)
        assert node.request("run.arm", {"config_revision": revision}, run_id=run)["ok"]
        assert node.request("run.start", {"config_revision": revision}, run_id=run)["ok"]
        native_library.native_radio_tx_done(radio)
        node.tick()
        node.drain()
        before = native_library.native_radio_generation(radio)
        if cleanup == "stop":
            assert node.request("run.stop", {"reason": "operator"}, run_id=run)["ok"]
        elif cleanup == "lease":
            node.tick(5000001)
        else:
            native_library.node_control_link(node.node, False)
            native_library.node_control_link(node.node, True)
        node.drain()
        if cleanup != "stop":
            node.claim()
        assert node.request("status.get")["result"]["state"] == "idle"
        node.tick(1000000)
        node.drain()
        assert native_library.native_radio_generation(radio) == before
        assert not node.request("run.start", {"config_revision": revision}, run_id=run)["ok"]
    finally:
        node.close()


def test_stopping_blocked_range_report_releases_resources_with_explicit_incomplete_validity(
    native_library,
):
    radio = native_library.native_radio_create()
    node = NativeNode(native_library, radio=radio)
    try:
        link = Link(fragment_payload_bytes=16, guard_us=0)
        run, revision, _ = setup(node, length=8192, link=link, duration=120000)
        assert node.request("run.arm", {"config_revision": revision}, run_id=run)["ok"]
        lifetime = preview(
            KnownDataPlan(
                link=link,
                spec=KnownDataSpec(message_count=1, message_bytes=8192, max_duration_ms=120000),
            )
        )["timing"]["budget"]["reassembly_timeout_us"]
        remaining = lifetime + 5_000_001
        while remaining > 1000000:
            assert node.request("control.keepalive")["ok"]
            node.tick(1000000)
            node.drain()
            remaining -= 1000000
        assert node.request("control.keepalive")["ok"]
        node.tick(remaining)
        for _ in range(12):
            node.tick()  # Deliberately leave telemetry queued.
        assert node.request("run.stop", {"reason": "operator"}, run_id=run)["ok"]
        summary = node.request("run.summary", run_id=run)["result"]
        assert "missing_range_evidence_incomplete" in summary["validity_reasons"]
        assert summary["stop_reason"] == "timeout"
        assert node.request("status.get")["result"]["state"] == "idle"
        assert node.request("artifact.list")["result"]["artifacts"] == []
    finally:
        node.close()


@pytest.mark.parametrize(
    "field",
    ["message_max", "ack_timeout_us", "drain_us", "processing_budget_us", "reassembly_timeout_us"],
)
def test_invalid_prepared_bounds_reject_before_buffers_or_rf(native_library, field):
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
        link = Link(ack_mode="stop_wait", max_retries=2)
        assert node.request("config.set", {"radio": {}, "link": link.model_dump()})["ok"]
        plan = KnownDataPlan(
            link=link, spec=KnownDataSpec(message_count=1, message_bytes=64, max_duration_ms=10000)
        )
        spec = plan.spec.model_dump()
        budget = preview(plan)["timing"]["budget"]
        if field == "message_max":
            spec["message_bytes"] = 65537
        else:
            budget[field] = 0 if field != "reassembly_timeout_us" else 1
        before = native_library.native_radio_transfers()
        rejected = node.request("run.prepare", {"spec": spec, "budget": budget}, run_id=run)
        assert not rejected["ok"] and rejected["error"]["code"] == "INVALID_ARGUMENT"
        assert native_library.native_radio_transfers() == before
        assert not node.allocations
        assert node.request("artifact.list")["result"]["artifacts"] == []
    finally:
        node.close()
