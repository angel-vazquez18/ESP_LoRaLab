"""Bounded read-only dashboard projections share the physical campaign owner."""

from fastapi.testclient import TestClient
from test_campaign_reruns_evidence import connect, plan, start
from test_node_control_native import native_library as native_library
from test_physical_campaign_execution import wait_for

from lora_testbed.app import create_app


def test_saved_plan_pages_show_current_requirements_without_rewriting_cached_intent(
    native_library, tmp_path
):
    with TestClient(create_app(data_dir=tmp_path)) as client:
        saved = plan(client)
        path = f"/api/physical-campaigns/plans/{saved['id']}/view"
        response = client.get(path)
        assert response.status_code == 200, response.text
        assert not any(row["readiness"]["ready"] for row in response.json()["cases"]["rows"])
        connect(client, native_library)
        current = client.get(path).json()
        assert all(row["readiness"]["ready"] for row in current["cases"]["rows"])
        assert current["record"]["plan_sha256"] == saved["plan_sha256"]
        assert client.get(f"/api/physical-campaigns/plans/{saved['id']}").json() == saved


def test_long_plan_and_execution_views_bound_rows_without_losing_case_identity(tmp_path):
    with TestClient(create_app(data_dir=tmp_path)) as client:
        saved = client.post(
            "/api/physical-campaigns/plans",
            json={
                "name": "Long dashboard ledger",
                "repetitions": 100,
                "templates": [{"label": "B", "case": {"kind": "memory_probe", "role": "B"}}],
            },
        ).json()
        result = start(client, saved)
        assert result["status"] == "blocked"
        for kind, identifier, source in (
            ("plans", saved["id"], saved),
            ("executions", result["id"], result),
        ):
            path = f"/api/physical-campaigns/{kind}/{identifier}/view"
            response = client.get(path + "?offset=32")
            assert response.status_code == 200, response.text
            view = response.json()
            assert view["cases"]["offset"] == 32 and view["cases"]["total"] == 100
            assert len(view["cases"]["rows"]) == 32 and view["cases"]["next_offset"] == 64
            key = "id" if kind == "plans" else "case_id"
            assert [row[key] for row in view["cases"]["rows"]] == [
                row[key] for row in source["cases"][32:64]
            ]
            assert "selected_case_ids" not in view["record"]
            assert client.get(path + "?offset=-1").status_code == 422
            assert client.get(path + "?offset=4097").status_code == 422
        assert client.get(f"/api/physical-campaigns/executions/{result['id']}").json() == result


def test_repeated_active_view_reads_never_start_duplicate_children(native_library, tmp_path):
    with TestClient(create_app(data_dir=tmp_path)) as client:
        connect(client, native_library)
        saved = plan(client, (512,), iterations=10000)
        started = client.post(
            "/api/physical-campaigns/executions", json={"plan_id": saved["id"]}
        ).json()
        identifier = started["id"]
        original = wait_for(client, identifier, lambda row: row["cases"][0]["child"] is not None)
        for _ in range(3):
            response = client.get(f"/api/physical-campaigns/executions/{identifier}/view")
            assert response.status_code == 200, response.text
            assert response.json()["cases"]["rows"][0]["child"] == original["cases"][0]["child"]
            state = client.get("/api/state").json()["physical_campaigns"]["active"]
            assert "selected_case_ids" not in state and "host_sources" not in state
        assert len(client.app.state.host.diagnostics.snapshot()["runs"]) == 1
        client.post(
            f"/api/physical-campaigns/executions/{identifier}/cancel", json={}
        ).raise_for_status()
