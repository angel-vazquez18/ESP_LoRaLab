"""Successful protected setup must emit safe facts before any recording callback."""

import asyncio
import json
from uuid import uuid4

import pytest
from test_node_control_native import NativeSerial
from test_node_control_native import native_library as native_library

from lora_testbed.nodes import NodeSession


def test_protected_setup_never_exposes_keys_to_trace_callbacks(native_library):
    async def scenario():
        peer = NativeSerial(native_library, radio=native_library.native_radio_create())
        node = NodeSession("A", lambda *_: None, lambda _: peer)
        trace = []
        await node.connect("fixture-only-protected-session")
        try:
            reply = await node.request(
                "session.open",
                {
                    "session_id": "0102030405060708",
                    "peer_device_id": "esp-66778899aabb",
                    "peer_boot_id": "esp-66778899aabb:1",
                    "security": "aes128_gcm",
                    "tx_key_hex": "11" * 16,
                    "rx_key_hex": "22" * 16,
                },
                run_id=str(uuid4()),
                on_record=trace.append,
            )
            assert reply["state"] == "idle"
            assert trace and all(s not in json.dumps(trace) for s in ("11" * 16, "22" * 16))
            assert trace[0]["record"]["kind"] == "session.setup"
            assert trace[0]["record"]["key_material_included"] is False
        finally:
            await node.close()

    asyncio.run(scenario())


def test_ephemeral_key_sets_are_independent_and_closed_setup_cannot_be_reused():
    from lora_testbed.session_keys import EphemeralKeySet

    first, second = EphemeralKeySet(), EphemeralKeySet()
    try:
        a = first.arguments("A", "0102030405060708", "esp-66778899aabb", "esp-66778899aabb:1")
        b = first.arguments("B", "0102030405060708", "esp-001122334455", "esp-001122334455:1")
        later = second.arguments("A", "0102030405060709", "esp-66778899aabb", "esp-66778899aabb:1")
        fresh = (
            len({a["tx_key_hex"], a["rx_key_hex"], later["tx_key_hex"], later["rx_key_hex"]}) == 4
        )
        assert fresh, "Fresh independent source/run keys were not generated"
        roles_match = a["tx_key_hex"] == b["rx_key_hex"] and a["rx_key_hex"] == b["tx_key_hex"]
        assert roles_match, "Peer source mapping is inconsistent"
        assert first.key_set_id != second.key_set_id
        assert "tx_key_hex" not in repr(first)
    finally:
        first.close()
        second.close()
    with pytest.raises(ValueError, match="retired"):
        first.arguments("A", "0102030405060708", "esp-66778899aabb", "esp-66778899aabb:1")


def test_node_observation_store_refuses_secret_fields_before_disk_write(tmp_path):
    from lora_testbed.storage import Store

    store = Store(tmp_path)
    sentinel = "11" * 16
    try:
        with pytest.raises(ValueError, match="Secret-bearing"):
            store.append_node_event(
                "A", {"record": {"name": "session.open", "args": {"tx_key_hex": sentinel}}}
            )
        leaked = any(
            sentinel.encode() in path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
        )
        assert not leaked, "A secret-bearing observation reached a file"
    finally:
        store.close()


def test_two_protected_host_runs_use_fresh_keys_and_export_no_key_material(
    tmp_path, native_library
):
    import contextlib
    import io
    import zipfile

    from test_multi_fragment_radio import Pair
    from test_radio_runs import connected_bench

    from lora_testbed.experiments_v2 import Link
    from lora_testbed.radio_runs import RadioRunRequest

    captured = []

    class AuditSerial(NativeSerial):
        def write(self, wire):
            command = json.loads(wire)
            if command["name"] == "session.open" and command["args"]["security"] == "aes128_gcm":
                captured.append(
                    (
                        command["run_id"],
                        bytearray.fromhex(command["args"]["tx_key_hex"]),
                        bytearray.fromhex(command["args"]["rx_key_hex"]),
                    )
                )
            return super().write(wire)

    async def scenario():
        host, serials = await connected_bench(
            tmp_path, native_library, lambda role, **kw: AuditSerial(**kw)
        )
        pair = Pair(host, native_library)
        pair.serials = serials
        bridge = None
        try:
            bridge = asyncio.create_task(pair.bridge())
            identifiers = []
            for _ in range(2):
                started = await host.start_radio(
                    RadioRunRequest(
                        security="aes128_gcm", message_bytes=321, link=Link(ack_mode="stop_wait")
                    )
                )
                async with asyncio.timeout(15):
                    while host.radio.busy:
                        await asyncio.sleep(0.01)
                saved = host.radio.get(started["id"])
                assert saved["status"] == "completed", saved.get("error")
                assert saved["verification"]["bytes_equal"]
                assert saved["security"]["assessment"]["node_reported_authenticated_fragments"] == 3
                assert saved["security"]["assessment"]["receiver_data_arrivals"] == 3
                assert saved["security"]["keys_retired_on_host"] is True
                identifiers.append(saved["security"]["key_set_id"])
                exported = host.radio.export(saved["id"])
                with zipfile.ZipFile(io.BytesIO(exported)) as archive:
                    for name in archive.namelist():
                        if name.endswith((".json", ".ndjson")):
                            text = archive.read(name).decode()
                            assert not any(
                                '"' + field + '": "' in text
                                for field in ("tx_key_hex", "rx_key_hex")
                            )
                assert all(
                    not n.health.security_ready and n.rf_run_id is None
                    for n in host.physical.values()
                )
            assert len(set(identifiers)) == 2
            independent_sources = len({bytes(item[1]) for item in captured})
            assert independent_sources == 4, "Actual source/run key material was reused"
            secrets = [bytes(key) for _, tx, rx in captured for key in (tx, rx)]
            for path in tmp_path.rglob("*"):
                if path.is_file():
                    data = path.read_bytes()
                    absent = all(
                        key not in data and key.hex().encode() not in data.lower()
                        for key in secrets
                    )
                    assert absent, "Run key material reached a saved file"
            for identifier in host.radio.snapshot()["runs"]:
                with zipfile.ZipFile(io.BytesIO(host.radio.export(identifier["id"]))) as archive:
                    for name in archive.namelist():
                        data = archive.read(name)
                        absent = all(
                            key not in data and key.hex().encode() not in data.lower()
                            for key in secrets
                        )
                        assert absent, "Run key material reached an export"
        finally:
            for _, tx, rx in captured:
                for key in (tx, rx):
                    for index in range(len(key)):
                        key[index] = 0
            if bridge:
                bridge.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bridge
            await host.close()

    asyncio.run(scenario())


def test_public_api_rejects_supplied_keys_without_echoing_invalid_values(tmp_path):
    from fastapi.testclient import TestClient

    from lora_testbed.app import create_app

    sentinel = "11" * 16
    with TestClient(create_app(data_dir=tmp_path)) as client:
        response = client.post(
            "/api/radio/preflight", json={"security": "aes128_gcm", "tx_key_hex": sentinel}
        )
        assert response.status_code == 422
        assert sentinel not in response.text


@pytest.mark.parametrize("fault", ["host_config", "receiver_key"])
def test_host_mismatch_and_wrong_key_rf_arrival_remain_distinct(tmp_path, native_library, fault):
    import contextlib

    from test_multi_fragment_radio import Pair
    from test_radio_runs import FaultSerial, connected_bench, finish_run

    from lora_testbed.radio_runs import RadioRunRequest

    class WrongKeySerial(NativeSerial):
        def write(self, wire):
            command = json.loads(wire)
            if command["name"] == "session.open":
                command["args"]["rx_key_hex"] = "33" * 16  # Public test-only fault value.
                wire = json.dumps(command, separators=(",", ":")).encode() + b"\n"
            return super().write(wire)

    async def scenario():
        def factory(role, **kw):
            if fault == "host_config":
                return FaultSerial(bad_config=role == "B", **kw)
            return WrongKeySerial(**kw) if role == "B" else NativeSerial(**kw)

        host, serials = await connected_bench(tmp_path, native_library, factory)
        pair, bridge = Pair(host, native_library), None
        pair.serials = serials
        try:
            bridge = asyncio.create_task(pair.bridge())
            started = await host.start_radio(
                RadioRunRequest(security="aes128_gcm", message_bytes=32)
            )
            await finish_run(host)
            record = host.radio.get(started["id"])
            assert record["status"] == "failed"
            observed = record["security"]["assessment"]
            assert record["security"]["keys_retired_on_host"]
            if fault == "host_config":
                assert observed["classification"] == "host_configuration_rejected_before_rf"
                assert observed["receiver_data_arrivals"] == 0
                assert record["security"]["key_set_id"] is None
                assert not pair.frames
            else:
                assert observed["classification"] == "authentication_rejected_after_rf_arrival"
                assert (
                    observed["receiver_data_arrivals"] > 0
                    and observed["authentication_rejections"] > 0
                )
                assert observed["node_reported_authenticated_fragments"] == 0
            assert record["cleanup"]["confirmed"]
            assert all(not node.health.security_ready for node in host.physical.values())
        finally:
            if bridge:
                bridge.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bridge
            await host.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("action", ["cancel", "disconnect"])
def test_protected_cancel_or_disconnect_closes_peer_before_a_fresh_run(
    tmp_path, native_library, action
):
    import contextlib

    from test_multi_fragment_radio import Pair
    from test_radio_runs import connected_bench, finish_run

    from lora_testbed.experiments_v2 import Link
    from lora_testbed.radio_runs import RadioRunRequest

    async def scenario():
        host, serials = await connected_bench(tmp_path, native_library)
        bridge = None
        try:
            first = await host.start_radio(
                RadioRunRequest(
                    security="aes128_gcm", message_bytes=32, link=Link(ack_mode="stop_wait")
                )
            )
            async with asyncio.timeout(3):
                while host.radio.current and host.radio.current["stage"] != "transmitting":
                    await asyncio.sleep(0.005)
            if action == "cancel":
                await host.radio.stop(first["id"])
            else:
                await host.physical["A"].close(release=False)
                await finish_run(host)
            record = host.radio.get(first["id"])
            assert record["status"] == ("cancelled" if action == "cancel" else "interrupted")
            assert record["security"]["keys_retired_on_host"]
            assert not host.physical["B"].health.security_ready
            assert host.physical["B"].rf_run_id is None
            if action == "disconnect":
                serials["A"] = NativeSerial(
                    native_library, radio=native_library.native_radio_create(), boot=2
                )
                host.physical["A"].opener = lambda _: serials["A"]
                await host.physical["A"].connect("fixture-only-reconnected-A")
            pair = Pair(host, native_library)
            pair.serials = serials
            bridge = asyncio.create_task(pair.bridge())
            second = await host.start_radio(
                RadioRunRequest(security="aes128_gcm", message_bytes=32)
            )
            await finish_run(host)
            fresh = host.radio.get(second["id"])
            assert fresh["status"] == "completed", fresh.get("error")
            assert fresh["verification"]["bytes_equal"]
            assert fresh["security"]["key_set_id"] != record["security"]["key_set_id"]
            assert fresh["session_id"] != record["session_id"]
        finally:
            if bridge:
                bridge.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bridge
            await host.close()

    asyncio.run(scenario())


def test_cancelled_uncertain_protected_setup_closes_attempted_owner_and_retires_keys(
    tmp_path, native_library
):
    import contextlib

    from test_multi_fragment_radio import Pair
    from test_radio_runs import FaultSerial, connected_bench, finish_run

    from lora_testbed.radio_runs import RadioRunRequest

    async def scenario():
        host, serials = await connected_bench(
            tmp_path,
            native_library,
            lambda role, **kw: FaultSerial(
                drop_reply="session.open" if role == "A" else None, **kw
            ),
        )
        bridge = None
        try:
            first = await host.start_radio(RadioRunRequest(security="aes128_gcm", message_bytes=32))
            async with asyncio.timeout(3):
                while not serials["A"].dropped:
                    await asyncio.sleep(0.005)
            await host.radio.stop(first["id"])
            prior = host.radio.get(first["id"])
            assert prior["status"] == "cancelled" and prior["cleanup"]["confirmed"]
            assert prior["security"]["keys_retired_on_host"]
            assert "session.close" in serials["A"].names
            pair = Pair(host, native_library)
            pair.serials = serials
            bridge = asyncio.create_task(pair.bridge())
            second = await host.start_radio(
                RadioRunRequest(security="aes128_gcm", message_bytes=32)
            )
            await finish_run(host)
            fresh = host.radio.get(second["id"])
            assert fresh["status"] == "completed", fresh.get("error")
            assert fresh["security"]["key_set_id"] != prior["security"]["key_set_id"]
        finally:
            if bridge:
                bridge.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bridge
            await host.close()

    asyncio.run(scenario())


def test_key_generation_failure_has_no_key_fallback_or_input_bearing_error(monkeypatch):
    import secrets

    from lora_testbed.session_keys import EphemeralKeySet

    monkeypatch.setattr(secrets, "token_bytes", lambda _: b"\x11" * 16)
    with pytest.raises(ValueError, match="fresh ephemeral") as error:
        EphemeralKeySet()
    assert "11" * 16 not in str(error.value)


@pytest.mark.parametrize("encoded", [False, True, "double"])
def test_persistence_guard_fences_structured_and_serialized_private_commands(encoded):
    from lora_testbed.session_keys import require_public_metadata

    record = {"name": "session.open", "args": {"tx_key_hex": "11" * 16, "rx_key_hex": "22" * 16}}
    if encoded:
        record = json.dumps(record)
    if encoded == "double":
        record = json.dumps(record)
    with pytest.raises(ValueError, match="Secret-bearing"):
        require_public_metadata({"wrapped": record})
    require_public_metadata({"notes": 'The field "tx_key_hex" is excluded', "tx_key_hex": None})


def test_live_two_node_state_refresh_is_bounded_and_tracks_disconnect(tmp_path, native_library):
    from time import monotonic

    from test_radio_runs import connected_bench

    async def scenario():
        host, _ = await connected_bench(tmp_path, native_library)
        try:
            started = monotonic()
            snapshot = host.snapshot()
            elapsed = monotonic() - started
            assert snapshot["connected_node_count"] == 2
            assert elapsed < 1.0, f"Two-node state refresh took {elapsed:.3f} seconds"
            await host.physical["B"].close()
            fresh = host.snapshot()
            assert fresh["connected_node_count"] == 1
            assert not next(n for n in fresh["hardware_nodes"] if n["id"] == "B")["connected"]
        finally:
            await host.close()

    asyncio.run(scenario())
