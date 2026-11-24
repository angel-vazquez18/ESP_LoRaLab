"""Current OLED observations remain distinct from physical screen qualification."""

from fastapi.testclient import TestClient
from test_node_audio_host import AutoAudio
from test_node_control_native import NativeSerial
from test_node_control_native import native_library as native_library

from lora_testbed.app import create_app


def test_fully_configured_oled_ptt_radio_health_remains_bounded_and_goes_stale_on_disconnect(
    native_library, tmp_path
):
    audio = AutoAudio()
    serial = NativeSerial(
        native_library,
        audio=audio.port,
        ptt=lambda _: False,
        radio=native_library.native_radio_create(),
        display=lambda *_: True,
        display_status=lambda _: 1,
    )
    with TestClient(create_app(data_dir=tmp_path)) as client:
        host = client.app.state.host
        node = host.physical["A"]
        node.opener = lambda _: serial
        client.portal.call(node.connect, "isolated-all-peripherals")
        client.portal.call(node.request, "config.set", {"radio": {}, "link": {}})
        status = client.portal.call(node.request, "status.get")
        assert status["radio"] is not None
        observed = node.snapshot()["display"]
        assert observed["ready"] and observed["fresh"] and not observed["physical_qualified"]
        arm = client.post("/api/nodes/A/audio/ptt", json={"sample_count": 160})
        assert arm.status_code == 202, arm.text
        active = client.portal.call(node.request, "status.get")
        assert active["capability_availability"]["resource_limits"]["oled"]["state"] == "ready"
        stopped = client.post(f"/api/audio/operations/{arm.json()['id']}/stop")
        assert stopped.status_code == 200
        client.portal.call(node.close)
        assert not node.snapshot()["display"]["ready"] and not node.snapshot()["display"]["fresh"]
