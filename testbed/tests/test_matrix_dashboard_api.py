"""Dashboard and CLI use a shared plan, readiness and durable procedure record."""

import asyncio
import io
import zipfile

from httpx import ASGITransport, AsyncClient
from test_node_control_native import NativeSerial
from test_node_control_native import native_library as native_library

from lora_testbed.app import create_app
from lora_testbed.integration_matrices import GROUPS


def test_dashboard_matrix_honors_exact_preview_and_exports_same_cases(tmp_path, native_library):
    async def scenario():
        app = create_app(tmp_path)
        async with app.router.lifespan_context(app):
            host = app.state.host
            node = host.physical["A"]
            peer = NativeSerial(native_library)
            node.opener = lambda _: peer
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://127.0.0.1"
            ) as ui:
                state = (await ui.get("/api/state")).json()
                options = state["procedures"]["matrix_options"]
                assert set(options) == set(GROUPS)
                assert options["SEC-04"]["kind"] == "local"
                assert options["PKT-01"]["choose_security"]
                assert options["IF-01"]["groups"] == list(GROUPS["IF-01"])
                args = {
                    "catalog_id": "IF-01",
                    "groups": ["C1"],
                    "roles": ["A"],
                    "repetitions": 1,
                    "valid_cycles": 1,
                }
                endpoint = "/api/procedures/matrix"
                disconnected = (await ui.post(f"{endpoint}/preview", json=args)).json()
                assert disconnected["ready_case_count"] == 0
                await node.connect("fixture-only-A")
                plan = (await ui.post(f"{endpoint}/preview", json=args)).json()
                assert plan["ready_case_count"] == 1 and not plan["full_plan"]
                mismatched = await ui.post(
                    endpoint + "?expected_plan_sha256=" + "0" * 64, json=args
                )
                assert mismatched.status_code == 409
                assert host.procedures.runs() == [] and not host.busy
                started = await ui.post(
                    endpoint + "?expected_plan_sha256=" + plan["sha256"], json=args
                )
                assert started.status_code == 202
                run_id = started.json()["id"]
                async with asyncio.timeout(10):
                    await host.procedures.task
                inactive = await ui.post(f"/api/procedures/stop?expected_run_id={run_id}")
                assert inactive.status_code == 409
                state = (await ui.get("/api/state")).json()
                assert state["procedures"]["runs"][0]["procedure_revision"]
                base = f"/api/procedures/runs/{run_id}"
                result = (await ui.get(base)).json()
                assert result["sha256"] == plan["sha256"]
                assert result["status"] == "completed" and result["assessment"] == "pass"
                assert not result["hardware_validated"]
                [case] = result["cases"]
                assert case["id"] == plan["cases"][0]["id"]
                response = await ui.get(f"{base}/evidence", params={"case_id": case["id"]})
                assert response.json()["events"]
                exported = await ui.get(f"{base}/export/zip")
                assert exported.status_code == 200
                with zipfile.ZipFile(io.BytesIO(exported.content)) as bundle:
                    assert bundle.testzip() is None
                    assert all(
                        name in bundle.namelist() for name in ("procedure.json", "cases.csv")
                    )

    asyncio.run(scenario())
