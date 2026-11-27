"""Stopping a parent must end nested work without holding its launch lock."""

import asyncio
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from lora_testbed.app import create_app
from lora_testbed.host import Host
from lora_testbed.procedure_runs import ProcedureService


def isolated_host():
    """Use the real stop paths without a store, serial port or firmware fixture."""
    host = Host.__new__(Host)
    host.lock = asyncio.Lock()
    host.physical_campaigns = SimpleNamespace(busy=False, current=None)
    host.procedures = ProcedureService.__new__(ProcedureService)
    host.procedures.current = {"id": "procedure", "status": "running", "reason": None}
    return host


def test_global_stop_cancels_parent_before_another_nested_trial_starts():
    async def scenario():
        host = isolated_host()
        entered, trial_stopped = asyncio.Event(), asyncio.Event()
        launches = []

        async def stop_trial():
            trial_stopped.set()
            return {"status": "cancelled"}

        host.lab_trials = SimpleNamespace(busy=True, stop=stop_trial)

        async def procedure():
            try:
                for ordinal in range(2):
                    launches.append(ordinal)
                    entered.set()
                    await trial_stopped.wait()
            except asyncio.CancelledError:
                await host.lab_trials.stop()
                host.procedures.current["status"] = "cancelled"

        host.procedures.task = asyncio.create_task(procedure())
        await entered.wait()
        result = await host.stop()
        await host.procedures.task
        assert result["status"] == "cancelled"
        assert launches == [0]
        assert not host.procedures.busy
        assert trial_stopped.is_set()

    asyncio.run(scenario())


@pytest.mark.parametrize("endpoint", ["/api/procedures/stop", "/api/v2/stop"])
def test_procedure_stop_endpoint_allows_nested_launch_to_finish_cleanup(endpoint):
    async def scenario():
        host = isolated_host()
        launch_gate, entered = asyncio.Event(), asyncio.Event()
        launched = []

        async def start_radio(request):
            launched.append(request)
            return {"id": "child"}

        host.require_available_bench = lambda owner: None
        host.radio = SimpleNamespace(start=start_radio)

        async def nested_child():
            await launch_gate.wait()
            await host.start_radio("isolated-child")

        async def procedure():
            child = asyncio.create_task(nested_child())
            entered.set()
            try:
                await asyncio.shield(child)
            except asyncio.CancelledError:
                # The nested runner must finish its pending launch and cleanup.
                launch_gate.set()
                await child
                host.procedures.current["status"] = "cancelled"

        host.procedures.task = asyncio.create_task(procedure())
        await entered.wait()
        app = create_app()
        app.state.host = host
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            stopped = asyncio.create_task(client.post(endpoint))
            try:
                done, _ = await asyncio.wait({stopped}, timeout=1)
                assert done, "Stop held the bench lock needed by nested cleanup"
                response = stopped.result()
                assert response.status_code == 200
                assert response.json()["status"] == "cancelled"
                assert launched == ["isolated-child"]
                assert not host.lock.locked()
                assert not host.procedures.busy
            finally:
                if not stopped.done():
                    stopped.cancel()
                await asyncio.gather(stopped, host.procedures.task, return_exceptions=True)

    asyncio.run(scenario())


def test_repeated_stop_and_cancelled_caller_preserve_procedure_cleanup():
    async def scenario():
        host = isolated_host()
        entered, cleaning, finish_cleanup = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def procedure():
            try:
                entered.set()
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cleaning.set()
                await finish_cleanup.wait()
                host.procedures.current["status"] = "cancelled"

        host.procedures.task = asyncio.create_task(procedure())
        await entered.wait()
        first = asyncio.create_task(host.procedures.stop())
        await cleaning.wait()
        second = asyncio.create_task(host.procedures.stop())
        await asyncio.sleep(0)
        first.cancel()
        try:
            await asyncio.gather(first, return_exceptions=True)
            assert not host.procedures.task.done()
            assert host.procedures.task.cancelling() == 1
            finish_cleanup.set()
            result = await second
            assert result["status"] == "cancelled"
            assert not host.procedures.busy
        finally:
            finish_cleanup.set()
            await asyncio.gather(first, second, host.procedures.task, return_exceptions=True)

    asyncio.run(scenario())
