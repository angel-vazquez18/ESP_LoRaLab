"""Actual file length/hash verification and immutable commit in native C."""

import hashlib

import pytest
from test_node_artifacts_native import files, reserve, spec
from test_node_chunks_native import chunk
from test_node_control_native import NativeNode
from test_node_control_native import native as native
from test_node_control_native import native_library as native_library


def upload(node, data, **updates):
    value = reserve(
        node, spec(len(data), **{"sha256": hashlib.sha256(data).hexdigest(), **updates})
    )
    for offset in range(0, len(data), 1024):
        assert node.request("artifact.put", chunk(value, data[offset : offset + 1024], offset))[
            "ok"
        ]
    return value


@pytest.mark.parametrize("length", [1, 1024, 1025, 48000, 131072])
def test_full_file_commits_with_independent_hash_and_becomes_immutable(native, length):
    native.claim()
    data = bytes(i % 251 for i in range(length))
    value = upload(native, data)
    command = native.command("artifact.commit", {"artifact_id": value["artifact_id"]})
    reply = native.send(command)[0]
    assert reply["ok"]
    manifest = reply["result"]
    assert manifest["state"] == "committed" and manifest["next_offset"] == length
    assert manifest["sha256"] == hashlib.sha256(data).hexdigest()
    assert native.send(command)[0] == reply
    assert native.request("artifact.commit", command["args"])["result"] == manifest
    assert (
        native.request("artifact.put", chunk(value, data[:1]))["error"]["code"] == "INVALID_STATE"
    )
    assert files(native)[0] == manifest


def test_incomplete_commit_leaves_upload_usable_then_completes(native):
    native.claim()
    value = reserve(native, spec(8))
    assert native.request("artifact.put", chunk(value, b"aaaa"))["ok"]
    assert (
        native.request("artifact.commit", {"artifact_id": value["artifact_id"]})["error"]["code"]
        == "INVALID_STATE"
    )
    assert files(native)[0]["state"] == "uploading"
    assert native.request("artifact.put", chunk(value, b"aaaa", 4))["ok"]
    assert (
        native.request("artifact.put", chunk(value, b"a", 8))["error"]["code"] == "OFFSET_MISMATCH"
    )
    assert native.request("artifact.commit", {"artifact_id": value["artifact_id"]})["ok"]


def test_wrong_final_hash_fails_readonly_until_delete_then_new_upload_works(native):
    native.claim()
    value = upload(native, b"abcdefgh", sha256="0" * 64)
    command = native.command("artifact.commit", {"artifact_id": value["artifact_id"]})
    reply = native.send(command)[0]
    assert reply["error"]["code"] == "CHECKSUM_MISMATCH"
    assert native.send(command)[0] == reply
    assert files(native)[0]["state"] == "failed"
    assert native.request("artifact.put", chunk(value, b"a"))["error"]["code"] == "INVALID_STATE"
    assert native.request("artifact.commit", command["args"])["error"]["code"] == "INVALID_STATE"
    assert native.request("artifact.delete", command["args"])["ok"]
    value = upload(native, b"abcdefgh")
    assert native.request("artifact.commit", {"artifact_id": value["artifact_id"]})["ok"]


@pytest.mark.parametrize("wrong_hash", [False, True])
def test_commit_reply_allocation_failures_do_not_publish_transitions(native_library, wrong_hash):
    accepted = dropped = 0
    for position in range(180):
        node = NativeNode(native_library)
        try:
            node.claim()
            updates = {"sha256": "0" * 64} if wrong_hash else {}
            value = upload(node, b"abcdefgh", **updates)
            command = node.command("artifact.commit", {"artifact_id": value["artifact_id"]})
            native_library.native_allocator_fail_after(position)
            records = node.send(command)
            native_library.native_allocator_fail_after(-1)
            replies = [r for r in records if r["kind"] == "reply"]
            if replies:
                accepted += 1
                assert files(node)[0]["state"] == ("failed" if wrong_hash else "committed")
            else:
                dropped += 1
                assert files(node)[0]["state"] == "uploading"
            assert next(iter(node.allocations.values())).raw == b"abcdefgh"
        finally:
            native_library.native_allocator_fail_after(-1)
            node.close()
    assert accepted and dropped


def test_committed_bytes_survive_release_while_unfinished_uploads_do_not(native):
    native.claim()
    committed = upload(native, b"abcdefgh")
    assert native.request("artifact.commit", {"artifact_id": committed["artifact_id"]})["ok"]
    reserve(native)
    assert native.request("control.release")["ok"]
    assert len(native.allocations) == 1
    native.claim()
    assert [f["artifact_id"] for f in files(native)] == [committed["artifact_id"]]
