"""Campaign ownership and child evidence through the real host/native control seam."""

import asyncio

from fastapi.testclient import TestClient
from test_node_control_native import NativeSerial
from test_node_control_native import native_library as native_library

from lora_testbed.app import create_app


def wait_terminal(client, identifier):
    async def wait():
        async with asyncio.timeout(8):
            while client.app.state.host.physical_campaigns.busy:
                await asyncio.sleep(0.01)

    client.portal.call(wait)
    response = client.get(f"/api/physical-campaigns/executions/{identifier}")
    assert response.status_code == 200, response.text
    return response.json()


def test_one_node_campaign_executes_actual_diagnostic_and_preserves_immutable_plan(
    native_library, tmp_path
):
    with TestClient(create_app(data_dir=tmp_path)) as client:
        host = client.app.state.host
        serial = NativeSerial(native_library)
        host.physical["B"].opener = lambda _: serial
        client.portal.call(host.physical["B"].connect, "isolated-campaign-node-b")
        plan = client.post(
            "/api/physical-campaigns/plans",
            json={
                "name": "One-node actual diagnostic",
                "templates": [
                    {
                        "label": "memory",
                        "case": {
                            "kind": "memory_probe",
                            "role": "B",
                            "iterations": 1,
                            "payload_bytes": 1024,
                        },
                    }
                ],
            },
        ).json()
        started = client.post("/api/physical-campaigns/executions", json={"plan_id": plan["id"]})
        assert started.status_code == 202, started.text
        saved = wait_terminal(client, started.json()["id"])
        assert saved["status"] == "completed", saved
        assert not saved["hardware_qualified"]
        assert saved["plan_sha256"] == plan["plan_sha256"]
        case = saved["cases"][0]
        assert case["case_id"] == plan["cases"][0]["id"]
        assert case["status"] == "completed"
        assert case["child"]["service"] == "diagnostic"
        child = client.get("/api/diagnostic-runs/" + case["child"]["id"]).json()
        assert (
            child["status"] == "completed"
            and child["node_result"]["result"]["iterations_completed"] == 1
        )
        assert child["cleanup"]["confirmed"] and child["physical_binding"]["role"] == "B"
        assert client.get("/api/physical-campaigns/plans/" + plan["id"]).json() == plan
        assert not client.get("/api/state").json()["bench_busy"]


def wait_for(client, identifier, predicate):
    from time import monotonic

    deadline = monotonic() + 8
    while monotonic() < deadline:
        record = client.get(f"/api/physical-campaigns/executions/{identifier}").json()
        if predicate(record):
            return record
        client.portal.call(asyncio.sleep, 0.01)
    raise AssertionError(f"Campaign did not reach expected state: {record}")


def test_pause_finishes_current_child_holds_ownership_and_resumes_saved_order(
    native_library, tmp_path
):
    with TestClient(create_app(data_dir=tmp_path)) as client:
        host = client.app.state.host
        serial = NativeSerial(native_library)
        host.physical["B"].opener = lambda _: serial
        client.portal.call(host.physical["B"].connect, "isolated-pause-node-b")
        plan = client.post(
            "/api/physical-campaigns/plans",
            json={
                "name": "Saved seeded order",
                "repetitions": 1,
                "order": "randomized",
                "order_seed": 19,
                "templates": [
                    {
                        "label": f"memory-{size}",
                        "case": {
                            "kind": "memory_probe",
                            "role": "B",
                            "iterations": 8,
                            "payload_bytes": size,
                        },
                    }
                    for size in (512, 1024, 2048)
                ],
            },
        ).json()
        started = client.post(
            "/api/physical-campaigns/executions", json={"plan_id": plan["id"]}
        ).json()
        identifier = started["id"]
        wait_for(client, identifier, lambda record: record["cases"][0]["child"] is not None)
        paused = client.post(f"/api/physical-campaigns/executions/{identifier}/pause", json={})
        assert paused.status_code == 202, paused.text
        saved = wait_for(client, identifier, lambda record: record["status"] == "paused")
        assert [case["status"] for case in saved["cases"]] == ["completed", "pending", "pending"]
        assert client.get("/api/state").json()["bench_busy"]
        assert (
            client.post(
                "/api/physical-campaigns/executions", json={"plan_id": plan["id"]}
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/nodes/B/memory-probe", json={"iterations": 1, "payload_bytes": 512}
            ).status_code
            == 409
        )
        assert client.post("/api/nodes/B/connection", json={"port": None}).status_code == 409
        assert host.physical["B"].connected
        resumed = client.post(f"/api/physical-campaigns/executions/{identifier}/resume", json={})
        assert resumed.status_code == 202, resumed.text
        saved = wait_terminal(client, identifier)
        assert saved["status"] == "completed", saved
        assert [case["case_id"] for case in saved["cases"]] == [
            case["id"] for case in plan["cases"]
        ]
        assert all(case["status"] == "completed" for case in saved["cases"])
        assert len({case["child"]["id"] for case in saved["cases"]}) == 3

        requests = [
            client.get("/api/diagnostic-runs/" + case["child"]["id"]).json()["arguments"]
            for case in saved["cases"]
        ]
        assert [args["payload_bytes"] for args in requests] == [2048, 512, 1024]


def test_cancel_retains_active_child_and_reason_codes_unstarted_cases(native_library, tmp_path):
    with TestClient(create_app(data_dir=tmp_path)) as client:
        host = client.app.state.host
        serial = NativeSerial(native_library)
        host.physical["B"].opener = lambda _: serial
        client.portal.call(host.physical["B"].connect, "isolated-cancel-node-b")
        plan = client.post(
            "/api/physical-campaigns/plans",
            json={
                "name": "Cancel active child",
                "repetitions": 3,
                "templates": [
                    {
                        "label": "memory",
                        "case": {
                            "kind": "memory_probe",
                            "role": "B",
                            "iterations": 8,
                            "payload_bytes": 4096,
                        },
                    }
                ],
            },
        ).json()
        started = client.post(
            "/api/physical-campaigns/executions", json={"plan_id": plan["id"]}
        ).json()
        identifier = started["id"]
        wait_for(client, identifier, lambda record: record["cases"][0]["child"] is not None)
        response = client.post(
            f"/api/physical-campaigns/executions/{identifier}/cancel",
            json={"reason": "Keep the partial memory result"},
        )
        assert response.status_code == 200, response.text
        saved = response.json()
        assert saved["status"] == "cancelled"
        assert saved["reason"] == "Keep the partial memory result"
        assert [case["status"] for case in saved["cases"]] == ["cancelled", "skipped", "skipped"]
        assert all(case["reason_code"] == "operator_cancel" for case in saved["cases"][1:])
        child = client.get("/api/diagnostic-runs/" + saved["cases"][0]["child"]["id"]).json()
        assert child["status"] == "cancelled" and child["cleanup"]["confirmed"]
        assert child["node_result"]["status"] == "cancelled"
        assert child["node_result"]["result"]["iterations_completed"] < 8
        assert saved["cleanup"]["confirmed"]
        assert not host.busy and host.physical["B"].health.state == "idle"
        following = client.post(
            "/api/nodes/B/memory-probe", json={"iterations": 1, "payload_bytes": 512}
        )
        assert following.status_code == 200, following.text


def test_mixed_one_node_cases_reuse_crypto_serial_and_audio_runners(native_library, tmp_path):
    from test_node_audio_host import AudioSerial

    with TestClient(create_app(data_dir=tmp_path)) as client:
        host = client.app.state.host
        serial = AudioSerial(native_library)
        host.physical["B"].opener = lambda _: serial
        client.portal.call(host.physical["B"].connect, "isolated-mixed-node-b")
        plan = client.post(
            "/api/physical-campaigns/plans",
            json={
                "name": "Mixed local checks",
                "templates": [
                    {
                        "label": "memory",
                        "case": {"kind": "memory_probe", "role": "B", "iterations": 1},
                    },
                    {
                        "label": "crypto",
                        "case": {
                            "kind": "crypto_benchmark",
                            "role": "B",
                            "request": {"iterations": 1, "payload_bytes": 16},
                        },
                    },
                    {"label": "serial", "case": {"kind": "serial_check", "role": "B", "cycles": 1}},
                    {
                        "label": "capture",
                        "case": {
                            "kind": "audio",
                            "role": "B",
                            "action": "capture",
                            "sample_count": 160,
                        },
                    },
                ],
            },
        ).json()
        started = client.post(
            "/api/physical-campaigns/executions", json={"plan_id": plan["id"]}
        ).json()
        saved = wait_terminal(client, started["id"])
        assert saved["status"] == "completed", saved
        assert [case["child"]["service"] for case in saved["cases"]] == [
            "diagnostic",
            "diagnostic",
            "procedure",
            "audio",
        ]
        assert all(case["status"] == "completed" for case in saved["cases"])
        crypto = client.get("/api/diagnostic-runs/" + saved["cases"][1]["child"]["id"]).json()
        assert crypto["node_result"]["result"]["checked_complete"]
        partial_serial = client.get(
            "/api/procedures/runs/" + saved["cases"][2]["child"]["id"]
        ).json()
        assert not partial_serial["full_procedure_passed"]
        audio = client.get("/api/audio/operations/" + saved["cases"][3]["child"]["id"]).json()
        assert audio["node_result"]["result"]["samples_completed"] == 160
        import io
        import wave

        with wave.open(
            io.BytesIO(client.get("/api/audio/operations/" + audio["id"] + "/wav").content)
        ) as wav:
            assert wav.readframes(160) == serial.audio.pcm
        assert not saved["hardware_qualified"]


def test_campaign_runs_known_data_then_secure_voice_through_actual_pair(native_library, tmp_path):
    import contextlib

    from test_artifact_transfers import finished
    from test_voice_workflows import AudioPair

    from lora_testbed.audio import inspect_wav, pcm_wav, save_wav
    from lora_testbed.campaign_plans import CampaignSpec
    from lora_testbed.host import Host

    async def scenario():
        host = Host(tmp_path)
        pair = AudioPair(host, native_library)
        bridge = None
        try:
            await pair.connect()
            wav = pcm_wav(b"\x00\x08" * 160, 160)
            reference = inspect_wav(wav, "short-reference.wav")
            save_wav(tmp_path, reference, wav)
            host.store.save_reference(reference)
            plan = host.campaign_plans.create(
                CampaignSpec.model_validate(
                    {
                        "name": "Actual data and voice",
                        "directions": ["B_TO_A"],
                        "templates": [
                            {
                                "label": "data",
                                "case": {
                                    "kind": "known_data",
                                    "request": {"message_bytes": 97, "source_seed": 17},
                                },
                            },
                            {
                                "label": "voice",
                                "case": {
                                    "kind": "voice",
                                    "request": {
                                        "source": "reference",
                                        "reference_id": reference["id"],
                                        "sample_count": 160,
                                        "include_comparisons": False,
                                    },
                                },
                            },
                        ],
                    }
                )
            )
            bridge = asyncio.create_task(pair.bridge())
            started = await host.start_campaign(plan["id"])
            saved = await finished(host.physical_campaigns, started["id"])
            assert saved["status"] == "completed", saved
            assert [case["child"]["service"] for case in saved["cases"]] == ["radio", "voice"]
            radio = host.radio.get(saved["cases"][0]["child"]["id"])
            assert radio["sender"] == "B" and radio["verification"]["bytes_equal"]
            assert radio["plan"]["spec"]["source_seed"] == 17
            assert len(host.radio.content(radio["id"], "source").read_bytes()) == 97
            assert (
                host.radio.content(radio["id"], "source").read_bytes()
                == host.radio.content(radio["id"], "recovered").read_bytes()
            )
            voice = host.voice.get(saved["cases"][1]["child"]["id"])
            assert (
                voice["sender"] == "B"
                and voice["delivery_verified"]
                and voice["playback_completed"]
            )
            assert saved["cleanup"]["confirmed"] and not saved["hardware_qualified"]
        finally:
            if bridge:
                bridge.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bridge
            await host.close()

    asyncio.run(scenario())


def test_restart_interrupts_paused_campaign_without_connecting_or_resuming(tmp_path):
    import json
    import subprocess
    import sys
    import textwrap

    import pytest

    from lora_testbed.host import Host

    script = textwrap.dedent("""
        import asyncio, json, os, sys
        from pathlib import Path
        from lora_testbed.host import Host
        from lora_testbed.campaign_plans import CampaignSpec
        async def main():
            host = Host(Path(sys.argv[1]))
            plan = host.campaign_plans.create(CampaignSpec.model_validate({
                "name":"Crash while paused", "repetitions":2,
                "templates":[{"label":"memory", "case":{"kind":"memory_probe"}}]}))
            started = await host.start_campaign(plan["id"])
            host.physical_campaigns.pause(started["id"])
            await asyncio.sleep(0)
            print(json.dumps({
                "execution": started["id"], "plan": plan["id"], "hash": plan["plan_sha256"]
            }), flush=True)
            os._exit(0)
        asyncio.run(main())
    """)
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=8,
    )
    identifiers = json.loads(result.stdout)
    host = Host(tmp_path)
    try:
        saved = host.physical_campaigns.get(identifiers["execution"])
        assert saved["status"] == "interrupted"
        assert saved["reason_code"] == "host_restart"
        assert all(
            case["status"] == "skipped" and case["reason_code"] == "host_restart"
            for case in saved["cases"]
        )
        assert not saved["cleanup"]["confirmed"]
        assert host.campaign_plans.get(identifiers["plan"])["plan_sha256"] == identifiers["hash"]
        assert not host.busy and not any(node.connected for node in host.physical.values())
        with pytest.raises(ValueError, match="not active"):
            host.physical_campaigns.resume(saved["id"])
    finally:
        asyncio.run(host.close())


def test_blocked_full_procedure_cases_remain_present_without_hardware_or_fake_success(tmp_path):
    from lora_testbed.catalog import ROWS

    with TestClient(create_app(data_dir=tmp_path)) as client:
        plan = client.post(
            "/api/physical-campaigns/plans",
            json={
                "name": "All required procedures",
                "templates": [
                    {"label": row[0], "case": {"kind": "procedure", "catalog_id": row[0]}}
                    for row in ROWS
                ],
            },
        ).json()
        assert len(plan["cases"]) == 23
        started = client.post(
            "/api/physical-campaigns/executions", json={"plan_id": plan["id"]}
        ).json()
        saved = wait_terminal(client, started["id"])
        assert saved["status"] == "blocked"
        assert saved["case_counts"] == {"blocked": 23}
        assert all(
            case["child"] is None and case["reason_code"] == "capability_unavailable"
            for case in saved["cases"]
        )
        assert [case["case_id"] for case in saved["cases"]] == [
            case["id"] for case in plan["cases"]
        ]
        assert not any(node["connected"] for node in client.get("/api/state").json()["nodes"])
        assert not saved["hardware_qualified"]


def test_rf_child_failure_stops_both_armed_peers_and_skips_following_cases(
    native_library, tmp_path
):
    import json

    from test_artifact_transfers import finished
    from test_radio_runs import FaultSerial, connected_bench

    from lora_testbed.campaign_plans import CampaignSpec

    class FailedArm(FaultSerial):
        def __init__(self, role, **kwargs):
            super().__init__(**kwargs)
            self.role, self.failed = role, False

        def read(self, count):
            wire = super().read(count)
            if not wire:
                return wire
            record = json.loads(wire)
            if (
                self.role == "A"
                and not self.failed
                and self.commands.get(record.get("command_id")) == "run.arm"
                and record.get("ok")
            ):
                self.failed = True
                record.update(
                    ok=False,
                    result=None,
                    error={
                        "code": "IO_ERROR",
                        "message": "Injected arm reply failure",
                        "field": None,
                        "retryable": False,
                    },
                )
                return json.dumps(record).encode() + b"\n"
            return wire

    async def scenario():
        host, _ = await connected_bench(
            tmp_path, native_library, lambda role, **kwargs: FailedArm(role, **kwargs)
        )
        try:
            plan = host.campaign_plans.create(
                CampaignSpec.model_validate(
                    {
                        "name": "Fail after both arms",
                        "directions": ["A_TO_B"],
                        "templates": [
                            {
                                "label": "radio",
                                "case": {"kind": "known_data", "request": {"message_bytes": 64}},
                            },
                            {
                                "label": "following",
                                "case": {"kind": "memory_probe", "iterations": 1},
                            },
                        ],
                    }
                )
            )
            started = await host.start_campaign(plan["id"])
            saved = await finished(host.physical_campaigns, started["id"])
            assert saved["status"] == "failed"
            assert [case["status"] for case in saved["cases"]] == ["failed", "skipped"]
            assert saved["cases"][1]["reason_code"] == "child_failed"
            child = host.radio.get(saved["cases"][0]["child"]["id"])
            assert "Injected arm reply failure" in child["error"]
            assert child["cleanup"]["confirmed"] and saved["cleanup"]["confirmed"]
            assert all(
                node.health.state == "idle"
                and node.rf_run_id is None
                and not node.health.security_ready
                for node in host.physical.values()
            )
            assert not host.busy
        finally:
            await host.close()

    asyncio.run(scenario())


def test_cancel_during_final_cleanup_cannot_leave_a_finished_campaign_cancelling(
    native_library, tmp_path
):
    import json
    import threading
    import time

    entered = threading.Event()

    class FinalCleanupDelay(NativeSerial):
        def __init__(self):
            super().__init__(native_library)
            self.names, self.terminal, self.status_after_terminal = {}, False, 0

        def write(self, wire):
            command = json.loads(wire)
            self.names[command["command_id"]] = command["name"]
            return super().write(wire)

        def read(self, count):
            wire = super().read(count)
            if not wire:
                return wire
            record = json.loads(wire)
            if record.get("name") == "operation.result":
                self.terminal = True
            if self.terminal and self.names.get(record.get("command_id")) == "status.get":
                self.status_after_terminal += 1
                if self.status_after_terminal == 2:
                    entered.set()
                    time.sleep(0.15)  # Actual cleanup is still running while the operator stops.
            return wire

    with TestClient(create_app(data_dir=tmp_path)) as client:
        host = client.app.state.host
        serial = FinalCleanupDelay()
        host.physical["B"].opener = lambda _: serial
        client.portal.call(host.physical["B"].connect, "isolated-final-cleanup")
        plan = client.post(
            "/api/physical-campaigns/plans",
            json={
                "name": "Stop at final cleanup",
                "templates": [
                    {
                        "label": "memory",
                        "case": {"kind": "memory_probe", "role": "B", "iterations": 1},
                    }
                ],
            },
        ).json()
        started = client.post(
            "/api/physical-campaigns/executions", json={"plan_id": plan["id"]}
        ).json()

        async def wait_cleanup():
            async with asyncio.timeout(3):
                while not entered.is_set():
                    await asyncio.sleep(0.002)

        client.portal.call(wait_cleanup)
        saved = client.post(
            f"/api/physical-campaigns/executions/{started['id']}/cancel", json={}
        ).json()
        assert saved["status"] == "completed", saved
        assert saved["finished_at"] and saved["cleanup"]["confirmed"] and not host.busy


def test_paused_campaign_rejects_same_boot_reconnect_and_never_closes_replacement(
    native_library, tmp_path
):
    with TestClient(create_app(data_dir=tmp_path)) as client:
        host = client.app.state.host
        peers = [NativeSerial(native_library), NativeSerial(native_library)]
        host.physical["B"].opener = lambda _: peers.pop(0)
        client.portal.call(host.physical["B"].connect, "isolated-original-b")
        plan = client.post(
            "/api/physical-campaigns/plans",
            json={
                "name": "Freeze enrolled connection",
                "repetitions": 2,
                "templates": [
                    {
                        "label": "memory",
                        "case": {"kind": "memory_probe", "role": "B", "iterations": 8},
                    }
                ],
            },
        ).json()
        started = client.post(
            "/api/physical-campaigns/executions", json={"plan_id": plan["id"]}
        ).json()
        identifier = started["id"]
        wait_for(client, identifier, lambda record: record["cases"][0]["child"] is not None)
        assert (
            client.post(
                f"/api/physical-campaigns/executions/{identifier}/pause", json={}
            ).status_code
            == 202
        )
        wait_for(client, identifier, lambda record: record["status"] == "paused")
        original = host.physical["B"].connection_id
        # Model an external unplug/reconnect; the public connection control already rejects it.
        client.portal.call(host.physical["B"].connect, "isolated-replacement-b")
        assert host.physical["B"].connection_id != original
        assert (
            client.post(
                f"/api/physical-campaigns/executions/{identifier}/resume", json={}
            ).status_code
            == 400
        )
        cancelled = client.post(
            f"/api/physical-campaigns/executions/{identifier}/cancel", json={}
        ).json()
        assert cancelled["status"] == "cancelled" and not cancelled["cleanup"]["confirmed"]
        assert host.physical["B"].connected and not host.busy
        assert cancelled["cases"][1]["status"] == "skipped"


def test_immediate_global_stop_skips_every_case_before_any_diagnostic_command(
    native_library, tmp_path
):
    import json

    from lora_testbed.campaign_plans import CampaignSpec
    from lora_testbed.host import Host

    class RecordedSerial(NativeSerial):
        def __init__(self):
            super().__init__(native_library)
            self.names = []

        def write(self, wire):
            self.names.append(json.loads(wire)["name"])
            return super().write(wire)

    async def scenario():
        host = Host(tmp_path)
        serial = RecordedSerial()
        host.physical["B"].opener = lambda _: serial
        try:
            await host.physical["B"].connect("isolated-immediate-stop")
            plan = host.campaign_plans.create(
                CampaignSpec.model_validate(
                    {
                        "name": "Immediate cancel",
                        "repetitions": 3,
                        "templates": [
                            {
                                "label": "memory",
                                "case": {"kind": "memory_probe", "role": "B", "iterations": 1},
                            }
                        ],
                    }
                )
            )
            started = await host.start_campaign(plan["id"])
            saved = await host.stop()
            assert saved["id"] == started["id"] and saved["status"] == "cancelled"
            assert all(
                case["status"] == "skipped" and case["child"] is None for case in saved["cases"]
            )
            assert "diag.run" not in serial.names and saved["cleanup"]["confirmed"]
            assert not host.busy
        finally:
            await host.close()

    asyncio.run(scenario())


def test_lost_diagnostic_acceptance_keeps_durable_child_link_and_skips_following_work(
    native_library, tmp_path
):
    import json

    class LostAcceptance(NativeSerial):
        def __init__(self):
            super().__init__(native_library)
            self.names = {}

        def write(self, wire):
            command = json.loads(wire)
            self.names[command["command_id"]] = command["name"]
            return super().write(wire)

        def read(self, count):
            wire = super().read(count)
            if wire and self.names.get(json.loads(wire).get("command_id")) == "diag.run":
                return b""  # Lose every acceptance retry; the C operation actually started.
            return wire

    with TestClient(create_app(data_dir=tmp_path)) as client:
        host = client.app.state.host
        serial = LostAcceptance()
        host.physical["B"].opener = lambda _: serial
        client.portal.call(host.physical["B"].connect, "isolated-lost-acceptance")
        plan = client.post(
            "/api/physical-campaigns/plans",
            json={
                "name": "Lost acceptance",
                "repetitions": 2,
                "templates": [
                    {
                        "label": "memory",
                        "case": {"kind": "memory_probe", "role": "B", "iterations": 10000},
                    }
                ],
            },
        ).json()
        started = client.post(
            "/api/physical-campaigns/executions", json={"plan_id": plan["id"]}
        ).json()
        saved = wait_terminal(client, started["id"])
        assert saved["status"] == "interrupted", saved
        assert [case["status"] for case in saved["cases"]] == ["failed", "skipped"]
        reference = saved["cases"][0]["child"]
        assert reference["service"] == "diagnostic"
        evidence = client.get(
            "/api/diagnostic-runs/" + reference["id"] + "/evidence?include_records=true"
        ).json()
        assert evidence["job"]["status"] == "failed"
        assert evidence["job"]["operation_id"] is None  # A missing acceptance is never invented.
        assert not evidence["job"]["cleanup"]["confirmed"] and not saved["cleanup"]["confirmed"]
        assert any(row["record"].get("name") == "diag.run" for row in evidence["wire"])
        assert not host.busy and not host.physical["B"].connected


def test_host_shutdown_during_child_acceptance_joins_campaign_before_store_close(
    native_library, tmp_path
):
    import json
    import threading
    import time

    from lora_testbed.campaign_plans import CampaignSpec
    from lora_testbed.host import Host

    entered = threading.Event()

    class SlowAcceptance(NativeSerial):
        def write(self, wire):
            if json.loads(wire)["name"] == "diag.run":
                entered.set()
                time.sleep(0.15)
            return super().write(wire)

    async def scenario():
        host = Host(tmp_path)
        serial = SlowAcceptance(native_library)
        host.physical["B"].opener = lambda _: serial
        await host.physical["B"].connect("isolated-campaign-shutdown")
        plan = host.campaign_plans.create(
            CampaignSpec.model_validate(
                {
                    "name": "Shutdown during acceptance",
                    "repetitions": 2,
                    "templates": [
                        {
                            "label": "memory",
                            "case": {"kind": "memory_probe", "role": "B", "iterations": 10000},
                        }
                    ],
                }
            )
        )
        started = await host.start_campaign(plan["id"])
        async with asyncio.timeout(2):
            while not entered.is_set():
                await asyncio.sleep(0.002)
        await host.close()
        assert serial.closed and host.physical_campaigns.current is None
        reopened = Host(tmp_path)
        try:
            saved = reopened.physical_campaigns.get(started["id"])
            assert saved["status"] == "interrupted" and saved["reason_code"] == "host_shutdown"
            assert (
                saved["cases"][1]["status"] == "skipped"
                and saved["cases"][1]["reason_code"] == "host_shutdown"
            )
            child = reopened.diagnostics.get(saved["cases"][0]["child"]["id"])
            assert child["status"] == "cancelled" and child["cleanup"]["confirmed"]
            assert child["node_result"] is not None
            assert saved["cleanup"]["confirmed"] and not reopened.busy
        finally:
            await reopened.close()

    asyncio.run(scenario())
