"""Production queue code is paced independently of any radio consumer."""

import ctypes as C

from test_node_control_native import ALLOC, FREE
from test_node_control_native import native_library as native_library


class Port(C.Structure):
    _fields_ = [("context", C.c_void_p), ("allocate", ALLOC), ("release", FREE)]


COUNTERS = (
    "phase frames_produced frames_missed frames_cancelled produced_bytes admitted_bytes "
    "overflow_dropped_bytes admitted_messages dropped_messages taken_messages sent_messages "
    "failed_messages sent_bytes failed_bytes consumer_discarded_bytes queue_discarded_messages "
    "queue_discarded_bytes partial_discarded_bytes ready_messages partial_bytes active_bytes "
    "occupancy_bytes peak_occupancy_bytes late_frames max_lateness_us trace_frames "
    "admitted_message_mask overflow_message_mask sent_message_mask "
    "failed_message_mask discarded_message_mask"
).split()


class Status(C.Structure):
    _fields_ = (
        [(name, C.c_int64) for name in ("started_us", "production_end_us", "drain_deadline_us")]
        + [(name, C.c_uint32) for name in COUNTERS]
        + [("drain_cutoff", C.c_bool), ("consistent", C.c_bool), ("cancel_requested", C.c_bool)]
    )


class Trace(C.Structure):
    _fields_ = [
        (name, C.c_uint32) for name in ("index", "planned_elapsed_us", "actual_elapsed_us")
    ] + [("produced", C.c_bool)]


class Queue:
    def __init__(self, lib):
        self.lib, self.allocations = lib, {}

        def allocate(_, size):
            buffer = C.create_string_buffer(size)
            pointer = C.addressof(buffer)
            self.allocations[pointer] = buffer
            return pointer

        def release(_, pointer):
            del self.allocations[pointer]

        self.callbacks = [ALLOC(allocate), FREE(release)]
        self.reference = C.create_string_buffer(bytes(index % 251 for index in range(1200)))
        lib.encoded_queue_create.argtypes = [Port, C.c_void_p, C.c_size_t, C.c_uint32]
        lib.encoded_queue_create.restype = C.c_void_p
        lib.encoded_queue_start.argtypes = [C.c_void_p, C.c_int64]
        lib.encoded_queue_start.restype = C.c_bool
        lib.encoded_queue_step.argtypes = [C.c_void_p, C.c_int64]
        lib.encoded_queue_snapshot.argtypes = [C.c_void_p, C.POINTER(Status)]
        lib.encoded_queue_trace.argtypes = [C.c_void_p, C.c_uint32, C.POINTER(Trace), C.c_size_t]
        lib.encoded_queue_trace.restype = C.c_size_t
        lib.encoded_queue_destroy.argtypes = [C.c_void_p]
        self.queue = lib.encoded_queue_create(
            Port(None, *self.callbacks), self.reference, 1200, 30_000_000
        )
        assert self.queue

    def status(self):
        value = Status()
        self.lib.encoded_queue_snapshot(self.queue, C.byref(value))
        return value

    def step(self, elapsed):
        self.lib.encoded_queue_step(self.queue, 1_000_000 + elapsed)

    def close(self):
        self.lib.encoded_queue_destroy(self.queue)
        assert not self.allocations


def test_sixty_second_source_keeps_its_rate_without_a_consumer_and_bounds_total_queue(
    native_library,
):
    queue = Queue(native_library)
    try:
        assert queue.lib.encoded_queue_start(queue.queue, 1_000_000)
        for index in range(3000):
            queue.step(index * 20_000)
            assert queue.status().occupancy_bytes <= 4800
        status = queue.status()
        assert status.frames_produced == 3000 and status.produced_bytes == 24000
        assert status.admitted_messages == 4 and status.admitted_bytes == 4800
        assert status.dropped_messages == 16 and status.overflow_dropped_bytes == 19200
        assert status.occupancy_bytes == status.peak_occupancy_bytes == 4800
        assert status.active_bytes == status.partial_bytes == 0
        queue.step(60_000_000)
        assert queue.status().phase == 2
        queue.step(90_000_000)
        drained = queue.status()
        assert drained.phase == 3 and drained.occupancy_bytes == 0
        assert drained.queue_discarded_messages == 4 and drained.queue_discarded_bytes == 4800
        trace = (Trace * 3000)()
        assert queue.lib.encoded_queue_trace(queue.queue, 0, trace, 3000) == 3000
        assert all(
            row.produced
            and row.index == index
            and row.planned_elapsed_us == row.actual_elapsed_us == index * 20_000
            for index, row in enumerate(trace)
        )
    finally:
        queue.close()


class Message(C.Structure):
    _fields_ = [("message_id", C.c_uint32), ("data", C.c_void_p), ("length", C.c_size_t)]


def consumer(lib):
    lib.encoded_queue_take.argtypes = [C.c_void_p, C.POINTER(Message)]
    lib.encoded_queue_take.restype = C.c_bool
    lib.encoded_queue_complete.argtypes = [C.c_void_p, C.c_uint32, C.c_uint32]
    lib.encoded_queue_complete.restype = C.c_bool


def test_fast_consumer_sends_all_actual_messages_and_releases_each_borrow(native_library):
    consumer(native_library)
    queue = Queue(native_library)
    try:
        assert queue.lib.encoded_queue_start(queue.queue, 1_000_000)
        identifiers = []
        for frame in range(3000):
            queue.step(frame * 20_000)
            message = Message()
            if queue.lib.encoded_queue_take(queue.queue, C.byref(message)):
                identifiers.append(message.message_id)
                assert message.length == 1200
                assert C.string_at(message.data, 1200) == queue.reference.raw[:1200]
                assert queue.status().active_bytes == 1200
                assert not queue.lib.encoded_queue_take(queue.queue, C.byref(Message()))
                assert queue.lib.encoded_queue_complete(queue.queue, message.message_id, 0)
                assert not queue.lib.encoded_queue_complete(queue.queue, message.message_id, 0)
        queue.step(60_000_000)
        status = queue.status()
        assert identifiers == list(range(1, 21))
        assert status.phase == 3 and status.occupancy_bytes == 0
        assert status.produced_bytes == status.admitted_bytes == status.sent_bytes == 24000
        assert status.sent_messages == status.taken_messages == 20
        assert status.overflow_dropped_bytes == status.queue_discarded_bytes == 0
    finally:
        queue.close()


def test_slow_consumer_keeps_active_and_partial_content_inside_capacity_and_drops_whole_messages(
    native_library,
):
    consumer(native_library)
    queue = Queue(native_library)
    try:
        assert queue.lib.encoded_queue_start(queue.queue, 1_000_000)
        for frame in range(150):
            queue.step(frame * 20_000)
        first = Message()
        assert queue.lib.encoded_queue_take(queue.queue, C.byref(first))
        assert first.message_id == 1
        for frame in range(150, 701):
            queue.step(frame * 20_000)
        assert queue.status().occupancy_bytes == 4800 and queue.status().active_bytes == 1200
        assert queue.lib.encoded_queue_complete(queue.queue, 1, 0)
        for frame in range(701, 751):
            queue.step(frame * 20_000)
        second = Message()
        assert queue.lib.encoded_queue_take(queue.queue, C.byref(second))
        assert second.message_id == 2
        partial = queue.status()
        assert partial.dropped_messages == 1 and partial.overflow_dropped_bytes == 1200
        assert partial.active_bytes == 1200 and partial.partial_bytes == 8
        assert partial.occupancy_bytes == 3608
        for frame in range(751, 3000):
            queue.step(frame * 20_000)
            assert queue.status().occupancy_bytes <= 4800
        queue.step(60_000_000)
        generated = queue.status()
        assert generated.frames_produced == 3000 and generated.frames_missed == 0
        assert generated.admitted_messages == 5 and generated.dropped_messages == 15
        queue.step(90_000_000)
        cutoff = queue.status()
        assert cutoff.drain_cutoff and cutoff.active_bytes == cutoff.occupancy_bytes == 1200
        assert cutoff.queue_discarded_messages == 3 and cutoff.queue_discarded_bytes == 3600
        assert C.string_at(second.data, 1200) == queue.reference.raw[:1200]
        # The consumer confirms its radio no longer uses the active bytes.
        assert queue.lib.encoded_queue_complete(queue.queue, 2, 2)
        terminal = queue.status()
        assert terminal.phase == 3 and terminal.occupancy_bytes == 0
        assert (
            terminal.admitted_bytes
            == terminal.sent_bytes
            + terminal.consumer_discarded_bytes
            + terminal.queue_discarded_bytes
        )
        assert terminal.produced_bytes == terminal.admitted_bytes + terminal.overflow_dropped_bytes
    finally:
        queue.close()


def test_cancel_discards_only_actual_partial_content_and_never_fabricates_future_frames(
    native_library,
):
    queue = Queue(native_library)
    try:
        queue.lib.encoded_queue_request_stop.argtypes = [C.c_void_p]
        assert queue.lib.encoded_queue_start(queue.queue, 1_000_000)
        queue.step(0)
        queue.lib.encoded_queue_request_stop(queue.queue)
        queue.step(5_000)
        cancelled = queue.status()
        assert cancelled.phase == 4 and cancelled.frames_produced == 1
        assert cancelled.frames_cancelled == 2999 and cancelled.frames_missed == 0
        assert (
            cancelled.produced_bytes
            == cancelled.admitted_bytes
            == cancelled.partial_discarded_bytes
            == 8
        )
        assert cancelled.occupancy_bytes == 0 and cancelled.trace_frames == 1
        rows = (Trace * 2)()
        assert queue.lib.encoded_queue_trace(queue.queue, 0, rows, 2) == 1
        assert rows[0].produced and rows[0].index == 0
    finally:
        queue.close()


class Sample(C.Structure):
    _fields_ = [
        ("index", C.c_uint32),
        ("planned_elapsed_us", C.c_uint32),
        ("actual_elapsed_us", C.c_uint32),
        ("missed_intervals", C.c_uint32),
        ("status", Status),
    ]


def test_queue_audit_samples_actual_five_hz_and_separates_warmup_from_drain(native_library):
    queue = Queue(native_library)
    try:
        lib = queue.lib
        lib.encoded_queue_samples.argtypes = [C.c_void_p, C.c_uint32, C.POINTER(Sample), C.c_size_t]
        lib.encoded_queue_samples.restype = C.c_size_t
        assert lib.encoded_queue_start(queue.queue, 1_000_000)
        for index in range(4501):
            queue.step(index * 20_000)
        rows = (Sample * 451)()
        assert lib.encoded_queue_samples(queue.queue, 0, rows, 451) == 451
        assert all(
            row.index == i
            and row.planned_elapsed_us == row.actual_elapsed_us == i * 200_000
            and row.missed_intervals == 0
            and row.status.consistent
            for i, row in enumerate(rows)
        )
        assert rows[15].actual_elapsed_us == 3_000_000
        assert rows[15].status.produced_bytes == 1208
        assert rows[300].status.produced_bytes == rows[450].status.produced_bytes == 24000
        assert rows[449].status.occupancy_bytes == 4800
        assert rows[450].status.occupancy_bytes == 0
    finally:
        queue.close()


def test_late_producer_reports_actual_wake_gaps_and_never_catches_up_after_cutoff(native_library):
    queue = Queue(native_library)
    try:
        assert queue.lib.encoded_queue_start(queue.queue, 1_000_000)
        queue.step(0)
        queue.step(500_000)
        queue.step(60_000_000)
        status = queue.status()
        assert status.frames_produced == 26 and status.frames_missed == 2974
        assert (
            status.produced_bytes == status.admitted_bytes == status.partial_discarded_bytes == 208
        )
        assert status.late_frames == 24 and status.max_lateness_us == 480_000
        rows = (Trace * 3000)()
        assert queue.lib.encoded_queue_trace(queue.queue, 0, rows, 3000) == 3000
        assert all(row.actual_elapsed_us == 500_000 for row in rows[1:26])
        assert not any(row.produced for row in rows[26:])
        samples = (Sample * 4)()
        queue.lib.encoded_queue_samples.argtypes = [
            C.c_void_p,
            C.c_uint32,
            C.POINTER(Sample),
            C.c_size_t,
        ]
        queue.lib.encoded_queue_samples.restype = C.c_size_t
        assert queue.lib.encoded_queue_samples(queue.queue, 0, samples, 4) == 3
        assert samples[1].planned_elapsed_us == 200_000
        assert samples[1].actual_elapsed_us == 500_000 and samples[1].missed_intervals == 1
        assert samples[2].actual_elapsed_us == 60_000_000 and samples[2].missed_intervals == 297
    finally:
        queue.close()


def test_slow_consumer_audit_identifies_whole_dropped_and_sent_message_ids(native_library):
    consumer(native_library)
    queue = Queue(native_library)
    try:
        assert queue.lib.encoded_queue_start(queue.queue, 1_000_000)
        for index in range(3000):
            queue.step(index * 20000)
        status = queue.status()
        assert status.admitted_message_mask == 0x0000F
        assert status.overflow_message_mask == 0xFFFF0
        message = Message()
        assert queue.lib.encoded_queue_take(queue.queue, C.byref(message))
        assert queue.lib.encoded_queue_complete(queue.queue, message.message_id, 0)
        queue.step(90_000_000)
        status = queue.status()
        assert status.sent_message_mask == 1 and status.failed_message_mask == 0
        assert status.discarded_message_mask == 0xE
    finally:
        queue.close()


def test_concurrent_producer_and_consumer_preserve_bytes_and_reconcile_all_admitted_content(
    native_library,
):
    from threading import Event, Thread
    from time import sleep

    consumer(native_library)
    queue = Queue(native_library)
    errors = []
    sent = []
    stopped = Event()
    threads = []
    try:
        assert queue.lib.encoded_queue_start(queue.queue, 1_000_000)

        def produce():
            try:
                for frame in range(3000):
                    if stopped.is_set():
                        return
                    queue.step(frame * 20000)
                    sleep(0)
                queue.step(60_000_000)
            except Exception as exc:
                errors.append(exc)

        def consume():
            try:
                while not stopped.is_set() and queue.status().phase < 3:
                    message = Message()
                    if queue.lib.encoded_queue_take(queue.queue, C.byref(message)):
                        assert (
                            C.string_at(message.data, message.length) == queue.reference.raw[:1200]
                        )
                        sent.append(message.message_id)
                        assert queue.lib.encoded_queue_complete(queue.queue, message.message_id, 0)
                    else:
                        sleep(0)
            except Exception as exc:
                errors.append(exc)

        threads = [Thread(target=produce), Thread(target=consume)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        assert all(not thread.is_alive() for thread in threads)
        assert not errors
        status = queue.status()
        assert status.consistent and status.frames_produced == 3000
        assert (
            status.produced_bytes == status.admitted_bytes + status.overflow_dropped_bytes == 24000
        )
        assert status.sent_bytes == status.admitted_bytes and status.occupancy_bytes == 0
        assert sent == sorted(set(sent))
        assert status.peak_occupancy_bytes <= 4800
    finally:
        stopped.set()
        for thread in threads:
            thread.join(timeout=5)
        if all(not thread.is_alive() for thread in threads):
            queue.close()


def test_terminal_payload_retirement_preserves_trace_and_stats(native_library):
    queue = Queue(native_library)
    try:
        lib = queue.lib
        lib.encoded_queue_retire_payload.argtypes = [C.c_void_p]
        lib.encoded_queue_retire_payload.restype = C.c_bool
        assert not lib.encoded_queue_retire_payload(queue.queue)
        assert lib.encoded_queue_start(queue.queue, 1_000_000)
        queue.step(0)
        lib.encoded_queue_request_stop.argtypes = [C.c_void_p]
        lib.encoded_queue_request_stop(queue.queue)
        queue.step(1)
        before = len(queue.allocations)
        assert lib.encoded_queue_retire_payload(queue.queue)
        assert len(queue.allocations) == before - 1
        assert queue.status().produced_bytes == 8 and queue.status().occupancy_bytes == 0
        rows = (Trace * 1)()
        assert lib.encoded_queue_trace(queue.queue, 0, rows, 1) == 1 and rows[0].produced
    finally:
        queue.close()
