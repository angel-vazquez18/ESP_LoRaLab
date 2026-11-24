"""C packet bytes and receive validation checked against independent public vectors."""

import ctypes as C
import hashlib
import json

import pytest
from test_node_control_native import HASH
from test_node_control_native import native_library as native_library

from lora_testbed.frames_v2 import data_frame
from lora_testbed.paths import REPOSITORY_ROOT as ROOT


class Receiver(C.Structure):
    _fields_ = (
        [("session", C.c_uint64)]
        + [
            (k, C.c_uint32)
            for k in (
                "seed",
                "message_count",
                "message_bytes",
                "highest_message",
                "highest_sequence",
            )
        ]
        + [("source", C.c_uint8), ("destination", C.c_uint8)]
    )


@pytest.fixture
def frames(native_library):
    lib = native_library
    lib.rf_single_encode.argtypes = [
        C.c_uint64,
        C.c_uint32,
        C.c_uint32,
        C.c_uint8,
        C.c_uint8,
        C.c_void_p,
        C.c_size_t,
        C.c_void_p,
    ]
    lib.rf_single_encode.restype = C.c_size_t
    lib.rf_known_data.argtypes = [HASH, C.c_void_p, C.c_uint32, C.c_uint32, C.c_void_p, C.c_size_t]
    lib.rf_known_data.restype = C.c_bool
    lib.rf_single_accept.argtypes = [
        C.POINTER(Receiver),
        C.c_void_p,
        C.c_size_t,
        C.c_uint32,
        HASH,
        C.c_void_p,
        C.c_void_p,
        C.c_void_p,
    ]
    lib.rf_single_accept.restype = C.c_int
    return lib


@HASH
def sha(_, source, length, target):
    C.memmove(target, hashlib.sha256(C.string_at(source, length)).digest(), 32)
    return True


def test_c_header_and_known_data_match_independent_public_vectors(frames):
    examples = json.loads((ROOT / "contracts/v2/conformance_vectors.json").read_text())
    frame = examples["rf_unprotected"]
    payload = bytes.fromhex(frame["payload_hex"])
    out = C.create_string_buffer(255)
    assert frames.rf_single_encode(0x0102030405060708, 1, 1, 1, 2, payload, len(payload), out) == 50
    assert out.raw[:50].hex() == frame["frame_hex"]
    known = examples["known_data"]
    assert frames.rf_known_data(sha, None, 743, 1, out, 64)
    assert out.raw[:64].hex() == known["payload_hex"]
    assert hashlib.sha256(out.raw[:64]).hexdigest() == known["sha256"]


@pytest.mark.parametrize("length", [1, 159, 160, 215])
def test_single_message_delivers_actual_bytes_once_and_rejects_changed_content(frames, length):
    source = C.create_string_buffer(length)
    assert frames.rf_known_data(sha, None, 743, 1, source, length)
    wire = data_frame("0102030405060708", 1, 1, 0, 1, length, "A", "B", source.raw)
    receiver = Receiver(0x0102030405060708, 743, 1, length, 0, 0, 1, 2)
    output, digest = C.create_string_buffer(215), C.create_string_buffer(32)
    for bad in [
        wire[:-1],
        wire[:8] + b"\0" * 8 + wire[16:],
        wire[:5] + b"\x02\x01" + wire[7:],
        wire[:24] + b"\0\x01" + wire[26:],
        wire[:38] + b"\0\x01" + wire[40:],
        wire[:-1] + bytes([wire[-1] ^ 1]),
    ]:
        assert (
            frames.rf_single_accept(
                C.byref(receiver), bad, len(bad), 215, sha, None, output, digest
            )
            != 0
        )
        assert receiver.highest_message == 0
    assert (
        frames.rf_single_accept(C.byref(receiver), wire, len(wire), 215, sha, None, output, digest)
        == 0
    )
    assert output.raw[:length] == source.raw
    assert digest.raw == hashlib.sha256(source.raw).digest()
    assert (
        frames.rf_single_accept(C.byref(receiver), wire, len(wire), 215, sha, None, output, digest)
        == 1
    )
    assert receiver.highest_message == 1
