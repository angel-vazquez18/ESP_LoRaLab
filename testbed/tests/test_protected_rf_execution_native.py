"""Protected DATA acceptance through the actual control/radio/reassembly path."""

import ctypes as C
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from test_node_control_native import NativeNode
from test_node_control_native import native_library as native_library
from test_secure_replay_native import KEY_A, KEY_B

from lora_testbed.experiments_v2 import KnownDataPlan, KnownDataSpec, Link, known_data, preview
from lora_testbed.frames_v2 import data_frame


def protected_setup(node, *, ack=False, sender=False, role="A", run=None, length=32):
    assert node.request("control.claim", {"node_role": role})["ok"]
    run = run or str(uuid4())
    peer = "esp-66778899aabb" if role == "A" else "esp-001122334455"
    assert node.request(
        "session.open",
        {
            "session_id": "0102030405060708",
            "peer_device_id": peer,
            "peer_boot_id": peer + ":1",
            "security": "aes128_gcm",
            "tx_key_hex": (KEY_A if role == "A" else KEY_B).hex(),
            "rx_key_hex": (KEY_B if role == "A" else KEY_A).hex(),
        },
        run_id=run,
    )["ok"]
    link = Link(
        fragment_payload_bytes=16,
        ack_mode="stop_wait" if ack else "none",
        max_retries=2 if ack else 0,
    )
    config = node.request("config.set", {"radio": {}, "link": link.model_dump()})
    assert config["ok"]
    plan = KnownDataPlan(
        link=link,
        spec=KnownDataSpec(
            message_count=1,
            message_bytes=length,
            security="aes128_gcm",
            direction="A_TO_B" if sender == (role == "A") else "B_TO_A",
            max_duration_ms=10000,
        ),
    )
    accepted = node.request(
        "run.prepare",
        {"spec": plan.spec.model_dump(), "budget": preview(plan)["timing"]["budget"]},
        run_id=run,
    )
    assert accepted["ok"], accepted
    node.tick()
    node.drain()
    return run, config["result"]["config_revision"]


def wire(index, *, ack=False, sequence=None):
    plain = known_data(743, 1, 32)[index * 16 : (index + 1) * 16]
    header = bytearray(
        data_frame("0102030405060708", sequence or index + 1, 1, index, 2, 32, "B", "A", plain)[:40]
    )
    header[4] = 3 if ack else 1
    return bytes(header) + AESGCM(KEY_B).encrypt(bytes(header[8:20]), plain, bytes(header))


def test_protected_node_rejects_bad_tag_and_replay_without_consuming_good_insertion(native_library):
    node = NativeNode(native_library, radio=native_library.native_radio_create())
    try:
        run, revision = protected_setup(node)
        assert node.request("run.arm", {"config_revision": revision}, run_id=run)["ok"]
        original = wire(0)
        bad = bytearray(original)
        bad[-1] ^= 1

        def inject(frame):
            native_library.native_radio_inject(node.radio, frame, len(frame), 2)
            node.tick()
            return node.drain()

        rejected = inject(bytes(bad))
        assert any(
            r.get("name") == "rx.rejected" and r["data"]["stage"] == "authentication"
            for r in rejected
        )
        wrong_session = bytearray(original)
        wrong_session[15] ^= 1
        session_rejected = inject(bytes(wrong_session))
        assert any(
            r.get("name") == "rx.rejected" and r["data"]["stage"] == "session"
            for r in session_rejected
        )
        downgrade = bytearray(
            data_frame("0102030405060708", 1, 1, 0, 2, 32, "B", "A", known_data(743, 1, 32)[:16])
        )
        downgraded = inject(bytes(downgrade))
        assert any(
            r.get("name") == "rx.rejected" and r["data"]["stage"] == "authentication"
            for r in downgraded
        )
        accepted = inject(original)
        assert sum(r.get("name") == "rx.accepted" for r in accepted) == 1
        replay = inject(original)
        assert any(
            r.get("name") == "rx.rejected" and r["data"]["stage"] == "replay" for r in replay
        )
        delivered = inject(wire(1))
        assert (
            sum(
                r.get("name") == "message.result" and r["data"]["status"] == "delivered"
                for r in delivered
            )
            == 1
        )
        summary = node.request("run.summary", run_id=run)["result"]
        assert summary["accepted_fragments"] == 2 and summary["delivered_messages"] == 1
    finally:
        node.close()


def sent(node):
    output = C.create_string_buffer(255)
    size = node.lib.native_radio_sent(node.radio, output)
    return output.raw[:size]


def ack_for(data, sequence, *, reference=None):
    header = bytearray(data[:40])
    original = header[16:20]
    header[3] = 2
    header[4] = 1
    header[5], header[6] = header[6], header[5]
    header[16:20] = sequence.to_bytes(4, "big")
    header[32:34] = bytes(2)
    header[34:38] = original if reference is None else reference.to_bytes(4, "big")
    return bytes(header) + AESGCM(KEY_B).encrypt(bytes(header[8:20]), b"", bytes(header))


def test_receiver_reacks_exact_authenticated_retry_with_a_fresh_nonce_and_one_delivery(
    native_library,
):
    node = NativeNode(native_library, radio=native_library.native_radio_create())
    try:
        run, revision = protected_setup(node, ack=True)
        assert node.request("run.arm", {"config_revision": revision}, run_id=run)["ok"]

        def inject(raw):
            native_library.native_radio_inject(node.radio, raw, len(raw), 2)
            node.tick()
            return node.drain()

        original = wire(0, ack=True)
        first = inject(original)
        assert sum(r.get("name") == "rx.accepted" for r in first) == 1
        node.tick(20001)
        node.drain()
        first_ack = sent(node)
        assert len(first_ack) == 56 and first_ack[4] == 1
        assert AESGCM(KEY_A).decrypt(first_ack[8:20], first_ack[40:], first_ack[:40]) == b""
        native_library.native_radio_tx_done(node.radio)
        node.tick()
        node.drain()
        repeated = inject(original)
        assert not any(r.get("name") in ("rx.accepted", "message.result") for r in repeated)
        node.tick(20001)
        node.drain()
        second_ack = sent(node)
        assert (
            len(second_ack) == 56 and second_ack[34:38] == first_ack[34:38] == b"\x00\x00\x00\x01"
        )
        assert int.from_bytes(second_ack[16:20], "big") == 2
        assert first_ack != second_ack
        assert AESGCM(KEY_A).decrypt(second_ack[8:20], second_ack[40:], second_ack[:40]) == b""
        native_library.native_radio_tx_done(node.radio)
        node.tick()
        node.drain()
        final = inject(wire(1, ack=True))
        assert (
            sum(
                r.get("name") == "message.result" and r["data"]["status"] == "delivered"
                for r in final
            )
            == 1
        )
        node.tick(20001)
        node.drain()
        native_library.native_radio_tx_done(node.radio)
        node.tick()
        node.drain()
        summary = node.request("run.summary", run_id=run)["result"]
        assert summary["accepted_fragments"] == 2 and summary["delivered_messages"] == 1
    finally:
        node.close()


@pytest.mark.parametrize("reason", ["authentication_failed", "wrong_reference"])
def test_invalid_protected_ack_does_not_advance_or_consume_sequence(native_library, reason):
    node = NativeNode(native_library, radio=native_library.native_radio_create())
    try:
        run, revision = protected_setup(node, ack=True, sender=True)
        assert node.request("run.arm", {"config_revision": revision}, run_id=run)["ok"]
        assert node.request("run.start", {"config_revision": revision}, run_id=run)["ok"]
        original = sent(node)
        assert len(original) == 72 and original[4] == 3
        assert (
            AESGCM(KEY_A).decrypt(original[8:20], original[40:], original[:40])
            == known_data(743, 1, 32)[:16]
        )
        native_library.native_radio_tx_done(node.radio)
        node.tick()
        node.drain()
        good = ack_for(original, 1)
        if reason == "authentication_failed":
            bad = good[:-1] + bytes([good[-1] ^ 1])
        else:
            bad = ack_for(original, 1, reference=2)
        native_library.native_radio_inject(node.radio, bad, len(bad), 2)
        node.tick()
        rejected = node.drain()
        [arrival] = [row["data"] for row in rejected if row.get("name") == "rx.frame"]
        [decision] = [row["data"] for row in rejected if row.get("name") == "rx.rejected"]
        assert arrival["crc_ok"] and decision["rx_done_us"] == arrival["rx_done_us"]
        assert decision["reason"] == reason
        assert not any(row.get("name") == "ack.result" for row in rejected)
        assert sent(node) == original
        plan = KnownDataPlan(
            link=Link(fragment_payload_bytes=16, ack_mode="stop_wait"),
            spec=KnownDataSpec(
                message_count=1, message_bytes=32, security="aes128_gcm", max_duration_ms=10000
            ),
        )
        timeout = preview(plan)["timing"]["budget"]["ack_timeout_us"]
        node.tick(timeout + 1)
        [expired] = [row["data"] for row in node.drain() if row.get("name") == "ack.result"]
        assert (expired["status"], expired["attempt_index"]) == ("timeout", 1)
        node.tick(50001)
        node.drain()
        assert sent(node) == original
        native_library.native_radio_tx_done(node.radio)
        node.tick()
        node.drain()
        native_library.native_radio_inject(node.radio, good, len(good), 2)
        node.tick()
        ack_records = node.drain()
        assert any(
            r.get("name") == "ack.result"
            and r["data"]["status"] == "received"
            and r["data"]["acked_frame_seq"] == 1
            for r in ack_records
        )
        node.tick(50001)
        node.drain()
        final = sent(node)
        assert final != original and int.from_bytes(final[16:20], "big") == 2
        native_library.native_radio_tx_done(node.radio)
        node.tick()
        node.drain()
        last_ack = ack_for(final, 2)
        native_library.native_radio_inject(node.radio, last_ack, len(last_ack), 2)
        node.tick()
        node.drain()
        summary = node.request("run.summary", run_id=run)["result"]
        assert summary["stop_reason"] == "completed", summary
        assert summary["original_packets"] == 2 and summary["tx_attempts"] == 3
    finally:
        node.close()


def test_two_c_nodes_recover_a_lost_protected_ack_without_duplicate_delivery(native_library):
    import base64
    import hashlib

    lib = native_library
    for name in ("native_radio_generation", "native_radio_listening", "native_radio_transmitting"):
        getattr(lib, name).argtypes = [C.c_void_p]
        getattr(lib, name).restype = C.c_uint
    nodes = {
        "A": NativeNode(lib, radio=lib.native_radio_create()),
        "B": NativeNode(lib, radio=lib.native_radio_create(), device="esp-66778899aabb"),
    }
    records, frames, in_flight = {role: [] for role in nodes}, [], []
    generations = dict.fromkeys(nodes, 0)
    dropped_ack = False
    run = str(uuid4())
    try:
        _, revision_a = protected_setup(nodes["A"], ack=True, sender=True, run=run)
        _, revision_b = protected_setup(nodes["B"], ack=True, role="B", run=run)
        assert nodes["B"].request("run.arm", {"config_revision": revision_b}, run_id=run)["ok"]
        assert nodes["A"].request("run.arm", {"config_revision": revision_a}, run_id=run)["ok"]
        assert nodes["A"].request("run.start", {"config_revision": revision_a}, run_id=run)["ok"]
        for _ in range(400):
            for role, node in nodes.items():
                node.tick(10000)
                records[role] += node.drain()
                generation = lib.native_radio_generation(node.radio)
                if generation != generations[role]:
                    generations[role] = generation
                    raw = sent(node)
                    frames.append((role, raw))
                    in_flight.append((node.now() + 20000, role, generation, raw))
            pending = []
            for due, role, generation, raw in in_flight:
                source, target = nodes[role], nodes["B" if role == "A" else "A"]
                if source.now() < due:
                    pending.append((due, role, generation, raw))
                    continue
                if not lib.native_radio_transmitting(source.radio):
                    continue
                lib.native_radio_tx_done(source.radio)
                drop = raw[3] == 2 and not dropped_ack
                if drop:
                    dropped_ack = True
                elif lib.native_radio_listening(target.radio):
                    lib.native_radio_inject(target.radio, raw, len(raw), 2)
            in_flight = pending
            if all(any(r.get("name") == "run.summary" for r in records[role]) for role in nodes):
                break
        else:
            pytest.fail("Protected pair did not reach two bounded summaries")
        summaries = {
            role: next(r["data"] for r in records[role] if r.get("name") == "run.summary")
            for role in nodes
        }
        assert all(s["stop_reason"] == "completed" for s in summaries.values()), summaries
        assert summaries["A"]["original_packets"] == 2 and summaries["A"]["tx_attempts"] == 3
        assert summaries["B"]["accepted_fragments"] == 2 and summaries["B"]["duplicates"] == 1
        assert summaries["B"]["delivered_messages"] == 1
        repeated_data = [
            raw for role, raw in frames if role == "A" and raw[16:20] == b"\x00\x00\x00\x01"
        ]
        assert len(repeated_data) == 2 and repeated_data[0] == repeated_data[1]
        ack_sequences = [int.from_bytes(raw[16:20], "big") for role, raw in frames if role == "B"]
        assert ack_sequences == [1, 2, 3]
        manifests = nodes["B"].request("artifact.list")["result"]["artifacts"]
        artifact = next(m for m in manifests if m["kind"] == "recovered")
        payload = known_data(743, 1, 32)
        assert artifact["sha256"] == hashlib.sha256(payload).hexdigest()
        readback = nodes["B"].request(
            "artifact.get",
            {"artifact_id": artifact["artifact_id"], "offset": 0, "length_bytes": 1024},
        )["result"]
        assert base64.b64decode(readback["data_b64"]) == payload
    finally:
        for node in nodes.values():
            node.close()


@pytest.mark.parametrize("cutoff", range(9))
def test_successful_receiver_drain_boundary_is_not_a_failed_receive_timeout(native_library, cutoff):
    node = NativeNode(native_library, radio=native_library.native_radio_create())
    try:
        run, revision = protected_setup(node, ack=True, length=16)
        assert node.request("run.arm", {"config_revision": revision}, run_id=run)["ok"]
        payload = known_data(743, 1, 16)
        header = bytearray(data_frame("0102030405060708", 1, 1, 0, 1, 16, "B", "A", payload)[:40])
        header[4] = 3
        raw = bytes(header) + AESGCM(KEY_B).encrypt(bytes(header[8:20]), payload, bytes(header))
        native_library.native_radio_inject(node.radio, raw, len(raw), 2)
        node.tick()
        events = node.drain()
        completed = next(
            r["data"]["complete_us"] for r in events if r.get("name") == "message.result"
        )
        node.tick(20001)
        node.drain()
        native_library.native_radio_tx_done(node.radio)
        node.tick()
        node.drain()
        plan = KnownDataPlan(
            link=Link(fragment_payload_bytes=16, ack_mode="stop_wait"),
            spec=KnownDataSpec(
                message_count=1, message_bytes=16, security="aes128_gcm", max_duration_ms=10000
            ),
        )
        boundary = completed + preview(plan)["timing"]["budget"]["drain_us"]
        native_library.native_radio_listening.argtypes = [C.c_void_p]
        native_library.native_radio_listening.restype = C.c_bool
        assert native_library.native_radio_listening(node.radio)
        assert node.request("run.summary", run_id=run)["result"]["delivered_messages"] == 1
        calls = 0

        def clock_crosses_during_poll():
            nonlocal calls
            calls += 1
            return boundary - 1 if calls <= cutoff else boundary + 1

        node.now = clock_crosses_during_poll
        native_library.native_radio_inject(node.radio, b"", 0, 512)  # Hardware RX timeout.
        node.tick()
        records = node.drain()
        node.now = lambda: boundary + 1
        node.tick()
        records += node.drain()
        terminal = next(r["data"] for r in records if r.get("name") == "run.summary")
        assert terminal["delivered_messages"] == 1
        assert terminal["stop_reason"] == "completed", terminal["stop_reason"]
    finally:
        node.close()


def test_delivered_receiver_with_unfinished_ack_still_fails_at_drain_deadline(native_library):
    node = NativeNode(native_library, radio=native_library.native_radio_create())
    try:
        run, revision = protected_setup(node, ack=True, length=16)
        assert node.request("run.arm", {"config_revision": revision}, run_id=run)["ok"]
        payload = known_data(743, 1, 16)
        header = bytearray(data_frame("0102030405060708", 1, 1, 0, 1, 16, "B", "A", payload)[:40])
        header[4] = 3
        raw = bytes(header) + AESGCM(KEY_B).encrypt(bytes(header[8:20]), payload, bytes(header))
        native_library.native_radio_inject(node.radio, raw, len(raw), 2)
        node.tick()
        node.drain()
        node.tick(20001)
        node.drain()  # ACK starts, but its completion is never supplied.
        node.tick(2100000)
        summary = next(r["data"] for r in node.drain() if r.get("name") == "run.summary")
        assert summary["delivered_messages"] == 1
        assert summary["stop_reason"] == "timeout"
    finally:
        node.close()
