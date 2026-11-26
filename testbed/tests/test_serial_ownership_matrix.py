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
        serial = NativeSerial(native_library)
        node.opener = lambda _: serial
        try:
            await node.connect("isolated-lease-node-b")
            spec = MatrixRequest(catalog_id="IF-01", groups=["C6"], roles=["B"])
            preview = host.procedures.matrix_preview(spec, host.radio)
            assert preview["ready_case_count"] == 6
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(30):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert saved["status"] == "completed" and saved["assessment"] == "inconclusive", saved
            assert not saved["hardware_validated"]
            ledger = list(host.procedures.all_evidence(saved["id"]))
            for case in saved["cases"]:
                rows = [row["document"] for row in ledger if row["case_id"] == case["id"]]
                if case["variant"] == "health_silence":
                    assert case["status"] == "blocked" and not rows
                    continue
                assert case["assessment"] == "pass" and case["cleanup_verified"]
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
        finally:
            await host.close()

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
