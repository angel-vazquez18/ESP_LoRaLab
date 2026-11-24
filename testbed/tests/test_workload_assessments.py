"""Assess real portable queue observations with explicitly injected fixture time."""

import base64
import ctypes as C
import hashlib

import pytest
from test_encoded_source_queue import COUNTERS, Message, Queue, Sample, Trace, consumer
from test_node_control_native import native_library as native_library


def source_status(value):
    return {
        **{name: getattr(value, name) for name in COUNTERS},
        **{
            name: getattr(value, name)
            for name in (
                "started_us",
                "production_end_us",
                "drain_deadline_us",
                "drain_cutoff",
                "consistent",
                "cancel_requested",
            )
        },
    }


def recorded_overloaded_queue(lib, fast=False, outcomes=None, cancel_at=None):
    consumer(lib)
    queue = Queue(lib)
    try:
        assert lib.encoded_queue_start(queue.queue, 1_000_000)
        for index in range(4501):
            if index == cancel_at:
                lib.encoded_queue_request_stop.argtypes = [C.c_void_p]
                lib.encoded_queue_request_stop(queue.queue)
            queue.step(index * 20000)
            if index == cancel_at:
                break
            if fast:
                message = Message()
                if lib.encoded_queue_take(queue.queue, C.byref(message)):
                    assert lib.encoded_queue_complete(
                        queue.queue, message.message_id, (outcomes or {}).get(message.message_id, 0)
                    )
        frames = (Trace * 3000)()
        trace_count = lib.encoded_queue_trace(queue.queue, 0, frames, 3000)
        assert trace_count == queue.status().trace_frames
        lib.encoded_queue_samples.argtypes = [C.c_void_p, C.c_uint32, C.POINTER(Sample), C.c_size_t]
        lib.encoded_queue_samples.restype = C.c_size_t
        samples = (Sample * 451)()
        count = lib.encoded_queue_samples(queue.queue, 0, samples, 451)
        return {
            "execution_status": "completed",
            "status": source_status(queue.status()),
            "frames": [
                {
                    "index": row.index,
                    "planned_elapsed_us": row.planned_elapsed_us,
                    "actual_elapsed_us": row.actual_elapsed_us if row.produced else None,
                    "produced": row.produced,
                }
                for row in frames[:trace_count]
            ],
            "queue_samples": [
                {
                    "index": row.index,
                    "planned_elapsed_us": row.planned_elapsed_us,
                    "actual_elapsed_us": row.actual_elapsed_us,
                    "missed_intervals": row.missed_intervals,
                    "status": source_status(row.status),
                }
                for row in samples[:count]
            ],
        }
    finally:
        queue.close()


def test_completed_overloaded_source_reconciles_and_is_a_valid_infeasibility_finding(
    native_library,
):
    from lora_testbed.workload_assessment import SourceEvidence, assess_source

    evidence = SourceEvidence.model_validate(recorded_overloaded_queue(native_library))
    result = assess_source(evidence)
    assert result["accounting"]["status"] == "consistent"
    totals = result["accounting"]["totals"]
    assert totals["produced_bytes"] == 24000 and totals["admitted_bytes"] == 4800
    assert totals["overflow_dropped_bytes"] == 19200 and totals["queue_discarded_bytes"] == 4800
    assert totals["sent_bytes"] == 0
    assert result["intervals"]["startup"]["produced_bytes"] == 1200
    assert result["intervals"]["production"]["produced_bytes"] == 22800
    assert result["intervals"]["production"]["overflow_dropped_bytes"] == 19200
    assert result["capacity"]["finding"] == "unsustainable"
    assert result["capacity"]["assessment"] == "consistent"
    assert not result["hardware_qualified"]
    assert result["delivery"]["rate_in_sender_window_bps"] is None


def test_fast_consumer_has_no_overload_and_delivery_uses_independent_archive_bytes(native_library):
    from lora_testbed.workload_assessment import SourceEvidence, assess_source

    trace = recorded_overloaded_queue(native_library, fast=True)
    reference = bytes(index % 251 for index in range(1200))
    # Two delivered messages, with an explicit zero hole between them.
    archive = reference + bytes(1200) + reference + bytes(20400)
    trace["delivery"] = {
        "message_ids": [1, 3],
        "reference_b64": base64.b64encode(reference).decode(),
        "archive_b64": base64.b64encode(archive).decode(),
        "archive_sha256": hashlib.sha256(archive).hexdigest(),
    }
    result = assess_source(SourceEvidence.model_validate(trace))
    assert result["capacity"]["finding"] == "no_overload_observed"
    assert result["accounting"]["totals"]["sent_bytes"] == 24000
    assert result["delivery"]["verified_bytes"] == 2400
    assert result["delivery"]["cohort_reported_bytes"] == 1200
    assert result["delivery"]["rate_in_sender_window_bps"] is None
    # A matching supplied digest cannot hide wrong content in a claimed delivery slot.
    trace["delivery"]["archive_b64"] = base64.b64encode(bytes(24000)).decode()
    trace["delivery"]["archive_sha256"] = hashlib.sha256(bytes(24000)).hexdigest()
    broken = assess_source(SourceEvidence.model_validate(trace))
    assert broken["delivery"]["assessment"] == "inconsistent"
    assert broken["delivery"]["verified_bytes"] is None


@pytest.mark.parametrize("fault", ["frame", "sample", "rf_gap", "counter", "late", "cancelled"])
def test_missing_or_inconsistent_source_evidence_cannot_claim_capacity(native_library, fault):
    from lora_testbed.workload_assessment import SourceEvidence, assess_source

    trace = recorded_overloaded_queue(native_library)
    if fault == "frame":
        del trace["frames"][1400]
    elif fault == "sample":
        del trace["queue_samples"][50]
    elif fault == "rf_gap":
        trace["telemetry_gaps"] = 1
    elif fault == "counter":
        trace["status"]["admitted_bytes"] = 4792
    elif fault == "late":
        trace["frames"][200]["actual_elapsed_us"] += 20000
        trace["status"].update(late_frames=1, max_lateness_us=20000)
    else:
        trace["status"].update(frames_produced=2999, frames_cancelled=1, produced_bytes=23992)
        trace["execution_status"] = "cancelled"
    result = assess_source(SourceEvidence.model_validate(trace))
    assert result["capacity"]["finding"] == "inconclusive"
    assert result["capacity"]["reasons"]
    assert not result["hardware_qualified"]


def memory_trace(lib):
    from uuid import uuid4

    from test_node_audio_native import AudioFixture
    from test_node_control_native import NativeNode

    audio = AudioFixture()
    node = NativeNode(lib, audio=audio.port)
    try:
        node.claim()
        rows = node.send(node.command("memory.start", {"duration_ms": 30000}))
        command = node.command("audio.capture", {"artifact_id": str(uuid4()), "sample_count": 160})
        accepted = node.send(command)
        rows.extend(accepted)
        operation = next(
            row["result"]["operation_id"] for row in accepted if row["kind"] == "reply"
        )
        node.tick(100000)
        rows.extend(node.drain())
        rows.extend(node.send(node.command("operation.stop", {"operation_id": operation})))
        node.tick(100000)
        rows.extend(node.drain())
        started = next(
            row["data"]["observation_id"] for row in rows if row.get("name") == "memory.sample"
        )
        rows.extend(node.send(node.command("memory.stop", {"observation_id": started})))
        status = node.request("memory.status")["result"]
        return {
            "status": status,
            "events": [row for row in rows if row.get("name") == "memory.sample"],
        }
    finally:
        node.close()


def test_stage_memory_retains_observed_lifetime_recovery_and_unknown_peaks(native_library):
    from lora_testbed.workload_assessment import MemoryEvidence, assess_memory

    trace = memory_trace(native_library)
    result = assess_memory(MemoryEvidence.model_validate(trace))
    assert result["assessment"] == "consistent", result["reasons"]
    assert result["observed"]["internal"]["sampled_min_free_bytes"] == 399680
    assert result["observed"]["internal"]["boot_minimum_free_bytes"] == 130000
    stages = result["stages"]
    assert [stage["stage"] for stage in stages] == ["idle", "preparing", "capture", "idle"]
    assert stages[2]["internal"]["sampled_max_known_requested_bytes"] == 320
    capture = next(
        buffer for buffer in result["buffer_lifetimes"] if buffer["requested_bytes"] == 320
    )
    assert capture["first_absent_sample_us"] is not None
    assert capture["exact_free_us"] is None
    assert result["true_peak"]["value"] is None and result["true_peak"]["reason"]
    assert result["recovery"]["internal_free_delta_bytes"] == 0
    assert not result["hardware_qualified"]


@pytest.mark.parametrize("fault", ["missing", "dropped", "boot", "active", "inventory", "minimum"])
def test_affected_memory_conclusions_are_inconclusive_after_trace_faults(native_library, fault):
    from lora_testbed.workload_assessment import MemoryEvidence, assess_memory

    trace = memory_trace(native_library)
    if fault == "missing":
        del trace["events"][1]
    elif fault == "dropped":
        trace["status"]["samples_dropped"] = 1
    elif fault == "boot":
        trace["events"][-1]["boot_id"] = "different-boot"
    elif fault == "active":
        trace["status"]["active"] = True
    elif fault == "inventory":
        trace["events"][1]["data"]["inventory_truncated"] = True
    else:
        trace["status"]["measurement_minimum"]["internal_free_bytes"] = 400000
    result = assess_memory(MemoryEvidence.model_validate(trace))
    assert result["assessment"] == "inconclusive" and result["reasons"]
    assert result["true_peak"]["value"] is None


def test_saved_assessment_reloads_exact_raw_evidence_and_never_qualifies_imports(
    native_library, tmp_path
):
    from fastapi.testclient import TestClient

    from lora_testbed.app import create_app

    document = {
        "source": recorded_overloaded_queue(native_library),
        "memory": memory_trace(native_library),
    }
    with TestClient(create_app(data_dir=tmp_path)) as client:
        response = client.post("/api/workload-assessments", json=document)
        assert response.status_code == 201, response.text
        saved = response.json()
        assert saved["origin"] == "imported_unverified"
        assert saved["evidence"]["source"]["frames"] == document["source"]["frames"]
        assert saved["assessments"]["source"]["capacity"]["finding"] == "unsustainable"
        assert saved["assessments"]["memory"]["assessment"] == "consistent"
        assert not saved["hardware_qualified"]
        assert len(saved["evidence_sha256"]) == len(saved["document_sha256"]) == 64
        assert client.get("/api/workload-assessments").json()["assessments"][0]["id"] == saved["id"]
    with TestClient(create_app(data_dir=tmp_path)) as client:
        assert client.get("/api/workload-assessments/" + saved["id"]).json() == saved
        invalid = client.post(
            "/api/workload-assessments",
            json={"source": document["source"], "tx_key_hex": "private"},
        )
        assert invalid.status_code == 422
        assert "private" not in invalid.text


def test_physical_memory_observer_can_surround_local_work_and_collect_its_actual_events(
    native_library, tmp_path
):
    import asyncio

    from fastapi.testclient import TestClient
    from test_node_control_native import NativeSerial

    from lora_testbed.app import create_app

    with TestClient(create_app(data_dir=tmp_path)) as client:
        host = client.app.state.host
        serial = NativeSerial(native_library)
        host.physical["B"].opener = lambda _: serial
        client.portal.call(host.physical["B"].connect, "isolated-observer-node")
        start = client.post("/api/nodes/B/memory-observation", json={"duration_ms": 3000})
        assert start.status_code == 200, start.text
        identifier = start.json()["observation_id"]
        assert (
            client.post("/api/nodes/B/memory-observation", json={"duration_ms": 3000}).status_code
            == 400
        )
        # The observer does not monopolize the bench; a genuine native diagnostic may run.
        diagnostic = client.post(
            "/api/nodes/B/memory-probe", json={"iterations": 1, "payload_bytes": 1024}
        )
        assert diagnostic.status_code == 200, diagnostic.text
        client.portal.call(asyncio.sleep, 0.25)
        collected = client.post(f"/api/nodes/B/memory-observation/{identifier}/collect?stop=true")
        assert collected.status_code == 201, collected.text
        record = collected.json()
        assert record["origin"] == "physical_readback"
        assert record["provenance"]["binding"]["role"] == "B"
        assert not record[
            "hardware_qualified"
        ]  # A software transport fixture cannot qualify hardware.
        assert record["evidence"]["memory"]["events"]
        assert not record["evidence"]["memory"]["status"]["active"]
        assert record["assessments"]["memory"]["assessment"] == "consistent", record["assessments"]


@pytest.mark.parametrize("fault", [None, "page", "connection", "shutdown"])
def test_terminal_source_collector_reads_native_pages_and_preserves_partial_failures(
    native_library, tmp_path, fault
):
    import asyncio
    from types import SimpleNamespace

    from test_codec_decode_native import encoded_source
    from test_fixed_source_rf_native import Producer, fixed_prepare
    from test_node_control_native import NativeNode

    from lora_testbed.physical_adapter import PhysicalAdapter
    from lora_testbed.storage import Store
    from lora_testbed.workload_observations import WorkloadObservations

    async def scenario():
        lib = native_library
        worker = Producer(lib)
        nodes = {
            "A": NativeNode(lib, radio=lib.native_radio_create(), source_worker=worker.port),
            "B": NativeNode(lib, radio=lib.native_radio_create(), device="esp-66778899aabb"),
        }
        store = Store(tmp_path)
        try:
            nodes["A"].claim()
            _, source = encoded_source(nodes["A"])
            run, revisions, _ = fixed_prepare(nodes, source)
            for role in ("B", "A"):
                assert nodes[role].request(
                    "run.arm", {"config_revision": revisions[role]}, run_id=run
                )["ok"]
            assert nodes["A"].request("run.start", {"config_revision": revisions["A"]}, run_id=run)[
                "ok"
            ]
            epoch = worker.at
            for frame in range(4501):
                worker.step(epoch + frame * 20000)

            paused = asyncio.Event()

            class Peer:
                connected = True
                connection_id = "isolated-original-connection"
                rf_run_id = run
                event_gaps = 0
                identity = SimpleNamespace(device_id="esp-001122334455", boot_id=nodes["A"].boot_id)
                calls = 0

                async def request(self, name, args=None, **options):
                    self.calls += 1
                    if self.calls == 4 and fault == "shutdown":
                        paused.set()
                        await asyncio.Event().wait()
                    if self.calls == 4 and fault == "page":
                        raise TimeoutError("Isolated readback timeout")
                    if self.calls == 4 and fault == "connection":
                        self.connection_id = "isolated-replacement-connection"
                    reply = nodes["A"].request(name, args, run_id=options.get("run_id"))
                    assert reply["ok"], reply
                    return reply["result"]

            peer = Peer()
            observations = WorkloadObservations(store, PhysicalAdapter({"A": peer}))
            if fault == "shutdown":
                task = asyncio.create_task(observations.collect_source("A", run))
                async with asyncio.timeout(2):
                    await paused.wait()
                    await observations.close()
                assert task.cancelled()
                saved = observations.get(observations.list()["assessments"][0]["id"])
            else:
                saved = await observations.collect_source("A", run)
            assert saved["origin"] == "physical_readback" and not saved["hardware_qualified"]
            assert saved["evidence"]["parent_run_id"] == run
            if fault:
                assert saved["evidence"]["source"]["collection_errors"]
                assert saved["assessments"]["source"]["capacity"]["finding"] == "inconclusive"
                assert 0 < len(saved["evidence"]["source"]["frames"]) < 3000
            else:
                assert len(saved["evidence"]["source"]["frames"]) == 3000
                assert saved["assessments"]["source"]["capacity"]["finding"] == "unsustainable"
                assert saved["assessments"]["source"]["delivery"]["assessment"] == "unavailable"
            assert peer.rf_run_id == run  # Reader does not close the parent's session.
            assert observations.get(saved["id"]) == saved
        finally:
            store.close()
            for node in nodes.values():
                node.close()

    asyncio.run(scenario())


def test_absent_psram_stays_unavailable_and_cannot_become_zero_usage(native_library):
    from lora_testbed.workload_assessment import MemoryEvidence, assess_memory

    trace = memory_trace(native_library)
    trace["status"]["measurement_minimum"]["psram_free_bytes"] = None
    for event in trace["events"]:
        event["data"]["memory"]["psram"] = None
    result = assess_memory(MemoryEvidence.model_validate(trace))
    assert result["observed"]["psram"]["availability"] == "unavailable"
    assert result["observed"]["psram"]["sampled_min_free_bytes"] is None
    assert result["observed"]["psram"]["sampled_max_known_requested_bytes"] is None


def test_delivery_cannot_exceed_the_number_of_messages_the_consumer_took(native_library):
    from lora_testbed.workload_assessment import SourceEvidence, assess_source

    trace = recorded_overloaded_queue(native_library)
    trace["delivery"] = {"message_ids": [1]}
    result = assess_source(SourceEvidence.model_validate(trace))
    assert result["delivery"]["assessment"] == "inconsistent"


def test_mixed_consumer_outcomes_reconcile_without_turning_failed_sends_into_delivery(
    native_library,
):
    from lora_testbed.workload_assessment import SourceEvidence, assess_source

    trace = recorded_overloaded_queue(native_library, fast=True, outcomes={2: 1, 3: 2})
    result = assess_source(SourceEvidence.model_validate(trace))
    totals = result["accounting"]["totals"]
    assert result["accounting"]["status"] == "consistent"
    assert totals["sent_messages"] == 18 and totals["sent_bytes"] == 21600
    assert totals["failed_messages"] == 1 and totals["failed_bytes"] == 1200
    assert totals["consumer_discarded_bytes"] == 1200
    assert result["intervals"]["production"]["produced_complete_messages"] == 19
    assert result["intervals"]["production"]["eventual_sent_messages_for_cohort"] == 17
    assert result["intervals"]["production"]["eventual_failed_messages_for_cohort"] == 1
    assert result["delivery"]["verified_bytes"] is None


def test_cancelled_partial_overflow_is_bytes_but_never_a_complete_message(native_library):
    from lora_testbed.workload_assessment import SourceEvidence, assess_source

    trace = recorded_overloaded_queue(native_library, cancel_at=650)
    trace["execution_status"] = "cancelled"
    result = assess_source(SourceEvidence.model_validate(trace))
    assert result["accounting"]["status"] == "consistent", result["accounting"]
    totals = result["accounting"]["totals"]
    assert totals["produced_bytes"] == 5200
    assert totals["overflow_dropped_bytes"] == 400 and totals["dropped_messages"] == 0
    assert result["intervals"]["production"]["overflow_complete_messages"] == 0
    assert result["capacity"]["finding"] == "inconclusive"
