"""Check declared numerical vectors and link them to real native TX evidence."""

import asyncio
import csv
import hashlib
import io
import json
import zipfile
from copy import deepcopy

from test_multi_fragment_radio import Pair
from test_node_control_native import native_library as native_library

from lora_testbed import model_series
from lora_testbed.host import Host
from lora_testbed.integration_matrices import MatrixRequest, compile_matrix


def test_model_plan_retains_factor_cross_product_and_golden_vectors():
    plan = compile_matrix(MatrixRequest(catalog_id="MODEL-01"))
    assert plan["full_plan"]
    reference = [case for case in plan["cases"] if case["group"] == "C1"]
    frames = [case for case in plan["cases"] if case["group"] == "C2"]
    assert len(reference) == 90 and len(frames) == 180
    assert all(case["message_count"] == 10 for case in frames)
    assert {case["expected_frame_bytes"] for case in reference} == {104, 120, 200, 216, 255}
    results = [model_series.reference_result(case) for case in reference]
    assert all(result["passed"] for result in results)
    assert {r["worksheet_airtime_us"] for r in results if r["worksheet_airtime_us"]} == {
        199936,
        343296,
        7872512,
    }
    assert {r["reference_ldro"] for r in results} == {False, True}
    reference_case = deepcopy(reference[0])
    reference_case["radio"]["preamble_symbols"] += 1
    assert model_series.reference_result(reference_case)["passed"]


def test_numerical_comparison_rejects_a_model_disagreement(tmp_path, monkeypatch):
    async def scenario():
        host = Host(tmp_path)
        try:
            spec = MatrixRequest(catalog_id="MODEL-01", groups=["C1"], subset_sizes=[64])
            assert not any(node.connected for node in host.physical.values())
            started = await host.start_procedure_matrix(spec)
            await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert saved["assessment"] == "fail"
            assert saved["mode"] == "numerical" and saved["physical_bindings"] == {}
            assert not saved["hardware_validated"]
            assert all(case["assessment"] == "fail" for case in saved["cases"])
            assert "model_comparison" not in saved
        finally:
            await host.close()

    monkeypatch.setattr(model_series, "airtime_us", lambda *_: 1)
    asyncio.run(scenario())


def test_isolated_frame_matrix_retains_proxy_residuals_instead_of_on_air_claim(
    tmp_path,
    native_library,
    monkeypatch,
):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library)
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            spec = MatrixRequest(
                catalog_id="MODEL-01",
                groups=["C2"],
                directions=["A_TO_B"],
                repetitions=1,
                messages_per_case=1,
            )
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(20):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert saved["assessment"] == "pass", saved
            assert not saved["full_procedure_passed"] and not saved["hardware_validated"]
            assert len(saved["cases"]) == 2
            for case, (_, transmitted) in zip(saved["cases"], pair.frames, strict=True):
                assert len(transmitted) == case["expected_frame_bytes"]
                assert case["measurements"]["sample_count"] == 1
                assert not case["measurements"]["on_air_marker_available"]
                assert not case["measurements"]["physical_agreement_assessed"]
                assert case["measurements"]["residual_us_median"] is not None
                [identifier] = case["run_ids"]
                assert host.radio.get(identifier)["verification"]["bytes_equal"]
            points = saved["model_comparison"]["points"]
            assert len(points) == 2
            for point in points:
                assert point["basis"] == "isolated_frame" and point["direction"] == "A_TO_B"
                assert point["residual_us"] == point["measured_us"] - point["predicted_us"]
            with zipfile.ZipFile(io.BytesIO(host.procedures.bundle(saved))) as archive:
                table = archive.read("model-comparison.csv")
                manifest = json.loads(archive.read("manifest.json"))["sha256"]
            rows = list(csv.DictReader(io.StringIO(table.decode())))
            assert len(rows) == 2 and {row["frame_bytes"] for row in rows} == {"104", "120"}
            assert manifest["model-comparison.csv"] == hashlib.sha256(table).hexdigest()
        finally:
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            await host.close()

    monkeypatch.setattr(model_series, "SPREADING", (7,))
    monkeypatch.setattr(model_series, "BANDWIDTH", (125000,))
    monkeypatch.setattr(model_series, "CODING", (5,))
    monkeypatch.setattr(model_series, "FRAME_PROFILES", ((64, "none"), (64, "aes128_gcm")))
    asyncio.run(scenario())


def test_message_model_reconciles_no_ack_ack_and_one_observed_retry(tmp_path, native_library):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library, lab=True)
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            spec = MatrixRequest(
                catalog_id="MODEL-01",
                groups=["C3"],
                directions=["A_TO_B"],
                repetitions=1,
                messages_per_case=1,
                subset_sizes=[64],
            )
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(25):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert saved["assessment"] == "pass", saved
            evidence = [
                row["document"]["message_observation"]
                for row in host.procedures.all_evidence(saved["id"])
                if "message_observation" in row["document"]
            ]
            assert [row["original_data_frames"] for row in evidence] == [1, 1, 1]
            assert [row["data_attempts"] for row in evidence] == [1, 1, 2]
            assert [row["confirmed_ack_transmissions"] for row in evidence] == [0, 1, 1]
            assert evidence[-1]["controlled_retry_checks"]
            assert all(row["within_expanded_budget"] for row in evidence)
            assert not any(row["physical_agreement_assessed"] for row in evidence)
            points = saved["model_comparison"]["points"]
            assert {point["configuration"] for point in points} == {
                "bytes_64_none",
                "bytes_64_ack",
                "bytes_64_controlled_retry",
            }
            assert all(point["basis"] == "sender_completion" for point in points)
            assert all(point["security"] == "aes128_gcm" for point in points)
            for point, record in zip(points, evidence, strict=True):
                assert point["predicted_us"] == record["modeled_nominal_sender_us"]
                assert point["measured_us"] == record["observed_sender_completion_us"]
                assert point["expanded_run_budget_us"] == record["modeled_worst_case_run_us"]
        finally:
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            await host.close()

    asyncio.run(scenario())
