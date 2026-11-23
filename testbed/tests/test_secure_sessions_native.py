"""Owned key setup/retirement through the real main-control command boundary."""

import ctypes as C
import json
from uuid import uuid4

import pytest
from test_node_control_native import NativeNode
from test_node_control_native import native_library as native_library


def protected_args(session="0102030405060708", tx="11" * 16, rx="22" * 16):
    return {
        "session_id": session,
        "peer_device_id": "esp-66778899aabb",
        "peer_boot_id": "esp-66778899aabb:1",
        "security": "aes128_gcm",
        "tx_key_hex": tx,
        "rx_key_hex": rx,
    }


def test_close_retires_keys_and_cached_setup_without_echoing_secrets(native_library):
    node = NativeNode(native_library, radio=native_library.native_radio_create())
    try:
        node.claim()
        run = str(uuid4())
        command = node.command("session.open", protected_args(), run_id=run)
        opened = node.send(command)
        assert next(r for r in opened if r["kind"] == "reply")["ok"]
        ready = node.request("status.get")["result"]
        assert ready["security_ready"] and ready["capability_availability"]["security_gcm"]
        blocked = node.request("run.prepare", {"spec": {}, "budget": {}}, run_id=run)
        assert not blocked["ok"] and blocked["error"]["code"] == "INVALID_STATE"
        closed = node.request("session.close", {}, run_id=run)
        assert closed["ok"] and not node.request("status.get")["result"]["security_ready"]
        replay = next(r for r in node.send(command) if r["kind"] == "reply")
        assert not replay["ok"] and replay["error"]["code"] == "COMMAND_EXPIRED"
        new = node.request(
            "session.open",
            protected_args("0102030405060709", "33" * 16, "44" * 16),
            run_id=str(uuid4()),
        )
        assert new["ok"] and node.request("status.get")["result"]["security_ready"]
        saved = json.dumps([opened, ready, closed, replay, new])
        assert all(secret not in saved for secret in ("11" * 16, "22" * 16, "33" * 16, "44" * 16))
    finally:
        node.close()


@pytest.mark.parametrize("ending", ["lease", "disconnect", "stop", "reset"])
def test_ownership_end_or_boot_invalidates_ready_keys_and_old_setup(native_library, ending):
    node = NativeNode(native_library, radio=native_library.native_radio_create())
    try:
        node.claim()
        run = str(uuid4())
        old = node.command("session.open", protected_args(), run_id=run)
        assert next(r for r in node.send(old) if r["kind"] == "reply")["ok"]
        assert node.request("status.get")["result"]["security_ready"]
        if ending == "lease":
            node.tick(5_000_001)
        elif ending == "disconnect":
            native_library.node_control_link(node.node, False)
            native_library.node_control_link(node.node, True)
        elif ending == "stop":
            assert node.request("run.stop", {"reason": "operator"}, run_id=run)["ok"]
        else:
            node.close()
            node = NativeNode(native_library, boot=2, radio=native_library.native_radio_create())
        if ending != "stop":
            node.claim()
        status = node.request("status.get")["result"]
        assert not status["security_ready"]
        reply = next(r for r in node.send(old) if r["kind"] == "reply")
        assert not reply["ok"]
        assert reply["error"]["code"] in ("NOT_OWNER", "COMMAND_EXPIRED", "STALE_BOOT")
        if ending == "stop":
            assert node.request("session.close", {}, run_id=run)["ok"]
        assert node.request(
            "session.open",
            protected_args("0102030405060710", "55" * 16, "66" * 16),
            run_id=str(uuid4()),
        )["ok"]
        assert node.request("status.get")["result"]["security_ready"]
    finally:
        node.close()


def test_no_key_effect_before_owned_correlated_reply_capacity(native_library):
    node = NativeNode(native_library, radio=native_library.native_radio_create())
    try:
        run = str(uuid4())
        assert (
            node.request("session.open", protected_args(), run_id=run)["error"]["code"]
            == "NOT_OWNER"
        )
        node.claim()
        assert not node.request("status.get")["result"]["security_ready"]
        for _ in range(4):
            node.feed(json.dumps(node.command("status.get")).encode() + b"\n")
        opening = node.command("session.open", protected_args(), run_id=run)
        node.feed(json.dumps(opening).encode() + b"\n")
        records = node.drain()
        assert len([r for r in records if r["kind"] == "reply"]) == 4
        assert not node.request("status.get")["result"]["security_ready"]
        # A later sequence has retired that request; a fresh owned setup is required.
        expired = next(r for r in node.send(opening) if r["kind"] == "reply")
        assert not expired["ok"]
        assert node.request("session.open", protected_args(), run_id=run)["ok"]
    finally:
        node.close()


@pytest.mark.parametrize(
    "bad",
    [
        {"tx_key_hex": "11" * 16, "rx_key_hex": "11" * 16},
        {"tx_key_hex": "AA" * 16},
        {"tx_key_hex": "1" * 31},
        {"rx_key_hex": None},
    ],
)
def test_invalid_source_keys_never_become_ready_and_do_not_echo_values(native_library, bad):
    node = NativeNode(native_library, radio=native_library.native_radio_create())
    try:
        node.claim()
        values = {**protected_args(), **bad}
        reply = node.request("session.open", values, run_id=str(uuid4()))
        assert not reply["ok"] and reply["error"]["code"] == "INVALID_ARGUMENT"
        assert not node.request("status.get")["result"]["security_ready"]
        assert all(
            not value or value not in json.dumps(reply)
            for name, value in values.items()
            if name.endswith("key_hex")
        )
        assert node.request("session.open", protected_args(), run_id=str(uuid4()))["ok"]
    finally:
        node.close()


def test_parser_rejection_scrubs_secret_strings_before_json_free(native_library):
    native_library.native_watch_secret.argtypes = [C.c_void_p, C.c_size_t]
    native_library.native_secret_frees.restype = C.c_long
    node = NativeNode(native_library, radio=native_library.native_radio_create())
    key = b"11" * 16  # Public sentinel observed at the deallocation boundary.
    try:
        node.claim()
        native_library.native_watch_secret(C.create_string_buffer(key), len(key))
        run = str(uuid4())
        assert node.request("session.open", protected_args(), run_id=run)["ok"]
        assert node.request("session.close", {}, run_id=run)["ok"]
        assert native_library.native_secret_frees() == 0
        # Duplicate-name rejection happens inside strict_json, before command dispatch.
        node.feed(b'{"tx_key_hex":"' + key + b'","tx_key_hex":"' + key + b'"}\n')
        assert native_library.native_secret_frees() == 0
    finally:
        native_library.native_watch_secret(None, 0)
        node.close()


def test_key_parse_allocation_failures_wipe_and_never_apply_without_a_reply(native_library):
    native_library.native_watch_secret.argtypes = [C.c_void_p, C.c_size_t]
    native_library.native_secret_frees.restype = C.c_long
    key = C.create_string_buffer(b"11" * 16)
    for position in range(160):
        node = NativeNode(native_library, radio=native_library.native_radio_create())
        try:
            node.claim()
            command = node.command("session.open", protected_args(), run_id=str(uuid4()))
            native_library.native_watch_secret(key, 32)
            native_library.native_allocator_fail_after(position)
            node.feed(json.dumps(command).encode() + b"\n")
            native_library.native_allocator_fail_after(-1)
            replies = [r for r in node.drain() if r["kind"] == "reply"]
            ready = node.request("status.get")["result"]["security_ready"]
            assert ready == bool(replies and replies[0]["ok"]), position
            assert native_library.native_secret_frees() == 0, position
        finally:
            native_library.native_allocator_fail_after(-1)
            native_library.native_watch_secret(None, 0)
            node.close()


def test_lease_loss_erases_partial_secret_record_and_discards_its_remainder(native_library):
    node = NativeNode(native_library, radio=native_library.native_radio_create())
    try:
        node.claim()
        assert node.request("session.open", protected_args(), run_id=str(uuid4()))["ok"]
        wire = json.dumps(
            node.command("session.open", protected_args(), run_id=str(uuid4()))
        ).encode()
        split = wire.index(b'"rx_key_hex"')
        node.feed(wire[:split])
        node.tick(5_000_001)
        health = [r["data"] for r in node.drain() if r.get("name") == "health"][-1]
        assert not health["security_ready"]
        assert health["memory"]["buffers"]["serial_rx"] == 0
        node.feed(wire[split:] + b"\n")
        assert not any(r["kind"] == "reply" for r in node.drain())
        node.claim()
        assert node.request(
            "session.open",
            protected_args("0102030405060711", "33" * 16, "44" * 16),
            run_id=str(uuid4()),
        )["ok"]
    finally:
        node.close()
