"""Linked physical reruns and complete verified bundles through public boundaries."""

import hashlib
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient
from test_node_control_native import NativeSerial
from test_node_control_native import native_library as native_library
from test_physical_campaign_execution import wait_for, wait_terminal

from lora_testbed.app import create_app


def plan(client, sizes=(512, 1024, 2048), iterations=1):
    response = client.post(
        "/api/physical-campaigns/plans",
        json={
            "name": "Selected rerun evidence",
            "order": "randomized",
            "order_seed": 19,
            "templates": [
                {
                    "label": str(size),
                    "case": {
                        "kind": "memory_probe",
                        "role": "B",
                        "iterations": iterations,
                        "payload_bytes": size,
                    },
                }
                for size in sizes
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def start(client, saved):
    response = client.post("/api/physical-campaigns/executions", json={"plan_id": saved["id"]})
    assert response.status_code == 202, response.text
    return wait_terminal(client, response.json()["id"])


def connect(client, lib):
    serial = NativeSerial(lib)
    node = client.app.state.host.physical["B"]
    node.opener = lambda _: serial
    client.portal.call(node.connect, "isolated-rerun-b")
    return serial


def test_selected_failed_case_rerun_keeps_original_and_uses_fresh_child(native_library, tmp_path):
    with TestClient(create_app(data_dir=tmp_path)) as client:
        serial = connect(client, native_library)
        saved = plan(client)
        serial.core.allocation_fails = True
        original = start(client, saved)
        assert original["status"] == "failed"
        selected = original["cases"][0]
        assert selected["child"] is not None
        serial.core.allocation_fails = False
        response = client.post(
            f"/api/physical-campaigns/executions/{original['id']}/rerun",
            json={"case_ids": [selected["case_id"]]},
        )
        assert response.status_code == 202, response.text
        result = wait_terminal(client, response.json()["id"])
        assert result["status"] == "completed", result
        assert result["id"] != original["id"]
        assert result["parent_execution_id"] == original["id"]
        assert result["case_count"] == 1
        assert result["cases"][0]["case_id"] == selected["case_id"]
        assert result["cases"][0]["child"] != selected["child"]
        assert client.get(f"/api/physical-campaigns/executions/{original['id']}").json() == original
        assert client.get(f"/api/physical-campaigns/plans/{saved['id']}").json() == saved


def test_subset_rerun_keeps_saved_order_and_rechecks_current_node(native_library, tmp_path):
    with TestClient(create_app(data_dir=tmp_path)) as client:
        saved = plan(client)
        original = start(client, saved)
        assert original["status"] == "blocked"
        # Caller order does not override the original seeded order.
        selected = [row["case_id"] for row in original["cases"]][::2]
        response = client.post(
            f"/api/physical-campaigns/executions/{original['id']}/rerun",
            json={"case_ids": list(reversed(selected))},
        )
        assert response.status_code == 202, response.text
        missing = wait_terminal(client, response.json()["id"])
        assert missing["status"] == "blocked"
        assert all(row["child"] is None for row in missing["cases"])
        connect(client, native_library)
        response = client.post(
            f"/api/physical-campaigns/executions/{original['id']}/rerun",
            json={"case_ids": list(reversed(selected))},
        )
        result = wait_terminal(client, response.json()["id"])
        assert result["status"] == "completed"
        assert [row["case_id"] for row in result["cases"]] == selected
        expected = [row for row in saved["cases"] if row["id"] in selected]
        for actual, intent in zip(result["cases"], expected, strict=True):
            child = client.get("/api/diagnostic-runs/" + actual["child"]["id"]).json()
            assert child["arguments"]["payload_bytes"] == intent["case"]["payload_bytes"]
            assert actual["canonical_index"] == intent["canonical_index"]
            assert actual["index"] == selected.index(actual["case_id"])


def test_terminal_diagnostic_bundle_has_exact_independently_verified_manifest(
    native_library, tmp_path
):
    with TestClient(create_app(data_dir=tmp_path)) as client:
        connect(client, native_library)
        result = start(client, plan(client, (512,)))
        response = client.get(f"/api/physical-campaigns/executions/{result['id']}/export")
        assert response.status_code == 200, response.text
        assert hashlib.sha256(response.content).hexdigest() == response.headers["x-content-sha256"]
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            hashes = json.loads(archive.read("sha256.json"))
            assert set(archive.namelist()) == set(hashes) | {"sha256.json"}
            for name, expected in hashes.items():
                assert hashlib.sha256(archive.read(name)).hexdigest() == expected
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["case_count"] == 1 and manifest["child_count"] == 1
            assert manifest["file_count"] >= 1
            assert json.loads(archive.read("campaign.json")) == result
            child = manifest["children"][0]
            assert child["service"] == "diagnostic"
            assert json.loads(archive.read(child["path"]))["status"] == "completed"


def test_corrupted_diagnostic_trace_is_rejected_instead_of_silently_omitted(
    native_library, tmp_path
):
    with TestClient(create_app(data_dir=tmp_path)) as client:
        connect(client, native_library)
        result = start(client, plan(client, (512,)))
        child = result["cases"][0]["child"]["id"]
        path = client.app.state.host.diagnostics.directory / f"{child}.ndjson"
        path.write_bytes(path.read_bytes().replace(b"memory_probe", b"memory_probf", 1))
        response = client.get(f"/api/physical-campaigns/executions/{result['id']}/export")
        assert response.status_code == 400
        assert "hash" in response.json()["detail"].lower()


def test_native_data_and_voice_bundle_follows_every_child_and_rejects_saved_corruption(
    native_library, tmp_path
):
    import asyncio
    import contextlib

    from test_artifact_transfers import finished
    from test_voice_workflows import AudioPair

    from lora_testbed.audio import inspect_wav, pcm_wav, save_wav
    from lora_testbed.campaign_plans import CampaignSpec
    from lora_testbed.host import Host
    from lora_testbed.physical_campaign_evidence import CampaignBundle, verify_campaign_bundle

    async def scenario():
        host = Host(tmp_path)
        pair = AudioPair(host, native_library)
        bridge = None
        try:
            await pair.connect()
            wav = pcm_wav(b"\x00\x08" * 160, 160)
            reference = inspect_wav(wav, "bundle-reference.wav")
            save_wav(tmp_path, reference, wav)
            host.store.save_reference(reference)
            saved = host.campaign_plans.create(
                CampaignSpec.model_validate(
                    {
                        "name": "Complete actual data and voice evidence",
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
            started = await host.start_campaign(saved["id"])
            result = await finished(host.physical_campaigns, started["id"])
            assert result["status"] == "completed", result
            content = CampaignBundle(host).build(result["id"])
            checked = verify_campaign_bundle(content)
            assert checked["case_count"] == 2 and checked["child_count"] > 6
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                assert {child["service"] for child in manifest["children"]} == {
                    "radio",
                    "voice",
                    "audio",
                    "transfer",
                }
                for entry in manifest["files"]:
                    assert (
                        hashlib.sha256(archive.read(entry["path"])).hexdigest() == entry["sha256"]
                    )
                assert any(
                    archive.read(entry["path"]) == wav
                    for entry in manifest["files"]
                    if entry["kind"] == "reference_wav"
                )
                assert (
                    len({entry["path"] for entry in manifest["children"]}) == checked["child_count"]
                )
            radio = host.radio.get(result["cases"][0]["child"]["id"])
            assert radio["saved_files"]["wire"]["sha256"]
            trace = host.radio.content(radio["id"], "wire")
            original = trace.read_bytes()
            damaged = original.replace(b'"recorded_at"', b'"recorded_as"', 1)
            assert damaged != original
            trace.write_bytes(damaged)
            with pytest.raises(ValueError, match="hash"):
                CampaignBundle(host).build(result["id"])
            trace.write_bytes(original)
            transfer_id = radio["transfers"][radio["receiver"]]
            payload = host.artifacts.content(transfer_id)
            original = payload.read_bytes()
            payload.write_bytes(bytes([original[0] ^ 1]) + original[1:])
            with pytest.raises(ValueError, match="hash"):
                CampaignBundle(host).build(result["id"])
        finally:
            if bridge:
                bridge.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bridge
            await host.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("state", ["running", "paused"])
def test_cold_restart_interrupts_actual_active_or_paused_campaign_without_resume(
    native_library, tmp_path, state
):
    import asyncio
    import subprocess
    import sys
    import textwrap
    from pathlib import Path

    from lora_testbed.host import Host

    script = textwrap.dedent("""
        import asyncio, json, os, sys
        from pathlib import Path
        from types import SimpleNamespace
        sys.path.insert(0, sys.argv[4])
        from test_node_control_native import NativeSerial, native_library
        from lora_testbed.host import Host
        from lora_testbed.campaign_plans import CampaignSpec
        async def main():
            lib = native_library.__wrapped__(SimpleNamespace(mktemp=lambda _: Path(sys.argv[2])))
            host = Host(Path(sys.argv[1]))
            serial = NativeSerial(lib)
            host.physical["B"].opener = lambda _: serial
            await host.physical["B"].connect("isolated-crash-b")
            paused = sys.argv[3] == "paused"
            saved = host.campaign_plans.create(CampaignSpec.model_validate({
                "name":"Actual cold crash", "repetitions":2,
                "templates":[{"label":"memory", "case":{
                    "kind":"memory_probe", "role":"B", "iterations":1 if paused else 10000}}]}))
            result = await host.start_campaign(saved["id"])
            if paused:
                host.physical_campaigns.pause(result["id"])
            async with asyncio.timeout(8):
                while True:
                    record = host.physical_campaigns.get(result["id"])
                    if paused and record["status"] == "paused":
                        break
                    if not paused and record["cases"][0]["child"]:
                        child = host.diagnostics.get(record["cases"][0]["child"]["id"])
                        if child["status"] == "running":
                            break
                    await asyncio.sleep(.01)
            print(json.dumps({"id":result["id"], "plan_id":saved["id"],
                              "plan_sha256":saved["plan_sha256"]}), flush=True)
            os._exit(0)
        asyncio.run(main())
    """)
    (tmp_path / "native-crash-build").mkdir()
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(tmp_path),
            str(tmp_path / "native-crash-build"),
            state,
            str(Path(__file__).parent),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    identifiers = json.loads(result.stdout)
    host = Host(tmp_path)
    try:
        record = host.physical_campaigns.get(identifiers["id"])
        assert record["status"] == "interrupted" and record["reason_code"] == "host_restart"
        assert not record["cleanup"]["confirmed"] and not host.busy
        assert not any(node.connected for node in host.physical.values())
        assert all(
            case["status"] in ("completed", "interrupted", "skipped") for case in record["cases"]
        )
        with pytest.raises(ValueError, match="not active"):
            host.physical_campaigns.resume(record["id"])
        from lora_testbed.physical_campaign_evidence import CampaignBundle, verify_campaign_bundle

        checked = verify_campaign_bundle(CampaignBundle(host).build(record["id"]))
        assert checked["case_count"] == 2
        assert (
            host.campaign_plans.get(identifiers["plan_id"])["plan_sha256"]
            == identifiers["plan_sha256"]
        )
    finally:
        asyncio.run(host.close())


@pytest.fixture
def saved_bundle(native_library, tmp_path):
    with TestClient(create_app(data_dir=tmp_path)) as client:
        connect(client, native_library)
        result = start(client, plan(client, (512,)))
        response = client.get(f"/api/physical-campaigns/executions/{result['id']}/export")
        assert response.status_code == 200, response.text
        return response.content


@pytest.mark.parametrize(
    "fault", ["corrupt", "missing", "count", "duplicate", "unsafe", "hash_shape"]
)
def test_offline_verification_rejects_corrupted_or_incomplete_archives(saved_bundle, fault):
    from lora_testbed.physical_campaign_evidence import verify_campaign_bundle

    with zipfile.ZipFile(io.BytesIO(saved_bundle)) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    original = verify_campaign_bundle(saved_bundle)
    assert original["child_count"] == 1 and original["case_count"] == 1
    if fault == "corrupt":
        name = next(name for name in members if name.startswith("evidence/"))
        members[name] += b" "
    elif fault == "missing":
        members.pop(next(name for name in members if name.startswith("children/")))
    elif fault == "count":
        value = json.loads(members["manifest.json"])
        value["case_count"] += 1
        members["manifest.json"] = json.dumps(value).encode()
        hashes = json.loads(members["sha256.json"])
        hashes["manifest.json"] = hashlib.sha256(members["manifest.json"]).hexdigest()
        members["sha256.json"] = json.dumps(hashes).encode()
    elif fault == "unsafe":
        members["../outside.bin"] = b"unexpected"
    elif fault == "hash_shape":
        members["sha256.json"] = json.dumps(list(members)).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
        if fault == "duplicate":
            with pytest.warns(UserWarning, match="Duplicate"):
                archive.writestr("campaign.json", members["campaign.json"])
    with pytest.raises(ValueError):
        verify_campaign_bundle(output.getvalue())


def test_offline_cli_verifies_without_backend_and_rejects_corruption(saved_bundle, tmp_path):
    from typer.testing import CliRunner

    from lora_testbed.cli import app

    path = tmp_path / "campaign.zip"
    path.write_bytes(saved_bundle)
    result = CliRunner().invoke(app, ["campaign-verify", str(path)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["case_count"] == 1
    path.write_bytes(b"damaged zip")
    result = CliRunner().invoke(app, ["campaign-verify", str(path)])
    assert result.exit_code == 1 and "Malformed" in result.output


@pytest.mark.parametrize(
    "fault,expected", [("empty", 422), ("duplicate", 400), ("unknown", 400), ("invalid", 422)]
)
def test_invalid_rerun_selection_does_not_create_an_execution(tmp_path, fault, expected):
    from uuid import uuid4

    with TestClient(create_app(data_dir=tmp_path)) as client:
        result = start(client, plan(client))
        selected = result["cases"][0]["case_id"]
        case_ids = {
            "empty": [],
            "duplicate": [selected, selected],
            "unknown": [str(uuid4())],
            "invalid": ["not-a-case"],
        }[fault]
        before = client.get("/api/physical-campaigns/executions").json()
        response = client.post(
            f"/api/physical-campaigns/executions/{result['id']}/rerun", json={"case_ids": case_ids}
        )
        assert response.status_code == expected, response.text
        assert client.get("/api/physical-campaigns/executions").json() == before


def test_active_export_rerun_and_competing_owner_are_rejected(native_library, tmp_path):
    with TestClient(create_app(data_dir=tmp_path)) as client:
        original = start(client, plan(client))
        connect(client, native_library)
        saved = plan(client, (512,), iterations=10000)
        response = client.post("/api/physical-campaigns/executions", json={"plan_id": saved["id"]})
        identifier = response.json()["id"]
        wait_for(client, identifier, lambda record: record["cases"][0]["child"] is not None)
        assert (
            client.get(f"/api/physical-campaigns/executions/{identifier}/export").status_code == 409
        )
        for parent in (
            client.get(f"/api/physical-campaigns/executions/{identifier}").json(),
            original,
        ):
            response = client.post(
                f"/api/physical-campaigns/executions/{parent['id']}/rerun",
                json={"case_ids": [parent["cases"][0]["case_id"]]},
            )
            assert response.status_code == 409, response.text
        assert (
            client.post(
                f"/api/physical-campaigns/executions/{identifier}/cancel", json={}
            ).status_code
            == 200
        )


@pytest.mark.parametrize("scope", ["header", "case"])
def test_corrupted_execution_ledger_rejects_read_rerun_and_export(native_library, tmp_path, scope):
    with TestClient(create_app(data_dir=tmp_path)) as client:
        connect(client, native_library)
        result = start(client, plan(client, (512,)))
        table = (
            "physical_campaign_executions_v1" if scope == "header" else "physical_campaign_cases_v1"
        )
        where = "id" if scope == "header" else "execution_id"
        db = client.app.state.host.store.db
        record = json.loads(
            db.execute(f"SELECT document FROM {table} WHERE {where}=?", (result["id"],)).fetchone()[
                0
            ]
        )
        record["status"] = "failed"
        db.execute(
            f"UPDATE {table} SET document=? WHERE {where}=?", (json.dumps(record), result["id"])
        )
        db.commit()
        path = f"/api/physical-campaigns/executions/{result['id']}"
        for response in (
            client.get(path),
            client.get(path + "/export"),
            client.post(path + "/rerun", json={"case_ids": [result["cases"][0]["case_id"]]}),
        ):
            assert response.status_code == 400 and "hash" in response.json()["detail"]


def test_cli_export_verifies_before_creating_file_and_preserves_existing_output(
    saved_bundle, tmp_path, monkeypatch
):
    from typer.testing import CliRunner

    from lora_testbed.cli import app
    from lora_testbed.physical_campaign_evidence import verify_campaign_bundle

    identifier = verify_campaign_bundle(saved_bundle)["execution_id"]
    data = saved_bundle

    def response(*args, **kwargs):
        result = io.BytesIO(data)
        result.headers = {"X-Content-SHA256": hashlib.sha256(data).hexdigest()}
        return result

    monkeypatch.setattr("lora_testbed.cli.urlopen", response)
    output = tmp_path / "download.zip"
    command = ["campaign-export", identifier, str(output)]
    result = CliRunner().invoke(app, command)
    assert result.exit_code == 0, result.output
    assert output.read_bytes() == saved_bundle
    result = CliRunner().invoke(app, command)
    assert result.exit_code == 1 and output.read_bytes() == saved_bundle
    data = b"damaged archive with a matching HTTP digest"
    destination = tmp_path / "rejected.zip"
    result = CliRunner().invoke(app, ["campaign-export", identifier, str(destination)])
    assert result.exit_code == 1 and not destination.exists()


def test_partial_serial_child_keeps_all_procedure_rows_without_full_qualification(
    native_library, tmp_path
):
    with TestClient(create_app(data_dir=tmp_path)) as client:
        connect(client, native_library)
        saved = client.post(
            "/api/physical-campaigns/plans",
            json={
                "name": "Partial physical serial evidence",
                "templates": [
                    {"label": "serial", "case": {"kind": "serial_check", "role": "B", "cycles": 1}}
                ],
            },
        ).json()
        result = start(client, saved)
        assert result["status"] == "completed", result
        response = client.get(f"/api/physical-campaigns/executions/{result['id']}/export")
        assert response.status_code == 200, response.text
        identifier = result["cases"][0]["child"]["id"]
        rows = list(client.app.state.host.procedures.all_evidence(identifier))
        assert rows
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            child = json.loads(archive.read(f"children/procedure/{identifier}.json"))
            assert not child["full_procedure_passed"]
            retained = [
                json.loads(line)
                for line in archive.read(f"evidence/procedure/{identifier}.jsonl").splitlines()
            ]
            assert retained == rows


@pytest.mark.parametrize("limit", ["expanded", "members"])
def test_offline_verification_enforces_expanded_archive_and_member_bounds(
    saved_bundle, limit, monkeypatch
):
    from lora_testbed import physical_campaign_evidence as evidence

    if limit == "expanded":
        # Compressed input fits; its expanded evidence does not.
        with zipfile.ZipFile(io.BytesIO(saved_bundle)) as archive:
            expanded = sum(entry.file_size for entry in archive.infolist())
        assert expanded > len(saved_bundle)
        monkeypatch.setattr(evidence, "MAX_BYTES", len(saved_bundle))
    else:
        monkeypatch.setattr(evidence, "MAX_MEMBERS", 2)
    with pytest.raises(ValueError, match="Expanded|excessive"):
        evidence.verify_campaign_bundle(saved_bundle)


def test_slow_campaign_export_does_not_block_control_state_requests(tmp_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from lora_testbed.physical_campaign_evidence import CampaignBundle

    started, release = threading.Event(), threading.Event()
    build = CampaignBundle.build

    def slow(self, identifier):
        started.set()
        assert release.wait(5)
        return build(self, identifier)

    monkeypatch.setattr(CampaignBundle, "build", slow)
    with TestClient(create_app(data_dir=tmp_path)) as client:
        result = start(client, plan(client))
        with ThreadPoolExecutor(max_workers=2) as pool:
            exported = pool.submit(
                client.get, f"/api/physical-campaigns/executions/{result['id']}/export"
            )
            assert started.wait(2)
            try:
                state = pool.submit(client.get, "/api/state").result(timeout=1)
                assert state.status_code == 200
            finally:
                release.set()
            assert exported.result(timeout=3).status_code == 200


def test_cancelled_export_and_host_shutdown_join_worker_before_database_close(
    tmp_path, monkeypatch
):
    import asyncio
    import threading

    from lora_testbed.campaign_plans import CampaignSpec
    from lora_testbed.host import Host
    from lora_testbed.physical_campaign_evidence import CampaignBundle

    started, release = threading.Event(), threading.Event()
    build = CampaignBundle.build

    def slow(self, identifier):
        started.set()
        assert release.wait(5)
        return build(self, identifier)

    monkeypatch.setattr(CampaignBundle, "build", slow)

    async def scenario():
        host = Host(tmp_path)
        saved = host.campaign_plans.create(
            CampaignSpec.model_validate(
                {
                    "name": "Join export",
                    "templates": [{"label": "missing", "case": {"kind": "memory_probe"}}],
                }
            )
        )
        result = await host.start_campaign(saved["id"])
        await host.physical_campaigns.task
        exporting = asyncio.create_task(host.campaign_exports.export(result["id"]))
        closing = None
        try:
            assert await asyncio.to_thread(started.wait, 2)
            with pytest.raises(RuntimeError, match="Another campaign export"):
                await host.campaign_exports.export(result["id"])
            exporting.cancel()
            await asyncio.sleep(0)
            closing = asyncio.create_task(host.close())
            await asyncio.sleep(0.02)
            assert not closing.done()
            with pytest.raises(RuntimeError, match="shutting down"):
                await host.campaign_exports.export(result["id"])
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await exporting
            await closing
            assert not host.campaign_exports.workers
        finally:
            release.set()
            await asyncio.gather(exporting, return_exceptions=True)
            if closing:
                await closing
            else:
                await host.close()

    asyncio.run(scenario())
