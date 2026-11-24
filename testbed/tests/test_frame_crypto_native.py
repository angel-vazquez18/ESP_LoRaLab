"""Public frame-cipher API linked to the actual pinned IDF PSA implementation."""

import ctypes as C
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path

import pytest

from lora_testbed.paths import REPOSITORY_ROOT as ROOT

VECTORS = json.loads((ROOT / "contracts/v2/security_vectors.json").read_text())
MAIN = ROOT / "firmware/lora_node/main"


@pytest.fixture(scope="session")
def frame_cipher():
    dependency = json.loads((MAIN / "security/crypto_dependency.json").read_text())
    idf = Path(os.environ.get("IDF_PATH", Path.home() / ".espressif/v6.0.2/esp-idf"))
    source = idf / "components/mbedtls/mbedtls"
    assert (source / "tf-psa-crypto/CMakeLists.txt").exists(), (
        "Native crypto checks require pinned ESP-IDF v6.0.2 sources; set IDF_PATH."
    )
    commit = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    assert commit == dependency["mbedtls_commit"], "Native crypto source differs from pinned IDF"
    subprocess.run(
        ["git", "-C", str(source), "diff", "--quiet", "HEAD", "--", "tf-psa-crypto"], check=True
    )
    assert shutil.which("cmake"), "Native crypto checks require CMake"
    cache = ROOT / "firmware/lora_node/.cache/native-crypto"
    cache.mkdir(parents=True, exist_ok=True)
    cmake = f'''cmake_minimum_required(VERSION 3.10.2)
project(loralab_native_crypto C)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(ENABLE_PROGRAMS OFF CACHE BOOL "" FORCE)
set(ENABLE_TESTING OFF CACHE BOOL "" FORCE)
set(GEN_FILES OFF CACHE BOOL "" FORCE)
set(TF_PSA_CRYPTO_FATAL_WARNINGS OFF CACHE BOOL "" FORCE)
set(TF_PSA_CRYPTO_CONFIG_FILE
    "{ROOT / "testbed/tests/native/psa_crypto_config.h"}"
    CACHE FILEPATH "" FORCE)
add_subdirectory("{source / "tf-psa-crypto"}" tfpsa)
add_library(frame_crypto SHARED "{MAIN / "security/frame_crypto.c"}")
target_include_directories(frame_crypto PRIVATE "{MAIN}")
target_link_libraries(frame_crypto PRIVATE tfpsacrypto)
target_compile_options(frame_crypto PRIVATE -Wall -Wextra -Werror)
set_target_properties(frame_crypto PROPERTIES PREFIX "" SUFFIX ".so")
'''
    project = cache / "CMakeLists.txt"
    if not project.exists() or project.read_text() != cmake:
        project.write_text(cmake)
    args = ["cmake", "-S", str(cache), "-B", str(cache / "build")]
    if platform.system() == "Darwin":
        args += [
            "-DCMAKE_C_COMPILER="
            + subprocess.check_output(["xcrun", "--find", "clang"], text=True).strip(),
            "-DCMAKE_OSX_SYSROOT="
            + subprocess.check_output(
                ["xcrun", "--sdk", "macosx", "--show-sdk-path"], text=True
            ).strip(),
        ]
    with (cache / "build.log").open("w") as log:
        configured = subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, timeout=60)
        assert configured.returncode == 0, (cache / "build.log").read_text()[-8000:]
        built = subprocess.run(
            ["cmake", "--build", str(cache / "build"), "--target", "frame_crypto", "-j", "4"],
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=180,
        )
        assert built.returncode == 0, (cache / "build.log").read_text()[-8000:]
    lib = C.CDLL(str(cache / "build/frame_crypto.so"))
    lib.rf_crypto_create.argtypes = [C.c_void_p, C.c_size_t, C.POINTER(C.c_void_p)]
    lib.rf_crypto_destroy.argtypes = [C.POINTER(C.c_void_p)]
    lib.rf_crypto_seal.argtypes = [
        C.c_void_p,
        C.c_void_p,
        C.c_void_p,
        C.c_size_t,
        C.c_void_p,
        C.c_size_t,
        C.POINTER(C.c_size_t),
    ]
    lib.rf_crypto_open.argtypes = [
        C.c_void_p,
        C.c_void_p,
        C.c_size_t,
        C.c_void_p,
        C.c_size_t,
        C.POINTER(C.c_size_t),
    ]
    return lib


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
