"""The RF families share the procedure ledger and match settings by direction."""

import asyncio
import csv
import hashlib
import io
import json
import zipfile
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
            comparison = saved["sweep_comparison"]
            assert comparison["factor"] == "tx_power_dbm"
            assert len(comparison["settings"]) == 7
            [baseline] = comparison["baselines"]
            assert (
                baseline["settings_matched"]
                and baseline["changes"]["delivery_percent"]["delta"] == 0
            )
            with zipfile.ZipFile(io.BytesIO(host.procedures.bundle(saved))) as bundle:
                sample = bundle.read("rf-comparison.csv")
                rows = list(csv.DictReader(io.StringIO(sample.decode())))
                hashes = json.loads(bundle.read("manifest.json"))["sha256"]
            assert len(rows) == 7 and {row["direction"] for row in rows} == {"B_TO_A"}
            assert {float(row["delivery_percent"]) for row in rows} == {100}
            assert hashes["rf-comparison.csv"] == hashlib.sha256(sample).hexdigest()
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


def test_sweep_retains_bounded_non_delivery_with_complete_evidence(tmp_path, native_library):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library, drop="data")
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            spec = MatrixRequest(
                catalog_id="RF-02",
                groups=["C2"],
                directions=["A_TO_B"],
                repetitions=1,
                messages_per_case=1,
            )
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(55):
                await host.procedures.task
            result = host.procedures.get(started["id"])
            assert result["assessment"] == "pass" and len(result["cases"]) == 3, result
            first, *intact = result["cases"]
            report = first["measurements"]
            assert report["complete_observation_cohort"]
            assert report["observed_non_deliveries"] == 1 and report["unresolved_messages"] == 0
            assert report["unique_original_delivery_ratio"] == 0
            assert report["useful_bits_per_active_tx_second"] == 0
            assert report["signal_sample_count"] == 0 and report["rssi_dbm_median"] is None
            assert all(c["measurements"]["unique_original_delivery_ratio"] == 1 for c in intact)
            [identifier] = first["run_ids"]
            failed_delivery = host.radio.get(identifier)
            assert failed_delivery["verification"] is None
            assert failed_delivery["accounting"]["observed_delivery_failure"]
            assert failed_delivery["missing_evidence"]["missing_indexes"] == [0]
            assert failed_delivery["cleanup"]["confirmed"]
            assert not result["hardware_validated"]
        finally:
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            await host.close()

    asyncio.run(scenario())


def test_sweep_report_keeps_unresolved_observations_out_of_delivery_and_goodput():
    report = rf_sweeps.report([], 1)
    assert report["unresolved_messages"] == 1
    assert report["observed_non_deliveries"] == 0
    assert report["unique_original_delivery_ratio"] is None
    assert report["useful_bits_per_active_tx_second"] is None


def test_saved_comparison_preserves_individual_repetitions_and_matches_before_after():
    run = compile_matrix(MatrixRequest(catalog_id="RF-02", directions=["A_TO_B"]))
    for case in run["cases"]:
        case["status"] = "blocked"
        if case["value"] != 125000:
            continue
        if case["group"] == "C2" and case["repetition"] == 3:
            continue
        case["status"] = "completed"
        ratio = (
            1.0
            if case["group"] == "C1" or (case["group"] == "C2" and case["repetition"] == 1)
            else 0.0
        )
        case["measurements"] = {
            "sample_count": 100,
            "complete_observation_cohort": True,
            "unique_original_delivery_ratio": ratio,
        }
    comparison = rf_sweeps.compare_saved_cases(run)
    row = comparison["settings"][0]
    assert row["value"] == 125000
    assert row["ranges"]["delivery_percent"] == {"count": 2, "min": 0, "median": 50, "max": 100}
    assert [trial["values"]["delivery_percent"] for trial in row["repetitions"]] == [100, 0, None]
    assert row["ranges"]["rssi_dbm"] is None
    assert [pair["changes"]["delivery_percent"]["delta"] for pair in comparison["baselines"]] == [
        -100,
        -100,
        -100,
    ]
    changed = next(case for case in run["cases"] if case["group"] == "C3")
    changed["requested_settings"] = {"frequency_hz": 916000000}
    first = rf_sweeps.compare_saved_cases(run)["baselines"][0]
    assert not first["settings_matched"] and first["changes"]["delivery_percent"]["delta"] is None
