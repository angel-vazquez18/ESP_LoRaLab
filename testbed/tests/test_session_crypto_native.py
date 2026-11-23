"""Session key ownership and nonce exhaustion through the public crypto owner."""

import ctypes as C
import json

from native_crypto import load_frame_cipher

from lora_testbed.paths import REPOSITORY_ROOT

FIXTURE = json.loads((REPOSITORY_ROOT / "contracts/v2/security_vectors.json").read_text())


def session_library():
    lib = load_frame_cipher()
    lib.rf_secure_create.argtypes = [
        C.c_uint64,
        C.c_uint8,
        C.c_void_p,
        C.c_void_p,
        C.POINTER(C.c_void_p),
    ]
    lib.rf_secure_reserve.argtypes = [C.c_void_p, C.c_uint32, C.POINTER(C.c_uint32)]
    lib.rf_secure_ready.argtypes = [C.c_void_p]
    lib.rf_secure_ready.restype = C.c_bool
    lib.rf_secure_close.argtypes = [C.POINTER(C.c_void_p)]
    lib.rf_secure_seal.argtypes = [
        C.c_void_p,
        C.c_void_p,
        C.c_void_p,
        C.c_size_t,
        C.c_void_p,
        C.c_size_t,
        C.POINTER(C.c_size_t),
    ]
    lib.rf_secure_open.argtypes = [
        C.c_void_p,
        C.c_void_p,
        C.c_size_t,
        C.c_void_p,
        C.c_size_t,
        C.POINTER(C.c_size_t),
    ]
    return lib


def test_reserved_final_sequence_encrypts_once_and_never_wraps():
    lib = session_library()
    keys = {
        role: C.create_string_buffer(bytes.fromhex(value))
        for role, value in FIXTURE["source_keys_hex"].items()
    }
    owner = C.c_void_p()
    assert lib.rf_secure_create(0x0102030405060708, 1, keys["A"], keys["B"], C.byref(owner)) == 0
    try:
        assert lib.rf_secure_ready(owner)
        first = C.c_uint32()
        assert lib.rf_secure_reserve(owner, 0xFFFFFFFF, C.byref(first)) == 0 and first.value == 1
        v = FIXTURE["vectors"][-1]
        header = C.create_string_buffer(bytes.fromhex(v["header_aad_hex"]))
        body = C.create_string_buffer(bytes.fromhex(v["plaintext_hex"]))
        frame = C.create_string_buffer(255)
        written = C.c_size_t()
        assert lib.rf_secure_seal(owner, header, body, 199, frame, 255, C.byref(written)) == 0
        assert frame.raw[: written.value].hex() == v["frame_hex"]
        assert lib.rf_secure_reserve(owner, 1, C.byref(first)) == 6 and first.value == 0
        assert lib.rf_secure_seal(owner, header, body, 199, frame, 255, C.byref(written)) != 0
        assert written.value == 0
    finally:
        assert lib.rf_secure_close(C.byref(owner)) == 0
        assert not owner.value and not lib.rf_secure_ready(owner)


def test_each_source_owns_its_counter_and_opposite_receive_key():
    lib = session_library()
    keys = {
        role: C.create_string_buffer(bytes.fromhex(key))
        for role, key in FIXTURE["source_keys_hex"].items()
    }
    owners = {role: C.c_void_p() for role in "AB"}
    try:
        for role, number in [("A", 1), ("B", 2)]:
            other = "B" if role == "A" else "A"
            assert (
                lib.rf_secure_create(
                    0x0102030405060708, number, keys[role], keys[other], C.byref(owners[role])
                )
                == 0
            )
        for role, index in [("B", 2), ("A", 0)]:
            other = "B" if role == "A" else "A"
            first = C.c_uint32()
            assert lib.rf_secure_reserve(owners[role], 1, C.byref(first)) == 0 and first.value == 1
            v = FIXTURE["vectors"][index]
            header = C.create_string_buffer(bytes.fromhex(v["header_aad_hex"]))
            body = bytes.fromhex(v["plaintext_hex"])
            frame = C.create_string_buffer(255)
            written = C.c_size_t()
            assert (
                lib.rf_secure_seal(
                    owners[role],
                    header,
                    C.create_string_buffer(body),
                    len(body),
                    frame,
                    255,
                    C.byref(written),
                )
                == 0
            )
            assert frame.raw[: written.value].hex() == v["frame_hex"]
            recovered = C.create_string_buffer(199)
            assert (
                lib.rf_secure_open(
                    owners[other], frame, written.value, recovered, 199, C.byref(written)
                )
                == 0
            )
            assert recovered.raw[: written.value] == body
    finally:
        for owner in owners.values():
            assert lib.rf_secure_close(C.byref(owner)) == 0


def test_failed_output_attempt_burns_sequence_and_binding_rejects_before_encryption():
    lib = session_library()
    owner = C.c_void_p()
    keys = {
        role: C.create_string_buffer(bytes.fromhex(key))
        for role, key in FIXTURE["source_keys_hex"].items()
    }
    assert lib.rf_secure_create(0x0102030405060708, 1, keys["A"], keys["B"], C.byref(owner)) == 0
    try:
        v = FIXTURE["vectors"][0]
        h = bytearray.fromhex(v["header_aad_hex"])
        body = C.create_string_buffer(bytes.fromhex(v["plaintext_hex"]))
        output = C.create_string_buffer(b"Z" * 255, 255)
        written = C.c_size_t(999)
        first = C.c_uint32()
        assert (
            lib.rf_secure_seal(
                owner, C.create_string_buffer(bytes(h)), body, 10, output, 255, C.byref(written)
            )
            == 1
        )
        assert not written.value and output.raw == b"Z" * 255
        assert lib.rf_secure_reserve(owner, 2, C.byref(first)) == 0
        wrong = bytearray(h)
        wrong[8] ^= 1
        assert (
            lib.rf_secure_seal(
                owner, C.create_string_buffer(bytes(wrong)), body, 10, output, 255, C.byref(written)
            )
            == 1
        )
        assert (
            lib.rf_secure_seal(
                owner, C.create_string_buffer(bytes(h)), body, 10, output, 1, C.byref(written)
            )
            == 1
        )
        assert not written.value and output.raw == b"Z" * 255
        assert (
            lib.rf_secure_seal(
                owner, C.create_string_buffer(bytes(h)), body, 10, output, 255, C.byref(written)
            )
            == 1
        )
        h[19] = 2
        assert (
            lib.rf_secure_seal(
                owner, C.create_string_buffer(bytes(h)), body, 10, output, 255, C.byref(written)
            )
            == 0
        )
    finally:
        assert lib.rf_secure_close(C.byref(owner)) == 0


def test_partial_two_key_setup_releases_the_first_import_when_second_has_no_slot():
    lib = session_library()
    keys = {
        role: C.create_string_buffer(bytes.fromhex(key))
        for role, key in FIXTURE["source_keys_hex"].items()
    }
    held = []
    session = C.c_void_p()
    spare = C.c_void_p()
    try:
        for _ in range(256):
            owner = C.c_void_p()
            result = lib.rf_crypto_create(keys["A"], 16, C.byref(owner))
            if result:
                assert result == 5 and not owner.value
                break
            held.append(owner)
        else:
            raise AssertionError("The pinned static native key store should reach a finite limit")
        assert len(held) > 1
        released = held.pop()
        assert lib.rf_crypto_destroy(C.byref(released)) == 0
        # Exactly one slot is free, so the second source import must fail.
        assert (
            lib.rf_secure_create(0x0102030405060708, 1, keys["A"], keys["B"], C.byref(session)) == 5
        )
        assert not session.value
        assert lib.rf_crypto_create(keys["A"], 16, C.byref(spare)) == 0
    finally:
        assert lib.rf_secure_close(C.byref(session)) == 0
        assert lib.rf_crypto_destroy(C.byref(spare)) == 0
        for owner in held:
            assert lib.rf_crypto_destroy(C.byref(owner)) == 0
