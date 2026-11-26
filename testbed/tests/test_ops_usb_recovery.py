"""Exercise node interruption evidence through the production serial and radio services."""

import asyncio
import json
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from test_multi_fragment_radio import Pair
from test_node_control_native import NativeSerial
from test_node_control_native import native_library as native_library

from lora_testbed.app import create_app
from lora_testbed.integration_matrices import MatrixRequest, compile_matrix
from lora_testbed.radio_runs import RadioRunRequest


@pytest.mark.parametrize("group", ["C1", "C2"])
def test_interruption_plan_covers_either_side_in_both_directions_and_three_repetitions(group):
    spec = MatrixRequest(catalog_id="OPS-01", groups=[group])
    cases = compile_matrix(spec)["cases"]
    expected = {
        (target, direction, repetition)
        for target in "AB"
        for direction in spec.directions
        for repetition in range(1, 4)
    }
    assert len(cases) == len(expected) == 12
    assert {(row["target_role"], row["direction"], row["repetition"]) for row in cases} == expected


@pytest.mark.parametrize("direction", ["A_TO_B", "B_TO_A"])
@pytest.mark.parametrize("target", ["A", "B"])
@pytest.mark.parametrize("group", ["C1", "C2"])
def test_interruption_stops_the_peer_and_verifies_recovery_through_the_api(
    tmp_path, native_library, direction, target, group
):
    async def scenario():
        app = create_app(tmp_path)
        async with app.router.lifespan_context(app):
            host = app.state.host
            pair = Pair(host, native_library)
            await pair.connect()
            reset = group == "C2"
            field = "ops_reset_evidence" if reset else "ops_usb_evidence"
            request = RadioRunRequest(
                direction=direction, security="aes128_gcm" if reset else "none"
            )
            faulted = await host.start_radio(request)
            replacement = NativeSerial(
                native_library,
                radio=native_library.native_radio_create(),
                device=faulted["physical_bindings"][target]["device_id"],
                boot=2 if reset else 1,
            )

            def lose_serial(_count):
                raise OSError("isolated USB read failure")

            report_boot = reset and target == "B"
            unexpected_boot = (
                json.dumps(replacement.core.request()).encode() + b"\n" if report_boot else b""
            )
            async with asyncio.timeout(8):
                while host.radio.current["stage"] != "transmitting":
                    await asyncio.sleep(0.005)
                pair.serials[target].read = (
                    (lambda _: unexpected_boot) if report_boot else lose_serial
                )
                await host.radio.task
            old = host.radio.get(faulted["id"])
            assert old["status"] == "interrupted", old
            assert old["connection_failures"][target]["kind"] == (
                "identity_change" if report_boot else "serial_io"
            )
            assert not old["cleanup"]["confirmed"]
            peer = "B" if target == "A" else "A"
            assert old["cleanup"]["details"][peer]["confirmed"]
            assert host.physical[peer].health.state == "idle"
            pair.serials[target] = replacement
            host.physical[target].opener = lambda _: replacement
            await host.physical[target].connect("fixture-reconnected-" + target)
            stale = None
            if reset:
                stale = await host.start_procedure_matrix(
                    MatrixRequest(
                        catalog_id="IF-01",
                        groups=["C5"],
                        repetitions=1,
                        roles=[target],
                    )
                )
                async with asyncio.timeout(12):
                    await host.procedures.task
                [saved_case] = [
                    row
                    for row in host.procedures.get(stale["id"])["cases"]
                    if row["variant"] == "stale_boot"
                ]
                assert saved_case["assessment"] == "pass", saved_case
            bridge = asyncio.create_task(pair.bridge())
            try:
                retry = await host.start_radio(request)
                async with asyncio.timeout(8):
                    await host.radio.task
            finally:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            child = host.radio.get(retry["id"])
            assert child["verification"]["bytes_equal"]
            assert [row["role"] for row in child["events"] if row["name"] == "tx.attempt"] == [
                direction[0]
            ]
            for node in host.physical.values():
                await node.close()
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://127.0.0.1"
            ) as ui:
                endpoint = "/api/procedures/matrix"
                arguments = {"catalog_id": "OPS-01", "groups": [group], "repetitions": 1}
                missing = (await ui.post(f"{endpoint}/preview", json=arguments)).json()
                assert missing["ready_case_count"] == 0 and missing["case_count"] == 4
                reference = {
                    "target_role": target,
                    "direction": direction,
                    "repetition": 1,
                    "interrupted": faulted["id"],
                    "recovery": retry["id"],
                }
                arguments[field] = [reference]
                if reset:
                    reference["stale_boot_procedure"] = str(uuid4())
                    missing_proof = (await ui.post(f"{endpoint}/preview", json=arguments)).json()
                    assert missing_proof["ready_case_count"] == 0
                    reference["stale_boot_procedure"] = stale["id"]
                preview = (await ui.post(f"{endpoint}/preview", json=arguments)).json()
                assert preview["ready_case_count"] == 1
                result = await ui.post(endpoint, json=arguments)
                assert result.status_code == 202, result.json()
                async with asyncio.timeout(5):
                    await host.procedures.task
                saved = host.procedures.get(result.json()["id"])
                [case] = [row for row in saved["cases"] if row["assessment"] == "pass"]
                assert case["run_ids"] == [faulted["id"], retry["id"]]
                assert case["measurements"]["target_role"] == target
                assert 0 < case["measurements"]["fault_to_cleanup_ms"] < 5000
                assert case["measurements"]["peer_cleanup"]["confirmed"]
                assert not case["measurements"]["faulted_cleanup"]["confirmed"]
                if reset:
                    proof = case["measurements"]["reset_proof"]
                    assert proof["procedure_id"] == stale["id"]
                    assert proof["new_boot_id"] != proof["old_boot_id"]
                    assert proof["new_key_set_id"] != proof["old_key_set_id"]
                    assert proof["idle_without_session_or_keys"] and proof["stale_boot_rejected"]
                assert not saved["hardware_validated"] and not saved["full_procedure_passed"]

                reference["target_role"] = peer
                rejected = await ui.post(endpoint, json=arguments)
                assert rejected.status_code == 202
                async with asyncio.timeout(5):
                    await host.procedures.task
                saved = host.procedures.get(rejected.json()["id"])
                [case] = [row for row in saved["cases"] if row["status"] != "blocked"]
                assert case["assessment"] == "inconclusive"
                assert "selected role" in case["reason"]

    asyncio.run(scenario())
