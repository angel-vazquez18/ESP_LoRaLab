"""Read actual committed RAM files and verify their independently reconstructed bytes."""

import base64
import hashlib
import zlib
from uuid import uuid4

import pytest
from test_node_artifacts_native import files, reserve
from test_node_commit_native import upload
from test_node_control_native import native as native
from test_node_control_native import native_library as native_library


def get(node, value, offset=0, length=1024, **updates):
    return node.request(
        "artifact.get",
        {"artifact_id": value["artifact_id"], "offset": offset, "length_bytes": length, **updates},
    )


@pytest.mark.parametrize("length", [1, 2, 3, 1024, 1025, 48000, 131072])
def test_committed_file_roundtrip_has_exact_bytes_hash_partial_chunk_and_eof(native, length):
    native.claim()
    source = bytes(i * 37 % 256 for i in range(length))
    value = upload(native, source)
    assert native.request("artifact.commit", {"artifact_id": value["artifact_id"]})["ok"]
    recovered = bytearray()
    for offset in range(0, length, 1024):
        result = get(native, value, offset)["result"]
        raw = base64.b64decode(result["data_b64"], validate=True)
        assert len(raw) == result["length_bytes"] == min(1024, length - offset)
        assert result["offset"] == offset
        assert result["crc32"] == f"{zlib.crc32(raw):08x}"
        assert result["eof"] is (offset + len(raw) == length)
        recovered.extend(raw)
    assert recovered == source
    assert hashlib.sha256(recovered).hexdigest() == value["sha256"]
    eof = get(native, value, length)["result"]
    assert eof["data_b64"] == "" and eof["length_bytes"] == 0
    assert eof["crc32"] == "00000000" and eof["eof"] is True
    assert files(native)[0]["state"] == "committed"


@pytest.mark.parametrize(
    ("update", "code"),
    [
        ({"offset": 9}, "OFFSET_MISMATCH"),
        ({"offset": -1}, "INVALID_ARGUMENT"),
        ({"offset": True}, "INVALID_ARGUMENT"),
        ({"offset": 0.0}, "INVALID_ARGUMENT"),
        ({"length_bytes": 0}, "INVALID_ARGUMENT"),
        ({"length_bytes": 1025}, "INVALID_ARGUMENT"),
        ({"length_bytes": True}, "INVALID_ARGUMENT"),
        ({"artifact_id": str(uuid4())}, "ARTIFACT_NOT_FOUND"),
        ({"extra": 1}, "INVALID_ARGUMENT"),
    ],
)
def test_invalid_reads_do_not_change_file_and_following_valid_read_succeeds(native, update, code):
    native.claim()
    value = upload(native, b"abcdefgh")
    assert native.request("artifact.commit", {"artifact_id": value["artifact_id"]})["ok"]
    before = files(native)
    assert get(native, value, **update)["error"]["code"] == code
    assert files(native) == before
    assert base64.b64decode(get(native, value)["result"]["data_b64"]) == b"abcdefgh"


def test_unfinished_failed_and_deleted_files_are_never_readable(native):
    native.claim()
    unfinished = reserve(native)
    assert get(native, unfinished)["error"]["code"] == "INVALID_STATE"
    failed = upload(native, b"abcdefgh", sha256="0" * 64)
    assert not native.request("artifact.commit", {"artifact_id": failed["artifact_id"]})["ok"]
    assert get(native, failed)["error"]["code"] == "INVALID_STATE"
    assert native.request("artifact.delete", {"artifact_id": failed["artifact_id"]})["ok"]
    assert get(native, failed)["error"]["code"] == "ARTIFACT_NOT_FOUND"
    complete = upload(native, b"abcdefgh")
    assert native.request("artifact.commit", {"artifact_id": complete["artifact_id"]})["ok"]
    assert get(native, complete)["ok"]
