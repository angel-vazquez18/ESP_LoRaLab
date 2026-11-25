"""Verify packet boundary and matched security cases through the shared runner."""

import asyncio
from collections import Counter

import pytest
from test_multi_fragment_radio import Pair
from test_node_control_native import native_library as native_library

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
                negative = [
                    e["document"]
                    for e in host.procedures.all_evidence(saved["id"])
                    if e["document"].get("source") == "read-only host preflight"
                ]
                assert len(negative) == 2 and all(e["rejection_observed"] for e in negative)
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
