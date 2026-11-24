"""Real pinned library geometry and public node metadata; no physical ports."""

import subprocess

import pytest
from native_codec2 import build_codec2
from test_node_control_native import NativeNode
from test_node_control_native import native_library as native_library


def test_node_reports_checked_codec_dependency_and_only_implemented_operations(
    native_library,
):
    node = NativeNode(native_library)
    try:
        capabilities = node.request("hello")["result"]["capabilities"]
        info = (
            capabilities["resource_limits"].get("codec_io")
            or capabilities["resource_limits"]["codec2_library"]
        )
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
        assert capabilities["codec2_3200"]
        assert capabilities["resource_limits"]["codec_io"]["commands"] == ["audio.encode"]
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


def test_configured_audio_radio_health_remains_bounded_after_an_error(native_library):
    from uuid import uuid4

    from test_node_audio_native import AudioFixture

    audio = AudioFixture()
    node = NativeNode(native_library, audio=audio.port, radio=native_library.native_radio_create())
    try:
        hello = node.request("hello")["result"]
        assert hello["capabilities"]["resource_limits"]["codec_io"]["library_ready"]
        assert hello["capabilities"]["resource_limits"]["max_record_bytes"] == 4096
        node.claim()
        assert node.request("config.set", {"radio": {"spreading_factor": 12}, "link": {}})["ok"]
        rejected = node.request("run.start", {"config_revision": 1}, run_id=str(uuid4()))
        assert rejected["error"]["code"] == "INVALID_STATE"
        status = node.request("status.get")["result"]
        assert status["capability_availability"]["radio"]
        assert status["capability_availability"]["audio_capture"]
        assert status["last_error"]["code"] == "INVALID_STATE"
        assert "codec2_library" not in status["capability_availability"]["resource_limits"]
        node.tick(1000000)
        assert any(r.get("name") == "health" for r in node.drain())
    finally:
        node.close()
