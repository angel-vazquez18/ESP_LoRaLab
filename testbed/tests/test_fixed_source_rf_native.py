"""Advance the producer clock independently from the native radio/USB consumer."""

import ctypes as C

import pytest
from test_codec_decode_native import encoded_source
from test_encoded_source_queue import Status
from test_node_control_native import (
    SOURCE_RESERVE,
    SOURCE_START,
    SOURCE_STOP,
    NativeNode,
    SourceWorkerPort,
)
from test_node_control_native import native_library as native_library
from test_protected_voice_native import prepare_voice


class Producer:
    def __init__(self, lib):
        self.lib, self.queue, self.at = lib, None, 0
        self.last = 0
        self.fail_stop = False
        lib.encoded_queue_start.argtypes = [C.c_void_p, C.c_int64]
        lib.encoded_queue_start.restype = C.c_bool
        lib.encoded_queue_step.argtypes = [C.c_void_p, C.c_int64]
        lib.encoded_queue_request_stop.argtypes = [C.c_void_p]
        lib.encoded_queue_snapshot.argtypes = [C.c_void_p, C.POINTER(Status)]
        self.callbacks = [
            SOURCE_RESERVE(self.reserve),
            SOURCE_START(self.start),
            SOURCE_STOP(self.stop),
        ]
        self.port = SourceWorkerPort(None, *self.callbacks)

    def reserve(self, _, queue):
        self.queue = queue
        return queue

    def start(self, _, worker, at):
        self.at = self.last = at
        return self.lib.encoded_queue_start(worker, at)

    def stop(self, _, worker):
        if self.fail_stop:
            return False
        status = Status()
        self.lib.encoded_queue_snapshot(worker, C.byref(status))
        self.lib.encoded_queue_step(worker, self.last)
        self.queue = None
        return True

    def step(self, now):
        if self.queue:
            self.last = now
            self.lib.encoded_queue_step(self.queue, now)


def fixed_prepare(nodes, source, ack=False, radio=None):
    return prepare_voice(
        nodes,
        source,
        ack=ack,
        budget_overrides={"reassembly_timeout_us": 90_000_000},
        radio=radio,
        overrides={
            "catalog_id": "VOICE-03",
            "source": "fixed_rate_encoded",
            "message_count": 20,
            "source_duration_ms": 60000,
            "max_duration_ms": 90000,
        },
    )


def test_stalled_radio_does_not_throttle_the_source_or_exceed_total_payload_capacity(
    native_library,
):
    lib = native_library
    worker = Producer(lib)
    nodes = {
        "A": NativeNode(lib, radio=lib.native_radio_create(), source_worker=worker.port),
        "B": NativeNode(lib, radio=lib.native_radio_create(), device="esp-66778899aabb"),
    }
    try:
        nodes["A"].claim()
        _, source = encoded_source(nodes["A"])
        run, revisions, _ = fixed_prepare(nodes, source)
        for role in ("B", "A"):
            assert nodes[role].request("run.arm", {"config_revision": revisions[role]}, run_id=run)[
                "ok"
            ]
        assert nodes["A"].request("run.start", {"config_revision": revisions["A"]}, run_id=run)[
            "ok"
        ]
        # Do not poll/complete radio or the control loop: only the producer wakes.
        start = worker.at
        for index in range(3000):
            worker.step(start + index * 20000)
        reply = nodes["A"].request("run.source", run_id=run)
        assert reply["ok"], reply
        report = reply["result"]
        assert report["status"]["produced_bytes"] == 24000
        assert report["status"]["occupancy_bytes"] <= 4800
        assert report["status"]["overflow_dropped_bytes"] >= 18000
        assert report["delivered_message_ids"] == []
    finally:
        for node in nodes.values():
            node.close()


@pytest.mark.parametrize("fault", ["none", "drop", "authenticated_bad_content"])
def test_twenty_real_protected_messages_use_unique_sequences_and_independent_receiver_archive(
    native_library, fault
):
    import hashlib

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from test_codec_encode_native import readback
    from test_protected_rf_execution_native import sent
    from test_secure_replay_native import KEY_A

    from lora_testbed.source_protocol_v2 import Report

    lib = native_library
    for name in ("native_radio_generation", "native_radio_listening", "native_radio_transmitting"):
        getattr(lib, name).argtypes = [C.c_void_p]
        getattr(lib, name).restype = C.c_uint
    worker = Producer(lib)
    nodes = {
        "A": NativeNode(lib, radio=lib.native_radio_create(), source_worker=worker.port),
        "B": NativeNode(lib, radio=lib.native_radio_create(), device="esp-66778899aabb"),
    }
    try:
        nodes["A"].claim()
        identifier, source = encoded_source(nodes["A"])
        expected = readback(nodes["A"], identifier, 1200)
        run, revisions, _ = fixed_prepare(nodes, source)
        for role in ("B", "A"):
            assert nodes[role].request("run.arm", {"config_revision": revisions[role]}, run_id=run)[
                "ok"
            ]
        assert nodes["A"].request("run.start", {"config_revision": revisions["A"]}, run_id=run)[
            "ok"
        ]
        epoch = worker.at
        frames, records, generation = [], {"A": [], "B": []}, 0
        for tick in range(4801):
            for node in nodes.values():
                node.time = epoch + tick * 20000
            worker.step(nodes["A"].now())
            for role, node in nodes.items():
                node.tick(0)
                records[role].extend(node.drain())
                if tick % 100 == 0:
                    assert node.request("control.keepalive")["ok"]
            current = lib.native_radio_generation(nodes["A"].radio)
            if current != generation:
                generation = current
                raw = sent(nodes["A"])
                frames.append(raw)
                assert lib.native_radio_listening(nodes["B"].radio)
                first_final = raw[20:24] == b"\x00\x00\x00\x01" and raw[24:26] == b"\x00\x07"
                injected = raw
                if first_final and fault == "authenticated_bad_content":
                    plain = AESGCM(KEY_A).decrypt(raw[8:20], raw[40:], raw[:40])
                    injected = raw[:40] + AESGCM(KEY_A).encrypt(
                        raw[8:20], bytes([plain[0] ^ 1]) + plain[1:], raw[:40]
                    )
                if not (first_final and fault == "drop"):
                    lib.native_radio_inject(nodes["B"].radio, injected, len(injected), 2)
                lib.native_radio_tx_done(nodes["A"].radio)
        messages = {index: bytearray() for index in range(1, 21)}
        sequences = []
        for frame in frames:
            message = int.from_bytes(frame[20:24], "big")
            sequences.append(int.from_bytes(frame[16:20], "big"))
            messages[message].extend(AESGCM(KEY_A).decrypt(frame[8:20], frame[40:], frame[:40]))
        assert len(frames) == 160 and sequences == list(range(1, 161))
        assert all(bytes(message) == expected for message in messages.values())
        report = Report.model_validate(nodes["A"].request("run.source", run_id=run)["result"])
        assert report.status.sent_messages == 20 and report.status.sent_bytes == 24000
        assert report.status.produced_bytes == report.status.admitted_bytes == 24000
        assert report.status.occupancy_bytes == report.status.frames_missed == 0
        assert report.delivered_message_ids == []  # Sender has no independent delivery evidence.
        boundary_reply = nodes["A"].request(
            "run.source", {"view": "frames", "offset": 150, "limit": 1}, run_id=run
        )
        assert boundary_reply["ok"], boundary_reply["error"]
        boundary = Report.model_validate(boundary_reply["result"])
        assert (
            boundary.frames[0].planned_elapsed_us
            == boundary.frames[0].actual_elapsed_us
            == 3_000_000
        )
        final_sample_reply = nodes["A"].request(
            "run.source", {"view": "samples", "offset": 300, "limit": 1}, run_id=run
        )
        assert final_sample_reply["ok"]
        sample = Report.model_validate(final_sample_reply["result"]).samples[0]
        assert sample.actual_elapsed_us == 60_000_000 and sample.status.produced_bytes == 24000
        receiver = Report.model_validate(nodes["B"].request("run.source", run_id=run)["result"])
        assert receiver.delivered_message_ids == list(range(1 if fault == "none" else 2, 21))
        archive = readback(nodes["B"], receiver.archive_artifact_id, 24000)
        assert archive == (expected if fault == "none" else bytes(1200)) + expected * 19
        assert receiver.archive_sha256 == hashlib.sha256(archive).hexdigest()
        summaries = {
            role: [row["data"] for row in rows if row.get("name") == "run.summary"]
            for role, rows in records.items()
        }
        assert len(summaries["A"]) == len(summaries["B"]) == 1
        assert summaries["B"][0]["useful_delivered_bytes"] == (24000 if fault == "none" else 22800)
        for role in ("A", "B"):
            assert nodes[role].request("session.close", run_id=run)["ok"]
    finally:
        for node in nodes.values():
            node.close()


def test_failed_worker_join_retains_reference_and_cleanup_can_be_retried(native_library):
    lib = native_library
    worker = Producer(lib)
    nodes = {
        "A": NativeNode(lib, radio=lib.native_radio_create(), source_worker=worker.port),
        "B": NativeNode(lib, radio=lib.native_radio_create(), device="esp-66778899aabb"),
    }
    try:
        nodes["A"].claim()
        identifier, source = encoded_source(nodes["A"])
        run, _, _ = fixed_prepare(nodes, source)
        worker.fail_stop = True
        before = sum(C.sizeof(value) for value in nodes["A"].allocations.values())
        failed = nodes["A"].request("session.close", run_id=run)
        assert not failed["ok"]
        assert worker.queue is not None
        assert sum(C.sizeof(value) for value in nodes["A"].allocations.values()) == before
        assert not nodes["A"].request("artifact.delete", {"artifact_id": identifier})["ok"]
        assert nodes["A"].request("status.get")["result"]["state"] == "stopping"
        assert not nodes["A"].request("diag.run", {"duration_ms": 1000, "probe_bytes": 1024})["ok"]
        report = nodes["A"].request("run.summary", run_id=run)
        assert "SOURCE_STOP_FAILED" in report["result"]["cleanup_errors"]
        worker.fail_stop = False
        assert nodes["A"].request("session.close", run_id=run)["ok"]
        assert worker.queue is None
        assert nodes["A"].request("artifact.delete", {"artifact_id": identifier})["ok"]
    finally:
        worker.fail_stop = False
        for node in nodes.values():
            node.close()


@pytest.mark.parametrize("exhaust_first", [False, True])
def test_lost_ack_retries_exact_bytes_without_slowing_sixty_second_production(
    native_library, exhaust_first
):
    from test_protected_rf_execution_native import sent

    lib = native_library
    for name in ("native_radio_generation", "native_radio_listening", "native_radio_transmitting"):
        getattr(lib, name).argtypes = [C.c_void_p]
        getattr(lib, name).restype = C.c_uint
    worker = Producer(lib)
    nodes = {
        "A": NativeNode(lib, radio=lib.native_radio_create(), source_worker=worker.port),
        "B": NativeNode(lib, radio=lib.native_radio_create(), device="esp-66778899aabb"),
    }
    try:
        nodes["A"].claim()
        _, source = encoded_source(nodes["A"])
        run, revisions, _ = fixed_prepare(nodes, source, ack=True)
        for role in ("B", "A"):
            assert nodes[role].request("run.arm", {"config_revision": revisions[role]}, run_id=run)[
                "ok"
            ]
        assert nodes["A"].request("run.start", {"config_revision": revisions["A"]}, run_id=run)[
            "ok"
        ]
        epoch = worker.at
        generations, flights, frames, records = (
            dict.fromkeys(nodes, 0),
            [],
            [],
            {role: [] for role in nodes},
        )
        dropped = False
        for tick in range(9601):
            for node in nodes.values():
                node.time = epoch + tick * 10000
            worker.step(nodes["A"].now())
            pending = []
            for due, role, raw in flights:
                source_node, target = nodes[role], nodes["B" if role == "A" else "A"]
                if tick < due:
                    pending.append((due, role, raw))
                    continue
                lib.native_radio_tx_done(source_node.radio)
                lost = raw[3] == 2 and (
                    not dropped or (exhaust_first and raw[20:24] == bytes([0, 0, 0, 1]))
                )
                if lost:
                    dropped = True
                elif lib.native_radio_listening(target.radio):
                    lib.native_radio_inject(target.radio, raw, len(raw), 2)
            flights = pending
            for role, node in nodes.items():
                node.tick(0)
                records[role].extend(node.drain())
                if tick % 100 == 0:
                    assert node.request("control.keepalive")["ok"]
                generation = lib.native_radio_generation(node.radio)
                if generation != generations[role]:
                    generations[role] = generation
                    raw = sent(node)
                    frames.append((role, raw))
                    flights.append((tick + 2, role, raw))
        report = nodes["A"].request("run.source", run_id=run)["result"]
        assert report["status"]["produced_bytes"] == 24000
        assert report["status"]["sent_bytes"] == (22800 if exhaust_first else 24000)
        assert report["status"]["failed_bytes"] == (1200 if exhaust_first else 0)
        assert report["status"]["frames_missed"] == report["status"]["overflow_dropped_bytes"] == 0
        assert nodes["B"].request("run.source", run_id=run)["result"][
            "delivered_message_ids"
        ] == list(range(2 if exhaust_first else 1, 21))
        first = [raw for role, raw in frames if role == "A" and raw[16:20] == bytes([0, 0, 0, 1])]
        assert len(first) == (3 if exhaust_first else 2) and all(
            frame == first[0] for frame in first
        )
        receiver = next(row["data"] for row in records["B"] if row.get("name") == "run.summary")
        assert receiver["delivered_messages"] == (19 if exhaust_first else 20)
        assert receiver["duplicates"] == (2 if exhaust_first else 1)
    finally:
        for node in nodes.values():
            node.close()


def test_slow_airtime_configuration_can_prepare_without_promising_complete_delivery(native_library):
    lib = native_library
    worker = Producer(lib)
    nodes = {
        "A": NativeNode(lib, radio=lib.native_radio_create(), source_worker=worker.port),
        "B": NativeNode(lib, radio=lib.native_radio_create(), device="esp-66778899aabb"),
    }
    try:
        nodes["A"].claim()
        _, source = encoded_source(nodes["A"])
        run, _, _ = fixed_prepare(nodes, source, ack=True, radio={"spreading_factor": 12})
        assert worker.queue is not None and worker.at == 0
        assert (
            nodes["A"].request("run.source", run_id=run)["result"]["status"]["produced_bytes"] == 0
        )
        for role in ("A", "B"):
            assert nodes[role].request("session.close", run_id=run)["ok"]
    finally:
        for node in nodes.values():
            node.close()
