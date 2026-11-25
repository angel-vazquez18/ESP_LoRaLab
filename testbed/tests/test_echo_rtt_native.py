"""Verified echoes through the actual owned C control/radio path, with explicit clocks."""

import ctypes as C
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from test_node_control_native import NativeNode
from test_node_control_native import native_library as native_library
from test_secure_replay_native import KEY_A, KEY_B

from lora_testbed.experiments_v2 import (
    Link,
    known_data,
    preview,
)
from lora_testbed.run_protocol_v2 import EchoPlan, EchoSpec

SESSION = "0102030405060708"


class EchoPair:
    def __init__(self, lib, protected=False):
        self.lib, self.protected = lib, protected
        self.a = NativeNode(lib, radio=lib.native_radio_create())
        self.b = NativeNode(lib, radio=lib.native_radio_create(), device="esp-66778899aabb")
        self.b.time = 101_000_000  # Peer clock must never enter requester RTT arithmetic.
        self.run = str(uuid4())
        self.session = SESSION
        self.revisions = {}
        self.events = {"A": [], "B": []}

    def prepare(self, *, length=32, fragment=64, direction="A_TO_B"):
        link = Link(fragment_payload_bytes=fragment)
        self.plan = EchoPlan(
            link=link,
            spec=EchoSpec(
                direction=direction,
                message_bytes=length,
                max_duration_ms=10000,
                security="aes128_gcm" if self.protected else "none",
            ),
        )
        spec = self.plan.spec.model_dump()
        budget = preview(self.plan)["timing"]["budget"]
        for role, node, peer in (
            ("A", self.a, "esp-66778899aabb"),
            ("B", self.b, "esp-001122334455"),
        ):
            assert node.request("control.claim", {"node_role": role})["ok"]
            assert node.request(
                "session.open",
                {
                    "session_id": self.session,
                    "peer_device_id": peer,
                    "peer_boot_id": peer + ":1",
                    "security": spec["security"],
                    "tx_key_hex": (KEY_A if role == "A" else KEY_B).hex()
                    if self.protected
                    else None,
                    "rx_key_hex": (KEY_B if role == "A" else KEY_A).hex()
                    if self.protected
                    else None,
                },
                run_id=self.run,
            )["ok"]
            config = node.request("config.set", {"radio": {}, "link": link.model_dump()})
            assert config["ok"]
            self.revisions[role] = config["result"]["config_revision"]
            prepared = node.request(
                "run.prepare", {"spec": spec, "budget": budget}, run_id=self.run
            )
            assert prepared["ok"], prepared
            self.tick(role)
        source = direction[0]
        for role in ("B", "A") if source == "A" else ("A", "B"):
            assert self.node(role).request(
                "run.arm", {"config_revision": self.revisions[role]}, run_id=self.run
            )["ok"]
        assert self.node(source).request(
            "run.start", {"config_revision": self.revisions[source]}, run_id=self.run
        )["ok"]

    def node(self, role):
        return self.a if role == "A" else self.b

    def tick(self, role, advance=0):
        node = self.node(role)
        node.tick(advance)
        records = node.drain()
        self.events[role].extend(records)
        return records

    def sent(self, role):
        out = C.create_string_buffer(255)
        size = self.lib.native_radio_sent(self.node(role).radio, out)
        assert size, "Expected an actual radio submission"
        return out.raw[:size]

    def tx_done(self, role, advance=1000):
        self.lib.native_radio_tx_done(self.node(role).radio)
        return self.tick(role, advance)

    def inject(self, role, wire, advance=1000):
        self.lib.native_radio_inject(self.node(role).radio, wire, len(wire), 2)
        return self.tick(role, advance)

    def reply(self):
        request = self.sent("A")
        self.tx_done("A")
        self.inject("B", request)
        self.tick("B", 20000)
        reply = self.sent("B")
        self.tx_done("B")
        return reply

    def summary(self, role="A"):
        reply = self.node(role).request("run.summary", run_id=self.run)
        assert reply["ok"], reply
        return reply["result"]

    def close(self):
        self.a.close()
        self.b.close()


@pytest.mark.parametrize("protected", [False, True])
def test_real_pair_echoes_exact_bytes_and_reports_only_requester_local_rtt(
    native_library, protected
):
    pair = EchoPair(native_library, protected)
    try:
        pair.prepare()
        request = pair.sent("A")
        assert request[3] == 3 and not request[4] & 2
        request_sequence = int.from_bytes(request[16:20], "big")
        pair.tx_done("A")
        pair.inject("B", request)
        pair.tick("B", 20000)
        reply = pair.sent("B")
        assert reply[3] == 4 and reply[5:7] == b"\x02\x01"
        assert int.from_bytes(reply[34:38], "big") == request_sequence
        assert int.from_bytes(reply[16:20], "big") > 0
        payload = (
            AESGCM(KEY_B).decrypt(reply[8:20], reply[40:], reply[:40]) if protected else reply[40:]
        )
        assert payload == known_data(743, 1, 32)
        pair.tx_done("B")
        pair.inject("A", reply, advance=17000)
        results = [row["data"] for row in pair.events["A"] if row.get("name") == "echo.result"]
        assert len(results) == 1 and results[0]["valid"], results
        result = results[0]
        transmitted = next(
            row["data"] for row in pair.events["A"] if row.get("name") == "tx.attempt"
        )
        assert result["request_frame_seq"] == request_sequence
        assert result["tx_command_us"] == transmitted["tx_command_us"]
        assert result["reply_accepted_us"] == pair.a.now()
        assert result["rtt_us"] == result["reply_accepted_us"] - result["tx_command_us"]
        assert 0 < result["rtt_us"] < 100000 and pair.b.now() > 100000000
        pair.inject("A", reply)
        assert (
            sum(
                row.get("name") == "echo.result" and row["data"]["valid"]
                for row in pair.events["A"]
            )
            == 1
        )
        assert any(
            row.get("name") == "rx.rejected" and row["data"]["reason"] == "duplicate"
            for row in pair.events["A"]
        )
    finally:
        pair.close()


def changed_reply(reply, protected, fault):
    header = bytearray(reply[:40])
    body = bytearray(
        AESGCM(KEY_B).decrypt(reply[8:20], reply[40:], reply[:40]) if protected else reply[40:]
    )
    if fault == "wrong_session":
        header[15] ^= 1
    elif fault == "wrong_source":
        header[5], header[6] = 1, 2
    elif fault == "wrong_reference":
        header[37] += 1
    elif fault == "wrong_message":
        header[23] += 1
    elif fault == "content_mismatch":
        body[-1] ^= 1
    elif fault == "unexpected_frame":
        header[3] = 3
        header[34:38] = bytes(4)
    elif fault == "invalid_frame":
        header[38] = 1
    elif fault == "protection_mismatch":
        header[4] ^= 1
        protected = not protected
    result = bytes(header) + (
        AESGCM(KEY_B).encrypt(bytes(header[8:20]), bytes(body), bytes(header))
        if protected
        else bytes(body)
    )
    if fault == "authentication_failed":
        result = result[:-1] + bytes([result[-1] ^ 1])
    return result


@pytest.mark.parametrize("protected", [False, True])
@pytest.mark.parametrize(
    "fault",
    [
        "wrong_session",
        "wrong_source",
        "wrong_reference",
        "wrong_message",
        "content_mismatch",
        "unexpected_frame",
        "invalid_frame",
        "protection_mismatch",
    ],
)
def test_rejected_echo_cannot_create_a_sample_or_consume_valid_reply(
    native_library, protected, fault
):
    pair = EchoPair(native_library, protected)
    try:
        pair.prepare()
        reply = pair.reply()
        rejected = pair.inject("A", changed_reply(reply, protected, fault))
        assert any(
            row.get("name") == "rx.rejected" and row["data"]["reason"] == fault for row in rejected
        ), rejected
        assert not any(row.get("name") == "echo.result" for row in rejected)
        assert pair.summary()["echo"]["rtt_us"] is None
        accepted = pair.inject("A", reply)
        assert (
            sum(row.get("name") == "echo.result" and row["data"]["valid"] for row in accepted) == 1
        )
    finally:
        pair.close()


def test_bad_echo_tag_is_not_accepted_or_committed_to_replay_window(native_library):
    pair = EchoPair(native_library, True)
    try:
        pair.prepare()
        reply = pair.reply()
        rejected = pair.inject("A", changed_reply(reply, True, "authentication_failed"))
        assert any(
            row.get("name") == "rx.rejected" and row["data"]["stage"] == "authentication"
            for row in rejected
        )
        assert pair.summary()["echo"]["rtt_us"] is None
        assert any(
            row.get("name") == "echo.result" and row["data"]["valid"]
            for row in pair.inject("A", reply)
        )
    finally:
        pair.close()


@pytest.mark.parametrize("protected", [False, True])
def test_missing_reply_times_out_late_reply_is_excluded_and_new_session_recovers(
    native_library, protected
):
    pair = EchoPair(native_library, protected)
    try:
        pair.prepare()
        reply = pair.reply()
        pair.tick("A", 4000000)
        assert pair.a.request("control.keepalive")["ok"]
        pair.tick("A", 4000000)
        results = [row["data"] for row in pair.events["A"] if row.get("name") == "echo.result"]
        assert len(results) == 1 and results[0]["reason"] == "timeout"
        assert not results[0]["valid"] and results[0]["rtt_us"] is None
        late = pair.inject("A", reply)
        assert any(
            row.get("name") == "rx.rejected" and row["data"]["reason"] == "late" for row in late
        )
        assert pair.summary()["echo"]["reply_accepted_us"] is None
        assert pair.a.request("control.keepalive")["ok"]
        pair.tick("A", 2000000)
        assert pair.summary()["echo"]["rtt_us"] is None
        assert pair.summary()["stop_reason"] == "timeout"
        pair.tick("B", 2000000)
        for role in ("A", "B"):
            assert pair.node(role).request("session.close", run_id=pair.run)["ok"]
        pair.run = str(uuid4())
        pair.session = "0202030405060708"
        pair.prepare()
        accepted = pair.inject("A", pair.reply())
        assert any(row.get("name") == "echo.result" and row["data"]["valid"] for row in accepted)
    finally:
        pair.close()


@pytest.mark.parametrize("protected", [False, True])
def test_duplicate_request_does_not_transmit_a_second_reply(native_library, protected):
    pair = EchoPair(native_library, protected)
    try:
        pair.prepare()
        request = pair.sent("A")
        pair.tx_done("A")
        pair.inject("B", request)
        pair.tick("B", 20000)
        first = pair.sent("B")
        pair.tx_done("B")
        rejected = pair.inject("B", request)
        assert any(
            row.get("name") == "rx.rejected"
            and row["data"]["reason"] == "duplicate"
            and row["data"]["stage"] == "replay"
            for row in rejected
        )
        pair.tick("B", 20001)
        assert pair.sent("B") == first
        assert sum(row.get("name") == "tx.attempt" for row in pair.events["B"]) == 1
    finally:
        pair.close()


@pytest.mark.parametrize("cleanup", ["stop", "lease", "disconnect"])
def test_pending_echo_cleanup_never_becomes_a_sample_or_resumes(native_library, cleanup):
    pair = EchoPair(native_library, True)
    try:
        pair.prepare()
        pair.tx_done("A")
        if cleanup == "stop":
            records = pair.a.send(
                pair.a.command("run.stop", {"reason": "operator"}, run_id=pair.run)
            )
            pair.events["A"].extend(records)
            assert next(row for row in records if row["kind"] == "reply")["ok"]
        elif cleanup == "lease":
            pair.tick("A", 5000001)
        else:
            native_library.node_control_link(pair.a.node, False)
            native_library.node_control_link(pair.a.node, True)
        pair.tick("A")
        if cleanup != "stop":
            pair.a.claim()
        assert pair.a.request("status.get")["result"]["state"] == "idle"
        summaries = [row["data"] for row in pair.events["A"] if row.get("name") == "run.summary"]
        if cleanup != "disconnect":
            assert len(summaries) == 1
            assert not summaries[0]["echo"]["valid"] and summaries[0]["echo"]["rtt_us"] is None
        else:
            assert not summaries  # USB loss discards the unobservable outgoing queue.
        if cleanup == "stop":
            assert pair.summary()["echo"]["rtt_us"] is None
        else:
            assert not pair.a.request("run.summary", run_id=pair.run)["ok"]
            assert [C.sizeof(buffer) for buffer in pair.a.allocations.values()] == [32]
        assert not pair.a.request(
            "run.start", {"config_revision": pair.revisions["A"]}, run_id=pair.run
        )["ok"]
        assert not any(
            row.get("name") == "echo.result" and row["data"]["valid"] for row in pair.events["A"]
        )
    finally:
        pair.close()


@pytest.mark.parametrize("protected,length", [(False, 215), (True, 199)])
def test_echo_uses_single_radio_frame_at_exact_capacity(native_library, protected, length):
    pair = EchoPair(native_library, protected)
    try:
        pair.prepare(length=length, fragment=length)
        assert len(pair.sent("A")) == 255
        reply = pair.reply()
        assert len(reply) == 255
        assert any(
            row.get("name") == "echo.result" and row["data"]["valid"]
            for row in pair.inject("A", reply)
        )
    finally:
        pair.close()


@pytest.mark.parametrize(
    "spec,link",
    [
        ({"message_count": 2}, {}),
        ({"message_bytes": 65}, {"fragment_payload_bytes": 64}),
        ({"security": "aes128_gcm", "message_bytes": 200}, {"fragment_payload_bytes": 200}),
        ({}, {"ack_mode": "stop_wait", "max_retries": 2}),
        ({"message_bytes": 216}, {}),
    ],
)
def test_public_echo_plan_rejects_unbounded_or_unsupported_geometry(spec, link):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        EchoPlan.model_validate({"spec": spec, "link": link})


def test_public_echo_result_refuses_invented_or_inconsistent_latency():
    from pydantic import ValidationError

    from lora_testbed.rf_events_v2 import EchoData

    base = dict(
        session_id=SESSION,
        request_frame_seq=1,
        reply_frame_seq=1,
        payload_bytes=32,
        payload_sha256="a" * 64,
        tx_command_us=100,
        reply_accepted_us=120,
        rtt_us=20,
        valid=True,
        reason="matched",
    )
    assert EchoData.model_validate(base).rtt_us == 20
    for change in (
        {"rtt_us": 21},
        {"tx_command_us": 121},
        {"request_frame_seq": None},
        {"reason": "timeout"},
        {"valid": False},
        {"reply_accepted_us": None},
    ):
        with pytest.raises(ValidationError):
            EchoData.model_validate({**base, **change})
    assert (
        EchoData.model_validate(
            {**base, "valid": False, "reason": "timeout", "rtt_us": None, "reply_accepted_us": None}
        ).rtt_us
        is None
    )


@pytest.mark.parametrize("protected", [False, True])
def test_role_b_can_request_echo_with_its_own_clock(native_library, protected):
    pair = EchoPair(native_library, protected)
    try:
        pair.prepare(direction="B_TO_A")
        request = pair.sent("B")
        assert request[5:7] == bytes([2, 1])
        pair.tx_done("B")
        pair.inject("A", request)
        pair.tick("A", 20000)
        reply = pair.sent("A")
        assert reply[5:7] == bytes([1, 2])
        pair.tx_done("A")
        accepted = pair.inject("B", reply)
        result = next(row["data"] for row in accepted if row.get("name") == "echo.result")
        assert result["valid"] and result["reply_accepted_us"] == pair.b.now()
        assert result["tx_command_us"] > 100000000 and result["rtt_us"] < 100000
        if protected:
            assert AESGCM(KEY_A).decrypt(reply[8:20], reply[40:], reply[:40]) == known_data(
                743, 1, 32
            )
    finally:
        pair.close()


def test_unconfirmed_transmission_produces_no_successful_rtt(native_library):
    pair = EchoPair(native_library, True)
    try:
        pair.prepare()
        pair.tick("A", 1000000)  # No radio TX-done interrupt; finite radio timeout.
        result = next(row["data"] for row in pair.events["A"] if row.get("name") == "echo.result")
        assert result["reason"] == "tx_failed" and not result["valid"]
        assert result["tx_command_us"] is None and result["reply_accepted_us"] is None
        assert result["rtt_us"] is None and pair.summary()["stop_reason"] == "error"
        assert pair.a.request("status.get")["result"]["state"] == "idle"
    finally:
        pair.close()
