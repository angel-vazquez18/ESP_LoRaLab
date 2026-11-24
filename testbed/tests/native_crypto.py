"""Build the actual pinned PSA implementation for shared native firmware checks."""

import ctypes as C
import json
import os
import platform
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from lora_testbed.paths import REPOSITORY_ROOT as ROOT

MAIN = ROOT / "firmware/lora_node/main"


@lru_cache(maxsize=1)
def load_frame_cipher():
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
add_library(frame_crypto SHARED
    "{MAIN / "security/frame_crypto.c"}"
    "{MAIN / "security/session_crypto.c"}")
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
