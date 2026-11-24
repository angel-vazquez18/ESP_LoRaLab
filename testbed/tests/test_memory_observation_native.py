"""Finite memory observations use real control and an explicit injected clock."""

from test_node_control_native import NativeNode
from test_node_control_native import native_library as native_library


def test_idle_observer_samples_at_ten_hz_without_confusing_boot_and_window_minima(native_library):
    node = NativeNode(native_library)
    try:
        node.claim()
        started = node.request("memory.start", {"duration_ms": 30000})
        assert started["ok"], started.get("error")
        identifier = started["result"]["observation_id"]
        observations = []
        for _ in range(10):
            node.tick(100_000)
            observations.extend(
                row["data"] for row in node.drain() if row.get("name") == "memory.sample"
            )
        assert len(observations) == 10
        assert [sample["taken_us"] for sample in observations] == list(
            range(1_100_000, 2_000_001, 100_000)
        )
        assert all(sample["observation_id"] == identifier for sample in observations)
        last = observations[-1]
        assert last["measurement_minimum"]["internal_free_bytes"] == 400000
        assert last["memory"]["internal"]["minimum_free_bytes"] == 130000
        assert last["workload_minimum"] is None
        stopped = node.request("memory.stop", {"observation_id": identifier})
        assert stopped["ok"] and stopped["result"]["active"] is False
        node.tick(1_000_000)
        assert not any(row.get("name") == "memory.sample" for row in node.drain())
    finally:
        node.close()


def test_memory_status_uses_fresh_reads_and_preserves_the_sequence_fence(native_library):
    node = NativeNode(native_library)
    try:
        node.claim()
        assert node.request("memory.start", {"duration_ms": 30000})["ok"]
        command = node.command("memory.status")
        first = node.send(command)[0]
        node.tick(100_000)
        node.drain()
        expired = node.send(command)[0]
        assert not expired["ok"] and expired["error"]["code"] == "COMMAND_EXPIRED"
        later = node.request("memory.status")
        assert later["ok"]
        assert later["result"]["samples_taken"] > first["result"]["samples_taken"]
    finally:
        node.close()


def test_owner_loss_stops_memory_sampling_without_automatic_resume(native_library):
    node = NativeNode(native_library)
    try:
        node.claim()
        assert node.request("memory.start", {"duration_ms": 30000})["ok"]
        node.tick(5_000_001)
        node.drain()
        node.claim()
        status = node.request("memory.status")["result"]
        assert status["active"] is False
        samples = status["samples_taken"]
        node.tick(100_000)
        node.drain()
        assert node.request("memory.status")["result"]["samples_taken"] == samples
    finally:
        node.close()


def test_named_inventory_counts_owned_payload_once_and_never_exports_pointers(native_library):
    import ctypes as C
    import json

    from test_node_audio_native import pcm_file

    node = NativeNode(native_library)
    try:
        node.claim()
        pcm_file(node, samples=16)
        assert node.request("memory.start", {"duration_ms": 30000})["ok"]
        node.tick(100_000)
        sample = next(row["data"] for row in node.drain() if row.get("name") == "memory.sample")
        names = {buffer["name"]: buffer for buffer in sample["known_buffers"]}
        assert names["artifact_slot_0"]["requested_bytes"] == 32
        assert names["artifact_slot_0"]["region"] == "internal"
        assert sample["known_requested_bytes"]["internal"] == sum(
            C.sizeof(buffer) for buffer in node.allocations.values()
        )
        assert (
            sample["known_requested_bytes"]["unknown"] > 0
        )  # Native calloc metadata is outside the injected allocator.
        assert sample["inventory_truncated"] is False and sample["overlap_detected"] is False
        assert all(str(pointer) not in json.dumps(sample) for pointer in node.allocations)
    finally:
        node.close()


def test_capture_stage_observations_keep_workload_minimum_after_cleanup(native_library):
    from uuid import uuid4

    from test_node_audio_native import AudioFixture

    audio = AudioFixture()
    node = NativeNode(native_library, audio=audio.port)
    try:
        node.claim()
        assert node.request("memory.start", {"duration_ms": 30000})["ok"]
        command = node.command("audio.capture", {"artifact_id": str(uuid4()), "sample_count": 160})
        records = node.send(command)
        accepted = next(row for row in records if row["kind"] == "reply")
        assert accepted["ok"]
        node.tick(100_000)
        records.extend(node.drain())
        stop = node.command("operation.stop", {"operation_id": accepted["result"]["operation_id"]})
        records.extend(node.send(stop))
        node.tick(100_000)
        records.extend(node.drain())
        samples = [row["data"] for row in records if row.get("name") == "memory.sample"]
        assert any(
            sample["stage"] == "capture" and sample["reason"] == "stage_entry" for sample in samples
        )
        exit_sample = next(
            sample
            for sample in samples
            if sample["stage"] == "capture" and sample["reason"] == "stage_exit"
        )
        assert exit_sample["known_requested_bytes"]["internal"] == 320
        last = samples[-1]
        assert last["stage"] == "idle" and last["workload_id"] is None
        assert last["workload_minimum"]["workload_id"] == command["command_id"]
        assert last["workload_minimum"]["minimum"]["internal_free_bytes"] == 399680
        assert last["known_requested_bytes"]["internal"] == 0
        assert last["measurement_minimum"]["internal_free_bytes"] == 399680
    finally:
        node.close()


def test_encoding_counts_committed_input_and_output_once_without_aliasing(native_library):
    import ctypes as C
    from uuid import uuid4

    from test_node_audio_native import pcm_file

    node = NativeNode(native_library)
    try:
        node.claim()
        source = pcm_file(node, samples=160)
        assert node.request("memory.start", {"duration_ms": 30000})["ok"]
        rows = node.send(
            node.command(
                "audio.encode",
                {"source_artifact_id": source["artifact_id"], "artifact_id": str(uuid4())},
            )
        )
        sample = next(
            row["data"]
            for row in rows
            if row.get("name") == "memory.sample" and row["data"]["stage"] == "encode"
        )
        names = {buffer["name"]: buffer for buffer in sample["known_buffers"]}
        assert names["artifact_slot_0"]["requested_bytes"] == 320
        assert names["artifact_slot_1"]["requested_bytes"] == 8
        assert names["codec_clip_owner"]["requested_bytes"] > 0
        assert names["codec_state"]["requested_bytes"] > 0
        assert sample["known_requested_bytes"]["internal"] == sum(
            C.sizeof(buffer) for buffer in node.allocations.values()
        )
        assert sample["overlap_detected"] is False
        assert sample["untracked_allocations"] is True
    finally:
        node.close()


def test_late_tick_reports_missed_periods_without_inventing_samples(native_library):
    node = NativeNode(native_library)
    try:
        node.claim()
        assert node.request("memory.start", {"duration_ms": 30000})["ok"]
        node.tick(350_000)
        samples = [row["data"] for row in node.drain() if row.get("name") == "memory.sample"]
        assert len(samples) == 1 and samples[0]["taken_us"] == 1_350_000
        assert samples[0]["missed_periods"] == 2
        node.tick(50_000)
        following = [row["data"] for row in node.drain() if row.get("name") == "memory.sample"]
        assert len(following) == 1 and following[0]["taken_us"] == 1_400_000
        assert following[0]["missed_periods"] == 2
    finally:
        node.close()


def test_deadline_counts_missing_observations_and_stops_without_catchup(native_library):
    node = NativeNode(native_library)
    try:
        node.claim()
        assert node.request("memory.start", {"duration_ms": 1000})["ok"]
        node.tick(1_000_000)
        rows = [row["data"] for row in node.drain() if row.get("name") == "memory.sample"]
        assert len(rows) == 1 and rows[0]["reason"] == "deadline"
        assert rows[0]["missed_periods"] == 9
        status = node.request("memory.status")["result"]
        assert status["active"] is False and status["samples_taken"] == 2
        node.tick(100_000)
        assert not any(row.get("name") == "memory.sample" for row in node.drain())
    finally:
        node.close()


def test_telemetry_backpressure_retains_exact_observation_drop_counts(native_library):
    node = NativeNode(native_library)
    try:
        node.claim()
        assert node.request("memory.start", {"duration_ms": 30000})["ok"]
        for _ in range(15):
            node.tick(100_000)
        status = node.request("memory.status")["result"]
        assert status["samples_taken"] == 16
        assert status["samples_dropped"] == 7
        assert status["missed_periods"] == 0
        node.tick(100_000)
        observed = next(row["data"] for row in node.drain() if row.get("name") == "memory.sample")
        assert observed["samples_dropped"] == 7
    finally:
        node.close()


def test_rf_work_uses_nonoverlapping_inventory_and_survives_observed_stop(native_library):
    import ctypes as C

    from test_rf_execution_native import setup

    node = NativeNode(native_library, radio=native_library.native_radio_create())
    try:
        node.claim()
        assert node.request("memory.start", {"duration_ms": 30000})["ok"]
        run, revision, _ = setup(node, sender=True)
        assert node.request("run.arm", {"config_revision": revision}, run_id=run)["ok"]
        rows = node.send(node.command("run.start", {"config_revision": revision}, run_id=run))
        sample = next(
            row["data"]
            for row in rows
            if row.get("name") == "memory.sample" and row["data"]["stage"] == "running"
        )
        assert sample["workload_id"] == run
        assert sample["known_requested_bytes"]["internal"] == sum(
            C.sizeof(buffer) for buffer in node.allocations.values()
        )
        assert sample["overlap_detected"] is False
        assert node.request("run.stop", {"reason": "operator"}, run_id=run)["ok"]
        assert node.request("session.close", run_id=run)["ok"]
        for file in node.request("artifact.list")["result"]["artifacts"]:
            node.request("artifact.delete", {"artifact_id": file["artifact_id"]})
        node.tick(100_000)
        recovered = next(row["data"] for row in node.drain() if row.get("name") == "memory.sample")
        assert recovered["known_requested_bytes"]["internal"] == 0
        assert recovered["workload_minimum"]["workload_id"] == run
        assert node.request("memory.status")["result"]["active"] is True
    finally:
        node.close()


def test_new_workload_minimum_resets_without_rewriting_measurement_minimum(native_library):
    from uuid import uuid4

    from test_node_audio_native import AudioFixture

    audio = AudioFixture()
    node = NativeNode(native_library, audio=audio.port)
    try:
        node.claim()
        assert node.request("memory.start", {"duration_ms": 30000})["ok"]
        for samples in (320, 160):
            command = node.command(
                "audio.capture", {"artifact_id": str(uuid4()), "sample_count": samples}
            )
            reply = next(row for row in node.send(command) if row["kind"] == "reply")
            assert reply["ok"]
            node.tick(100_000)
            node.drain()
            assert node.request(
                "operation.stop", {"operation_id": reply["result"]["operation_id"]}
            )["ok"]
        status = node.request("memory.status")["result"]
        assert status["workload_minimum"]["workload_id"] == command["command_id"]
        assert status["workload_minimum"]["minimum"]["internal_free_bytes"] == 399680
        assert status["measurement_minimum"]["internal_free_bytes"] == 399360
    finally:
        node.close()


def test_idle_and_recovery_windows_have_30_seconds_of_explicit_fixture_samples(native_library):
    from uuid import uuid4

    from test_node_audio_native import AudioFixture

    audio = AudioFixture()
    node = NativeNode(native_library, audio=audio.port)
    try:
        node.claim()
        assert node.request("memory.start", {"duration_ms": 90000})["ok"]

        def window():
            observations = []
            for index in range(300):
                if index % 20 == 0:
                    assert node.request("control.keepalive")["ok"]
                node.tick(100_000)
                observations.extend(
                    row["data"] for row in node.drain() if row.get("name") == "memory.sample"
                )
            return observations

        baseline = window()
        assert len(baseline) == 300
        assert all(sample["memory"]["internal"]["free_bytes"] == 400000 for sample in baseline)
        capture = node.request("audio.capture", {"artifact_id": str(uuid4()), "sample_count": 160})
        assert capture["ok"]
        node.tick(100_000)
        node.drain()
        assert node.request("operation.stop", {"operation_id": capture["result"]["operation_id"]})[
            "ok"
        ]
        recovery = window()
        assert len(recovery) == 300
        assert all(
            sample["memory"]["internal"]["free_bytes"] == 400000
            and sample["known_requested_bytes"]["internal"] == 0
            for sample in recovery
        )
        assert recovery[-1]["measurement_minimum"]["internal_free_bytes"] == 399680
        assert recovery[-1]["missed_periods"] == 0
    finally:
        node.close()


def test_sampling_allocation_failure_cannot_prevent_audio_cleanup(native_library):
    from uuid import uuid4

    from test_node_audio_native import AudioFixture

    audio = AudioFixture()
    node = NativeNode(native_library, audio=audio.port)
    try:
        node.claim()
        assert node.request("memory.start", {"duration_ms": 30000})["ok"]
        assert node.request("audio.capture", {"artifact_id": str(uuid4()), "sample_count": 160})[
            "ok"
        ]
        audio.progress.failed = True
        native_library.native_allocator_fail_after(0)
        node.tick(100_000)
        native_library.native_allocator_fail_after(-1)
        node.drain()
        assert audio.stops == 1 and not node.allocations
        assert node.request("status.get")["result"]["state"] == "idle"
        assert node.request("memory.status")["result"]["samples_dropped"] > 0
    finally:
        native_library.native_allocator_fail_after(-1)
        node.close()


def test_duplicate_memory_commands_do_not_restart_or_repeat_stop(native_library):
    node = NativeNode(native_library)
    try:
        node.claim()
        start = node.command("memory.start", {"duration_ms": 30000})
        first = next(row for row in node.send(start) if row["kind"] == "reply")
        node.tick(100_000)
        node.drain()
        duplicate = next(row for row in node.send(start) if row["kind"] == "reply")
        assert duplicate == first
        assert node.request("memory.status")["result"]["samples_taken"] == 2
        stop = node.command("memory.stop", {"observation_id": first["result"]["observation_id"]})
        assert next(row for row in node.send(stop) if row["kind"] == "reply")["ok"]
        total = node.request("memory.status")["result"]["samples_taken"]
        assert next(row for row in node.send(stop) if row["kind"] == "reply")["ok"]
        assert node.request("memory.status")["result"]["samples_taken"] == total
    finally:
        node.close()


def test_all_capabilities_active_run_and_prior_error_keep_health_bounded(native_library):
    import json

    from test_node_audio_native import AudioFixture
    from test_rf_execution_native import setup

    audio = AudioFixture()
    node = NativeNode(
        native_library,
        radio=native_library.native_radio_create(),
        audio=audio.port,
        ptt=lambda _: False,
        display=lambda *_: True,
        display_status=lambda _: 1,
        boot=4294967295,
    )
    try:
        node.time = 123456789000000
        node.claim()
        assert node.request("memory.start", {"duration_ms": 30000})["ok"]
        run, revision, _ = setup(node, sender=True)
        assert node.request("run.arm", {"config_revision": revision}, run_id=run)["ok"]
        assert node.request("run.start", {"config_revision": revision}, run_id=run)["ok"]
        assert not node.request("audio.capture", {"artifact_id": "bad", "sample_count": 160})["ok"]
        reply = node.request("status.get")
        assert reply["ok"] and reply["result"]["state"] == "running"
        assert reply["result"]["last_error"]["code"] == "INVALID_ARGUMENT"
        assert len(json.dumps(reply, separators=(",", ":")).encode()) + 1 <= 4096
    finally:
        node.close()
