"""Actual C echo nodes through the production shared physical host service/API."""

import asyncio
import contextlib
import hashlib
import io
import json
import zipfile

import httpx
import pytest
from test_multi_fragment_radio import Pair
from test_node_control_native import native_library as native_library

from lora_testbed.app import create_app
from lora_testbed.host import Host
from lora_testbed.radio_runs import EchoRadioRunRequest, RadioRunRequest


@pytest.mark.parametrize(
    "direction,security",
    [
        ("A_TO_B", "none"),
        ("B_TO_A", "none"),
        ("A_TO_B", "aes128_gcm"),
        ("B_TO_A", "aes128_gcm"),
    ],
)
def test_shared_api_echo_pair_readback_and_distribution(
    tmp_path, native_library, direction, security
):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library)
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            app = create_app(tmp_path)
            app.state.host = host
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                body = dict(direction=direction, security=security, message_bytes=64)
                assert (await client.post("/api/echo/preflight", json=body)).json()["ready"]
                response = await client.post("/api/echo/runs", json=body)
                assert response.status_code == 202, response.text
                identifier = response.json()["id"]
                with pytest.raises(RuntimeError):
                    await host.start_radio(RadioRunRequest())
                async with asyncio.timeout(20):
                    await host.radio.task
                saved = host.radio.get(identifier)
                assert saved["status"] == "completed", saved.get("error")
                assert saved["verification"]["bytes_equal"]
                assert saved["timing"]["n"] == 1, saved["timing"]
                sample = saved["timing"]["samples"][0]
                assert sample["rtt_us"] == sample["reply_accepted_us"] - sample["tx_command_us"]
                assert (
                    bytes.fromhex(sample["reply_hex"])
                    == host.radio.content(identifier, "source").read_bytes()
                )
                assert sample["host_transaction_ns"] > sample["rtt_us"] * 1000
                assert saved["cleanup"]["confirmed"] and saved["security"]["keys_retired_on_host"]
                distribution = (
                    await client.post("/api/echo/distribution", json=[identifier])
                ).json()
                assert distribution["groups"][0]["n"] == 1
                assert distribution["groups"][0]["p95_us"] == sample["rtt_us"]
                assert (
                    await client.post("/api/echo/distribution", json=[identifier, identifier])
                ).status_code == 400
                with zipfile.ZipFile(io.BytesIO(host.radio.export(identifier))) as archive:
                    checks = json.loads(archive.read("sha256.json"))
                    assert all(
                        hashlib.sha256(archive.read(name)).hexdigest() == digest
                        for name, digest in checks.items()
                    )
                assert not saved["hardware_qualified"]
                # A changed finalized file cannot silently remain a valid distribution.
                path = host.radio.content(identifier, "source")
                path.write_bytes(b"changed")
                corrupted = host.radio.echo_distribution([identifier])["groups"][0]
                assert corrupted["n"] == 0
                assert corrupted["exclusions"][0]["reason"] == "saved_evidence_unverified"
        finally:
            if bridge:
                bridge.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bridge
            await host.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "fault", ["echo_reply", "echo_request", "event_gap", "cancel", "disconnect"]
)
def test_missing_echo_and_partial_lifecycle_never_invent_a_sample(tmp_path, native_library, fault):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(
            host,
            native_library,
            drop=fault if fault.startswith("echo_") else None,
            event_loss=("A", "echo.result") if fault == "event_gap" else None,
        )
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            started = await host.start_radio(EchoRadioRunRequest(message_bytes=32, timeout_ms=4000))
            if fault in ("cancel", "disconnect"):
                while host.radio.current["stage"] != "transmitting":
                    await asyncio.sleep(0.005)
                if fault == "cancel":
                    await host.radio.stop(started["id"])
                else:
                    await host.physical["A"].close()
            async with asyncio.timeout(20):
                await host.radio.task
            saved = host.radio.get(started["id"])
            assert saved["timing"]["n"] == 0, saved
            assert saved["timing"]["median_us"] is None and saved["timing"]["p95_us"] is None
            if fault.startswith("echo_"):
                assert saved["status"] == "completed", saved.get("error")
                assert saved["timing"]["exclusions"][0]["reason"] == "timeout"
            else:
                assert saved["status"] in ("cancelled", "failed", "interrupted")
            assert saved["cleanup"]["confirmed"] == (fault != "disconnect")
            assert not host.busy
        finally:
            if bridge:
                bridge.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bridge
            await host.close()

    asyncio.run(scenario())


def test_echo_statistics_worker_remains_responsive_and_joins_cancelled_request_before_close(
    tmp_path, monkeypatch
):
    import threading

    async def scenario():
        host = Host(tmp_path)
        entered, release = threading.Event(), threading.Event()

        def blocked(identifiers):
            entered.set()
            assert release.wait(2)
            # Shutdown must leave this store open until its reader is finished.
            return host.store.db.execute("SELECT 1").fetchone()[0]

        monkeypatch.setattr(host.radio, "echo_distribution", blocked)
        task = asyncio.create_task(host.radio.collect_echo_distribution(["test-only"]))
        closing = None
        try:
            async with asyncio.timeout(1):
                while not entered.is_set():
                    await asyncio.sleep(0.001)
            assert host.snapshot()["mode"] == "hardware"
            with pytest.raises(RuntimeError, match="Another echo distribution"):
                await host.radio.collect_echo_distribution(["test-only"])
            task.cancel()
            closing = asyncio.create_task(host.close())
            await asyncio.sleep(0.01)
            assert not task.done() and not closing.done()
            with pytest.raises(RuntimeError, match="shutting down"):
                await host.radio.collect_echo_distribution(["test-only"])
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            await closing
            assert not host.radio.evidence_worker.workers
        finally:
            release.set()
            if closing is None:
                await host.close()

    asyncio.run(scenario())


def test_echo_cli_uses_shared_endpoints_and_keeps_explicit_selection(monkeypatch):
    from typer.testing import CliRunner

    from lora_testbed import cli

    calls = []
    monkeypatch.setattr(cli, "request", lambda path, body=None: calls.append((path, body)))
    runner = CliRunner()
    assert (
        runner.invoke(cli.app, ["echo-start", "--direction", "B_TO_A", "--preview"]).exit_code == 0
    )
    assert calls[-1][0] == "/api/echo/preflight" and calls[-1][1]["direction"] == "B_TO_A"
    assert runner.invoke(cli.app, ["echo-start"]).exit_code == 0
    assert calls[-1][0] == "/api/echo/runs"
    assert runner.invoke(cli.app, ["echo-distribution", "run-a", "run-b"]).exit_code == 0
    assert calls[-1] == ("/api/echo/distribution", ["run-a", "run-b"])


def test_echo_selection_rejects_excess_evidence_before_unbounded_hash_work(tmp_path, monkeypatch):
    from test_echo_accounting import record

    async def scenario():
        host = Host(tmp_path)
        value = record()
        value["saved_files"] = {
            "source": {"length_bytes": 32},
            "wire": {"length_bytes": 64 * 1024 * 1024},
        }
        opened = []
        monkeypatch.setattr(host.radio, "get", lambda _: value)
        monkeypatch.setattr(host.radio, "content", lambda _, kind: opened.append(kind))
        try:
            with pytest.raises(ValueError, match="64 MiB"):
                await host.radio.collect_echo_distribution([value["id"]])
            assert opened == ["source"]
        finally:
            await host.close()

    asyncio.run(scenario())


def test_repeated_echo_runs_retire_only_verified_run_artifacts(tmp_path, native_library):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library)
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            originals = {}
            for role in "AB":
                upload = await host.artifacts.start_upload(role, b"user-owned source")
                await host.artifacts.task
                originals[role] = host.artifacts.get(upload["id"])["manifest"]["artifact_id"]
            for _ in range(6):
                started = await host.start_radio(EchoRadioRunRequest(message_bytes=32))
                async with asyncio.timeout(15):
                    await host.radio.task
                saved = host.radio.get(started["id"])
                assert saved["status"] == "completed", saved.get("error")
                assert saved["timing"]["n"] == 1
                for role in "AB":
                    listing = await host.physical[role].request("artifact.list")
                    assert [item["artifact_id"] for item in listing["artifacts"]] == [
                        originals[role]
                    ]
            assert (
                host.radio.echo_distribution([row["id"] for row in host.radio.snapshot()["runs"]])[
                    "groups"
                ][0]["n"]
                == 6
            )
        finally:
            if bridge:
                bridge.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bridge
            await host.close()

    asyncio.run(scenario())


def test_echo_artifact_retirement_failure_still_closes_both_sessions(
    tmp_path, native_library, monkeypatch
):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library)
        bridge = None
        original = host.radio.command

        async def command(record, role, name, *args, **kwargs):
            if role == "A" and name == "artifact.delete":
                raise ValueError("Injected artifact retirement failure")
            return await original(record, role, name, *args, **kwargs)

        monkeypatch.setattr(host.radio, "command", command)
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            started = await host.start_radio(EchoRadioRunRequest(message_bytes=32))
            async with asyncio.timeout(15):
                await host.radio.task
            saved = host.radio.get(started["id"])
            assert saved["status"] == "failed" and "retire" in saved["error"]
            assert not saved["cleanup"]["confirmed"] and saved["timing"]["n"] == 0
            assert all(detail["confirmed"] for detail in saved["cleanup"]["details"].values())
            assert not saved["cleanup"]["retired_echo_artifacts"]["A"]["confirmed"]
            assert saved["cleanup"]["retired_echo_artifacts"]["B"]["confirmed"]
            assert (await host.physical["A"].request("artifact.list"))["artifacts"]
            assert (await host.physical["B"].request("artifact.list"))["artifacts"] == []
        finally:
            if bridge:
                bridge.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bridge
            await host.close()

    asyncio.run(scenario())
