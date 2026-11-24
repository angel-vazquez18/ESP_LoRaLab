"""Authenticated acceptance and once-only insertion through the session owner."""

import ctypes as C
import struct

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from test_session_crypto_native import session_library

INSERT = C.CFUNCTYPE(C.c_bool, C.c_void_p, C.c_void_p, C.c_void_p, C.c_size_t)
KEY_A, KEY_B = bytes(range(16)), bytes(range(16, 32))
SESSION = 0x0102030405060708


def frame(sequence, *, ack=False, body=b"public replay!!!", session=SESSION):
    header = struct.pack(
        ">2sBBBBBBQIIHHIHIH",
        b"LT",
        2,
        1,
        3 if ack else 1,
        1,
        2,
        0,
        session,
        sequence,
        sequence,
        0,
        1,
        len(body),
        len(body),
        0,
        0,
    )
    return header + AESGCM(KEY_A).encrypt(header[8:20], body, header)


def test_replay_window_authenticates_before_committing_and_accepts_unseen_reordering():
    lib = session_library()
    owner = C.c_void_p()
    assert lib.rf_secure_create(SESSION, 2, KEY_B, KEY_A, C.byref(owner)) == 0
    lib.rf_secure_receive.argtypes = [
        C.c_void_p,
        C.c_void_p,
        C.c_size_t,
        C.c_int64,
        C.c_bool,
        C.c_uint32,
        INSERT,
        C.c_void_p,
    ]
    inserted = []
    callback = INSERT(
        lambda _, header, body, length: inserted.append(C.string_at(body, length)) or True
    )

    def receive(raw, now=100, ack=False):
        return lib.rf_secure_receive(owner, raw, len(raw), now, ack, 1000, callback, None)

    try:
        assert receive(frame(1)) == 0
        assert receive(frame(1)) == 2
        assert len(inserted) == 1
        assert receive(frame(130)) == 0
        assert receive(frame(1)) == 3
        assert receive(frame(129)) == 0
        bad = bytearray(frame(131))
        bad[-1] ^= 1
        assert receive(bytes(bad)) == 4
        assert receive(frame(131)) == 0
        assert len(inserted) == 4
        assert receive(frame(4)) == 0  # 127 behind the highest accepted sequence 131.
        assert receive(frame(3)) == 3  # Exactly 128 behind is outside the window.
        assert receive(frame(0xFFFFFFFF)) == 0
        assert receive(frame(0xFFFFFFFF - 127)) == 0
        assert receive(frame(0xFFFFFFFF - 128)) == 3
    finally:
        assert lib.rf_secure_close(C.byref(owner)) == 0


def test_failed_insertion_does_not_consume_sequence_and_exact_retry_has_bounded_reack():
    lib = session_library()
    lib.rf_secure_receive.argtypes = [
        C.c_void_p,
        C.c_void_p,
        C.c_size_t,
        C.c_int64,
        C.c_bool,
        C.c_uint32,
        INSERT,
        C.c_void_p,
    ]
    owner = C.c_void_p()
    assert lib.rf_secure_create(SESSION, 2, KEY_B, KEY_A, C.byref(owner)) == 0
    inserted = []
    allow = False

    def insert(_, header, body, size):
        if not allow:
            return False
        inserted.append(C.string_at(body, size))
        return True

    callback = INSERT(insert)

    def receive(raw, now=100, ack=True):
        return lib.rf_secure_receive(owner, raw, len(raw), now, ack, 1000, callback, None)

    try:
        original = frame(1, ack=True)
        assert receive(original) == 5
        allow = True
        assert receive(original) == 0
        assert receive(original, 200) == 1
        assert len(inserted) == 1
        # Repeating a retry does not extend the first acceptance's horizon.
        assert receive(original, 1099) == 1
        assert receive(original, 1100) == 2
        changed = frame(1, ack=True, body=b"different public")
        assert receive(changed, 300) == 2
        assert receive(original, 300, ack=False) == 2
        for sequence in range(2, 19):
            assert receive(frame(sequence, ack=True), 400) == 0
        assert receive(original, 500) == 2  # Evicted from the 16-frame hash cache.
        assert receive(frame(19, session=SESSION + 1)) == 5
        assert receive(frame(19)) == 0
        assert len(inserted) == 19
    finally:
        assert lib.rf_secure_close(C.byref(owner)) == 0
