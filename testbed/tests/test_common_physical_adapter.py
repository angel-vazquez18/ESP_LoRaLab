"""Production physical adapter boundaries over real native serial peers."""

import asyncio

import pytest
from test_node_control_native import NativeSerial
from test_node_control_native import native_library as native_library

from lora_testbed.nodes import NodeSession


def test_reconnect_with_same_device_and_boot_invalidates_previous_work_binding(native_library):
    from lora_testbed.physical_adapter import PhysicalAdapter

    async def scenario():
        serials = []

        def open_serial(_):
            serial = NativeSerial(native_library)
            serials.append(serial)
            return serial

        node = NodeSession("A", lambda *_: None, open_serial)
        adapter = PhysicalAdapter({"A": node})
        try:
            await node.connect("isolated-adapter")
            binding = adapter.bind("A")
            assert (await adapter.request(binding, "status.get"))["state"] == "idle"
            await node.close()
            await node.connect("isolated-adapter")
            assert node.identity.boot_id == binding["boot_id"]
            with pytest.raises(ValueError, match="connection|reconnect"):
                await adapter.request(binding, "status.get")
            result = await adapter.cleanup(binding)
            assert not result["confirmed"]
            assert node.connected  # Cleanup of old work cannot close this fresh connection.
            fresh = adapter.bind("A")
            assert fresh["connection_id"] != binding["connection_id"]
            assert (await adapter.request(fresh, "status.get"))["state"] == "idle"
        finally:
            await node.close()
        assert all(serial.closed for serial in serials)

    asyncio.run(scenario())


def test_cleanup_attempts_session_close_after_failed_stop_and_keeps_the_error(native_library):
    import json
    from uuid import uuid4

    from lora_testbed.physical_adapter import PhysicalAdapter

    class StopReplyFailure(NativeSerial):
        def __init__(self):
            super().__init__(native_library, radio=native_library.native_radio_create())
            self.commands = {}
            self.stop_failed = False

        def write(self, wire):
            command = json.loads(wire)
            self.commands[command["command_id"]] = command["name"]
            return super().write(wire)

        def _pump(self):
            self.core.tick()
            for record in self.core.drain():
                if (
                    self.commands.get(record.get("command_id")) == "run.stop"
                    and not self.stop_failed
                ):
                    self.stop_failed = True
                    record.update(
                        ok=False,
                        result=None,
                        error={
                            "code": "INTERNAL_ERROR",
                            "message": "Injected stop reply failure",
                            "field": None,
                            "retryable": False,
                        },
                    )
                self.queue.put(json.dumps(record).encode() + b"\n")

    async def scenario():
        serial = StopReplyFailure()
        node = NodeSession("A", lambda *_: None, lambda _: serial)
        adapter = PhysicalAdapter({"A": node})
        try:
            await node.connect("isolated-cleanup")
            binding = adapter.bind("A")
            run = str(uuid4())
            await adapter.request(
                binding,
                "session.open",
                {
                    "session_id": "0102030405060708",
                    "peer_device_id": "esp-66778899aabb",
                    "peer_boot_id": "esp-66778899aabb:1",
                    "security": "none",
                    "tx_key_hex": None,
                    "rx_key_hex": None,
                },
                run_id=run,
            )
            result = await adapter.cleanup(binding, run_id=run)
            assert result["confirmed"] and node.connected and node.rf_run_id is None
            assert any(error["command"] == "run.stop" for error in result["errors"])
            assert "session closed" in result["steps"]
            assert (await adapter.request(binding, "status.get"))["state"] == "idle"
        finally:
            await node.close()

    asyncio.run(scenario())


def test_failed_audio_readback_keeps_committed_capture_for_explicit_recovery(
    native_library, tmp_path
):
    from test_artifact_transfers import finished
    from test_node_audio_host import audio_bench

    async def scenario():
        async with audio_bench(native_library, tmp_path) as (host, serial):
            serial.corruption = "crc"
            started = await host.audio_action("A", "capture", sample_count=160)
            record = await finished(host.audio, started["id"])
            assert record["status"] == "failed" and record["clip"] is None
            assert "checksum" in record["error"].lower() or "crc" in record["error"].lower()
            serial.corruption = None
            files = (await host.physical["A"].request("artifact.list"))["artifacts"]
            assert any(
                file["artifact_id"] == record["artifact_id"] and file["state"] == "committed"
                for file in files
            )
            assert record["retained_capture"]["artifact_id"] == record["artifact_id"]
            assert record["cleanup_details"]["confirmed"] and not host.busy
            recovered = await host.audio_action("A", "retrieve", artifact_id=record["artifact_id"])
            assert (await finished(host.audio, recovered["id"]))["status"] == "completed"

    asyncio.run(scenario())


def test_diagnostic_job_has_bound_identity_terminal_summary_and_idle_cleanup(
    native_library, tmp_path
):
    from lora_testbed.host import Host

    async def scenario():
        host = Host(tmp_path)
        serial = NativeSerial(native_library)
        host.physical["A"].opener = lambda _: serial
        try:
            await host.physical["A"].connect("isolated-diagnostic-job")
            accepted = await host.memory_probe("A", 2, 1024)
            assert accepted["host_run_id"]
            async with asyncio.timeout(5):
                while host.busy:
                    await asyncio.sleep(0.01)
            record = host.diagnostics.get(accepted["host_run_id"])
            assert record["status"] == "completed" and record["cleanup"]["confirmed"]
            assert record["node_result"]["operation_id"] == accepted["operation_id"]
            assert record["physical_binding"]["connection_id"] == host.physical["A"].connection_id
            assert record["error"] is None
        finally:
            await host.close()
        reopened = Host(tmp_path)
        try:
            assert reopened.diagnostics.get(accepted["host_run_id"])["status"] == "completed"
            assert not reopened.busy and not reopened.physical["A"].connected
        finally:
            await reopened.close()

    asyncio.run(scenario())


def test_immediate_diagnostic_stop_cleans_before_releasing_bench_and_next_job_succeeds(
    native_library, tmp_path
):
    from lora_testbed.host import Host

    async def scenario():
        host = Host(tmp_path)
        serial = NativeSerial(native_library)
        host.physical["A"].opener = lambda _: serial
        try:
            await host.physical["A"].connect("isolated-diag-stop")
            first = await host.memory_probe("A", 10000, 1024)
            stopped = await host.stop_node_operation("A", first["operation_id"])
            assert stopped["cleanup"]["confirmed"] and not host.busy
            record = host.diagnostics.get(first["host_run_id"])
            assert record["status"] == "cancelled"
            second = await host.memory_probe("A", 1, 1024)
            async with asyncio.timeout(5):
                while host.busy:
                    await asyncio.sleep(0.01)
            assert host.diagnostics.get(second["host_run_id"])["status"] == "completed"
        finally:
            await host.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "role,command",
    [
        ("A", "config.set"),
        ("B", "session.open"),
        ("A", "run.prepare"),
        ("B", "run.arm"),
        ("A", "run.arm"),
        ("A", "run.start"),
    ],
)
@pytest.mark.parametrize("cleanup_failure", [False, True])
def test_each_rf_stage_preserves_primary_and_cleanup_errors_then_allows_fresh_diagnostic(
    native_library,
    tmp_path,
    role,
    command,
    cleanup_failure,
):
    import json

    from test_radio_runs import FaultSerial, connected_bench

    from lora_testbed.radio_runs import RadioRunRequest

    state = {"primary": False, "cleanup": False}

    class StageFailure(FaultSerial):
        def __init__(self, selected, **kwargs):
            super().__init__(**kwargs)
            self.selected = selected

        def read(self, count):
            wire = super().read(count)
            if not wire:
                return wire
            record = json.loads(wire)
            name = self.commands.get(record.get("command_id"))
            message = None
            if self.selected == role and record.get("ok") is True:
                if name == command and not state["primary"]:
                    state["primary"] = True
                    message = "Injected primary lifecycle failure"
                elif (
                    state["primary"]
                    and cleanup_failure
                    and name == "status.get"
                    and not state["cleanup"]
                ):
                    state["cleanup"] = True
                    message = "Injected secondary cleanup failure"
            if message:
                record.update(
                    ok=False,
                    result=None,
                    error={
                        "code": "INTERNAL_ERROR",
                        "message": message,
                        "field": None,
                        "retryable": False,
                    },
                )
                return json.dumps(record).encode() + b"\n"
            return wire

    async def scenario():
        host, serials = await connected_bench(
            tmp_path, native_library, lambda selected, **kwargs: StageFailure(selected, **kwargs)
        )
        try:
            run = await host.start_radio(RadioRunRequest())
            async with asyncio.timeout(8):
                while host.busy:
                    await asyncio.sleep(0.01)
            saved = host.radio.get(run["id"])
            assert saved["status"] == "failed" and "primary lifecycle" in saved["error"]
            detail = saved["cleanup"]["details"][role]
            assert saved["cleanup"]["confirmed"] is (not cleanup_failure)
            if cleanup_failure:
                assert any("secondary cleanup" in error["error"] for error in detail["errors"])
                assert not host.physical[role].connected
                with pytest.raises(ValueError, match="disconnected"):
                    await host.start_radio(RadioRunRequest())
                replacement = NativeSerial(
                    native_library,
                    radio=native_library.native_radio_create(),
                    device="esp-001122334455" if role == "A" else "esp-66778899aabb",
                )
                host.physical[role].opener = lambda _: replacement
                await host.physical[role].connect("fresh-after-uncertain-cleanup")
            assert host.radio.content(saved["id"], "wire").stat().st_size > 0
            valid = await host.memory_probe(role, 1, 1024)
            async with asyncio.timeout(5):
                while host.busy:
                    await asyncio.sleep(0.01)
            assert host.diagnostics.get(valid["host_run_id"])["status"] == "completed"
        finally:
            await host.close()

    asyncio.run(scenario())


def test_missing_diagnostic_result_keeps_timeout_distinct_from_cleanup_failure(
    native_library,
    tmp_path,
    monkeypatch,
):
    import json

    from lora_testbed import diagnostic_jobs
    from lora_testbed.host import Host

    monkeypatch.setattr(diagnostic_jobs, "WAIT_SECONDS", 0.2)

    class LostResultAndCleanupFailure(NativeSerial):
        def __init__(self):
            super().__init__(native_library)
            self.commands, self.started, self.failed_cleanup = {}, False, False

        def write(self, wire):
            command = json.loads(wire)
            self.commands[command["command_id"]] = command["name"]
            if command["name"] == "diag.run":
                self.started = True
            return super().write(wire)

        def _pump(self):
            self.core.tick()
            for record in self.core.drain():
                if record.get("name") == "operation.result":
                    continue
                if (
                    self.started
                    and not self.failed_cleanup
                    and self.commands.get(record.get("command_id")) == "status.get"
                ):
                    self.failed_cleanup = True
                    record.update(
                        ok=False,
                        result=None,
                        error={
                            "code": "INTERNAL_ERROR",
                            "message": "Secondary cleanup fault",
                            "field": None,
                            "retryable": False,
                        },
                    )
                self.queue.put(json.dumps(record).encode() + b"\n")

    async def scenario():
        host = Host(tmp_path)
        serial = LostResultAndCleanupFailure()
        host.physical["A"].opener = lambda _: serial
        try:
            await host.physical["A"].connect("isolated-diag-result-loss")
            accepted = await host.memory_probe("A", 1, 1024)
            async with asyncio.timeout(5):
                while host.busy:
                    await asyncio.sleep(0.01)
            record = host.diagnostics.get(accepted["host_run_id"])
            assert record["status"] == "failed" and "Timeout" in record["error"]
            assert record["node_result"] is None and not record["cleanup"]["confirmed"]
            assert any(
                "Secondary cleanup" in error["error"] for error in record["cleanup"]["errors"]
            )
            assert not host.physical["A"].connected
            evidence = host.diagnostics.evidence(accepted["host_run_id"])
            assert any(row["record"].get("name") == "diag.run" for row in evidence["wire"])
            assert evidence["job"]["wire_sha256"]
        finally:
            await host.close()

    asyncio.run(scenario())


def test_active_diagnostic_shutdown_is_interrupted_and_restart_never_connects(
    native_library, tmp_path
):
    from lora_testbed.host import Host

    async def scenario():
        host = Host(tmp_path)
        serial = NativeSerial(native_library)
        host.physical["A"].opener = lambda _: serial
        await host.physical["A"].connect("isolated-active-diagnostic")
        accepted = await host.memory_probe("A", 10000, 1024)
        await host.close()
        assert serial.closed
        reopened = Host(tmp_path)
        try:
            record = reopened.diagnostics.get(accepted["host_run_id"])
            assert record["status"] == "interrupted" and record["cleanup"]["confirmed"]
            assert not reopened.busy and not any(
                node.connected for node in reopened.physical.values()
            )
        finally:
            await reopened.close()

    asyncio.run(scenario())


def test_shutdown_during_diagnostic_acceptance_waits_for_cleanup_before_closing_store(
    native_library, tmp_path
):
    import json
    import threading
    import time

    from lora_testbed.host import Host

    entered = threading.Event()

    class SlowDiagnosticWrite(NativeSerial):
        def write(self, wire):
            if json.loads(wire)["name"] == "diag.run":
                entered.set()
                time.sleep(0.1)
            return super().write(wire)

    async def scenario():
        host = Host(tmp_path)
        serial = SlowDiagnosticWrite(native_library)
        host.physical["A"].opener = lambda _: serial
        await host.physical["A"].connect("isolated-start-shutdown")
        start = asyncio.create_task(host.memory_probe("A", 10000, 1024))
        async with asyncio.timeout(2):
            while not entered.is_set():
                await asyncio.sleep(0.002)
        await host.close()
        await asyncio.gather(start, return_exceptions=True)
        assert serial.closed and host.diagnostics.current is None
        reopened = Host(tmp_path)
        try:
            records = reopened.diagnostics.snapshot()["runs"]
            assert len(records) == 1 and records[0]["status"] == "interrupted"
            assert records[0]["cleanup"]["confirmed"]
        finally:
            await reopened.close()

    asyncio.run(scenario())


def test_diagnostic_http_job_and_hashed_command_evidence_share_the_host(native_library, tmp_path):
    from fastapi.testclient import TestClient

    from lora_testbed.app import create_app

    with TestClient(create_app(data_dir=tmp_path)) as client:
        host = client.app.state.host
        serial = NativeSerial(native_library)
        host.physical["A"].opener = lambda _: serial
        client.portal.call(host.physical["A"].connect, "isolated-diag-api")
        response = client.post(
            "/api/nodes/A/memory-probe", json={"iterations": 1, "payload_bytes": 1024}
        )
        assert response.status_code == 200
        accepted = response.json()

        async def finished():
            async with asyncio.timeout(5):
                while host.busy:
                    await asyncio.sleep(0.01)

        client.portal.call(finished)
        run_id = accepted["host_run_id"]
        record = client.get(f"/api/diagnostic-runs/{run_id}").json()
        evidence = client.get(f"/api/diagnostic-runs/{run_id}/evidence?include_records=true").json()
        assert record["status"] == "completed" and record["cleanup"]["confirmed"]
        assert evidence["job"]["wire_sha256"] == record["wire_sha256"]
        assert any(row["record"].get("name") == "diag.run" for row in evidence["wire"])
        assert any(row["name"] == "operation.result" for row in evidence["operation_events"])
        assert client.get("/api/state").json()["diagnostic_runs"]["active_id"] is None
