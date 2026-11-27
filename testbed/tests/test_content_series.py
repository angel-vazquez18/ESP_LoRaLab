"""Verify packet boundary and matched security cases through the shared runner."""

import asyncio
from collections import Counter
from copy import deepcopy

import pytest
from test_multi_fragment_radio import Pair
from test_node_control_native import native_library as native_library

from lora_testbed.content_series import compare_protection
from lora_testbed.host import Host
from lora_testbed.integration_matrices import MatrixRequest, compile_matrix


def test_packet_plan_uses_negotiated_size_and_retains_above_limit_rejection():
    plan = compile_matrix(MatrixRequest(catalog_id="PKT-01"), message_limit=12345)
    limits = {case["message_bytes"] for case in plan["cases"] if case["group"] == "C2"}
    assert limits == {12344, 12345}
    rejects = [case for case in plan["cases"] if case["group"] == "C3"]
    assert len(rejects) == 6
    assert all(case["message_bytes"] == 12346 for case in rejects)
    assert {
        case["final_fragment_bytes"] for case in plan["cases"] if case["message_bytes"] == 161
    } == {1}
    coinciding = compile_matrix(MatrixRequest(catalog_id="PKT-01"), message_limit=321)
    assert not any(case["group"] == "C2" for case in coinciding["cases"])


@pytest.mark.parametrize("identifier", ["PKT-01", "SEC-01"])
def test_content_series_runs_boundary_cases_and_separate_security_modes(
    tmp_path, native_library, identifier
):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library)
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            spec = MatrixRequest(
                catalog_id=identifier,
                repetitions=1,
                messages_per_case=1,
                subset_sizes=[160, 161, 65537] if identifier == "PKT-01" else [64, 321],
            )
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(30):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert saved["status"] == "completed", saved
            assert not saved["full_procedure_passed"] and not saved["hardware_validated"]
            if identifier == "PKT-01":
                assert saved["assessment"] == "pass"
                assert {c["message_bytes"] for c in saved["cases"]} == {160, 161, 65537}
                assert len(pair.frames) == 8
                negative = [case for case in saved["cases"] if case["group"] == "C3"]
                assert len(negative) == 2
                for case in negative:
                    rejected, recovered = [host.radio.get(run_id) for run_id in case["run_ids"]]
                    assert not rejected["events"] and not rejected["prepared"]
                    assert (
                        rejected["resource_refusal"]["reply"]["error"]["code"] == "RESOURCE_LIMIT"
                    )
                    assert recovered["verification"]["bytes_equal"]
            else:
                assert saved["assessment"] == "inconclusive"
                assert Counter(c["status"] for c in saved["cases"]) == {
                    "completed": 10,
                    "blocked": 2,
                }
                paired = {}
                for case in saved["cases"]:
                    if case["driver"] != "content_series":
                        continue
                    record = host.radio.get(case["run_ids"][0])
                    assert record["verification"]["bytes_equal"]
                    lengths = [
                        e["data"]["frame_bytes"]
                        for e in record["events"]
                        if e["name"] == "tx.attempt" and e["data"]["frame_type"] == "data"
                    ]
                    paired[(case["direction"], case["message_bytes"], case["security"])] = lengths
                for direction in ("A_TO_B", "B_TO_A"):
                    for size in (64, 321):
                        assert paired[direction, size, "aes128_gcm"] == [
                            length + 16 for length in paired[direction, size, "none"]
                        ]
                assert len(saved["security_comparison"]) == 4
                for row in saved["security_comparison"]:
                    plain, secure = row["unprotected"], row["protected"]
                    assert row["matched_pairs"] == row["timed_pairs"] == 1
                    assert row["overhead_bytes"] == (16 if row["message_bytes"] == 64 else 48)
                    assert secure["wire_bytes"] - plain["wire_bytes"] == row["overhead_bytes"]
                    for metrics in (plain, secure):
                        assert metrics["unique_original_delivery_ratio"] == 1
                        assert metrics["delivered_bytes"] == row["message_bytes"]
                        assert metrics["goodput_bps"] == (
                            row["message_bytes"]
                            * 8_000_000
                            / metrics["sender_transfer_duration_us"]
                        )
                candidates = [
                    case
                    for case in saved["cases"]
                    if case["driver"] == "content_series"
                    and case["message_bytes"] == 64
                    and case["direction"] == "A_TO_B"
                ]
                sample_rows = {
                    case["id"]: {
                        row["document"]["ordinal"]: row["document"]
                        for row in host.procedures.evidence(saved["id"], case_id=case["id"])
                    }
                    for case in candidates
                }
                secure_case = next(
                    case["id"] for case in candidates if case["security"] == "aes128_gcm"
                )
                mismatched = deepcopy(sample_rows)
                mismatched[secure_case][1]["protection_observation"]["source_seed"] += 1
                [bad_source] = compare_protection(candidates, mismatched.get)
                assert bad_source["status"] == "inconclusive" and bad_source["matched_pairs"] == 0
                assert "overhead_bytes" not in bad_source
                sample_rows[secure_case][1]["accounting"]["sender_transfer_window"][
                    "duration_us"
                ] = None
                [untimed] = compare_protection(candidates, sample_rows.get)
                assert untimed["status"] == "inconclusive" and untimed["timed_pairs"] == 0
                assert untimed["overhead_bytes"] == 16
                assert untimed["protected"]["goodput_bps"] is None
        finally:
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            await host.close()

    asyncio.run(scenario())


def test_wrong_key_rejection_and_profile_preflight_keep_secrets_private(tmp_path, native_library):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library, lab=True)
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            spec = MatrixRequest(
                catalog_id="SEC-01",
                groups=["C3"],
                directions=["A_TO_B"],
                repetitions=1,
                messages_per_case=1,
            )
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(20):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert saved["status"] == "completed" and saved["assessment"] == "pass", saved
            wrong_key, profile = saved["cases"]
            rejected = host.radio.get(wrong_key["run_ids"][1])
            assert rejected["security"]["controlled_receiver_key_mismatch"]
            assert rejected["security"]["keys_retired_on_host"] and rejected["cleanup"]["confirmed"]
            assert rejected["summaries"]["B"]["delivered_messages"] == 0
            trace = host.radio.content(rejected["id"], "wire").read_text()
            assert "authentication_failed" in trace and "wire_sha256" in trace
            assert '"tx_key_hex":' not in trace and '"rx_key_hex":' not in trace
            assert len(wrong_key["run_ids"]) == 3 and len(profile["run_ids"]) == 2
            assert len(pair.frames) == 5
        finally:
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            await host.close()

    asyncio.run(scenario())


def test_protected_packet_limit_retires_keys_before_verified_recovery(tmp_path, native_library):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library)
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            spec = MatrixRequest(
                catalog_id="PKT-01",
                groups=["C3"],
                repetitions=1,
                directions=["A_TO_B"],
                rf_security="aes128_gcm",
            )
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(20):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert saved["status"] == "completed" and saved["assessment"] == "pass", saved
            [case] = saved["cases"]
            rejected, recovered = [host.radio.get(identifier) for identifier in case["run_ids"]]
            evidence = rejected["resource_refusal"]
            assert evidence["reply"]["error"]["code"] == "RESOURCE_LIMIT"
            assert evidence["status_before"]["security_ready"] is True
            assert evidence["status_after"]["security_ready"] is True
            assert evidence["preserved"]["no_execution_events"]
            assert rejected["cleanup"]["confirmed"] and rejected["security"]["keys_retired_on_host"]
            assert recovered["verification"]["bytes_equal"] and recovered["cleanup"]["confirmed"]
            assert recovered["security"]["key_set_id"] != rejected["security"]["key_set_id"]
            trace = host.radio.content(rejected["id"], "wire").read_text()
            assert '"name":"run.arm"' not in trace and '"name":"run.start"' not in trace
            assert '"tx_key_hex":' not in trace and '"rx_key_hex":' not in trace
            assert len(pair.frames) == 1
        finally:
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            await host.close()

    asyncio.run(scenario())
