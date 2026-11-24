"""Real radio driver over an injected SPI/GPIO boundary, never a physical port."""

import shutil
import subprocess
import sys

import pytest

from lora_testbed.paths import REPOSITORY_ROOT as ROOT


@pytest.fixture(scope="session")
def radio_fixture(tmp_path_factory):
    compiler = shutil.which("clang") or shutil.which("cc")
    assert compiler, "Radio native checks require a C compiler"
    main = ROOT / "firmware/lora_node/main"
    vendor = main / "radio/vendor/sx126x"
    output = tmp_path_factory.mktemp("radio-driver") / "radio-fixture"
    toolchain = ["xcrun", "--sdk", "macosx", "clang"] if sys.platform == "darwin" else [compiler]
    result = subprocess.run(
        [
            *toolchain,
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-g",
            "-I",
            str(main),
            "-I",
            str(vendor),
            str(main / "radio/node_radio.c"),
            str(vendor / "sx126x.c"),
            str(ROOT / "testbed/tests/native/radio_fixture.c"),
            "-o",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return output


@pytest.mark.parametrize(
    "scenario",
    [
        "initialize",
        "settings",
        "tx",
        "tx_cancel",
        "tx_timeout",
        "tx_irq_timeout",
        "tx_bad_irq",
        "tx_io_failure",
        "busy",
        "absent",
        "command_rejected",
        "io_failure",
        "gpio_failure",
        "unknown_board",
        "stop",
    ],
)
def test_radio_boundary(radio_fixture, scenario):
    result = subprocess.run(
        [str(radio_fixture), scenario], capture_output=True, text=True, timeout=3
    )
    assert result.returncode == 0, result.stdout + result.stderr
