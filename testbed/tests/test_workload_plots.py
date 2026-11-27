"""Bounded plot views retain actual observations and independent full exports."""

import hashlib
import json

import pytest
from fastapi.testclient import TestClient
from test_node_control_native import native_library as native_library
from test_workload_assessments import memory_trace, recorded_overloaded_queue

from lora_testbed.app import create_app


def test_plot_projection_contains_actual_samples_and_full_export_retains_every_row(
    native_library, tmp_path
):
    evidence = {
        "source": recorded_overloaded_queue(native_library),
        "memory": memory_trace(native_library),
    }
    with TestClient(create_app(data_dir=tmp_path)) as client:
        saved = client.post("/api/workload-assessments", json=evidence).json()
        path = "/api/workload-assessments/" + saved["id"]
        response = client.get(path + "/plots?max_points=32")
        assert response.status_code == 200, response.text
        view = response.json()
        assert view["record"]["origin"] == "imported_unverified"
        assert not view["record"]["hardware_qualified"]
        source = view["source"]
        assert 1 < len(source["points"]) <= 32
        assert source["total_samples"] == 451
        samples = {row["index"]: row for row in evidence["source"]["queue_samples"]}
        for point in source["points"]:
            original = samples[point["index"]]
            assert point["elapsed_us"] == original["actual_elapsed_us"]
            assert point["values"]["occupancy_bytes"] == original["status"]["occupancy_bytes"]
            assert (
                point["values"]["overflow_dropped_bytes"]
                == original["status"]["overflow_dropped_bytes"]
            )
        assert source["summary"]["capacity"]["finding"] == "unsustainable"
        assert source["summary"]["intervals"]["production"]["nominal_interval_us"] == [
            3000000,
            60000000,
        ]
        assert view["memory"]["summary"]["true_peak"]["value"] is None
        assert (
            view["memory"]["summary"]["observed"]["internal"]["boot_minimum_free_bytes"] == 130000
        )
        exported = client.get(path + "/export")
        assert exported.status_code == 200
        assert "attachment" in exported.headers["content-disposition"]
        assert exported.headers["x-content-sha256"] == hashlib.sha256(exported.content).hexdigest()
        original = json.loads(exported.content)
        assert len(original["evidence"]["source"]["frames"]) == 3000
        assert len(original["evidence"]["source"]["queue_samples"]) == 451
        assert original == saved


def test_missing_prefix_and_null_psram_are_visible_without_synthetic_observations(
    native_library, tmp_path
):
    evidence = {
        "source": recorded_overloaded_queue(native_library),
        "memory": memory_trace(native_library),
    }
    del evidence["source"]["queue_samples"][0]
    del evidence["memory"]["events"][1]
    evidence["memory"]["status"]["measurement_minimum"]["psram_free_bytes"] = None
    for event in evidence["memory"]["events"]:
        event["data"]["memory"]["psram"] = None
    with TestClient(create_app(data_dir=tmp_path)) as client:
        saved = client.post("/api/workload-assessments", json=evidence).json()
        view = client.get("/api/workload-assessments/" + saved["id"] + "/plots").json()
        assert view["source"]["gap_count"] >= 1
        assert view["source"]["summary"]["capacity"]["finding"] == "inconclusive"
        assert view["source"]["points"][0]["index"] == 1
        assert view["memory"]["gap_count"] >= 1
        assert view["memory"]["summary"]["assessment"] == "inconclusive"
        assert all(
            point["values"]["psram_free_bytes"] is None for point in view["memory"]["points"]
        )
        assert view["memory"]["summary"]["observed"]["psram"]["availability"] == "unavailable"


def long_memory_trace(lib):
    from test_node_artifacts_native import spec
    from test_node_control_native import NativeNode

    node = NativeNode(lib)
    records = []

    def send(name, args=None):
        rows = node.send(node.command(name, args))
        records.extend(rows)
        reply = next(row for row in rows if row["kind"] == "reply")
        assert reply["ok"], reply
        return reply["result"]

    try:
        node.claim()
        send("memory.start", {"duration_ms": 300000})
        artifact = spec(1024)
        for index in range(1, 3001):
            node.tick(100000)
            records.extend(node.drain())
            if index == 1499:
                send("artifact.begin", artifact)
            elif index == 1500:
                send("artifact.delete", {"artifact_id": artifact["artifact_id"]})
            if index % 10 == 0:
                send("control.keepalive")
        status = send("memory.status")
        return {
            "status": status,
            "events": [row for row in records if row.get("name") == "memory.sample"],
        }
    finally:
        node.close()


def test_five_minute_native_observation_keeps_a_one_sample_peak_and_full_export(
    native_library, tmp_path
):
    evidence = {"memory": long_memory_trace(native_library)}
    assert len(evidence["memory"]["events"]) >= 3001
    with TestClient(create_app(data_dir=tmp_path)) as client:
        response = client.post("/api/workload-assessments", json=evidence)
        assert response.status_code == 201, response.text
        saved = response.json()
        path = "/api/workload-assessments/" + saved["id"]
        view = client.get(path + "/plots?max_points=32").json()["memory"]
        assert len(view["points"]) <= 32 and view["total_samples"] >= 3001
        assert view["summary"]["assessment"] == "consistent", view["summary"]["reasons"]
        assert min(point["values"]["internal_free_bytes"] for point in view["points"]) == 398976
        assert max(point["values"]["known_internal_bytes"] for point in view["points"]) == 1024
        assert view["points"][0]["elapsed_us"] == 0
        assert view["points"][-1]["elapsed_us"] == 300000000
        assert view["gap_count"] == 0
        assert len(client.get(path + "/export").json()["evidence"]["memory"]["events"]) == len(
            evidence["memory"]["events"]
        )


def test_conflicting_sender_clock_cannot_be_drawn_as_one_continuous_history(
    native_library, tmp_path
):
    evidence = {"source": recorded_overloaded_queue(native_library)}
    evidence["source"]["queue_samples"][10]["status"]["started_us"] += 1
    with TestClient(create_app(data_dir=tmp_path)) as client:
        saved = client.post("/api/workload-assessments", json=evidence).json()
        view = client.get("/api/workload-assessments/" + saved["id"] + "/plots").json()["source"]
        assert not view["points"]
        assert view["clock"]["unavailable_reason"]
        assert view["total_samples"] == 451
        assert view["summary"]["capacity"]["finding"] == "inconclusive"


def many_stage_trace(lib):
    from test_node_control_native import NativeNode

    node = NativeNode(lib)
    records = []

    def send(name, args=None):
        rows = node.send(node.command(name, args))
        records.extend(rows)
        reply = next(row for row in rows if row["kind"] == "reply")
        assert reply["ok"], reply
        return reply["result"]

    try:
        node.claim()
        started = send("memory.start", {"duration_ms": 30000})
        for _index in range(40):
            send("diag.run", {"kind": "memory_probe", "iterations": 1, "payload_bytes": 1})
            for _ in range(2):
                node.tick(10000)
                records.extend(node.drain())
        send("memory.stop", {"observation_id": started["observation_id"]})
        status = send("memory.status")
        return {
            "status": status,
            "events": [row for row in records if row.get("name") == "memory.sample"],
        }
    finally:
        node.close()


def test_stage_and_buffer_paging_are_bounded_and_leave_complete_evidence_unchanged(
    native_library, tmp_path
):
    with TestClient(create_app(data_dir=tmp_path)) as client:
        saved = client.post(
            "/api/workload-assessments", json={"memory": many_stage_trace(native_library)}
        ).json()
        path = "/api/workload-assessments/" + saved["id"]
        first = client.get(path + "/plots").json()["memory"]
        assert first["stages"]["total"] > 32 and first["buffers"]["total"] > 32
        assert len(first["stages"]["rows"]) == len(first["buffers"]["rows"]) == 32
        assert first["stages"]["next_offset"] == first["buffers"]["next_offset"] == 32
        second = client.get(path + "/plots?stage_offset=32&buffer_offset=32").json()["memory"]
        assert second["stages"]["rows"][0] == saved["assessments"]["memory"]["stages"][32]
        assert (
            second["buffers"]["rows"][0] == saved["assessments"]["memory"]["buffer_lifetimes"][32]
        )
        assert client.get(path).json() == saved
        assert client.get(path + "/plots?max_points=31").status_code == 422
        assert client.get(path + "/plots?max_points=961").status_code == 422


def test_missing_memory_tail_stops_at_last_observed_sample(native_library, tmp_path):
    evidence = {"memory": memory_trace(native_library)}
    removed = evidence["memory"]["events"].pop()
    last = evidence["memory"]["events"][-1]["data"]["taken_us"]
    origin = evidence["memory"]["status"]["started_us"]
    with TestClient(create_app(data_dir=tmp_path)) as client:
        saved = client.post("/api/workload-assessments", json=evidence).json()
        view = client.get("/api/workload-assessments/" + saved["id"] + "/plots").json()["memory"]
        assert view["bounds_us"][1] == last - origin
        assert all(
            point["index"] < removed["data"]["sample_index"] for point in view["points"]
        )
        assert view["gap_count"] >= 1
        assert "Final rows" in view["gaps"]["rows"][-1]["reasons"][0]
        assert view["summary"]["assessment"] == "inconclusive"


def test_mixed_boot_memory_cannot_be_plotted_in_one_clock(native_library, tmp_path):
    from uuid import uuid4

    evidence = {"memory": memory_trace(native_library)}
    evidence["memory"]["events"][-1]["boot_id"] = str(uuid4())
    with TestClient(create_app(data_dir=tmp_path)) as client:
        saved = client.post("/api/workload-assessments", json=evidence).json()
        view = client.get("/api/workload-assessments/" + saved["id"] + "/plots").json()["memory"]
        assert not view["points"] and view["bounds_us"] is None
        assert view["clock"]["unavailable_reason"]
        assert view["total_samples"] == len(evidence["memory"]["events"])


@pytest.mark.parametrize("suffix", ["/plots", "/export"])
def test_corrupted_saved_observations_are_neither_plotted_nor_exported(
    native_library, tmp_path, suffix
):
    app = create_app(data_dir=tmp_path)
    with TestClient(app) as client:
        saved = client.post(
            "/api/workload-assessments", json={"memory": memory_trace(native_library)}
        ).json()
        saved["evidence"]["memory"]["events"][0]["data"]["memory"]["internal"]["free_bytes"] -= 1
        db = app.state.host.store.db
        db.execute(
            "UPDATE workload_assessments_v1 SET document=? WHERE id=?",
            (json.dumps(saved), saved["id"]),
        )
        db.commit()
        response = client.get("/api/workload-assessments/" + saved["id"] + suffix)
        assert response.status_code == 400
        assert "hash differs" in response.json()["detail"]
