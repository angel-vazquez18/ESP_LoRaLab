"""Build the same pinned Codec 2 subset used by ESP-IDF, without physical I/O."""

import platform
import shutil
import subprocess
from functools import lru_cache

from lora_testbed.paths import REPOSITORY_ROOT as ROOT

COMPONENT = ROOT / "firmware/lora_node/components/loralab_codec2"


@lru_cache(maxsize=1)
def build_codec2():
    assert shutil.which("cmake"), "Native codec checks require CMake and a host C compiler"
    subprocess.run(
        ["python3", str(ROOT / "scripts/vendor_codec2.py"), "--check"],
        check=True,
        capture_output=True,
        text=True,
    )
    cache = ROOT / "firmware/lora_node/.cache/native-codec2"
    cache.mkdir(parents=True, exist_ok=True)
    cmake = f'''cmake_minimum_required(VERSION 3.16)
project(loralab_native_codec2 C)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
include("{COMPONENT / "core.cmake"}")
add_library(loralab_codec2 STATIC ${{LORALAB_CODEC2_SOURCES}})
loralab_codec2_configure(loralab_codec2)
add_executable(codec2_probe "{ROOT / "testbed/tests/native/codec2_probe.c"}")
target_include_directories(codec2_probe PRIVATE
    "{COMPONENT / "vendor/src"}" "{COMPONENT / "generated"}")
target_link_libraries(codec2_probe PRIVATE loralab_codec2 m)
if(APPLE)
    target_link_options(codec2_probe PRIVATE -Wl,-dead_strip)
else()
    target_link_options(codec2_probe PRIVATE -Wl,--gc-sections)
endif()
add_library(codec2_fault STATIC ${{LORALAB_CODEC2_SOURCES}})
loralab_codec2_configure(codec2_fault)
target_compile_definitions(codec2_fault PRIVATE
    malloc=codec_test_malloc calloc=codec_test_calloc free=codec_test_free)
add_executable(codec2_allocation_probe "{ROOT / "testbed/tests/native/codec2_allocation_probe.c"}")
target_link_libraries(codec2_allocation_probe PRIVATE codec2_fault m)
if(APPLE)
    target_link_options(codec2_allocation_probe PRIVATE -Wl,-dead_strip)
else()
    target_link_options(codec2_allocation_probe PRIVATE -Wl,--gc-sections)
endif()
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
        for command in [args, ["cmake", "--build", str(cache / "build"), "-j", "4"]]:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=120)
            assert result.returncode == 0, (cache / "build.log").read_text()[-6000:]
    return cache / "build/libloralab_codec2.a"
