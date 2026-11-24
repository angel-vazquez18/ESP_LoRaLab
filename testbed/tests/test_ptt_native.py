"""Host-armed finite input through the production serial/control and GPIO seams."""

import ctypes as C
from uuid import uuid4

import pytest
from test_node_audio_native import AudioFixture, result
from test_node_control_native import AudioProgress, NativeNode
from test_node_control_native import native_library as native_library


def test_bounced_press_starts_exactly_one_host_selected_finite_capture(native_library):
    pressed = False
    audio = AudioFixture()
    node = NativeNode(native_library, audio=audio.port, ptt=lambda _: pressed)
    try:
        node.claim()
        artifact_id = str(uuid4())
        command = node.command("ptt.arm", {"artifact_id": artifact_id, "sample_count": 160})
        accepted = node.send(command)[0]
        assert accepted["ok"]
        assert node.send(command)[0] == accepted
        assert audio.starts == 0
        node.tick(50_000)  # Release must be stable after arm.
        for level in (True, False, True, False, True):
            pressed = level
            node.tick(5_000)
        node.tick(49_999)
        assert audio.starts == 0
        node.tick(1)
        assert audio.starts == 1 and audio.capture and audio.target == 160
        C.memmove(audio.destination, b"\x00\x08" * 160, 320)
        audio.progress = AudioProgress(160, 4960, 0, True, False)
        node.tick()
        terminal = result(node)
        assert terminal["operation_id"] == accepted["result"]["operation_id"]
        assert terminal["status"] == "completed"
        assert terminal["result"]["artifact"]["artifact_id"] == artifact_id
        for _ in range(3):
            node.tick(50_000)
        assert audio.starts == 1
        assert node.send(command)[0] == accepted
        node.tick(50_000)
        assert audio.starts == 1
        assert node.request("status.get")["result"]["state"] == "idle"
    finally:
        node.close()


@pytest.mark.parametrize("state", ["disabled", "no_microphone", "unowned", "busy"])
def test_unavailable_unowned_and_busy_buttons_cannot_start_capture(native_library, state):
    pressed = True
    audio = AudioFixture()
    if state == "no_microphone":
        audio.port.capture = False
    node = NativeNode(
        native_library, audio=audio.port, ptt=None if state == "disabled" else lambda _: pressed
    )
    try:
        if state != "unowned":
            node.claim()
        if state == "busy":
            assert node.request(
                "audio.capture", {"artifact_id": str(uuid4()), "sample_count": 160}
            )["ok"]
        initial = audio.starts
        rejected = node.request("ptt.arm", {"artifact_id": str(uuid4()), "sample_count": 160})
        expected = {
            "disabled": "MISSING_CAPABILITY",
            "no_microphone": "MISSING_CAPABILITY",
            "unowned": "NOT_OWNER",
            "busy": "BUSY",
        }[state]
        assert not rejected["ok"] and rejected["error"]["code"] == expected
        for value in (False, True, False, True):
            pressed = value
            node.tick(100_000)
        assert audio.starts == initial
    finally:
        node.close()


@pytest.mark.parametrize("reason", ["stop", "lease", "disconnect", "deadline"])
def test_stop_and_ownership_loss_retire_pending_press_and_require_new_release(
    native_library, reason
):
    pressed = False
    audio = AudioFixture()
    node = NativeNode(native_library, audio=audio.port, ptt=lambda _: pressed)
    try:
        node.claim()
        armed = node.request("ptt.arm", {"artifact_id": str(uuid4()), "sample_count": 160})
        assert armed["ok"]
        node.tick(50_000)
        pressed = True
        node.tick()
        node.tick(49_999)
        assert audio.starts == 0
        if reason == "stop":
            node.request("operation.stop", {"operation_id": armed["result"]["operation_id"]})
        elif reason == "lease":
            node.tick(5_000_000)
        elif reason == "disconnect":
            node.lib.node_control_link(node.node, False)
            node.lib.node_control_link(node.node, True)
        else:
            # Keep ownership but do not finish the pending debounce during the wait.
            pressed = False
            for _ in range(31):
                node.request("control.keepalive")
                node.tick(1_000_000)
                node.drain()
            pressed = True
        node.tick(1)
        assert audio.starts == 0 and audio.stops == 0  # No DMA existed to stop.
        if reason in ("lease", "disconnect"):
            node.claim()
        assert node.request("artifact.list")["result"]["artifacts"] == []
        assert node.request("ptt.arm", {"artifact_id": str(uuid4()), "sample_count": 160})["ok"]
        node.tick(100_000)
        assert audio.starts == 0
        pressed = False
        node.tick()
        node.tick(50_000)
        pressed = True
        node.tick()
        node.tick(50_000)
        assert audio.starts == 1
    finally:
        node.close()


def test_driver_failure_and_reply_allocation_failures_never_leave_an_armed_capture(native_library):
    for position in range(80):
        button = [False]
        audio = AudioFixture()
        node = NativeNode(native_library, audio=audio.port, ptt=lambda _, button=button: button[0])
        try:
            node.claim()
            command = node.command("ptt.arm", {"artifact_id": str(uuid4()), "sample_count": 160})
            native_library.native_allocator_fail_after(position)
            records = node.send(command)
            native_library.native_allocator_fail_after(-1)
            accepted = next((r for r in records if r["kind"] == "reply" and r["ok"]), None)
            assert audio.starts == 0
            if accepted:
                node.request("operation.stop", {"operation_id": accepted["result"]["operation_id"]})
            assert node.request("artifact.list")["result"]["artifacts"] == []
            assert node.request("ptt.arm", {"artifact_id": str(uuid4()), "sample_count": 160})["ok"]
            node.tick(50_000)
            audio.fail_start = True
            button[0] = True
            node.tick()
            node.tick(50_000)
            terminal = result(node)
            assert terminal["status"] == "failed"
            assert node.request("artifact.list")["result"]["artifacts"] == []
            audio.fail_start = False
            assert node.request("ptt.arm", {"artifact_id": str(uuid4()), "sample_count": 160})["ok"]
            button[0] = False
            node.tick()
            node.tick(50_000)
            button[0] = True
            node.tick()
            node.tick(50_000)
            audio.progress = AudioProgress(160, 4960, 0, True, False)
            node.tick()
            assert result(node)["status"] == "completed"
        finally:
            native_library.native_allocator_fail_after(-1)
            node.close()


@pytest.mark.parametrize("value", [0, 24001, True, 1.5, "160"])
def test_invalid_ptt_geometry_has_no_reservation_or_button_effect(native_library, value):
    audio = AudioFixture()
    node = NativeNode(native_library, audio=audio.port, ptt=lambda _: True)
    try:
        node.claim()
        response = node.request("ptt.arm", {"artifact_id": str(uuid4()), "sample_count": value})
        assert not response["ok"] and response["error"]["code"] == "INVALID_ARGUMENT"
        assert node.request("artifact.list")["result"]["artifacts"] == []
        node.tick(100_000)
        assert audio.starts == 0
    finally:
        node.close()
