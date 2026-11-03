"""Exercise the physical host path using isolated serial peers; never open hardware."""

import hashlib
import io
import json
import time
import zipfile

import pytest
from fastapi.testclient import TestClient
from test_nodes import FirmwarePeer
from typer.testing import CliRunner

from lora_testbed import cli
from lora_testbed.app import create_app
from lora_testbed.catalog import LOCAL_TESTS, ROWS
from lora_testbed.nodes import NodeSession


@pytest.fixture
def bench(tmp_path, monkeypatch):
    peers = {f"test-{role}": FirmwarePeer() for role in "AB"}
    for role in "AB":
        peers[f"test-{role}"].identity.update(device_id=f"device-{role}", boot_id=f"boot-{role}")
    monkeypatch.setattr(
        "lora_testbed.host.discover_ports", lambda: [{"device": port} for port in peers]
    )
    monkeypatch.setattr(
        "lora_testbed.host.NodeSession",
        lambda role, on_event: NodeSession(role, on_event, opener=lambda port: peers[port]),
    )
    with TestClient(create_app(tmp_path)) as client:
        yield client, peers


def connect(client, role):
    response = client.post(f"/api/nodes/{role}/connection", json={"port": f"test-{role}"})
    assert response.status_code == 200, response.text
    return response.json()


def finish(client, identity):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        record = client.get(f"/api/procedures/runs/{identity}").json()
        if record["finished_at"]:
            return record
        time.sleep(0.01)
    pytest.fail("Physical diagnostic check did not finish")


def test_host_is_physical_only_and_never_opens_a_port_at_startup(bench):
    client, peers = bench
    state = client.get("/api/state").json()
    assert state["mode"] == "hardware" and state["connected_node_count"] == 0
    assert len(state["nodes"]) == 2 and not any(n["connected"] for n in state["nodes"])
    assert not any(p.writes for p in peers.values())
    assert len(state["catalog"]) == 23
    assert [e["id"] for e in state["catalog"] if e["available"]] == ["IF-01"]
    for path in (
        "/api/bench/mode",
        "/api/nodes/connection",
        "/api/v2/runs",
        "/api/v2/campaigns",
        "/api/campaigns",
        "/api/procedures/integration",
    ):
        assert client.post(path, json={"mode": "simulated"}).status_code == 410
    assert client.get("/api/protocol/v2/execution").json()["execution_modes"] == []
    assert client.post("/api/runs", json={"loss_rate": 0.5}).status_code == 422
    assert client.post("/api/runs", json={"simulation": {}}).status_code == 422
    with client.websocket_connect("/api/live") as socket:
        assert socket.receive_json()["mode"] == "hardware"
    assert not any(p.writes for p in peers.values())
    assert (
        client.get("/api/state", headers={"Origin": "https://unrelated.example"}).status_code == 403
    )


@pytest.mark.parametrize("role", ["A", "B"])
def test_one_node_checks_use_either_role_and_retain_raw_evidence(bench, role):
    client, peers = bench
    connect(client, role)
    preflight = client.post("/api/experiments/IF-01/preflight", json={}).json()
    assert preflight["ready"] and preflight["roles"] == [role]
    started = client.post("/api/procedures/serial", json={"cycles": 2})
    assert started.status_code == 201, started.text
    result = finish(client, started.json()["id"])
    assert result["status"] == "completed" and result["assessment"] == "pass"
    assert result["mode"] == "hardware" and result["roles"] == [role]
    assert not result["full_procedure_passed"] and not result["hardware_validated"]
    assert result["identities"][role]["device_id"] == f"device-{role}"
    other = "B" if role == "A" else "A"
    assert not peers[f"test-{other}"].writes
    evidence = client.get(f"/api/procedures/runs/{result['id']}/evidence").json()["events"]
    commands = [
        r["document"]["record"]
        for r in evidence
        if r["document"].get("direction") == "host_to_node"
    ]
    replies = [
        r["document"]["record"]
        for r in evidence
        if r["document"].get("direction") == "node_to_host"
    ]
    assert [c["name"] for c in commands] == [
        "hello",
        "control.keepalive",
        "status.get",
        "control.keepalive",
        "status.get",
    ]
    assert [r["command_id"] for r in replies] == [c["command_id"] for c in commands]
    assert all(r["boot_id"] == f"boot-{role}" for r in replies)
    archive = client.get(f"/api/procedures/runs/{result['id']}/export/zip")
    with zipfile.ZipFile(io.BytesIO(archive.content)) as package:
        assert json.loads(package.read("provenance.json"))["mode"] == "hardware"
        for name, digest in json.loads(package.read("manifest.json"))["sha256"].items():
            assert hashlib.sha256(package.read(name)).hexdigest() == digest
    assert client.get("/api/state").json()["hardware_nodes"][0 if role == "A" else 1]["connected"]


@pytest.mark.parametrize("code", [r[0] for r in ROWS])
def test_requirements_are_per_test_not_a_global_two_node_gate(bench, code):
    client, _ = bench
    connect(client, "B")
    result = client.post(f"/api/experiments/{code}/preflight", json={}).json()
    assert result["required_nodes"] == (1 if code in LOCAL_TESTS else 2)
    if code in LOCAL_TESTS:
        assert result["roles"] == ["B"]
        assert not any("disconnected" in b for b in result["blockers"])
    else:
        assert result["roles"] == ["A", "B"] and not result["ready"]
        assert "Node A is disconnected" in result["blockers"]
    assert result["ready"] == (code == "IF-01")


@pytest.mark.parametrize("code", ["MEM-01", "OPS-01"])
def test_mixed_tests_distinguish_local_and_rf_workloads(bench, code):
    client, _ = bench
    connect(client, "A")
    local = client.post(f"/api/experiments/{code}/preflight", json={"workload": "local"}).json()
    rf = client.post(f"/api/experiments/{code}/preflight", json={"workload": "rf"}).json()
    assert local["required_nodes"] == 1 and local["roles"] == ["A"]
    assert rf["required_nodes"] == 2 and "Node B is disconnected" in rf["blockers"]


def test_two_nodes_can_be_checked_sequentially_or_selected_independently(bench):
    client, _ = bench
    connect(client, "A")
    connect(client, "B")
    default = client.post("/api/experiments/IF-01/preflight", json={}).json()
    assert default["ready"] and default["roles"] == ["A"]
    link = client.post("/api/experiments/IF-02/preflight", json={}).json()
    assert not link["ready"] and not any("disconnected" in b for b in link["blockers"])
    assert any("radio" in b for b in link["blockers"])
    start = client.post("/api/procedures/serial", json={"roles": ["A", "B"], "cycles": 2})
    result = finish(client, start.json()["id"])
    assert result["status"] == "completed"
    assert [c["role"] for c in result["cases"]] == ["A", "B"]
    assert client.post("/api/nodes/A/connection", json={"port": None}).status_code == 200
    assert client.post("/api/experiments/IF-01/preflight", json={}).json()["roles"] == ["B"]


def test_missing_duplicate_incompatible_nodes_and_unsupported_workloads_are_rejected(bench):
    client, peers = bench
    assert client.post("/api/procedures/serial", json={}).status_code == 400
    connect(client, "A")
    assert client.post("/api/procedures/serial", json={"roles": ["B"]}).status_code == 400
    assert client.post("/api/procedures/serial", json={"roles": ["A", "A"]}).status_code == 422
    assert client.post("/api/procedures/serial", json={"roles": []}).status_code == 422
    assert client.post("/api/procedures/serial", json={"cycles": 11}).status_code == 422
    assert client.post("/api/procedures/serial", json={"simulation": {}}).status_code == 422
    assert client.post("/api/nodes/B/connection", json={"port": "test-A"}).status_code == 400
    peers["test-B"].identity["device_id"] = peers["test-A"].identity["device_id"]
    response = client.post("/api/nodes/B/connection", json={"port": "test-B"})
    assert response.status_code == 400 and "physical device" in response.text
    assert peers["test-B"].closed
    assert (
        client.post("/api/experiments/IF-02/preflight", json={"workload": "local"}).status_code
        == 400
    )
    assert (
        client.post("/api/experiments/VOICE-01/preflight", json={"workload": "rf"}).status_code
        == 400
    )
    assert client.post("/api/experiments/unknown/preflight", json={}).status_code == 400


def test_connection_rejects_simulated_provenance(bench):
    client, peers = bench
    peers["test-A"].identity["provenance"] = "simulated"
    result = client.post("/api/nodes/A/connection", json={"port": "test-A"})
    assert result.status_code == 400 and "provenance" in result.text
    assert peers["test-A"].closed


def test_cancellation_retains_evidence_and_releases_bench_ownership(bench):
    client, _ = bench
    connect(client, "A")
    start = client.post("/api/procedures/serial", json={"cycles": 10}).json()
    assert client.post("/api/procedures/serial", json={}).status_code == 409
    assert client.post("/api/nodes/A/connection", json={"port": None}).status_code == 409
    assert client.get(f"/api/procedures/runs/{start['id']}/export/zip").status_code == 409
    stopped = client.post("/api/procedures/stop").json()
    assert stopped["status"] == "cancelled" and stopped["finished_at"]
    assert not stopped["full_procedure_passed"]
    assert client.post("/api/procedures/stop").json()["id"] == stopped["id"]
    assert client.get(f"/api/procedures/runs/{start['id']}/evidence").json()["events"]
    next_run = client.post("/api/procedures/serial", json={"cycles": 1}).json()
    assert finish(client, next_run["id"])["status"] == "completed"


def test_no_reply_fails_check_and_recovery_is_possible(bench, monkeypatch):
    client, peers = bench
    connect(client, "A")
    original_request = NodeSession.request

    async def bounded(self, name, *args, **kwargs):
        return await original_request(
            self, name, *args, **{**kwargs, "timeout": 0.04, "retries": 0}
        )

    monkeypatch.setattr(NodeSession, "request", bounded)
    write = peers["test-A"].write
    monkeypatch.setattr(peers["test-A"], "write", lambda wire: len(wire))
    result = client.post("/api/procedures/serial", json={"cycles": 1}).json()
    failed = finish(client, result["id"])
    assert failed["status"] == "failed" and failed["assessment"] == "inconclusive"
    assert "No v2 reply" in failed["reason"]
    assert client.get(f"/api/procedures/runs/{result['id']}/evidence").json()["events"]
    monkeypatch.setattr(peers["test-A"], "write", write)
    result = client.post("/api/procedures/serial", json={"cycles": 1}).json()
    assert finish(client, result["id"])["status"] == "completed"


def test_device_reset_during_check_preserves_interrupted_evidence(bench):
    client, peers = bench
    connect(client, "A")
    start = client.post("/api/procedures/serial", json={"cycles": 10}).json()
    peers["test-A"].emit(1, boot="new-boot")
    result = finish(client, start["id"])
    assert result["status"] == "failed" and result["assessment"] == "inconclusive"
    assert "reset" in result["reason"] or "disconnected" in result["reason"]
    assert result["identities"]["A"]["boot_id"] == "boot-A"


def test_cli_uses_physical_node_controls_and_single_node_defaults(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "request", lambda path, body=None: calls.append((path, body)))
    runner = CliRunner()
    assert runner.invoke(cli.app, ["serial-check"]).exit_code == 0
    assert calls[-1] == ("/api/procedures/serial", {"roles": None, "cycles": 3})
    assert runner.invoke(cli.app, ["serial-check", "--role", "B"]).exit_code == 0
    assert calls[-1][1]["roles"] == ["B"]
    assert runner.invoke(cli.app, ["preflight", "MEM-01", "--workload", "rf"]).exit_code == 0
    assert calls[-1][1]["workload"] == "rf"
    for removed in ("mode", "connect", "run-v2", "campaign-v2", "integration-check"):
        assert runner.invoke(cli.app, [removed]).exit_code != 0


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"node_role": "B"}, "ownership"),
        ({"uptime_us": 0}, "uptime"),
        ({"telemetry_drops": 1}, "telemetry"),
    ],
)
def test_invalid_observed_status_never_passes_diagnostic_check(bench, override, reason):
    client, peers = bench
    connect(client, "A")
    peers["test-A"].status_override = override
    started = client.post("/api/procedures/serial", json={"cycles": 1}).json()
    result = finish(client, started["id"])
    assert result["status"] == "failed" and result["assessment"] == "inconclusive"
    assert reason in result["reason"].lower()
    assert not result["full_procedure_passed"]


def test_shutdown_restart_and_historical_procedure_records_remain_honest(tmp_path, monkeypatch):
    peer = FirmwarePeer()
    monkeypatch.setattr("lora_testbed.host.discover_ports", lambda: [{"device": "test-A"}])
    monkeypatch.setattr(
        "lora_testbed.host.NodeSession",
        lambda role, on_event: NodeSession(role, on_event, opener=lambda _: peer),
    )
    with TestClient(create_app(tmp_path)) as client:
        connect(client, "A")
        started = client.post("/api/procedures/serial", json={"cycles": 10}).json()
    # The backend lifespan interrupts the check and releases its diagnostic lease.
    assert peer.closed
    assert any(json.loads(w)["name"] == "control.release" for w in peer.writes)
    with TestClient(create_app(tmp_path)) as reopened:
        result = reopened.get(f"/api/procedures/runs/{started['id']}").json()
        assert result["status"] == "interrupted" and result["assessment"] == "inconclusive"
        assert result["finished_at"] and not result["full_procedure_passed"]
        assert reopened.get("/api/state").json()["connected_node_count"] == 0
        assert reopened.get(f"/api/procedures/runs/{started['id']}/evidence").json()["events"]


def test_restart_recovers_incomplete_historical_record_without_relabeling(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        service = client.app.state.host.procedures
        service.save(
            {
                "id": "historical",
                "created_at": "2026-10-30T00:00:00Z",
                "catalog_id": "IF-01",
                "mode": "simulated",
                "status": "running",
                "assessment": "not_assessed",
                "cases": [{"id": "old-case", "status": "running"}],
                "full_procedure_passed": False,
            }
        )
    with TestClient(create_app(tmp_path)) as client:
        result = client.get("/api/procedures/runs/historical").json()
        assert result["mode"] == "simulated" and result["status"] == "interrupted"
        assert result["assessment"] == "inconclusive" and not result["matches_current_profile"]
        assert result["cases"][0]["status"] == "interrupted"


def test_default_local_selection_skips_an_unhealthy_other_node(bench):
    client, _ = bench
    connect(client, "A")
    connect(client, "B")
    host = client.app.state.host
    host.physical["A"].last_health = time.monotonic() - 4
    result = client.post("/api/experiments/IF-01/preflight", json={}).json()
    assert result["ready"] and result["roles"] == ["B"]
    explicit = client.post("/api/experiments/IF-01/preflight", json={"roles": ["A"]}).json()
    assert not explicit["ready"] and any("health" in b for b in explicit["blockers"])
