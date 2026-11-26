"""Verify linked bench campaigns and their durable evidence through the shared runner."""

import asyncio
import hashlib
import io
import json
import zipfile
from copy import deepcopy
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from test_multi_fragment_radio import Pair
from test_node_control_native import native_library as native_library

from lora_testbed import ops_matrix
from lora_testbed.app import create_app
from lora_testbed.campaign_plans import CampaignSpec
from lora_testbed.host import Host
from lora_testbed.integration_matrices import MatrixRequest, compile_matrix


def test_ops_default_preserves_all_100_unique_linked_cases_and_bounds(tmp_path):
    host = Host(tmp_path)
    try:
        spec = MatrixRequest(catalog_id="OPS-01")
        plan = compile_matrix(spec)
        assert plan["full_plan"]
        stability = [case for case in plan["cases"] if case["group"] == "C6"]
        assert len(stability) == 4
        assert all(
            case["observation_s"] == 3600 and case["firmware_health_hz"] == 1 for case in stability
        )
        assert {case["radio_load_period_s"] for case in stability} == {None, 60}
        restart = [case for case in plan["cases"] if case["group"] == "C3"]
        assert len(restart) == 12
        assert len({(row["variant"], row["direction"], row["repetition"]) for row in restart}) == 12
        assert not compile_matrix(spec.model_copy(update={"ops_observation_s": 5}))["full_plan"]
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
                catalog_id="OPS-01", groups=["C3", "C7"], messages_per_case=1, repetitions=1
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


@pytest.mark.parametrize("stop_during_load", [False, True])
def test_ops_stability_tracks_passive_health_and_owns_loaded_transfer_cleanup(
    tmp_path, native_library, stop_during_load
):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library)
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            spec = MatrixRequest(
                catalog_id="OPS-01",
                groups=["C6"],
                directions=["B_TO_A"],
                ops_observation_s=7,
            )
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(25):
                if stop_during_load:
                    while not host.radio.busy:
                        await asyncio.sleep(0.02)
                    await host.procedures.stop(expected_run_id=started["id"])
                else:
                    await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert not saved["hardware_validated"] and not saved["full_procedure_passed"]
            idle, loaded = saved["cases"]
            assert idle["assessment"] == "pass" and idle["cleanup_verified"], idle
            assert not idle["run_ids"] and idle["measurements"]["planned_loads"] == 0
            assert all(
                metrics["samples"] >= 5 and metrics["max_gap_us"] < 2_000_000
                for metrics in idle["measurements"]["health"].values()
            )
            assert loaded["cleanup_verified"], loaded
            [identifier] = loaded["run_ids"]
            child = host.radio.get(identifier)
            if stop_during_load:
                assert saved["status"] == loaded["status"] == child["status"] == "cancelled"
            else:
                assert saved["status"] == "completed" and loaded["assessment"] == "pass", loaded
                assert loaded["measurements"]["verified_loads"] == 1
                assert child["verification"]["bytes_equal"]
                assert [role for role, _ in pair.frames] == ["B"]
            assert child["cleanup"]["confirmed"]
            assert all(
                not node.rf_run_id and node.health.state == "idle"
                for node in host.physical.values()
            )
            records = [row["document"] for row in host.procedures.all_evidence(saved["id"])]
            assert any("host_peak_rss_bytes" in row for row in records)
            assert any("final_status" in row for row in records)
            assert all(
                row["document"]["name"] == "health"
                for batch in records
                for row in batch.get("periodic_health", [])
            )
            with zipfile.ZipFile(io.BytesIO(host.procedures.bundle(saved))) as archive:
                names = json.loads(archive.read("manifest.json"))["sha256"]
                digest = hashlib.sha256(archive.read("evidence.jsonl")).hexdigest()
            assert names["evidence.jsonl"] == digest
        finally:
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            await host.close()

    asyncio.run(scenario())


def test_ops_control_faults_preserve_configuration_and_recover_in_both_directions(
    tmp_path, native_library
):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library)
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            spec = MatrixRequest(catalog_id="OPS-01", groups=["C4"], repetitions=1)
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(35):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert saved["status"] == "completed" and saved["assessment"] == "pass", saved
            assert len(saved["cases"]) == 4
            for case in saved["cases"]:
                assert case["cleanup_verified"]
                result = case["measurements"]
                assert result["target_role"] == case["direction"][0]
                before, after = [host.radio.get(identifier) for identifier in case["run_ids"]]
                assert before["session_id"] != after["session_id"]
                assert before["verification"]["sha256"] == after["verification"]["sha256"]
                assert (
                    before["verification"]["bytes_equal"] and after["verification"]["bytes_equal"]
                )
                control = result["control"]
                if case["variant"] == "invalid_configuration":
                    assert control["observed_error"] == "INVALID_ARGUMENT"
                    assert control["configuration_before"] == control["configuration_after"]
                else:
                    assert control["timed_out"] and len(control["operation_results"]) == 1
            assert [role for role, _ in pair.frames] == ["A", "A", "B", "B"] * 2
        finally:
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            await host.close()

    asyncio.run(scenario())


def test_ops_receive_gap_preserves_verified_bytes_and_excludes_rf_loss(tmp_path, native_library):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library)
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            spec = MatrixRequest(catalog_id="OPS-01", groups=["C5"], repetitions=1)
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(35):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert saved["status"] == "completed" and saved["assessment"] == "pass", saved
            assert len(saved["cases"]) == 2
            for case in saved["cases"]:
                assert case["cleanup_verified"] and case["assessment"] == "pass", case
                result = case["measurements"]
                assert result["excluded_from_rf_loss_analysis"] and result["verified_recovery"]
                before, trial, after = [
                    host.radio.get(identifier) for identifier in case["run_ids"]
                ]
                assert len({child["session_id"] for child in (before, trial, after)}) == 3
                assert before["status"] == after["status"] == "completed"
                assert trial["status"] == "failed" and trial["cleanup"]["confirmed"]
                assert all(child["verification"]["bytes_equal"] for child in (before, trial, after))
                assert (
                    len({child["verification"]["sha256"] for child in (before, trial, after)}) == 1
                )
                accounting = trial["accounting"]
                assert accounting["reason_code"] == "telemetry_gap"
                assert accounting["evidence_complete"] is False
                assert "unique_original_delivery_ratio" not in accounting
                assert "goodput_bps" not in accounting
                fixture = result["fixture"]
                receiver = trial["receiver"]
                assert (
                    fixture["role"] == receiver and fixture["omitted_event"]["name"] == "rx.frame"
                )
                assert fixture["omitted_event"]["run_id"] == trial["id"]
                assert fixture["deltas"][receiver] == {
                    "event_gaps": 1,
                    "framing_errors": 0,
                    "telemetry_drops": 0,
                }
                assert not any(
                    event["role"] == receiver and event["name"] == "rx.frame"
                    for event in trial["events"]
                )
            assert [role for role, _ in pair.frames] == ["A"] * 3 + ["B"] * 3
            assert all(not node.rf_run_id for node in host.physical.values())
        finally:
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            await host.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("variant", "direction"), [("restart_active", "A_TO_B"), ("restart_paused", "B_TO_A")]
)
def test_ops_restart_checks_saved_checkpoint_and_explicit_fresh_campaign(
    tmp_path, native_library, variant, direction
):
    async def scenario():
        before = Host(tmp_path)
        pair = Pair(before, native_library)
        await pair.connect()
        bridge = None
        try:
            if variant == "restart_paused":
                bridge = asyncio.create_task(pair.bridge())
            plan = before.campaign_plans.create(
                CampaignSpec.model_validate(
                    {
                        "name": "Restart test",
                        "repetitions": 2,
                        "directions": [direction],
                        "templates": [
                            {
                                "label": "known data",
                                "case": {"kind": "known_data"},
                            }
                        ],
                    }
                )
            )
            started = await before.start_campaign(plan["id"])
            identifier = started["id"]
            async with asyncio.timeout(5):
                while not before.radio.current or before.radio.current["stage"] != "transmitting":
                    await asyncio.sleep(0.005)
                if variant == "restart_paused":
                    before.physical_campaigns.pause(identifier)
                    while before.physical_campaigns.current["status"] != "paused":
                        await asyncio.sleep(0.005)
        finally:
            await before.close()
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)

        app = create_app(tmp_path)
        async with app.router.lifespan_context(app):
            host = app.state.host
            campaigns = host.physical_campaigns
            original = campaigns.get(identifier)
            assert original["status"] == "interrupted"
            assert original["reason_code"] == "host_shutdown"
            assert not host.busy and not any(node.connected for node in host.physical.values())
            with pytest.raises(ValueError, match="not active"):
                campaigns.resume(identifier)
            case_id = original["cases"][0]["case_id"]
            new_pair = Pair(host, native_library)
            await new_pair.connect()
            bridge = asyncio.create_task(new_pair.bridge())
            try:
                fresh = await host.rerun_campaign(identifier, [case_id])
                async with asyncio.timeout(8):
                    await campaigns.task
            finally:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            assert [role for role, _ in new_pair.frames] == [direction[0]]
            assert campaigns.get(fresh["id"])["status"] == "completed"
            for node in host.physical.values():
                await node.close()
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://127.0.0.1"
            ) as ui:
                endpoint = "/api/procedures/matrix"
                arguments = {"catalog_id": "OPS-01", "groups": ["C3"], "repetitions": 1}
                plan = (await ui.post(f"{endpoint}/preview", json=arguments)).json()
                assert plan["ready_case_count"] == 0 and plan["case_count"] == 4
                arguments["ops_restart_evidence"] = [
                    {
                        "variant": variant,
                        "direction": direction,
                        "repetition": 1,
                        "interrupted": identifier,
                        "recovery": str(uuid4()),
                    }
                ]
                missing = (await ui.post(f"{endpoint}/preview", json=arguments)).json()
                assert missing["ready_case_count"] == 0
                assert ["Unknown physical campaign execution"] in [
                    row["blockers"] for row in missing["cases"]
                ]
                arguments["ops_restart_evidence"][0]["recovery"] = fresh["id"]
                plan = (await ui.post(f"{endpoint}/preview", json=arguments)).json()
                assert plan["ready_case_count"] == 1
                accepted = await ui.post(
                    f"{endpoint}?expected_plan_sha256={plan['sha256']}",
                    json=arguments,
                )
                assert accepted.status_code == 202, accepted.json()
                async with asyncio.timeout(5):
                    await host.procedures.task
                saved = host.procedures.get(accepted.json()["id"])
                [case] = [row for row in saved["cases"] if row["status"] != "blocked"]
                assert case["assessment"] == "pass" and case["cleanup_verified"], case
                assert case["campaign_ids"] == [identifier, fresh["id"]]
                assert case["measurements"]["verification"]["bytes_equal"]
                assert not saved["hardware_validated"] and not saved["full_procedure_passed"]
                assert not host.busy and not saved["physical_bindings"]
                damaged = host.radio.content(case["run_ids"][-1], "recovered")
                damaged.write_bytes(b"unexpected")
                accepted = await ui.post(endpoint, json=arguments)
                assert accepted.status_code == 202
                async with asyncio.timeout(5):
                    await host.procedures.task
                rejected = host.procedures.get(accepted.json()["id"])
                [case] = [row for row in rejected["cases"] if row["status"] != "blocked"]
                assert case["assessment"] == "inconclusive" and "integrity" in case["reason"]

    asyncio.run(scenario())
