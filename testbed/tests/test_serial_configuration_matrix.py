"""Verify that the IF-01 error group keeps the node's applied settings."""

import asyncio

from test_node_control_native import NativeSerial
from test_node_control_native import native_library as native_library

from lora_testbed.experiments_v2 import Link, Radio
from lora_testbed.host import Host
from lora_testbed.integration_matrices import MatrixRequest


def test_invalid_configuration_keeps_prior_radio_link_and_revision(tmp_path, native_library):
    async def scenario():
        host = Host(tmp_path)
        serial = NativeSerial(native_library, radio=native_library.native_radio_create())
        no_radio = NativeSerial(native_library, device="esp-66778899aabb")
        spec = MatrixRequest(catalog_id="IF-01", groups=["C2"], roles=["A"])
        try:
            for role, peer in (("A", serial), ("B", no_radio)):
                host.physical[role].opener = lambda _, peer=peer: peer
                await host.physical[role].connect(f"isolated-config-{role}")
            prior = await host.physical["A"].request(
                "config.set",
                {"radio": Radio(tx_power_dbm=2).model_dump(), "link": Link().model_dump()},
            )
            assert prior["config_revision"] > 0 and prior["radio"]["tx_power_dbm"] == 2
            actual = await host.physical["A"].request("status.get")
            assert actual["radio"] == prior["radio"] and actual["link"] == prior["link"]
            preview = host.procedures.matrix_preview(spec, host.radio)
            assert preview["ready_case_count"] == 12
            absent = host.procedures.matrix_preview(
                spec.model_copy(update={"roles": ["B"]}), host.radio
            )
            assert absent["ready_case_count"] == 9
            assert all(
                case["blockers"]
                for case in absent["cases"]
                if case["variant"] == "configuration_unchanged"
            )
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(10):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert saved["status"] == "completed" and saved["assessment"] == "pass", saved
            assert not saved["hardware_validated"]
            observations = [
                row["document"]
                for row in host.procedures.all_evidence(saved["id"])
                if "configuration_before" in row["document"]
            ]
            assert len(observations) == 3
            for row in observations:
                assert row["expected_error"] == row["observed_error"] == "INVALID_ARGUMENT"
                assert row["configuration_before"] == row["configuration_after"] == prior
            node = host.physical["A"]
            assert not node.pending and node.health.state == "idle"
            assert node.health.config_revision == prior["config_revision"]
        finally:
            await host.close()

    asyncio.run(scenario())
