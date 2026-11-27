"""Verify campaign navigation observations through the running host and radio fixture."""

import asyncio
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from test_multi_fragment_radio import Pair
from test_node_control_native import native_library as native_library

from lora_testbed.app import create_app


@pytest.mark.parametrize("mode", ["complete", "missing", "separate_tabs"])
def test_campaign_navigation_requires_both_browser_actions_and_unchanged_execution(
    tmp_path, native_library, mode
):
    async def scenario():
        app = create_app(tmp_path)
        async with app.router.lifespan_context(app):
            host = app.state.host
            pair = Pair(host, native_library)
            await pair.connect()
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://127.0.0.1"
            ) as ui:
                request = {
                    "catalog_id": "IF-03",
                    "groups": ["C5"],
                    "repetitions": 1,
                    "messages_per_case": 1,
                }
                path = "/api/procedures/matrix"
                preview = (await ui.post(f"{path}/preview", json=request)).json()
                assert preview["ready_case_count"] == 1
                submitted = await ui.post(path, json=request)
                assert submitted.status_code == 202
                run_id = submitted.json()["id"]
                async with asyncio.timeout(5):
                    while not host.radio.current or host.radio.current["stage"] != "transmitting":
                        await asyncio.sleep(0.005)
                state = (await ui.get("/api/state")).json()
                identifier = state["campaign_view_observation_id"]
                assert identifier == state["physical_campaigns"]["active"]["id"]
                radio_id = host.radio.current["id"]
                before = host.physical_campaigns.get(identifier)
                tab, document, renewed = (str(uuid4()) for _ in range(3))
                observation_path = (
                    f"/api/physical-campaigns/executions/{identifier}/view-observation"
                )
                events = [
                    (tab, document, "campaigns", "navigate"),
                    (tab, document, "bench", "navigate"),
                    (tab, document, "campaigns", "navigate"),
                    (tab, renewed, "campaigns", "reload"),
                ]
                if mode == "separate_tabs":
                    other = str(uuid4())
                    events[-1:] = [
                        (other, document, "campaigns", "navigate"),
                        (other, renewed, "campaigns", "reload"),
                    ]
                for tab_id, page, view, kind in events if mode != "missing" else []:
                    result = await ui.post(
                        observation_path,
                        json={
                            "tab_id": tab_id,
                            "document_id": page,
                            "view": view,
                            "navigation_type": kind,
                        },
                    )
                    assert result.status_code == 200 and result.json()["recorded"]
                if mode != "missing":
                    duplicate = await ui.post(
                        observation_path,
                        json={
                            "tab_id": events[-1][0],
                            "document_id": renewed,
                            "view": "campaigns",
                            "navigation_type": "reload",
                        },
                    )
                    assert duplicate.json() == {"recorded": False, "reason": "unchanged view"}
                continued = await ui.get(f"/api/physical-campaigns/executions/{identifier}/view")
                assert continued.json()["record"]["document_sha256"] == before["document_sha256"]
                assert host.radio.current["id"] == radio_id
                bridge = asyncio.create_task(pair.bridge())
                try:
                    async with asyncio.timeout(20):
                        await host.procedures.task
                finally:
                    bridge.cancel()
                    await asyncio.gather(bridge, return_exceptions=True)
                saved = host.procedures.get(run_id)
                assert saved["status"] == "completed" and not saved["hardware_validated"]
                [case] = saved["cases"]
                metrics = case["measurements"]
                assert metrics["verified_messages"] == 6 and case["cleanup_verified"]
                assert case["assessment"] == ("pass" if mode == "complete" else "inconclusive")
                browser = metrics["browser_continuity"]
                assert browser["verified_in_same_tab"] is (mode == "complete")
                assert browser["observations"] == (0 if mode == "missing" else len(events))
                assert (await ui.get("/api/state")).json()["campaign_view_observation_id"] is None
                closed = await ui.post(
                    observation_path,
                    json={
                        "tab_id": tab,
                        "document_id": renewed,
                        "view": "campaigns",
                        "navigation_type": "reload",
                    },
                )
                assert closed.status_code == 400
                assert not host.busy

    asyncio.run(scenario())
