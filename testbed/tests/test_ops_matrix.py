"""Verify linked bench campaigns and their durable evidence through the shared runner."""

import asyncio
from copy import deepcopy

from test_multi_fragment_radio import Pair
from test_node_control_native import native_library as native_library

from lora_testbed import ops_matrix
from lora_testbed.host import Host
from lora_testbed.integration_matrices import MatrixRequest, compile_matrix


def test_ops_default_preserves_all_100_unique_linked_cases_and_bounds(tmp_path):
    host = Host(tmp_path)
    try:
        spec = MatrixRequest(catalog_id="OPS-01")
        plan = compile_matrix(spec)
        assert plan["full_plan"]
        stress = next(case for case in plan["cases"] if case["group"] == "C7")
        assert stress["planned_campaign_cases"] == 100
        campaign = host.campaign_plans.preview(ops_matrix.campaign_request(spec, stress))
        assert ops_matrix.verified_batches(campaign, 100)
        assert sum(case["required_nodes"] == 1 for case in campaign["cases"]) == 20
        assert sum(case["required_nodes"] == 2 for case in campaign["cases"]) == 80
        damaged = deepcopy(campaign)
        damaged["batches"][0]["duration_bound_s"] = 1801
        assert not ops_matrix.verified_batches(damaged, 100)
        damaged = deepcopy(campaign)
        damaged["batches"][0]["case_ids"][1] = damaged["batches"][0]["case_ids"][0]
        assert not ops_matrix.verified_batches(damaged, 100)
    finally:
        asyncio.run(host.close())


def test_ops_quick_campaign_verifies_local_and_paired_children_and_exports(
    tmp_path, native_library
):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library)
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            spec = MatrixRequest(
                catalog_id="OPS-01", groups=["C5", "C7"], messages_per_case=1, repetitions=1
            )
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(50):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert saved["status"] == "completed", saved
            assert not saved["hardware_validated"] and not saved["full_procedure_passed"]
            assert all(case["status"] == "blocked" for case in saved["cases"][:-1])
            case = saved["cases"][-1]
            assert case["assessment"] == "pass" and case["cleanup_verified"], case
            measurements = case["measurements"]
            assert measurements["completed_cases"] == measurements["planned_cases"] == 10
            assert measurements["verified_export"]["child_count"] == 26
            assert len(pair.frames) == 12
        finally:
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            await host.close()

    asyncio.run(scenario())
