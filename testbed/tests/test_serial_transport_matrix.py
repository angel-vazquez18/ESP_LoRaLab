"""Use the firmware transport declaration to select the right IF-01 cases."""

import asyncio
import io
import json
import zipfile

from test_node_control_native import NativeSerial
from test_node_control_native import native_library as native_library

from lora_testbed.host import Host
from lora_testbed.integration_matrices import MatrixRequest


class UARTIdentitySerial(NativeSerial):
    """Use a native parser for the records and declare the UART fixture identity."""

    def _pump(self):
        self.core.tick()
        for record in self.core.drain():
            identity = record.get("result")
            if record["kind"] == "reply" and identity and "supported_wire_versions" in identity:
                identity["capabilities"]["resource_limits"]["control_transport"] = "uart"
            self.queue.put(json.dumps(record, separators=(",", ":")).encode() + b"\n")


def test_if01_selects_firmware_transport_and_retains_unmatched_rows(tmp_path, native_library):
    async def scenario():
        host = Host(tmp_path)
        try:
            for role, serial in (
                ("A", NativeSerial(native_library, device="esp-001122334455")),
                ("B", UARTIdentitySerial(native_library, device="esp-66778899aabb")),
            ):
                node = host.physical[role]
                node.opener = lambda _, peer=serial: peer
                await node.connect("isolated-" + role)
            assert host.physical["A"].snapshot()["control_transport"] == "native_usb"
            assert host.physical["B"].snapshot()["control_transport"] == "uart"
            spec = MatrixRequest(
                catalog_id="IF-01",
                groups=["C1", "C3"],
                transports=["native_usb", "uart"],
                valid_cycles=1,
                repetitions=1,
            )
            preview = host.procedures.matrix_preview(spec, host.radio)
            assert preview["ready_case_count"] == 20
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(20):
                await host.procedures.task
            record = host.procedures.get(started["id"])
            counts = {}
            for case in record["cases"]:
                key = (case["role"], case["transport"], case["status"])
                counts[key] = counts.get(key, 0) + 1
            assert counts == {
                ("A", "native_usb", "completed"): 10,
                ("A", "uart", "blocked"): 10,
                ("B", "native_usb", "blocked"): 10,
                ("B", "uart", "completed"): 10,
            }
            assert all(case["assessment"] == "pass" for case in record["cases"] if case["ready"])
            assert not record["hardware_validated"]
            assert record["connection_transports"] == {"A": "native_usb", "B": "uart"}
            with zipfile.ZipFile(io.BytesIO(host.procedures.bundle(record))) as evidence:
                provenance = json.loads(evidence.read("provenance.json"))
            assert provenance["connection_transports"] == record["connection_transports"]
            assert provenance["transport"] == "UART0 115200 8N1 and native USB Serial/JTAG"
        finally:
            await host.close()

    asyncio.run(scenario())
