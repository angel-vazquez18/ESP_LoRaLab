"""The host coordinates both independent node arms before allowing RF work."""

import asyncio
import json

from test_node_control_native import NativeSerial
from test_node_control_native import native_library as native_library
from test_radio_runs import connected_bench

from lora_testbed import radio_runs
from lora_testbed.radio_runs import RadioRunRequest


def test_receiver_arm_budget_expires_before_sender_start_is_issued(
    tmp_path, native_library, monkeypatch
):
    clock = [0.0]
    monkeypatch.setattr(radio_runs, "monotonic", lambda: clock[0])

    calls = []

    class DelayedArmSerial(NativeSerial):
        def __init__(self, role, **kwargs):
            super().__init__(**kwargs)
            self.role = role

        def write(self, wire):
            name = json.loads(wire)["name"]
            calls.append((self.role, name))
            if name == "run.arm" and self.role == "B":
                clock[0] += 5.001  # Explicit host scheduling delay, not a physical clock.
            return super().write(wire)

    async def scenario():
        host, _ = await connected_bench(
            tmp_path, native_library, lambda role, **kwargs: DelayedArmSerial(role, **kwargs)
        )
        try:
            started = await host.start_radio(RadioRunRequest())
            async with asyncio.timeout(5):
                while host.radio.busy:
                    await asyncio.sleep(0.01)
            saved = host.radio.get(started["id"])
            assert saved["status"] == "failed"
            assert "arm" in saved["error"].lower()
            assert not any(name == "run.start" for _, name in calls)
            assert saved["cleanup"]["confirmed"]
            assert all(node.rf_run_id is None for node in host.physical.values())
        finally:
            await host.close()

    asyncio.run(scenario())
