"""Run the reservation commands against production C, without opening a board."""

import asyncio
import ctypes as C
import hashlib
import json
import zlib
from copy import deepcopy
from uuid import uuid4

import pytest
from test_node_control_native import ALLOC, FREE, HASH, NativeNode, NativeSerial
from test_node_control_native import native as native
from test_node_control_native import native_library as native_library

from lora_testbed import artifact_contract_v2 as artifacts
from lora_testbed.adapters import require_artifact_compatible
from lora_testbed.nodes import NodeSession


def spec(length=16, **updates):
    return {
        "artifact_id": str(uuid4()),
        "kind": "source",
        "length_bytes": length,
        "sha256": hashlib.sha256(b"a" * min(length, 131072)).hexdigest(),
        "format": "known_data",
        **updates,
    }


def files(node):
    reply = node.request("artifact.list")
    assert reply["ok"], reply
    artifacts.ListResult.model_validate(reply["result"])
    return reply["result"]["artifacts"]


def reserve(node, value=None):
    value = spec() if value is None else value
    reply = node.request("artifact.begin", value)
    assert reply["ok"], reply
    assert reply["result"] == {"artifact_id": value["artifact_id"], "next_offset": 0}
    return value


def test_native_partial_artifact_advertisement_matches_generated_profile(native):
    identity = native.request()["result"]
    native.claim()
    health = native.request("status.get")["result"]
    descriptor = identity["capabilities"]["resource_limits"]["artifact_transfer"]
    assert descriptor == health["capability_availability"]["resource_limits"]["artifact_transfer"]
    assert set(descriptor["commands"]) == {
        "artifact.begin",
        "artifact.list",
        "artifact.delete",
        "artifact.put",
        "artifact.commit",
        "artifact.get",
    }
    assert descriptor["schema_sha256"] == artifacts.schema_digest()
    for name in descriptor["commands"]:
        limits = require_artifact_compatible(identity, name)
        assert limits.max_artifact_bytes == 131072
        assert limits.node_total_artifact_bytes == 262144
        assert limits.node_artifact_slots == 4
    assert not identity["capabilities"]["audio_capture"]
    assert not identity["capabilities"]["audio_playback"]


@pytest.mark.parametrize("slot_bytes", [1, 65536])
def test_four_slots_full_budget_large_list_and_delete_restore_capacity(native, slot_bytes):
    native.claim()
    expected = [reserve(native, spec(slot_bytes)) for _ in range(4)]
    before = files(native)
    assert len(json.dumps(before)) > 1024  # Read replies must bypass the mutation cache size.
    assert [f["artifact_id"] for f in before] == [s["artifact_id"] for s in expected]
    assert all(f["state"] == "uploading" and not f["in_use"] for f in before)
    assert all(f["next_offset"] == 0 for f in before)
    allocations = dict(native.allocations)
    assert native.request("artifact.begin", spec(1))["error"]["code"] == "RESOURCE_LIMIT"
    assert files(native) == before and native.allocations == allocations
    assert sum(C.sizeof(v) for v in native.allocations.values()) == slot_bytes * 4
    status = native.request("status.get")["result"]
    assert status["memory"]["buffers"]["artifacts_reserved"] == slot_bytes * 4
    first = expected[0]["artifact_id"]
    assert native.request("artifact.delete", {"artifact_id": first})["result"]["deleted"] is True
    replacement = reserve(native, spec(slot_bytes))
    assert replacement["artifact_id"] in {f["artifact_id"] for f in files(native)}
    assert len(native.allocations) == 4


def test_byte_budget_rejects_before_slot_count_and_keeps_existing_bytes(native):
    native.claim()
    reserve(native, spec(131072))
    reserve(native, spec(131072))
    before = files(native)
    for buffer in native.allocations.values():
        buffer[0] = b"z"
    assert native.request("artifact.begin", spec(1))["error"]["code"] == "RESOURCE_LIMIT"
    assert files(native) == before
    assert all(buffer[0] == b"z" for buffer in native.allocations.values())
    assert len(native.allocations) == 2


@pytest.mark.parametrize(
    ("update", "code"),
    [
        ({"length_bytes": 131073}, "RESOURCE_LIMIT"),
        ({"length_bytes": 0}, "INVALID_ARGUMENT"),
        ({"length_bytes": -1}, "INVALID_ARGUMENT"),
        ({"length_bytes": True}, "INVALID_ARGUMENT"),
        ({"length_bytes": "16"}, "INVALID_ARGUMENT"),
        ({"length_bytes": 16.0}, "INVALID_ARGUMENT"),
        ({"artifact_id": "invalid"}, "INVALID_ARGUMENT"),
        ({"artifact_id": "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"}, "INVALID_ARGUMENT"),
        ({"sha256": "A" * 64}, "INVALID_ARGUMENT"),
        ({"sha256": "0" * 63}, "INVALID_ARGUMENT"),
        ({"kind": "unknown"}, "INVALID_ARGUMENT"),
        ({"format": "codec2_3200_v1"}, "INVALID_ARGUMENT"),
        ({"format": "pcm_s16le_8000_mono", "length_bytes": 3}, "INVALID_ARGUMENT"),
        ({"format": "pcm_s16le_8000_mono", "length_bytes": 48002}, "INVALID_ARGUMENT"),
        ({"extra": 1}, "INVALID_ARGUMENT"),
    ],
)
def test_invalid_reservation_preserves_existing_file_and_allows_next_valid_one(
    native, update, code
):
    native.claim()
    reserve(native)
    before, allocations = files(native), dict(native.allocations)
    reply = native.request("artifact.begin", spec(**update))
    assert reply["error"]["code"] == code
    assert files(native) == before and native.allocations == allocations
    reserve(native)
    assert len(files(native)) == 2


@pytest.mark.parametrize("length", [2, 48000])
def test_pcm_reservation_manifest_has_exact_sample_metadata(native, length):
    native.claim()
    value = reserve(native, spec(length, kind="recovered", format="pcm_s16le_8000_mono"))
    manifest = files(native)[0]
    assert manifest["kind"] == value["kind"]
    assert manifest["sample_rate_hz"] == 8000 and manifest["sample_count"] == length // 2
    assert manifest["codec"] is None and manifest["frame_count"] is None
    assert manifest["source_artifact_id"] is None


def test_list_and_delete_reject_malformed_arguments_without_mutating_files(native):
    native.claim()
    reserve(native)
    before = files(native)
    for name, args in [
        ("artifact.list", {"unused": 1}),
        ("artifact.delete", {}),
        ("artifact.delete", {"artifact_id": None}),
        ("artifact.delete", {"artifact_id": "invalid"}),
        ("artifact.delete", {"artifact_id": before[0]["artifact_id"], "unused": 1}),
    ]:
        assert native.request(name, args)["error"]["code"] == "INVALID_ARGUMENT"
        assert files(native) == before


def test_buffer_allocation_failure_is_cached_without_reservation_or_leak(native):
    native.claim()
    reserve(native)
    before, allocations = files(native), dict(native.allocations)
    command = native.command("artifact.begin", spec(48000))
    native.allocation_fails = True
    reply = next(r for r in native.send(command) if r["kind"] == "reply")
    assert reply["error"]["code"] == "ALLOCATION_FAILED"
    native.allocation_fails = False
    assert native.send(command)[0] == reply
    assert files(native) == before and native.allocations == allocations
    reserve(native, command["args"])
    assert len(files(native)) == 2


def test_duplicate_begin_delete_and_changed_command_identity_are_safe(native):
    native.claim()
    command = native.command("artifact.begin", spec())
    reply = native.send(command)[0]
    allocations = dict(native.allocations)
    assert native.send(command)[0] == reply
    assert native.allocations == allocations
    changed = deepcopy(command)
    changed["args"]["length_bytes"] = 32
    assert native.send(changed)[0]["error"]["code"] == "COMMAND_CONFLICT"
    assert native.request("artifact.begin", command["args"])["error"]["code"] == "INVALID_STATE"
    delete = native.command("artifact.delete", {"artifact_id": command["args"]["artifact_id"]})
    deleted = native.send(delete)[0]
    assert deleted["ok"] and not native.allocations
    assert native.send(delete)[0] == deleted
    assert (
        native.request("artifact.delete", delete["args"])["error"]["code"] == "ARTIFACT_NOT_FOUND"
    )
    assert files(native) == []
    reserve(native, command["args"])


def test_evicted_reservation_reply_cannot_allocate_again(native):
    native.claim()
    command = native.command("artifact.begin", spec())
    assert native.send(command)[0]["ok"]
    for _ in range(17):
        assert native.request("control.keepalive")["ok"]
    assert native.send(command)[0]["error"]["code"] == "COMMAND_EXPIRED"
    assert len(files(native)) == len(native.allocations) == 1


@pytest.mark.parametrize("name", ["artifact.begin", "artifact.list", "artifact.delete"])
def test_artifact_commands_enforce_owner_boot_and_idle_state(native, name):
    native.claim()
    value = reserve(native)
    args = (
        value
        if name == "artifact.begin"
        else ({"artifact_id": value["artifact_id"]} if name == "artifact.delete" else {})
    )
    before = files(native)
    assert native.request(name, args, client=str(uuid4()))["error"]["code"] == "NOT_OWNER"
    assert (
        native.request(name, args, target_boot_id="esp-001122334455:2")["error"]["code"]
        == "STALE_BOOT"
    )
    operation = native.request(
        "diag.run", {"kind": "memory_probe", "iterations": 10000, "payload_bytes": 512}
    )["result"]
    assert native.request(name, args)["error"]["code"] == "BUSY"
    assert native.request("operation.stop", {"operation_id": operation["operation_id"]})["ok"]
    assert files(native) == before and len(native.allocations) == 1


@pytest.mark.parametrize("reason", ["release", "lease", "disconnect"])
def test_unfinished_reservations_are_released_on_ownership_loss(native, reason):
    native.claim()
    previous = reserve(native, spec(48000))
    if reason == "release":
        assert native.request("control.release")["ok"]
    elif reason == "lease":
        native.tick(5000000)
        native.drain()
    else:
        native.lib.node_control_link(native.node, False)
        native.lib.node_control_link(native.node, True)
    assert not native.allocations
    assert not native.request()["result"]["claimed"]
    native.client = str(uuid4())
    native.claim()
    assert files(native) == []
    assert (
        native.request("artifact.delete", {"artifact_id": previous["artifact_id"]})["error"]["code"]
        == "ARTIFACT_NOT_FOUND"
    )
    reserve(native, previous)


def test_reservation_can_be_associated_with_a_run_without_starting_an_operation(native):
    native.claim()
    run_id = str(uuid4())
    value = spec()
    assert native.request("artifact.begin", value, run_id=run_id)["ok"]
    assert (
        native.request("artifact.list", run_id=run_id)["result"]["artifacts"][0]["artifact_id"]
        == value["artifact_id"]
    )
    assert native.request("status.get")["result"]["operation_id"] is None
    assert native.request("artifact.delete", {"artifact_id": value["artifact_id"]}, run_id=run_id)[
        "ok"
    ]


def test_reboot_destroys_reservations_and_rejects_old_boot_requests(native_library):
    first = NativeNode(native_library)
    first.claim()
    reserve(first)
    command = first.command("artifact.list")
    first.close()
    second = NativeNode(native_library, boot=2)
    try:
        second.claim()
        assert (
            next(r for r in second.send(command) if r["kind"] == "reply")["error"]["code"]
            == "STALE_BOOT"
        )
        assert files(second) == []
    finally:
        second.close()


def test_reply_backpressure_does_not_allocate_until_the_command_can_be_replied_to(native):
    native.claim()
    for _ in range(4):
        native.feed(json.dumps(native.command()).encode() + b"\n")
    command = native.command("artifact.begin", spec())
    wire = json.dumps(command).encode() + b"\n"
    native.feed(wire)
    assert not native.allocations
    native.drain()
    native.feed(wire)
    assert next(r for r in native.drain() if r["kind"] == "reply")["ok"]
    assert len(native.allocations) == 1


def test_json_allocation_failures_never_publish_an_unacknowledged_reservation(native_library):
    accepted = rolled_back = 0
    for position in range(160):
        node = NativeNode(native_library)
        try:
            node.claim()
            original = reserve(node)
            allocations = dict(node.allocations)
            command = node.command("artifact.begin", spec(48000))
            native_library.native_allocator_fail_after(position)
            records = node.send(command)
            native_library.native_allocator_fail_after(-1)
            replies = [r for r in records if r["kind"] == "reply"]
            if replies and replies[0]["ok"]:
                accepted += 1
                assert len(files(node)) == len(node.allocations) == 2
            else:
                rolled_back += 1
                assert [f["artifact_id"] for f in files(node)] == [original["artifact_id"]]
                assert node.allocations == allocations
            assert native_library.native_allocations_live() == 0
        finally:
            native_library.native_allocator_fail_after(-1)
            node.close()
    assert accepted and rolled_back


def test_json_allocation_failures_do_not_delete_before_an_acknowledgement(native_library):
    accepted = rejected = 0
    for position in range(120):
        node = NativeNode(native_library)
        try:
            node.claim()
            value = reserve(node)
            command = node.command("artifact.delete", {"artifact_id": value["artifact_id"]})
            native_library.native_allocator_fail_after(position)
            records = node.send(command)
            native_library.native_allocator_fail_after(-1)
            replies = [r for r in records if r["kind"] == "reply"]
            if replies and replies[0]["ok"]:
                accepted += 1
                assert not files(node) and not node.allocations
            else:
                rejected += 1
                assert files(node)[0]["artifact_id"] == value["artifact_id"]
                assert len(node.allocations) == 1
        finally:
            native_library.native_allocator_fail_after(-1)
            node.close()
    assert accepted and rejected


def test_host_session_uses_real_store_and_rejects_unfinished_reads(native_library):
    async def scenario():
        serial = NativeSerial(native_library)
        session = NodeSession("B", lambda *_: None, lambda _: serial)
        await session.connect("isolated-native-artifacts")
        try:
            value = spec(48000, format="pcm_s16le_8000_mono")
            assert (await session.request("artifact.begin", value))["next_offset"] == 0
            result = await session.request("artifact.list")
            assert result["artifacts"][0]["artifact_id"] == value["artifact_id"]
            assert result["artifacts"][0]["sample_count"] == 24000
            sequence = session.sequence
            with pytest.raises(ValueError, match="INVALID_STATE"):
                await session.request(
                    "artifact.get",
                    {"artifact_id": value["artifact_id"], "offset": 0, "length_bytes": 1},
                )
            assert session.sequence == sequence + 1
            assert (
                await session.request("artifact.delete", {"artifact_id": value["artifact_id"]})
            )["deleted"]
            await session.request("artifact.begin", spec())
        finally:
            await session.close()
        assert serial.closed and not serial.core.allocations

    asyncio.run(scenario())


class StoreSpec(C.Structure):
    _fields_ = [(name, C.c_char_p) for name in ("artifact_id", "kind", "sha256", "format")] + [
        ("length_bytes", C.c_size_t)
    ]


def test_store_consumer_guards_and_lifetimes_after_real_commit(native_library):
    lib = native_library
    lib.artifact_store_create.argtypes = [C.c_void_p, ALLOC, FREE]
    lib.artifact_store_create.restype = C.c_void_p
    lib.artifact_store_destroy.argtypes = [C.c_void_p]
    lib.artifact_store_begin.argtypes = [C.c_void_p, C.c_char_p, C.POINTER(StoreSpec)]
    lib.artifact_store_begin.restype = C.c_int
    lib.artifact_store_delete.argtypes = [C.c_void_p, C.c_char_p]
    lib.artifact_store_delete.restype = C.c_int
    lib.artifact_store_acquire.argtypes = [
        C.c_void_p,
        C.c_char_p,
        C.POINTER(C.c_void_p),
        C.POINTER(C.c_size_t),
    ]
    lib.artifact_store_acquire.restype = C.c_int
    lib.artifact_store_release.argtypes = [C.c_void_p, C.c_char_p]
    lib.artifact_store_release_owner.argtypes = [C.c_void_p, C.c_char_p]
    lib.artifact_store_reserved_bytes.argtypes = [C.c_void_p]
    lib.artifact_store_reserved_bytes.restype = C.c_size_t
    lib.artifact_store_put.argtypes = [
        C.c_void_p,
        C.c_char_p,
        C.c_size_t,
        C.c_void_p,
        C.c_size_t,
        C.c_uint32,
    ]
    lib.artifact_store_prepare_commit.argtypes = [C.c_void_p, C.c_char_p, HASH, C.c_void_p]
    lib.artifact_store_accept_commit.argtypes = [C.c_void_p, C.c_char_p]
    node = NativeNode(lib)
    store = lib.artifact_store_create(None, node.callbacks[3], node.callbacks[4])
    assert store
    owner = str(uuid4()).encode()
    value = spec()
    identity = value["artifact_id"].encode()
    request = StoreSpec(identity, b"source", value["sha256"].encode(), b"known_data", 16)
    try:
        assert lib.artifact_store_begin(store, owner, C.byref(request)) == 0
        pointer, length = C.c_void_p(1), C.c_size_t(1)
        assert lib.artifact_store_acquire(store, identity, C.byref(pointer), C.byref(length)) == 5
        assert pointer.value is None and length.value == 0
        data = C.create_string_buffer(b"a" * 16, 16)
        assert lib.artifact_store_put(store, identity, 0, data, 16, zlib.crc32(data.raw)) == 0
        assert lib.artifact_store_prepare_commit(store, identity, node.callbacks[1], None) == 0
        lib.artifact_store_accept_commit(store, identity)
        assert lib.artifact_store_acquire(store, identity, C.byref(pointer), C.byref(length)) == 0
        assert C.string_at(pointer, length.value) == b"a" * 16
        assert lib.artifact_store_delete(store, identity) == 6
        assert lib.artifact_store_acquire(store, identity, C.byref(pointer), C.byref(length)) == 6
        assert pointer.value is None and length.value == 0
        lib.artifact_store_release_owner(store, owner)
        assert lib.artifact_store_reserved_bytes(store) == 16
        lib.artifact_store_release(store, identity)
        assert lib.artifact_store_delete(store, identity) == 0
        assert lib.artifact_store_reserved_bytes(store) == 0
        assert lib.artifact_store_acquire(store, identity, C.byref(pointer), C.byref(length)) == 4
        assert lib.artifact_store_begin(store, owner, C.byref(request)) == 0
        data = C.create_string_buffer(b"b" * 16, 16)
        assert lib.artifact_store_put(store, identity, 0, data, 16, zlib.crc32(data.raw)) == 0
        assert lib.artifact_store_prepare_commit(store, identity, node.callbacks[1], None) == 8
        lib.artifact_store_accept_commit(store, identity)
        assert lib.artifact_store_acquire(store, identity, C.byref(pointer), C.byref(length)) == 5
        lib.artifact_store_release_owner(store, str(uuid4()).encode())
        assert lib.artifact_store_reserved_bytes(store) == 16
        lib.artifact_store_release_owner(store, owner)
        assert lib.artifact_store_reserved_bytes(store) == 0
        assert not node.allocations
    finally:
        lib.artifact_store_destroy(store)
        node.close()
