"""The RF families share the procedure ledger and match settings by direction."""

import asyncio
from copy import deepcopy

import pytest
from test_multi_fragment_radio import Pair
from test_node_control_native import native_library as native_library

from lora_testbed import rf_sweeps
from lora_testbed.host import Host
from lora_testbed.integration_matrices import MatrixRequest, compile_matrix, link_request


@pytest.mark.parametrize(
    "identifier,count", [("RF-01", 6), ("RF-02", 3), ("RF-03", 4), ("RF-04", 7)]
)
def test_sweep_retains_matched_randomized_conditions_and_baselines(identifier, count):
    spec = MatrixRequest(catalog_id=identifier)
    plan = compile_matrix(spec)
    assert plan["full_plan"]
    for repetition in range(1, 4):
        relevant = [c for c in plan["cases"] if c["repetition"] == repetition]
        before, after = [], []
        for direction, results in zip(("A_TO_B", "B_TO_A"), (before, after), strict=True):
            cohort = [c for c in relevant if c["direction"] == direction]
            assert len(cohort) == count + 2
            assert cohort[0]["group"] == "C1" and cohort[-1]["group"] == "C3"
            assert cohort[0]["value"] == cohort[-1]["value"]
            results.extend((c["value"], link_request(spec, c, 3).source_seed) for c in cohort)
        assert before == after
    assert plan["sha256"] == compile_matrix(spec)["sha256"]


def test_power_sweep_changes_only_transmitter_and_projects_actual_observations(
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
                catalog_id="RF-04", directions=["B_TO_A"], repetitions=1, messages_per_case=1
            )
            record = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(30):
                await host.procedures.task
            saved = host.procedures.get(record["id"])
            assert saved["status"] == "completed" and saved["assessment"] == "pass", saved
            assert len(saved["cases"]) == 9
            predictions = set()
            for case in saved["cases"]:
                assert case["measurements"]["sample_count"] == 1
                assert case["measurements"]["rssi_dbm_median"] is not None
                predictions.add(case["measurements"]["predicted_airtime_us_median"])
                child = host.radio.get(case["run_ids"][0])
                assert child["applied_settings"]["B"]["radio"]["tx_power_dbm"] == case["value"]
                assert child["applied_settings"]["A"]["radio"]["tx_power_dbm"] == 2
                no_rx = deepcopy(child)
                no_rx["events"] = [e for e in no_rx["events"] if e["name"] != "rx.frame"]
                assert rf_sweeps.observation(no_rx) is None
            assert len(predictions) == 1
            assert not saved["hardware_validated"]
        finally:
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            await host.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("identifier", ["RF-01", "RF-02", "RF-03"])
def test_sweep_applies_each_value_without_changing_other_fields(
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
                directions=["A_TO_B"],
                repetitions=1,
                messages_per_case=1,
                groups=["C2"],
            )
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(20):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert saved["assessment"] == "pass", saved
            field, values, _ = rf_sweeps.FACTORS[identifier]
            assert {row["value"] for row in saved["cases"]} == set(values)
            applied = []
            predictions = []
            for row in saved["cases"]:
                child = host.radio.get(row["run_ids"][0])
                values_by_role = [child["applied_settings"][role]["radio"] for role in "AB"]
                assert values_by_role[0] == values_by_role[1]
                assert values_by_role[0][field] == row["value"]
                observed = dict(values_by_role[0])
                observed.pop(field)
                observed.pop("ldro_enabled")
                applied.append(observed)
                predictions.append(row["measurements"]["predicted_airtime_us_median"])
                assert row["measurements"]["sample_count"] == 1
                assert row["child_budget"]["reassembly_timeout_us"] > predictions[-1]
            assert all(item == applied[0] for item in applied)
            assert len(set(predictions)) == len(values)
        finally:
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            await host.close()

    asyncio.run(scenario())
