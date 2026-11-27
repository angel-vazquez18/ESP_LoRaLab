"""Exercise ownership rejection and real lease expiry on the serial matrix."""

import asyncio

import pytest
from test_node_control_native import NativeSerial
from test_node_control_native import native_library as native_library

from lora_testbed.host import Host
from lora_testbed.integration_matrices import MatrixRequest


def test_serial_ownership_matrix_observes_conflict_and_lease_expiry(tmp_path, native_library):
    async def scenario():
        host = Host(tmp_path)
        node = host.physical["B"]

        class ReopenableSerial(NativeSerial):
            def open(self, _):
                with self.lock:
                    self.closed = False
                return self

            def close(self):
                with self.lock:
                    self.closed = True

        serial = ReopenableSerial(native_library)
        node.opener = serial.open
        try:
            await node.connect("isolated-lease-node-b")
            spec = MatrixRequest(catalog_id="IF-01", groups=["C6"], roles=["B"])
            preview = host.procedures.matrix_preview(spec, host.radio)
            assert preview["ready_case_count"] == 9
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(50):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert saved["status"] == "completed" and saved["assessment"] == "pass", saved
            assert not saved["hardware_validated"]
            ledger = list(host.procedures.all_evidence(saved["id"]))
            for case in saved["cases"]:
                rows = [row["document"] for row in ledger if row["case_id"] == case["id"]]
                assert case["assessment"] == "pass" and case["cleanup_verified"]
                if case["variant"] == "health_silence":
                    [silence] = [r for r in rows if r.get("health_silence")]
                    assert silence["suppressed_events"]
                    assert {event["name"] for event in silence["suppressed_events"]} == {"health"}
                    assert 3 < silence["stale_at_age_s"] <= 3.5
                    assert (
                        5
                        < silence["unresponsive_at_age_s"]
                        <= silence["disconnected_at_age_s"]
                        <= 6.5
                    )
                    [restored] = [r for r in rows if "recovered_binding" in r]
                    prior, current = restored["previous_binding"], restored["recovered_binding"]
                    assert prior["device_id"] == current["device_id"]
                    assert prior["boot_id"] == current["boot_id"]
                    assert prior["connection_id"] != current["connection_id"]
                    continue
                replies = [row["record"] for row in rows if row["direction"] == "node_to_host"]
                assert replies[-1]["result"]["node_role"] == "B"
                if case["variant"] == "lease_recovery":
                    [observed] = [r for r in rows if "expired_health" in r]
                    assert 0 <= observed["observed_after_us"] < 2_000_000
                    assert observed["expired_health"]["node_role"] is None
                    assert observed["expired_health"]["state"] == "idle"
                    assert [r["error"]["code"] for r in replies if not r["ok"]] == ["NOT_OWNER"]
                else:
                    [claim] = [
                        r["record"]
                        for r in rows
                        if r["direction"] == "host_to_node"
                        and r["record"]["name"] == "control.claim"
                    ]
                    assert claim["client_id"] != node.client_id
                    assert [r["error"]["code"] for r in replies if not r["ok"]] == ["BUSY"]
            assert node.health.state == "idle" and not node.pending
            assert saved["serial_recovered_bindings"]["B"] == host.adapter.bind("B")
            assert node._health_probe is None
        finally:
            await host.close()
            serial.core.close()

    asyncio.run(scenario())


def test_cancelling_lease_probe_recovers_control(tmp_path, native_library):
    async def scenario():
        host = Host(tmp_path)
        node = host.physical["A"]
        node.opener = lambda _: NativeSerial(native_library)
        try:
            await node.connect("isolated-cancel-lease")
            expiry = asyncio.Event()

            def record(document):
                if "expired_health" in document:
                    expiry.set()

            probe = asyncio.create_task(node.exercise_lease_recovery(record))
            async with asyncio.timeout(8):
                await expiry.wait()
            probe.cancel()
            with pytest.raises(asyncio.CancelledError):
                await probe
            assert not node.control_cycle_active and node.connected and not node.pending
            status = await node.request("status.get")
            assert status["node_role"] == "A" and status["state"] == "idle"
        finally:
            await host.close()

    asyncio.run(scenario())
