"""Verify grouped timing through the shared bench and durable child evidence."""

import asyncio

from test_multi_fragment_radio import Pair
from test_node_control_native import NativeSerial
from test_node_control_native import native_library as native_library

from lora_testbed.host import Host
from lora_testbed.integration_matrices import MatrixRequest, compile_matrix


def test_timed_plans_cover_both_roles_and_have_fixed_default_counts():
    echo = compile_matrix(MatrixRequest(catalog_id="TIME-01"))
    assert echo["full_plan"]
    positive = [case for case in echo["cases"] if case["driver"] == "echo_batch"]
    missing = [case for case in echo["cases"] if case["driver"] == "echo_timeout_fixture"]
    assert len(positive) == 36 and all(case["message_count"] == 100 for case in positive)
    assert len(missing) == 6 and all(case["message_count"] == 1 for case in missing)

    local = compile_matrix(MatrixRequest(catalog_id="SEC-04"))
    assert local["full_plan"] and local["case_count"] == 24
    for role in ("A", "B"):
        cases = [case for case in local["cases"] if case["role"] == role]
        assert len(cases) == 12 and {case["iterations"] for case in cases} == {1000}
    assert not compile_matrix(MatrixRequest(catalog_id="SEC-04", roles=["A"]))["full_plan"]


def test_echo_matrix_reconciles_two_samples_per_matched_native_cohort(tmp_path, native_library):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library)
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            spec = MatrixRequest(
                catalog_id="TIME-01", directions=["A_TO_B"], repetitions=1, messages_per_case=2
            )
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(45):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert saved["status"] == "completed", saved
            assert not saved["hardware_validated"] and not saved["full_procedure_passed"]
            assert [case["assessment"] for case in saved["cases"]] == ["pass"] * 6 + [
                "inconclusive"
            ]
            assert saved["cases"][-1]["status"] == "blocked"
            assert saved["cases"][-1]["run_ids"] == []
            distributions = [
                row["document"]["round_trip_distribution"]
                for row in host.procedures.all_evidence(saved["id"])
                if "round_trip_distribution" in row["document"]
            ]
            assert len(distributions) == 6
            for distribution in distributions:
                assert distribution["selected_runs"] == 2
                [group] = distribution["groups"]
                assert group["n"] == 2 and group["p95_us"] >= group["median_us"] > 0
                assert group["cohort"]["requester"] == "A"
                assert {sample["boot_id"] for sample in group["samples"]} == {
                    group["cohort"]["requester_identity"]["boot_id"]
                }
        finally:
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            await host.close()

    asyncio.run(scenario())


def test_crypto_matrix_uses_only_selected_role_and_records_checked_local_timing(
    tmp_path, native_library
):
    async def scenario():
        host = Host(tmp_path)
        peer = NativeSerial(native_library)
        node = host.physical["B"]
        node.opener = lambda _: peer
        try:
            await node.connect("fixture-only-B")
            spec = MatrixRequest(
                catalog_id="SEC-04", roles=["B"], repetitions=1, diagnostic_iterations=1000
            )
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(45):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert saved["status"] == "completed" and saved["assessment"] == "pass", saved
            assert set(saved["physical_bindings"]) == {"B"}
            assert not saved["hardware_validated"] and not saved["full_procedure_passed"]
            for size, case in zip((16, 64, 160, 199), saved["cases"], strict=True):
                job = host.diagnostics.evidence(case["diagnostic_run_id"], include_records=True)
                assert job["job"]["cleanup"]["confirmed"]
                assert job["job"]["wire_sha256"]
                assert len(job["operation_events"]) > 200
                results = case["measurements"]
                assert results["identification"]["payload_bytes"] == size
                assert results["checked_samples"] == 4 * (1000 + 50 + 1)
                assert set(results["distributions"]) == {
                    "encrypt",
                    "decrypt",
                    "invalid_tag",
                    "copy",
                }
                for path in results["distributions"].values():
                    assert path["n"] == 1000 and path["checked_warmups"] == 50
                    assert path["first_call_us"] >= 0
                    assert path["max_us"] >= path["p95_us"] >= path["min_us"]
        finally:
            await host.close()

    asyncio.run(scenario())
