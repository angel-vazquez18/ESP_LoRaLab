"""CRC, byte-position and retry rules against the production firmware core."""

import base64
import zlib
from uuid import uuid4

import pytest
from test_node_artifacts_native import files, reserve, spec
from test_node_control_native import NativeNode
from test_node_control_native import native as native
from test_node_control_native import native_library as native_library


def chunk(value, data, offset=0, **updates):
    return {
        "artifact_id": value["artifact_id"],
        "offset": offset,
        "data_b64": base64.b64encode(data).decode(),
        "crc32": f"{zlib.crc32(data):08x}",
        **updates,
    }


def test_chunks_advance_and_identical_fresh_identity_retries_preserve_cursor(native):
    native.claim()
    value = reserve(native, spec(16))
    first = chunk(value, b"123456789")
    assert first["crc32"] == "cbf43926"
    assert native.request("artifact.put", first)["result"]["next_offset"] == 9
    assert native.request("artifact.put", chunk(value, b"abcd", 9))["result"]["next_offset"] == 13
    before = next(iter(native.allocations.values())).raw
    assert native.request("artifact.put", first)["result"]["next_offset"] == 9
    assert native.request("artifact.put", chunk(value, b"234", 1))["result"]["next_offset"] == 4
    assert files(native)[0]["next_offset"] == 13
    assert next(iter(native.allocations.values())).raw == before
    assert native.request("artifact.put", chunk(value, b"xyz", 13))["result"]["next_offset"] == 16
    assert next(iter(native.allocations.values())).raw == b"123456789abcdxyz"


@pytest.mark.parametrize("length", [1, 1024])
def test_chunk_size_boundaries_and_exact_command_retry(native, length):
    native.claim()
    value = reserve(native, spec(length))
    command = native.command("artifact.put", chunk(value, b"a" * length))
    reply = native.send(command)[0]
    assert reply["ok"] and reply["result"]["next_offset"] == length
    assert native.send(command)[0] == reply
    assert next(iter(native.allocations.values())).raw == b"a" * length


@pytest.mark.parametrize(
    ("update", "code"),
    [
        ({"offset": 3}, "OFFSET_MISMATCH"),
        ({"offset": 8}, "OFFSET_MISMATCH"),
        ({"offset": 7}, "OFFSET_MISMATCH"),
        ({"offset": True}, "INVALID_ARGUMENT"),
        ({"offset": 0.0}, "INVALID_ARGUMENT"),
        ({"offset": -1}, "INVALID_ARGUMENT"),
        ({"crc32": "00000000"}, "CHECKSUM_MISMATCH"),
        ({"crc32": "CBF43926"}, "INVALID_ARGUMENT"),
        ({"data_b64": "YR=="}, "INVALID_ARGUMENT"),
        ({"data_b64": "YQ==\n"}, "INVALID_ARGUMENT"),
        ({"data_b64": "YQ"}, "INVALID_ARGUMENT"),
        ({"data_b64": "===="}, "INVALID_ARGUMENT"),
        ({"data_b64": ""}, "INVALID_ARGUMENT"),
        ({"extra": 1}, "INVALID_ARGUMENT"),
        ({"artifact_id": "invalid"}, "INVALID_ARGUMENT"),
    ],
)
def test_rejected_chunks_leave_bytes_and_offset_unchanged_then_recover(native, update, code):
    native.claim()
    value = reserve(native, spec(8))
    before = next(iter(native.allocations.values())).raw
    assert native.request("artifact.put", chunk(value, b"ab", **update))["error"]["code"] == code
    assert files(native)[0]["next_offset"] == 0
    assert next(iter(native.allocations.values())).raw == before
    assert native.request("artifact.put", chunk(value, b"abcdefgh"))["ok"]


def test_conflicting_repeat_partial_overlap_gap_unknown_and_oversize_are_rejected(native):
    native.claim()
    value = reserve(native, spec(2048))
    assert native.request("artifact.put", chunk(value, b"abcd"))["ok"]
    before = next(iter(native.allocations.values())).raw
    for args, error in [
        (chunk(value, b"axcd"), "OFFSET_MISMATCH"),
        (chunk(value, b"cdef", 2), "OFFSET_MISMATCH"),
        (chunk(value, b"e", 5), "OFFSET_MISMATCH"),
        (chunk(value, b"x" * 1025, 4), "INVALID_ARGUMENT"),
        (chunk(value, b"e", 4, artifact_id=str(uuid4())), "ARTIFACT_NOT_FOUND"),
    ]:
        assert native.request("artifact.put", args)["error"]["code"] == error
        assert files(native)[0]["next_offset"] == 4
        assert next(iter(native.allocations.values())).raw == before
    assert native.request("artifact.put", chunk(value, b"e", 4))["ok"]


def test_chunk_json_reply_allocation_failures_do_not_write_or_advance(native_library):
    passed = rejected = 0
    for position in range(160):
        node = NativeNode(native_library)
        try:
            node.claim()
            value = reserve(node, spec(16))
            buffer = next(iter(node.allocations.values()))
            before = buffer.raw
            command = node.command("artifact.put", chunk(value, b"123456789"))
            native_library.native_allocator_fail_after(position)
            records = node.send(command)
            native_library.native_allocator_fail_after(-1)
            replies = [r for r in records if r["kind"] == "reply"]
            if replies and replies[0]["ok"]:
                passed += 1
                assert files(node)[0]["next_offset"] == 9
                assert buffer.raw[:9] == b"123456789"
            else:
                rejected += 1
                assert files(node)[0]["next_offset"] == 0 and buffer.raw == before
                assert node.request("artifact.put", command["args"])["ok"]
        finally:
            native_library.native_allocator_fail_after(-1)
            node.close()
    assert passed and rejected
