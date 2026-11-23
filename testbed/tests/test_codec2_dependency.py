"""Real pinned library geometry and public node metadata; no physical ports."""

import subprocess

import pytest
from native_codec2 import build_codec2
from test_node_control_native import NativeNode
from test_node_control_native import native_library as native_library


def test_node_reports_checked_codec_dependency_without_advertising_unimplemented_operations(
    native_library,
):
    node = NativeNode(native_library)
    try:
        capabilities = node.request("hello")["result"]["capabilities"]
        info = capabilities["resource_limits"]["codec2_library"]
        assert info["version"] == "1.2.0"
        assert info["source_commit"] == "06d4c11e699b0351765f10398abb4f663a984f36"
        assert info["library_ready"]
        assert info["mode"] == 3200
        assert (info["samples_per_frame"], info["bits_per_frame"], info["bytes_per_frame"]) == (
            160,
            64,
            8,
        )
        assert info["sample_rate_hz"] == 8000
        assert not capabilities["codec2_3200"]
    finally:
        node.close()


@pytest.mark.parametrize("mode", [0, 2400])
def test_unavailable_or_unsupported_codec_mode_has_no_working_capability(native_library, mode):
    node = NativeNode(native_library, codec2_mode=mode)
    try:
        capabilities = node.request("hello")["result"]["capabilities"]
        info = capabilities["resource_limits"]["codec2_library"]
        assert not capabilities["codec2_3200"]
        assert not info["library_ready"]
        assert (info["mode"], info["samples_per_frame"], info["bits_per_frame"]) == (0, 0, 0)
    finally:
        node.close()


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
