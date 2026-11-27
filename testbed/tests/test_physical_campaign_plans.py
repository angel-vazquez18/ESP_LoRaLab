"""Physical campaign plans persist exact intent without opening ports or executing."""

import pytest
from fastapi.testclient import TestClient
from test_node_control_native import native_library as native_library

from lora_testbed.app import create_app


def mixed_plan(**updates):
    return {
        "name": "Mixed local and RF checks",
        "repetitions": 2,
        "directions": ["A_TO_B", "B_TO_A"],
        "order": "randomized",
        "order_seed": 19,
        "templates": [
            {
                "label": "memory",
                "case": {
                    "kind": "memory_probe",
                    "role": "B",
                    "iterations": 2,
                    "payload_bytes": 1024,
                },
            },
            {
                "label": "radio",
                "case": {
                    "kind": "known_data",
                    "request": {"message_bytes": 64, "source_seed": 4294967295},
                },
            },
        ],
        **updates,
    }


def test_save_reload_preserves_seeded_order_case_links_and_single_vs_pair_requirements(tmp_path):
    with TestClient(create_app(data_dir=tmp_path)) as client:
        preview = client.post("/api/physical-campaigns/plans/preview", json=mixed_plan())
        assert preview.status_code == 200, preview.text
        document = preview.json()
        assert document["case_count"] == 6
        assert document["mode"] == "hardware" and document["execution_available"]
        for case in document["cases"]:
            if case["case"]["kind"] == "memory_probe":
                assert case["required_nodes"] == 1 and case["roles"] == ["B"]
                assert case["direction"] is None
            else:
                assert case["required_nodes"] == 2 and case["roles"] == ["A", "B"]
                assert case["case"]["request"]["source_seed"] == (
                    4294967295 if case["repetition"] == 1 else 0
                )
        again = client.post("/api/physical-campaigns/plans/preview", json=mixed_plan()).json()

        def order(value):
            return [
                (case["template_index"], case["repetition"], case["direction"])
                for case in value["cases"]
            ]

        assert order(document) == order(again)
        saved_response = client.post("/api/physical-campaigns/plans", json=mixed_plan())
        assert saved_response.status_code == 201, saved_response.text
        saved = saved_response.json()
        assert order(saved) == order(document)
        assert len({case["id"] for case in saved["cases"]}) == 6
        assert saved["batches"][0]["case_ids"] == [case["id"] for case in saved["cases"]]
        assert not any(node["connected"] for node in client.get("/api/state").json()["nodes"])
    with TestClient(create_app(data_dir=tmp_path)) as client:
        reloaded = client.get(f"/api/physical-campaigns/plans/{saved['id']}")
        assert reloaded.status_code == 200 and reloaded.json() == saved


def test_over_budget_totals_split_into_linked_batches_without_dropping_cases(tmp_path):
    spec = mixed_plan(
        repetitions=100,
        templates=[{"label": "memory", "case": {"kind": "memory_probe", "iterations": 1}}],
    )
    with TestClient(create_app(data_dir=tmp_path)) as client:
        response = client.post("/api/physical-campaigns/plans", json=spec)
        assert response.status_code == 201, response.text
        plan = response.json()
        assert plan["case_count"] == 100 and plan["duration_bound_s"] == 5000
        assert [batch["case_count"] for batch in plan["batches"]] == [36, 36, 28]
        assert all(
            batch["case_count"] <= 64 and batch["duration_bound_s"] <= 1800
            for batch in plan["batches"]
        )
        assert [identifier for batch in plan["batches"] for identifier in batch["case_ids"]] == [
            case["id"] for case in plan["cases"]
        ]
        for index, batch in enumerate(plan["batches"]):
            assert batch["parent_plan_id"] == plan["id"]
            assert batch["previous_batch_id"] == (
                plan["batches"][index - 1]["id"] if index else None
            )
            assert batch["next_batch_id"] == (
                plan["batches"][index + 1]["id"] if index + 1 < 3 else None
            )


def test_single_node_b_is_sufficient_for_local_case_and_rf_stays_blocked(native_library, tmp_path):
    from test_node_control_native import NativeSerial

    with TestClient(create_app(data_dir=tmp_path)) as client:
        host = client.app.state.host
        serial = NativeSerial(native_library, radio=native_library.native_radio_create())
        host.physical["B"].opener = lambda _: serial
        client.portal.call(host.physical["B"].connect, "isolated-plan-node-b")
        response = client.post(
            "/api/physical-campaigns/plans/preview", json=mixed_plan(repetitions=1)
        )
        assert response.status_code == 200, response.text
        cases = response.json()["cases"]
        local = next(case for case in cases if case["case"]["kind"] == "memory_probe")
        radios = [case for case in cases if case["case"]["kind"] == "known_data"]
        assert local["hardware_preflight"]["ready"] and local["roles"] == ["B"]
        assert all(not case["hardware_preflight"]["ready"] for case in radios)
        assert all(
            any(
                "A" in reason and "disconnected" in reason
                for reason in case["hardware_preflight"]["blockers"]
            )
            for case in radios
        )


def test_all_23_procedures_remain_in_plan_and_case_count_splits_at_64(tmp_path):
    ids = [
        "IF-01",
        "IF-02",
        "IF-03",
        "RF-01",
        "RF-02",
        "RF-03",
        "RF-04",
        "SEC-01",
        "SEC-02",
        "SEC-03",
        "SEC-04",
        "PKT-01",
        "PKT-02",
        "PKT-03",
        "TIME-01",
        "TIME-02",
        "MEM-01",
        "VOICE-01",
        "VOICE-02",
        "VOICE-03",
        "VOICE-04",
        "MODEL-01",
        "OPS-01",
    ]
    templates = [
        {"label": code, "case": {"kind": "procedure", "catalog_id": code, "budget_s": 1}}
        for code in ids
    ]
    templates += [
        {
            "label": code + "-rf",
            "case": {"kind": "procedure", "catalog_id": code, "workload": "rf", "budget_s": 1},
        }
        for code in ("MEM-01", "OPS-01")
    ]
    spec = mixed_plan(repetitions=3, order="sequential", templates=templates)
    with TestClient(create_app(data_dir=tmp_path)) as client:
        response = client.post("/api/physical-campaigns/plans", json=spec)
        assert response.status_code == 201, response.text
        plan = response.json()
        assert plan["case_count"] == 75
        assert [batch["case_count"] for batch in plan["batches"]] == [64, 11]
        assert {case["catalog_id"] for case in plan["cases"]} == set(ids)
        local = {"IF-01", "SEC-04", "MEM-01", "VOICE-01", "OPS-01"}
        for case in plan["cases"]:
            expected = 1 if case["catalog_id"] in local and case["case"]["workload"] != "rf" else 2
            assert case["required_nodes"] == expected
            assert not case["hardware_preflight"]["ready"]
            assert any(
                "procedure" in reason.lower() for reason in case["hardware_preflight"]["blockers"]
            )
        assert plan["execution_available"] and not plan["hardware_qualified"]


def test_existing_audio_voice_and_diagnostic_settings_are_typed_and_preserved(tmp_path):
    templates = [
        {"label": "memory", "case": {"kind": "memory_probe", "role": "B"}},
        {"label": "data", "case": {"kind": "known_data"}},
        {"label": "voice", "case": {"kind": "voice", "request": {"source": "microphone"}}},
        {
            "label": "capture",
            "case": {"kind": "audio", "role": "B", "action": "capture", "sample_count": 8000},
        },
        {
            "label": "crypto",
            "case": {"kind": "crypto_benchmark", "request": {"iterations": 2, "payload_bytes": 64}},
        },
        {"label": "serial", "case": {"kind": "serial_check", "role": "B", "cycles": 2}},
        {"label": "timing", "case": {"kind": "procedure", "catalog_id": "TIME-01", "budget_s": 1}},
    ]
    with TestClient(create_app(data_dir=tmp_path)) as client:
        response = client.post(
            "/api/physical-campaigns/plans", json=mixed_plan(repetitions=1, templates=templates)
        )
        assert response.status_code == 201, response.text
        plan = response.json()
        assert plan["case_count"] == 9
        assert plan["duration_bound_s"] == 1461
        assert sum(case["case"]["kind"] == "voice" for case in plan["cases"]) == 2
        audio = next(case for case in plan["cases"] if case["case"]["kind"] == "audio")
        assert audio["case"]["sample_count"] == 8000 and audio["roles"] == ["B"]
        crypto = next(case for case in plan["cases"] if case["case"]["kind"] == "crypto_benchmark")
        assert crypto["case"]["request"] == {"iterations": 2, "payload_bytes": 64}
        assert all(not case["hardware_preflight"]["ready"] for case in plan["cases"])
        assert plan["execution_available"]


def test_plan_listing_cli_and_hashes_use_the_same_saved_physical_intent(tmp_path, monkeypatch):
    import hashlib
    import json

    from typer.testing import CliRunner

    from lora_testbed import cli

    path = tmp_path / "physical-plan.json"
    path.write_text(json.dumps(mixed_plan()))
    calls = []
    monkeypatch.setattr(cli, "request", lambda endpoint, body=None: calls.append((endpoint, body)))
    runner = CliRunner()
    assert runner.invoke(cli.app, ["campaign-plan", str(path), "--preview"]).exit_code == 0
    assert calls[-1] == ("/api/physical-campaigns/plans/preview", mixed_plan())
    assert runner.invoke(cli.app, ["campaign-plan", str(path)]).exit_code == 0
    assert calls[-1][0] == "/api/physical-campaigns/plans"
    with TestClient(create_app(data_dir=tmp_path / "backend")) as client:
        record = client.post("/api/physical-campaigns/plans", json=mixed_plan()).json()
        summary = client.get("/api/physical-campaigns/plans")
        assert summary.status_code == 200
        assert summary.json()["plans"][0]["id"] == record["id"]
        assert "cases" not in summary.json()["plans"][0]
        assert (
            record["spec_sha256"]
            == hashlib.sha256(
                json.dumps(record["spec"], sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
        expected = record.pop("plan_sha256")
        assert (
            expected
            == hashlib.sha256(
                json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
        assert record["planner_source_sha256"]
        assert record["spec_schema_sha256"]
        assert not client.get("/api/state").json()["bench_busy"]


def test_saved_order_uses_the_declared_stable_seed_vector_and_changes_with_seed(tmp_path):
    with TestClient(create_app(data_dir=tmp_path)) as client:
        first = client.post(
            "/api/physical-campaigns/plans/preview", json=mixed_plan(order_seed=19)
        ).json()
        second = client.post(
            "/api/physical-campaigns/plans/preview", json=mixed_plan(order_seed=20)
        ).json()
        assert first["order_algorithm"] == "sha256_seed_and_canonical_index_v1"
        assert [case["canonical_index"] for case in first["cases"]] == [2, 0, 5, 4, 3, 1]
        assert [case["canonical_index"] for case in second["cases"]] == [5, 2, 1, 3, 4, 0]
        assert [case["canonical_index"] for case in first["cases"]] != [
            case["canonical_index"] for case in second["cases"]
        ]
        assert sorted(case["canonical_index"] for case in first["cases"]) == list(range(6))


def test_duplicate_device_identities_never_make_a_two_role_rf_case_ready(native_library, tmp_path):
    from test_node_control_native import NativeSerial

    with TestClient(create_app(data_dir=tmp_path)) as client:
        host = client.app.state.host
        for role in ("A", "B"):
            serial = NativeSerial(native_library, radio=native_library.native_radio_create())
            host.physical[role].opener = lambda _, selected=serial: selected
            client.portal.call(host.physical[role].connect, "isolated-duplicate-" + role)
        response = client.post(
            "/api/physical-campaigns/plans/preview", json=mixed_plan(repetitions=1)
        )
        assert response.status_code == 200, response.text
        radios = [case for case in response.json()["cases"] if case["case"]["kind"] == "known_data"]
        assert all(not case["hardware_preflight"]["ready"] for case in radios)
        assert all(
            any("distinct" in reason for reason in case["hardware_preflight"]["blockers"])
            for case in radios
        )


def test_atomic_over_budget_or_oversized_total_is_rejected_without_saving_partial_plan(tmp_path):
    with TestClient(create_app(data_dir=tmp_path)) as client:
        too_long = mixed_plan(
            templates=[
                {
                    "label": "long radio",
                    "case": {"kind": "known_data", "request": {"timeout_ms": 3600000}},
                }
            ]
        )
        response = client.post("/api/physical-campaigns/plans", json=too_long)
        assert response.status_code == 400 and "atomic" in response.text.lower()
        too_many = mixed_plan(
            repetitions=100,
            templates=[
                {"label": f"memory-{index}", "case": {"kind": "memory_probe"}}
                for index in range(64)
            ],
        )
        response = client.post("/api/physical-campaigns/plans", json=too_many)
        assert response.status_code == 400 and "4096" in response.text
        assert client.get("/api/physical-campaigns/plans").json()["plans"] == []


def test_historical_interrupted_and_blocked_campaign_cases_are_preserved(tmp_path):
    from uuid import uuid4

    from lora_testbed.storage import Store, utc_now

    original = {
        "id": str(uuid4()),
        "created_at": utc_now(),
        "name": "historical fixture",
        "status": "interrupted",
        "cases": [{"status": "blocked", "run_id": None}],
    }
    store = Store(tmp_path)
    store.save_campaign(original)
    store.close()
    with TestClient(create_app(data_dir=tmp_path)) as client:
        assert client.post("/api/physical-campaigns/plans", json=mixed_plan()).status_code == 201
        assert client.app.state.host.store.campaign(original["id"]) == original
        assert client.post("/api/campaigns", json={}).status_code == 410


@pytest.mark.parametrize(
    "changes",
    [
        {"repetitions": 0},
        {"repetitions": True},
        {"directions": ["A_TO_B", "A_TO_B"]},
        {
            "templates": [
                {"label": "x", "case": {"kind": "memory_probe"}},
                {"label": "x", "case": {"kind": "memory_probe"}},
            ]
        },
        {"templates": [{"label": "unknown", "case": {"kind": "simulated_radio"}}]},
        {
            "templates": [
                {
                    "label": "bad RF",
                    "case": {"kind": "known_data", "request": {"radio": {"spreading_factor": 6}}},
                }
            ]
        },
        {"templates": [{"label": "missing file", "case": {"kind": "audio", "action": "play"}}]},
        {
            "templates": [
                {
                    "label": "wrong params",
                    "case": {
                        "kind": "audio",
                        "action": "capture",
                        "artifact_id": "11111111-1111-4111-8111-111111111111",
                    },
                }
            ]
        },
        {
            "templates": [
                {
                    "label": "bad crypto",
                    "case": {"kind": "crypto_benchmark", "request": {"payload_bytes": 65}},
                }
            ]
        },
        {
            "templates": [
                {"label": "bad procedure", "case": {"kind": "procedure", "catalog_id": "UNKNOWN"}}
            ]
        },
        {
            "templates": [
                {
                    "label": "wrong scope",
                    "case": {"kind": "procedure", "catalog_id": "TIME-02", "workload": "local"},
                }
            ]
        },
        {
            "templates": [
                {
                    "label": "duplicate roles",
                    "case": {"kind": "procedure", "catalog_id": "IF-02", "roles": ["A", "A"]},
                }
            ]
        },
    ],
)
def test_invalid_physical_intent_is_rejected_before_any_plan_or_work(tmp_path, changes):
    with TestClient(create_app(data_dir=tmp_path)) as client:
        response = client.post("/api/physical-campaigns/plans", json=mixed_plan(**changes))
        assert response.status_code == 422, response.text
        assert client.get("/api/physical-campaigns/plans").json()["plans"] == []
        assert not client.get("/api/state").json()["bench_busy"]


def test_private_key_fields_are_rejected_without_echo_or_persistence(tmp_path):
    sentinel = "29" * 16
    spec = mixed_plan(
        templates=[
            {
                "label": "private",
                "case": {"kind": "known_data", "request": {"tx_key_hex": sentinel}},
            }
        ]
    )
    with TestClient(create_app(data_dir=tmp_path)) as client:
        response = client.post("/api/physical-campaigns/plans", json=spec)
        assert response.status_code == 422 and sentinel not in response.text
        assert client.get("/api/physical-campaigns/plans").json()["plans"] == []


def test_documented_example_is_a_valid_nine_case_offline_plan(tmp_path):
    import json

    from lora_testbed.paths import REPOSITORY_ROOT

    example = json.loads(
        (REPOSITORY_ROOT / "testbed/examples/local_and_radio_plan.json").read_text()
    )
    with TestClient(create_app(data_dir=tmp_path)) as client:
        response = client.post("/api/physical-campaigns/plans/preview", json=example)
        assert response.status_code == 200, response.text
        assert response.json()["case_count"] == 9
        assert response.json()["duration_bound_s"] == 600
        assert response.json()["execution_available"]
