"""Check each deliberate incompatibility through the production handshake."""

import asyncio

from test_node_control_native import NativeSerial
from test_node_control_native import native_library as native_library

from lora_testbed.host import Host
from lora_testbed.integration_matrices import MatrixRequest
from lora_testbed.serial_compatibility import INCOMPATIBILITIES


def test_version_fixture_closes_without_claiming_or_disturbing_live_role(tmp_path, native_library):
    async def scenario():
        host = Host(tmp_path)
        node = host.physical["B"]
        peer = NativeSerial(native_library)
        node.opener = lambda _: peer
        try:
            await node.connect("isolated-live-control")
            initial = host.adapter.bind("B")
            spec = MatrixRequest(catalog_id="IF-01", groups=["C4"], roles=["B"])
            plan = host.procedures.matrix_preview(spec, host.radio)
            assert plan["ready_case_count"] == 9
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(10):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert saved["status"] == "completed" and saved["assessment"] == "pass", saved
            assert not saved["hardware_validated"]
            rows = list(host.procedures.all_evidence(saved["id"]))
            for case in saved["cases"]:
                field, replacement, reason = INCOMPATIBILITIES[case["variant"]]
                assert case["cleanup_verified"] and case["assessment"] == "pass"
                documents = [row["document"] for row in rows if row["case_id"] == case["id"]]
                [report] = [doc for doc in documents if "modified_field" in doc]
                assert report["modified_field"] == field
                replies = [doc["record"] for doc in documents if doc["direction"] == "node_to_host"]
                expected = {**replies[0]["result"], field: replacement}
                assert report["reply"]["result"] == expected
                assert report["port_closed"] and report["connection_error"].endswith(reason)
                [probe] = report["commands"]
                assert probe["name"] == "hello" and probe["target_boot_id"] is None
                assert report["reply"]["command_id"] == probe["command_id"]
            assert host.adapter.bind("B") == initial
            assert not peer.closed and not node.pending and node.health.state == "idle"
        finally:
            await host.close()

    asyncio.run(scenario())
