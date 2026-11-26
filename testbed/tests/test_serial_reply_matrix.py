"""Use the actual retry controller and native firmware for IF-01 reply faults."""

import asyncio

import pytest
from test_node_control_native import NativeSerial
from test_node_control_native import native_library as native_library

from lora_testbed.host import Host
from lora_testbed.integration_matrices import MatrixRequest


def test_reply_perturbation_repeats_exact_command_and_observes_one_operation(
    tmp_path, native_library
):
    async def scenario():
        host = Host(tmp_path)
        node = host.physical["A"]
        node.opener = lambda _: NativeSerial(native_library)
        try:
            await node.connect("isolated-native-replies")
            spec = MatrixRequest(catalog_id="IF-01", groups=["C5"], roles=["A"])
            preview = host.procedures.matrix_preview(spec, host.radio)
            assert preview["ready_case_count"] == 12
            prior = host.adapter.bind("A")
            await node.close()
            node.opener = lambda _: NativeSerial(native_library, boot=2)
            await node.connect("isolated-native-replies")
            fresh = host.adapter.bind("A")
            assert fresh["device_id"] == prior["device_id"] and fresh["boot_id"] != prior["boot_id"]
            assert host.procedures.matrix_preview(spec, host.radio)["ready_case_count"] == 15
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(15):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert saved["status"] == "completed", saved
            assert saved["assessment"] == "pass" and not saved["hardware_validated"]
            ledger = list(host.procedures.all_evidence(saved["id"]))
            operations = set()
            for case in saved["cases"]:
                documents = [r["document"] for r in ledger if r["case_id"] == case["id"]]
                variant = case["variant"]
                assert case["assessment"] == "pass" and case["cleanup_verified"]
                if variant == "stale_boot":
                    [observed] = [row for row in documents if "previous_boot" in row]
                    assert observed["observed_error"] == "STALE_BOOT"
                    assert observed["unexpected_operation_ids"] == []
                    assert observed["previous_boot"] == {
                        k: v for k, v in prior.items() if k != "role"
                    }
                    assert observed["current_boot"] == {
                        k: v for k, v in fresh.items() if k != "role"
                    }
                    [command] = [
                        row["record"]
                        for row in documents
                        if row["direction"] == "host_to_node"
                        and row["record"]["name"] == "diag.run"
                    ]
                    assert command["target_boot_id"] == prior["boot_id"]
                    continue
                if variant == "conflicting_identity":
                    first, second = [
                        row["record"]
                        for row in documents
                        if row["direction"] == "host_to_node"
                        and row["record"]["name"] == "control.keepalive"
                    ]
                    assert first["command_id"] == second["command_id"] and first != second
                    assert [
                        row["record"]["error"]["code"]
                        for row in documents
                        if row["direction"] == "node_to_host" and not row["record"]["ok"]
                    ] == ["COMMAND_CONFLICT"]
                    continue
                [proof] = [row for row in documents if row.get("reply_recovery") == variant]
                assert proof["outcome"] == "pass"
                [fixture] = [row for row in documents if "perturbation" in row]
                [result] = proof["operation_results"]
                assert result["operation_id"] == fixture["reply"]["result"]["operation_id"]
                assert result["result"]["iterations_completed"] == 1
                operations.add(result["operation_id"])
                attempts = 1 if variant == "lost_reply" else 2
                assert len(proof["write_sha256"]) == attempts
                assert len(set(proof["write_sha256"])) == 1
                assert proof["timed_out"] is (variant == "lost_reply")
                assert proof["delayed_reply_delivered"] is (variant == "delayed_reply")
            assert len(operations) == 9
            assert node.health.state == "idle" and not node.pending and node._reply_probe is None
        finally:
            await host.close()

    asyncio.run(scenario())


def test_cancelling_delayed_reply_releases_pending_command_and_timer(tmp_path, native_library):
    async def scenario():
        host = Host(tmp_path)
        node = host.physical["B"]
        node.opener = lambda _: NativeSerial(native_library)
        try:
            await node.connect("isolated-delayed-cancel")
            intercepted = asyncio.Event()

            def record(document):
                if document.get("perturbation") == "delay":
                    intercepted.set()

            task = asyncio.create_task(node.exercise_reply_recovery("delayed_reply", record))
            async with asyncio.timeout(2):
                await intercepted.wait()
            _, probe = node._reply_probe
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert probe.timer.cancelled() and not probe.delivered_delayed
            assert node._reply_probe is None and not node.pending
            async with asyncio.timeout(2):
                while (await node.request("status.get"))["state"] != "idle":
                    await asyncio.sleep(0.01)
        finally:
            await host.close()

    asyncio.run(scenario())
