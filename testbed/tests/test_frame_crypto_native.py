"""Public frame-cipher API linked to the actual pinned IDF PSA implementation."""

import ctypes as C
import json

import pytest
from native_crypto import load_frame_cipher

from lora_testbed.paths import REPOSITORY_ROOT as ROOT

VECTORS = json.loads((ROOT / "contracts/v2/security_vectors.json").read_text())


@pytest.fixture(scope="session")
def frame_cipher():
    return load_frame_cipher()


@pytest.mark.parametrize("v", VECTORS["vectors"], ids=lambda v: v["name"])
def test_actual_psa_cipher_matches_public_frame_and_plaintext(frame_cipher, v):
    key = C.create_string_buffer(bytes.fromhex(VECTORS["source_keys_hex"][v["source_role"]]))
    owner = C.c_void_p()
    assert frame_cipher.rf_crypto_create(key, 16, C.byref(owner)) == 0
    try:
        header = C.create_string_buffer(bytes.fromhex(v["header_aad_hex"]))
        plaintext = C.create_string_buffer(bytes.fromhex(v["plaintext_hex"]))
        output = C.create_string_buffer(255)
        written = C.c_size_t(999)
        assert (
            frame_cipher.rf_crypto_seal(
                owner, header, plaintext, len(plaintext.raw) - 1, output, 255, C.byref(written)
            )
            == 0
        )
        assert output.raw[: written.value].hex() == v["frame_hex"]
        decoded = C.create_string_buffer(199)
        assert (
            frame_cipher.rf_crypto_open(
                owner, output, written.value, decoded, 199, C.byref(written)
            )
            == 0
        )
        assert decoded.raw[: written.value].hex() == v["plaintext_hex"]
    finally:
        assert frame_cipher.rf_crypto_destroy(C.byref(owner)) == 0
        assert not owner.value


def test_changed_frame_bytes_never_modify_plaintext_output_and_next_valid_frame_works(frame_cipher):
    v = VECTORS["vectors"][0]
    key = C.create_string_buffer(bytes.fromhex(VECTORS["source_keys_hex"]["A"]))
    owner = C.c_void_p()
    assert frame_cipher.rf_crypto_create(key, 16, C.byref(owner)) == 0
    frame = bytes.fromhex(v["frame_hex"])
    try:
        for index in range(len(frame)):
            changed = bytearray(frame)
            changed[index] ^= 1
            output = C.create_string_buffer(b"Z" * 199, 199)
            written = C.c_size_t(999)
            result = frame_cipher.rf_crypto_open(
                owner,
                C.create_string_buffer(bytes(changed)),
                len(changed),
                output,
                199,
                C.byref(written),
            )
            assert result in (2, 3), (index, result)
            assert written.value == 0 and output.raw == b"Z" * 199
            valid = C.create_string_buffer(frame)
            assert (
                frame_cipher.rf_crypto_open(owner, valid, len(frame), output, 199, C.byref(written))
                == 0
            )
            assert output.raw[: written.value].hex() == v["plaintext_hex"]
    finally:
        assert frame_cipher.rf_crypto_destroy(C.byref(owner)) == 0


def test_wrong_source_key_rejects_without_output_and_can_verify_its_own_frame(frame_cipher):
    owner = C.c_void_p()
    assert (
        frame_cipher.rf_crypto_create(
            C.create_string_buffer(bytes.fromhex(VECTORS["source_keys_hex"]["B"])),
            16,
            C.byref(owner),
        )
        == 0
    )
    try:
        a = bytes.fromhex(VECTORS["vectors"][0]["frame_hex"])
        output = C.create_string_buffer(b"Q" * 199, 199)
        written = C.c_size_t(999)
        assert (
            frame_cipher.rf_crypto_open(
                owner, C.create_string_buffer(a), len(a), output, 199, C.byref(written)
            )
            == 3
        )
        assert not written.value and output.raw == b"Q" * 199
        b = VECTORS["vectors"][2]
        wire = bytes.fromhex(b["frame_hex"])
        assert (
            frame_cipher.rf_crypto_open(
                owner, C.create_string_buffer(wire), len(wire), output, 199, C.byref(written)
            )
            == 0
        )
        assert output.raw[: written.value].hex() == b["plaintext_hex"]
    finally:
        assert frame_cipher.rf_crypto_destroy(C.byref(owner)) == 0


def test_empty_protected_ack_and_short_output_preflight(frame_cipher):
    v = VECTORS["vectors"][1]
    owner = C.c_void_p()
    assert (
        frame_cipher.rf_crypto_create(
            C.create_string_buffer(bytes.fromhex(VECTORS["source_keys_hex"]["B"])),
            16,
            C.byref(owner),
        )
        == 0
    )
    try:
        output = C.create_string_buffer(b"W" * 255, 255)
        written = C.c_size_t(999)
        header = C.create_string_buffer(bytes.fromhex(v["header_aad_hex"]))
        assert (
            frame_cipher.rf_crypto_seal(owner, header, None, 0, output, 55, C.byref(written)) == 1
        )
        assert not written.value and output.raw == b"W" * 255
        assert (
            frame_cipher.rf_crypto_seal(owner, header, None, 0, output, 56, C.byref(written)) == 0
        )
        assert written.value == 56 and output.raw[:56].hex() == v["frame_hex"]
        assert frame_cipher.rf_crypto_open(owner, output, 56, None, 0, C.byref(written)) == 0
        assert written.value == 0
        for n in (0, 39, 40, 55, 57, 256):
            guarded = C.create_string_buffer(b"D" * 199, 199)
            wire = C.create_string_buffer(output.raw + b"X")
            assert frame_cipher.rf_crypto_open(owner, wire, n, guarded, 199, C.byref(written)) != 0
            assert not written.value and guarded.raw == b"D" * 199
    finally:
        assert frame_cipher.rf_crypto_destroy(C.byref(owner)) == 0


def test_key_size_owner_lifecycle_and_many_imports_do_not_exhaust_key_slots(frame_cipher):
    key = C.create_string_buffer(bytes.fromhex(VECTORS["source_keys_hex"]["A"]))
    owner = C.c_void_p()
    for size in (0, 15, 17, 32):
        assert frame_cipher.rf_crypto_create(key, size, C.byref(owner)) == 1
        assert not owner.value
    assert frame_cipher.rf_crypto_create(None, 16, C.byref(owner)) == 1
    for _ in range(200):
        assert frame_cipher.rf_crypto_create(key, 16, C.byref(owner)) == 0
        original = owner.value
        assert frame_cipher.rf_crypto_create(key, 16, C.byref(owner)) == 1
        assert owner.value == original
        assert frame_cipher.rf_crypto_destroy(C.byref(owner)) == 0
        assert not owner.value
        assert frame_cipher.rf_crypto_destroy(C.byref(owner)) == 0
