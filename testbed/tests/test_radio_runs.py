"""Receiver-first workflow against two real C cores with a test-only RF bridge."""

import asyncio
import ctypes as C
import hashlib
import json

import pytest
from test_node_control_native import NativeSerial
from test_node_control_native import native_library as native_library

from lora_testbed.host import Host
from lora_testbed.radio_runs import RadioRunRequest


def test_unconnected_nodes_block_without_starting_a_job(tmp_path):
    async def scenario():
        host = Host(tmp_path)
        try:
            readiness = host.radio.preflight(RadioRunRequest())
            assert not readiness["ready"] and readiness["blockers"]
            with pytest.raises(ValueError, match="disconnected"):
                await host.start_radio(RadioRunRequest())
            assert not host.busy and host.radio.snapshot()["runs"] == []
        finally:
            await host.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("direction", ["A_TO_B", "B_TO_A"])
def test_real_core_pair_runs_receiver_first_with_exact_readback(
    tmp_path, native_library, direction
):
    async def scenario():
        host = Host(tmp_path)
        serials = {}
        for role, device in [("A", "esp-001122334455"), ("B", "esp-66778899aabb")]:
            radio = native_library.native_radio_create()
            serials[role] = NativeSerial(native_library, radio=radio, device=device)
            host.physical[role].opener = lambda _, s=serials[role]: s
            await host.physical[role].connect("isolated-" + role)

        async def bridge():
            source, destination = ("A", "B") if direction == "A_TO_B" else ("B", "A")
            for _ in range(500):
                output = C.create_string_buffer(255)
                with serials[source].lock:
                    length = native_library.native_radio_sent(serials[source].core.radio, output)
                if length:
                    with serials[destination].lock:
                        native_library.native_radio_inject(
                            serials[destination].core.radio, output, length, 2
                        )
                    with serials[source].lock:
                        native_library.native_radio_tx_done(serials[source].core.radio)
                    return
                await asyncio.sleep(0.005)
            raise AssertionError("Sender never submitted an RF frame")

        task = None
        try:
            run = await host.start_radio(RadioRunRequest(direction=direction, message_bytes=159))
            with pytest.raises(RuntimeError, match="owns"):
                await host.start_radio(RadioRunRequest())
            task = asyncio.create_task(bridge())
            async with asyncio.timeout(10):
                while host.radio.busy:
                    await asyncio.sleep(0.01)
            await task
            saved = host.radio.get(run["id"])
            assert saved["status"] == "completed", saved
            assert set(saved["available_content"]) == {"source", "recovered", "wire"}
            assert saved["verification"]["bytes_equal"] and not saved["hardware_qualified"]
            assert len({identity["device_id"] for identity in saved["identities"].values()}) == 2
            assert saved["summaries"][saved["receiver"]]["delivered_messages"] == 1
            wire = [
                json.loads(line)
                for line in host.radio.content(run["id"], "wire").read_text().splitlines()
            ]
            commands = [
                row["record"]["name"] for row in wire if row.get("direction") == "host_to_node"
            ]
            assert commands.index("run.arm") < commands.index("run.start")
            source = host.radio.content(run["id"], "source").read_bytes()
            recovered = host.radio.content(run["id"], "recovered").read_bytes()
            assert source == recovered and len(source) == 159
            import io
            import zipfile

            with zipfile.ZipFile(io.BytesIO(host.radio.export(run["id"]))) as archive:
                hashes = json.loads(archive.read("sha256.json"))
                assert "transfers/A.ndjson" in hashes and "transfers/B.json" in hashes
                assert all(
                    hashlib.sha256(archive.read(name)).hexdigest() == digest
                    for name, digest in hashes.items()
                )
            assert saved["verification"]["sha256"] == hashlib.sha256(recovered).hexdigest()
            assert all(
                node.health.state == "idle" and node.rf_run_id is None
                for node in host.physical.values()
            )
        finally:
            if task and not task.done():
                task.cancel()
            await host.close()

    asyncio.run(scenario())


def test_stop_before_job_task_starts_finishes_and_releases_ownership(tmp_path, native_library):
    async def scenario():
        host = Host(tmp_path)
        for role, device in [("A", "esp-001122334455"), ("B", "esp-66778899aabb")]:
            serial = NativeSerial(
                native_library, radio=native_library.native_radio_create(), device=device
            )
            host.physical[role].opener = lambda _, s=serial: s
            await host.physical[role].connect("isolated-" + role)
        try:
            run = await host.start_radio(RadioRunRequest())
            await host.radio.stop(run["id"])
            assert not host.busy
            assert host.radio.get(run["id"])["status"] == "cancelled"
        finally:
            await host.close()

    asyncio.run(scenario())


class FaultSerial(NativeSerial):
    """Inject faults only at the external serial-byte boundary."""

    def __init__(self, *args, drop_reply=None, drop_event=None, bad_config=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.commands = {}
        self.drop_reply, self.drop_event, self.bad_config = drop_reply, drop_event, bad_config
        self.dropped = False
        self.names = []

    def write(self, wire):
        command = json.loads(wire)
        self.commands[command["command_id"]] = command["name"]
        self.names.append(command["name"])
        return super().write(wire)

    def _pump(self):
        self.core.tick()
        for record in self.core.drain():
            name = self.commands.get(record.get("command_id"))
            if self.drop_reply and name == self.drop_reply and not self.dropped:
                self.dropped = True
                continue
            if self.drop_event and record.get("name") == self.drop_event and not self.dropped:
                self.dropped = True
                continue
            if self.bad_config and name == "config.set" and record["ok"]:
                record["result"]["radio"]["frequency_hz"] = 916000000
            self.queue.put(json.dumps(record).encode() + b"\n")


async def connected_bench(tmp_path, lib, factory=None):
    host = Host(tmp_path)
    serials = {}
    for role, device in [("A", "esp-001122334455"), ("B", "esp-66778899aabb")]:
        radio = lib.native_radio_create()
        serials[role] = (factory or (lambda role, **kw: NativeSerial(**kw)))(
            role, lib=lib, radio=radio, device=device
        )
        host.physical[role].opener = lambda _, s=serials[role]: s
        await host.physical[role].connect("isolated-" + role)
    return host, serials


async def forward_frame(serials, lib, source="A", destination="B"):
    for _ in range(500):
        output = C.create_string_buffer(255)
        with serials[source].lock:
            length = lib.native_radio_sent(serials[source].core.radio, output)
        if length:
            with serials[destination].lock:
                lib.native_radio_inject(serials[destination].core.radio, output, length, 2)
            with serials[source].lock:
                lib.native_radio_tx_done(serials[source].core.radio)
            return
        await asyncio.sleep(0.005)
    raise AssertionError("No RF frame was submitted")


async def finish_run(host):
    async with asyncio.timeout(10):
        while host.radio.busy:
            await asyncio.sleep(0.01)


def test_applied_settings_mismatch_never_arms_either_node(tmp_path, native_library):
    async def scenario():
        host, serials = await connected_bench(
            tmp_path, native_library, lambda role, **kw: FaultSerial(bad_config=role == "B", **kw)
        )
        try:
            run = await host.start_radio(RadioRunRequest())
            await finish_run(host)
            record = host.radio.get(run["id"])
            assert record["status"] == "failed" and "settings differ" in record["error"]
            assert not any("run.arm" in s.names or "run.start" in s.names for s in serials.values())
        finally:
            await host.close()

    asyncio.run(scenario())


def test_missing_observation_is_not_reported_as_radio_loss(tmp_path, native_library):
    async def scenario():
        host, serials = await connected_bench(
            tmp_path,
            native_library,
            lambda role, **kw: FaultSerial(drop_event="rx.frame" if role == "B" else None, **kw),
        )
        task = None
        try:
            run = await host.start_radio(RadioRunRequest())
            task = asyncio.create_task(forward_frame(serials, native_library))
            await finish_run(host)
            await task
            record = host.radio.get(run["id"])
            assert record["status"] == "failed"
            assert record["verification"]["bytes_equal"]
            assert "missing" in record["error"] or "incomplete" in record["error"]
            assert record["cleanup"]["confirmed"]
        finally:
            if task and not task.done():
                task.cancel()
            await host.close()

    asyncio.run(scenario())


def test_cancel_uncertain_session_open_closes_it_before_next_run(tmp_path, native_library):
    async def scenario():
        host, serials = await connected_bench(
            tmp_path,
            native_library,
            lambda role, **kw: FaultSerial(
                drop_reply="session.open" if role == "A" else None, **kw
            ),
        )
        try:
            run = await host.start_radio(RadioRunRequest())
            async with asyncio.timeout(3):
                while not serials["A"].dropped:
                    await asyncio.sleep(0.005)
            await host.radio.stop(run["id"])
            assert host.radio.get(run["id"])["cleanup"]["confirmed"]
            assert "session.close" in serials["A"].names
            second = await host.start_radio(RadioRunRequest())
            task = asyncio.create_task(forward_frame(serials, native_library))
            await finish_run(host)
            await task
            assert host.radio.get(second["id"])["status"] == "completed"
        finally:
            await host.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("action", ["cancel", "timeout", "disconnect", "evidence_failure"])
def test_incomplete_runs_preserve_reason_and_cleanup(tmp_path, native_library, monkeypatch, action):
    async def scenario():
        host, serials = await connected_bench(tmp_path, native_library)
        try:
            run = await host.start_radio(RadioRunRequest(timeout_ms=4000))
            async with asyncio.timeout(3):
                while host.radio.current and host.radio.current["stage"] != "transmitting":
                    await asyncio.sleep(0.005)
            if action == "cancel":
                await host.radio.stop(run["id"])
            elif action == "disconnect":
                await host.physical["B"].close(release=False)
                await finish_run(host)
            elif action == "evidence_failure":
                from pathlib import Path

                original = Path.open

                def fail_trace(path, *args, **kwargs):
                    if path == host.radio.directory / f"{run['id']}.ndjson":
                        raise OSError("fixture evidence write failed")
                    return original(path, *args, **kwargs)

                monkeypatch.setattr(Path, "open", fail_trace)
                await finish_run(host)
            else:
                # Advance only the injected device clock, keeping this deadline test deterministic.
                async with asyncio.timeout(2):
                    while True:
                        frame = C.create_string_buffer(255)
                        with serials["A"].lock:
                            submitted = native_library.native_radio_sent(
                                serials["A"].core.radio, frame
                            )
                        if submitted:
                            break
                        await asyncio.sleep(0.005)
                for serial in serials.values():
                    with serial.lock:
                        serial.core.tick(advance=4_001_000)
                await finish_run(host)
            record = host.radio.get(run["id"])
            assert record["status"] == (
                "cancelled"
                if action == "cancel"
                else "interrupted"
                if action == "disconnect"
                else "failed"
            )
            assert record["error"] and not host.busy and not record["hardware_qualified"]
            if action != "disconnect":
                assert record["cleanup"]["confirmed"], record["cleanup"]
                assert all(
                    node.health.state == "idle" and node.rf_run_id is None
                    for node in host.physical.values()
                )
            assert (
                host.radio.content(run["id"], "wire").stat().st_size > 0
                if action != "evidence_failure"
                else True
            )
        finally:
            await host.close()

    asyncio.run(scenario())


def test_restart_marks_saved_active_radio_interrupted_without_connecting(tmp_path, native_library):
    async def scenario():
        import sqlite3

        host, _ = await connected_bench(tmp_path / "live", native_library)
        backup = tmp_path / "restart"
        backup.mkdir()
        try:
            run = await host.start_radio(RadioRunRequest())
            with sqlite3.connect(backup / "testbed.sqlite3") as destination:
                host.store.db.backup(destination)
            resumed = Host(backup)
            try:
                saved = resumed.radio.get(run["id"])
                assert saved["status"] == "interrupted" and not saved["cleanup"]["confirmed"]
                assert not resumed.busy and not any(n.connected for n in resumed.physical.values())
            finally:
                await resumed.close()
            await host.radio.stop(run["id"])
        finally:
            await host.close()

    asyncio.run(scenario())


def test_radio_http_and_cli_share_the_backend_contract(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from typer.testing import CliRunner

    from lora_testbed import cli
    from lora_testbed.app import create_app

    with TestClient(create_app(data_dir=tmp_path)) as client:
        assert client.post("/api/radio/preflight", json={}).json()["ready"] is False
        assert client.post("/api/radio/runs", json={}).status_code == 400
        assert (
            client.post(
                "/api/radio/runs", json={"link": {"ack_mode": "stop_wait", "max_retries": 3}}
            ).status_code
            == 422
        )
        assert client.get("/api/radio/runs").json()["runs"] == []
        assert client.get("/api/state").json()["radio_runs"]["active_id"] is None
    calls = []
    monkeypatch.setattr(cli, "request", lambda path, body=None: calls.append((path, body)))
    runner = CliRunner()
    assert (
        runner.invoke(
            cli.app, ["radio-start", "--preview", "--direction", "B_TO_A", "--message-bytes", "159"]
        ).exit_code
        == 0
    )
    assert calls == [
        ("/api/radio/preflight", {"direction": "B_TO_A", "message_bytes": 159, "timeout_ms": 10000})
    ]


def test_duplicate_device_identity_blocks_radio_start(tmp_path, native_library):
    async def scenario():
        host, _ = await connected_bench(
            tmp_path,
            native_library,
            lambda role, **kw: NativeSerial(**{**kw, "device": "esp-001122334455"}),
        )
        try:
            ready = host.radio.preflight(RadioRunRequest())
            assert not ready["ready"] and any("distinct" in x for x in ready["blockers"])
            with pytest.raises(ValueError, match="distinct"):
                await host.start_radio(RadioRunRequest())
        finally:
            await host.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel_caller", [False, True])
def test_stop_during_failure_cleanup_waits_for_reserved_serial_write(
    tmp_path, native_library, cancel_caller
):
    import threading

    class HeldCleanup(FaultSerial):
        def __init__(self, *args, hold=False, **kwargs):
            super().__init__(*args, **kwargs)
            self.hold = hold
            self.entered = threading.Event()
            self.release = threading.Event()

        def write(self, wire):
            if self.hold and json.loads(wire)["name"] == "run.stop" and not self.entered.is_set():
                self.entered.set()
                assert self.release.wait(2), "Test did not release the serial boundary"
            return super().write(wire)

    async def scenario():
        host, serials = await connected_bench(
            tmp_path,
            native_library,
            lambda role, **kw: HeldCleanup(
                hold=role == "A", drop_event="run.prepared" if role == "B" else None, **kw
            ),
        )
        try:
            run = await host.start_radio(RadioRunRequest())
            async with asyncio.timeout(2):
                while not serials["A"].entered.is_set():
                    await asyncio.sleep(0.005)
            stopping = asyncio.create_task(host.radio.stop(run["id"]))
            await asyncio.sleep(0)
            if cancel_caller:
                stopping.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await stopping
            serials["A"].release.set()
            if not cancel_caller:
                await stopping
            await finish_run(host)
            record = host.radio.get(run["id"])
            assert record["status"] == "failed" and "preparation evidence" in record["error"]
            assert record["cleanup"]["confirmed"] and not host.busy
        finally:
            serials["A"].release.set()
            await host.close()

    asyncio.run(scenario())


def test_message_maximum_and_cli_bounds_reject_over_limit_before_any_job(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from typer.testing import CliRunner

    from lora_testbed import cli
    from lora_testbed.app import create_app

    with TestClient(create_app(data_dir=tmp_path)) as client:
        assert client.post("/api/radio/runs", json={"message_bytes": 65537}).status_code == 422
        valid = client.post(
            "/api/radio/preflight", json={"message_bytes": 65536, "timeout_ms": 900000}
        )
        assert valid.status_code == 200 and not valid.json()["ready"]
        assert client.get("/api/radio/runs").json()["runs"] == []
    calls = []
    monkeypatch.setattr(cli, "request", lambda path, body=None: calls.append((path, body)))
    runner = CliRunner()
    assert (
        runner.invoke(
            cli.app,
            ["radio-start", "--preview", "--message-bytes", "65536", "--timeout-ms", "900000"],
        ).exit_code
        == 0
    )
    assert calls[-1][1]["message_bytes"] == 65536
    assert runner.invoke(cli.app, ["radio-start", "--message-bytes", "65537"]).exit_code != 0
    assert len(calls) == 1


@pytest.mark.parametrize("older_peer", ["smaller_limits", "missing_fragmentation"])
def test_older_peer_blocks_multi_fragment_work_before_session_or_configuration(
    tmp_path, native_library, older_peer
):
    class OlderPeerSerial(FaultSerial):
        def read(self, count):
            wire = super().read(count)
            if not wire:
                return wire
            record = json.loads(wire)

            def rewrite(value):
                if isinstance(value, dict):
                    if older_peer == "missing_fragmentation" and "fragmentation" in value:
                        value["fragmentation"] = False
                    if older_peer == "smaller_limits" and "execution_limits" in value:
                        value["execution_limits"]["max_message_bytes"] = 160
                        value["execution_limits"]["max_fragments_per_message"] = 1
                    for child in value.values():
                        rewrite(child)
                elif isinstance(value, list):
                    for child in value:
                        rewrite(child)

            rewrite(record)
            return json.dumps(record).encode() + b"\n"

    async def scenario():
        host, serials = await connected_bench(
            tmp_path,
            native_library,
            lambda role, **kw: OlderPeerSerial(**kw) if role == "B" else FaultSerial(**kw),
        )
        try:
            request = RadioRunRequest(message_bytes=321)
            readiness = host.radio.preflight(request)
            expected = "max_message_bytes" if older_peer == "smaller_limits" else "fragmentation"
            assert not readiness["ready"]
            assert any(expected in blocker for blocker in readiness["blockers"])
            with pytest.raises(ValueError, match=expected):
                await host.start_radio(request)
            assert not host.busy and host.radio.snapshot()["runs"] == []
            assert not any(
                name in {"session.open", "config.set", "run.prepare", "run.arm", "run.start"}
                for serial in serials.values()
                for name in serial.names
            )
        finally:
            await host.close()

    asyncio.run(scenario())
