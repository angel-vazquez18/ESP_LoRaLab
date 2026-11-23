"""Real pinned library geometry and allocation cleanup; no physical ports."""

import subprocess

import pytest
from native_codec2 import build_codec2


def test_real_library_enables_only_3200_and_queries_160_sample_64_bit_frames():
    executable = build_codec2().parent / "codec2_probe"
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "160 64 8"


@pytest.mark.parametrize("failure", range(1, 13))
def test_partial_codec_construction_returns_unavailable_without_leaking(failure):
    executable = build_codec2().parent / "codec2_allocation_probe"
    result = subprocess.run(
        [str(executable), str(failure)], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stdout + result.stderr
