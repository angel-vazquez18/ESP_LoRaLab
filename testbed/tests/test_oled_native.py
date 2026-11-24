"""OLED receives only bounded views of actual control state, never run content."""

import ctypes as C
from uuid import uuid4

import pytest
from test_node_audio_native import AudioFixture, pcm_file
from test_node_control_native import NativeNode, NodeView
from test_node_control_native import native_library as native_library


def test_oled_follows_ownership_capture_stop_and_last_error_without_rendering_arguments(
    native_library,
):
    views = []

    def post(_, pointer):
        view = pointer.contents
        views.append(
            {
                "state": native_library.node_view_state_name(view.state).decode(),
                "error": bytes(view.error_code).decode(),
                "linked": bool(view.linked),
            }
        )
        return True

    audio = AudioFixture()
    node = NativeNode(native_library, audio=audio.port, display=post)
    try:
        node.tick()
        assert views[-1]["state"] == "UNCLAIMED"
        node.claim()
        node.tick(250_000)
        assert views[-1]["state"] == "CLAIMED"
        accepted = node.request("audio.capture", {"artifact_id": str(uuid4()), "sample_count": 160})
        assert accepted["ok"]
        node.tick(250_000)
        assert views[-1]["state"] == "CAPTURE"
        node.request("operation.stop", {"operation_id": accepted["result"]["operation_id"]})
        node.tick(250_000)
        assert views[-1]["state"] == "CLAIMED"
        node.request(
            "audio.capture", {"artifact_id": "private-content-not-for-display", "sample_count": 160}
        )
        node.tick(250_000)
        assert views[-1]["error"] == "INVALID_ARGUMENT"
        assert "private-content" not in str(views)
        node.lib.node_control_link(node.node, False)
        node.tick(250_000)
        assert views[-1]["state"] == "UNCLAIMED" and not views[-1]["linked"]
    finally:
        node.close()


def test_oled_text_and_bitmap_are_bounded_and_distinguish_current_state_from_last_error(
    native_library,
):
    native_library.node_view_text.argtypes = [C.POINTER(NodeView), C.c_void_p]
    native_library.node_view_bitmap.argtypes = [C.POINTER(NodeView), C.c_void_p]
    view = NodeView(
        state=3,
        role=b"A",
        claimed=True,
        linked=True,
        completed=0,
        total=160,
        uptime_us=1_000_000,
        error_code=b"INVALID_ARGUMENT",
    )
    lines = (C.c_char * (8 * 26))()
    native_library.node_view_text(C.byref(view), lines)
    decoded = [bytes(lines)[i : i + 26].split(b"\0", 1)[0].decode() for i in range(0, 8 * 26, 26)]
    assert decoded[0] == "LORALAB NODE A" and decoded[1] == "CAPTURE"
    assert decoded[2] == "WORK 0/160"
    assert decoded[4:6] == ["RECORDED ERROR", "INVALID_ARGUMENT"]
    assert decoded[7] == "UP 1 S"
    guarded = (C.c_ubyte * 1032)(*([0x55] * 1032))
    native_library.node_view_bitmap(C.byref(view), C.byref(guarded, 4))
    assert list(guarded[:4]) == [0x55] * 4 and list(guarded[-4:]) == [0x55] * 4
    # First glyph L: vertical stroke, then bottom stroke, with one blank column.
    assert bytes(guarded[4:9]) == b"\x7e\x40\x40\x40\x00"


def test_failed_display_sink_reports_fault_but_serial_and_diagnostics_keep_working(native_library):
    posts = []
    node = NativeNode(
        native_library,
        display=lambda _, view: posts.append(view.contents.state) or False,
        display_status=lambda _: 3,
    )
    try:
        node.tick()
        for _ in range(20):
            node.tick(1000)
        assert len(posts) == 1
        node.claim()
        node.tick()
        assert len(posts) == 2  # Ownership changes bypass the progress throttle.
        status = node.request("status.get")["result"]
        assert status["capability_availability"]["resource_limits"]["oled"]["state"] == "io_failed"
        assert not status["capability_availability"]["resource_limits"]["oled"][
            "physical_qualified"
        ]
        started = node.request(
            "diag.run", {"kind": "memory_probe", "iterations": 1, "payload_bytes": 16}
        )
        assert started["ok"]
        for _ in range(3):
            node.tick(1000)
            node.drain()
        assert node.request("status.get")["result"]["state"] == "idle"
    finally:
        node.close()


def test_oled_follows_actual_codec_and_playback_without_sticky_success(native_library):
    states = []
    audio = AudioFixture()
    node = NativeNode(
        native_library,
        audio=audio.port,
        display=lambda _, view: (
            states.append(native_library.node_view_state_name(view.contents.state).decode()) or True
        ),
    )
    try:
        node.claim()
        source = pcm_file(node, 1600)
        encoded_id = str(uuid4())
        assert node.request(
            "audio.encode", {"source_artifact_id": source["artifact_id"], "artifact_id": encoded_id}
        )["ok"]
        node.tick()
        assert states[-1] == "ENCODE"
        for _ in range(10):
            node.tick()
            node.drain()
        assert states[-1] == "CLAIMED"
        decoded = node.request(
            "audio.decode", {"source_artifact_id": encoded_id, "artifact_id": str(uuid4())}
        )
        assert decoded["ok"]
        node.tick()
        assert states[-1] == "DECODE"
        node.request("operation.stop", {"operation_id": decoded["result"]["operation_id"]})
        node.tick()
        assert states[-1] == "CLAIMED"
        played = node.request("audio.play", {"artifact_id": source["artifact_id"]})
        assert played["ok"]
        node.tick()
        assert states[-1] == "PLAY"
        node.request("operation.stop", {"operation_id": played["result"]["operation_id"]})
        node.tick()
        assert states[-1] == "CLAIMED"
    finally:
        node.close()


@pytest.mark.parametrize("sender", [True, False])
def test_oled_follows_actual_rf_direction_and_cancelled_session(native_library, sender):
    from test_rf_execution_native import setup

    from lora_testbed.experiments_v2 import known_data
    from lora_testbed.frames_v2 import data_frame

    states = []
    radio = native_library.native_radio_create()
    node = NativeNode(
        native_library,
        radio=radio,
        display=lambda _, view: (
            states.append(native_library.node_view_state_name(view.contents.state).decode()) or True
        ),
    )
    try:
        run, revision, _ = setup(node, sender=sender, length=321)
        assert states[-1] == "PREPARED"
        action = "run.start" if sender else "run.arm"
        assert node.request(action, {"config_revision": revision}, run_id=run)["ok"]
        node.tick()
        assert states[-1] == ("TX" if sender else "ARMED")
        if not sender:
            payload = known_data(743, 1, 321)
            frame = data_frame("0102030405060708", 1, 1, 0, 3, 321, "B", "A", payload[:160])
            native_library.native_radio_inject(radio, frame, len(frame), 2)
            node.tick()
            assert states[-1] == "RX"
        node.request("session.close", run_id=run)
        node.tick()
        assert states[-1] == "CLAIMED"
    finally:
        node.close()
