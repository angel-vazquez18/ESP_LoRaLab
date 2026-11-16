"""Finite audio control against the production C core and an isolated DMA seam."""

import ctypes as C
import struct

import pytest
from test_node_commit_native import upload
from test_node_control_native import (
    AUDIO_POLL,
    AUDIO_START,
    AUDIO_STOP,
    AudioPort,
    AudioProgress,
    NativeNode,
)
from test_node_control_native import native_library as native_library


class AudioFixture:
    def __init__(self):
        self.starts = self.stops = 0
        self.fail_start = False
        self.progress = AudioProgress()
        self.callbacks = [AUDIO_START(self.start), AUDIO_POLL(self.poll), AUDIO_STOP(self.stop)]
        self.port = AudioPort(True, *self.callbacks)

    def start(self, _, source, samples):
        self.starts += 1
        self.source = C.string_at(source, samples * 2)
        self.progress = AudioProgress()
        return not self.fail_start

    def poll(self, _, target):
        target[0] = self.progress

    def stop(self, _):
        self.stops += 1


@pytest.fixture
def audio_node(native_library):
    audio = AudioFixture()
    node = NativeNode(native_library, audio=audio.port)
    node.claim()
    yield node, audio
    node.close()


def pcm_file(node, samples=8000, commit=True, **updates):
    data = struct.pack("<h", 800) * samples
    file = upload(node, data, format="pcm_s16le_8000_mono", **updates)
    if commit:
        assert node.request("artifact.commit", {"artifact_id": file["artifact_id"]})["ok"]
    return file


def result(node):
    return next(r["data"] for r in node.drain() if r.get("name") == "operation.result")


@pytest.mark.parametrize("samples", [1, 128, 129, 24000])
def test_exact_playback_samples_dma_gain_and_duplicate_acceptance(audio_node, samples):
    node, audio = audio_node
    file = pcm_file(node, samples)
    command = node.command("audio.play", {"artifact_id": file["artifact_id"]})
    accepted = node.send(command)[0]
    assert accepted["ok"]
    assert node.send(command)[0] == accepted and audio.starts == 1
    assert node.request("artifact.delete", command["args"])["error"]["code"] == "BUSY"
    audio.progress = AudioProgress(samples, ((samples + 127) // 128) * 128, 0, True, False)
    node.tick()
    event = result(node)
    assert event["status"] == "completed"
    assert event["result"]["samples_completed"] == samples
    assert event["result"]["dma_completed"] and not event["result"]["heard_verified"]
    assert event["result"]["output_gain_denominator"] == 8
    assert event["result"]["hardware_gain_db"] == 6 and audio.stops == 1
    assert node.request("artifact.delete", command["args"])["ok"]


@pytest.mark.parametrize("invalid", ["format", "unfinished", "failed", "odd"])
def test_invalid_audio_never_starts_and_valid_playback_recovers(audio_node, invalid):
    node, audio = audio_node
    if invalid == "odd":
        bad = upload(node, b"a", format="known_data")
    elif invalid == "format":
        bad = upload(node, b"aaaa")
        assert node.request("artifact.commit", {"artifact_id": bad["artifact_id"]})["ok"]
    else:
        bad = pcm_file(
            node, 8, commit=False, **({"sha256": "0" * 64} if invalid == "failed" else {})
        )
        if invalid == "failed":
            assert not node.request("artifact.commit", {"artifact_id": bad["artifact_id"]})["ok"]
    assert not node.request("audio.play", {"artifact_id": bad["artifact_id"]})["ok"]
    assert audio.starts == 0
    good = pcm_file(node, 8)
    assert node.request("audio.play", {"artifact_id": good["artifact_id"]})["ok"]
    assert audio.starts == 1


@pytest.mark.parametrize(
    "reason", ["stop", "lease", "disconnect", "deadline", "driver", "underflow", "short"]
)
def test_audio_cleanup_before_unpin_and_following_playback(audio_node, reason):
    node, audio = audio_node
    file = pcm_file(node)
    args = {"artifact_id": file["artifact_id"]}
    accepted = node.request("audio.play", args)["result"]
    if reason == "stop":
        assert node.request("operation.stop", {"operation_id": accepted["operation_id"]})["ok"]
    elif reason == "lease":
        node.tick(5_000_000)
    elif reason == "disconnect":
        node.lib.node_control_link(node.node, False)
        node.lib.node_control_link(node.node, True)
    elif reason == "deadline":
        for _ in range(31):
            node.request("control.keepalive")
            node.tick(1_000_000)
            node.drain()
    elif reason == "driver":
        node.request("operation.stop", {"operation_id": accepted["operation_id"]})
        audio.fail_start = True
        assert node.request("audio.play", args)["ok"]  # Failure follows acceptance.
        audio.fail_start = False
    else:
        audio.progress = AudioProgress(
            7, 128, int(reason == "underflow"), True, reason == "underflow"
        )
        node.tick()
    assert audio.stops >= 1
    if reason in ("lease", "disconnect"):
        node.claim()
    assert node.request("status.get")["result"]["state"] == "idle"
    assert node.request("audio.play", args)["ok"]


def test_audio_reply_allocation_failure_does_not_start_or_pin(native_library):
    for position in range(80):
        audio = AudioFixture()
        node = NativeNode(native_library, audio=audio.port)
        try:
            node.claim()
            file = pcm_file(node, 8)
            command = node.command("audio.play", {"artifact_id": file["artifact_id"]})
            native_library.native_allocator_fail_after(position)
            records = node.send(command)
            native_library.native_allocator_fail_after(-1)
            accepted = any(r["kind"] == "reply" and r["ok"] for r in records)
            assert audio.starts == int(accepted)
            if accepted:
                node.request(
                    "operation.stop", {"operation_id": records[0]["result"]["operation_id"]}
                )
            assert node.request("artifact.delete", command["args"])["ok"]
        finally:
            native_library.native_allocator_fail_after(-1)
            node.close()


def test_output_conversion_is_explicit_signed_attenuated_and_equal_in_both_slots(native_library):
    values = [-32768, -32767, -9, -8, -7, 0, 7, 8, 9, 32767]
    source = struct.pack("<" + "h" * len(values), *values)
    target = (C.c_int16 * (len(values) * 2))()
    native_library.pcm_output_stereo(source, target, len(values))
    assert list(target) == [int(value / 8) for value in values for _ in range(2)]
