"""Exact retained DATA attempts against the real C radio over its SPI boundary."""

import ctypes as C
import hashlib

import pytest
from test_node_control_native import native_library as native_library
from test_rf_ack_native import AckReceiver, data
from test_rf_ack_native import acknowledgments as acknowledgments
from test_rf_reassembly_native import reconstruction as reconstruction


class Status(C.Structure):
    _fields_ = [
        ("state", C.c_uint32),
        ("originals", C.c_uint32),
        ("attempts", C.c_uint32),
        ("acks", C.c_uint32),
        ("rejected_acks", C.c_uint32),
        ("ack_deadline_us", C.c_int64),
        ("retry_at_us", C.c_int64),
        ("reason", C.c_char_p),
        ("last_ack_acceptance", C.c_uint32),
    ]


class Reference(C.Structure):
    _fields_ = [
        ("session", C.c_uint64),
        ("sequence", C.c_uint32),
        ("message", C.c_uint32),
        ("fragment", C.c_uint16),
        ("attempt", C.c_uint8),
    ]


class Observation(C.Structure):
    _fields_ = [
        ("kind", C.c_uint32),
        ("reference", Reference),
        ("status", C.c_uint32),
        ("length", C.c_uint16),
        ("command_us", C.c_int64),
        ("done_us", C.c_int64),
        ("crc_ok", C.c_bool),
        ("signal_valid", C.c_bool),
        ("rssi", C.c_float),
        ("snr", C.c_float),
        ("bytes", C.c_uint8 * 255),
    ]


@pytest.fixture
def sender(native_library):
    lib = native_library
    lib.native_radio_configure_default.argtypes = [C.c_void_p]
    lib.native_radio_configure_default.restype = C.c_bool
    # Port ABI is shared with packet allocation/hash callbacks.
    from test_rf_reassembly_native import Port

    lib.rf_sender_create.argtypes = [Port, C.c_void_p]
    lib.rf_sender_create.restype = C.c_void_p
    lib.rf_sender_begin.argtypes = [
        C.c_void_p,
        C.c_void_p,
        C.c_size_t,
        C.c_uint16,
        C.c_uint8,
        C.c_uint32,
        C.c_uint32,
        C.c_uint32,
        C.c_int64,
    ]
    lib.rf_sender_begin.restype = C.c_bool
    lib.rf_sender_poll.argtypes = [C.c_void_p, C.c_void_p]
    lib.rf_sender_poll.restype = C.c_bool
    lib.rf_sender_snapshot.argtypes = [C.c_void_p, C.POINTER(Status)]
    lib.rf_sender_cancel.argtypes = [C.c_void_p]
    lib.rf_sender_destroy.argtypes = [C.c_void_p]
    return lib


class Sender:
    def __init__(self, lib, acks):
        self.lib = lib
        self.events = []
        self.memory = AckReceiver(acks)
        self.radio = lib.native_radio_create()
        assert lib.native_radio_configure_default(self.radio)
        lib.native_radio_time(self.radio, 1000000)
        self.handle = lib.rf_sender_create(self.memory.port, self.radio)
        assert self.handle

    def status(self):
        value = Status()
        self.lib.rf_sender_snapshot(self.handle, C.byref(value))
        return value

    def tick(self, time):
        self.lib.native_radio_time(self.radio, time)
        # Drain one retained observation without inspecting implementation state.
        observation = Observation()
        for _ in range(2):
            if self.lib.rf_sender_poll(self.handle, C.byref(observation)):
                self.events.append(
                    (
                        observation.kind,
                        observation.reference.sequence,
                        observation.reference.attempt,
                        observation.status,
                    )
                )
        return self.status()

    def start(self, wire, retries=2):
        return self.lib.rf_sender_begin(
            self.handle, wire, len(wire), 160, retries, 50000, 20000, 80000, 10000000
        )

    def sent(self):
        output = C.create_string_buffer(255)
        size = self.lib.native_radio_sent(self.radio, output)
        return output.raw[:size]

    def close(self):
        self.lib.rf_sender_destroy(self.handle)
        self.memory.close()


def test_lost_first_attempt_retries_identical_bytes_and_accepts_only_matching_ack(
    sender, acknowledgments
):
    s = Sender(sender, acknowledgments)
    wire = data()
    try:
        assert s.start(wire)
        assert s.tick(1000000).attempts == 1
        assert s.sent() == wire
        sender.native_radio_tx_done(s.radio)
        waiting = s.tick(1100000)
        assert waiting.state == 2 and waiting.ack_deadline_us > 1100000
        guard = s.tick(waiting.ack_deadline_us)
        assert guard.state == 3
        retry = s.tick(guard.retry_at_us)
        assert retry.state == 1 and retry.originals == 1 and retry.attempts == 2
        assert hashlib.sha256(s.sent()).digest() == hashlib.sha256(wire).digest()
        sender.native_radio_tx_done(s.radio)
        s.tick(guard.retry_at_us + 100000)
        assert s.memory.offer(wire, now=0)
        ack = s.memory.take(20)
        sender.native_radio_inject(s.radio, ack, len(ack), 2)
        final = s.tick(guard.retry_at_us + 100001)
        assert final.state == 4 and final.acks == 1 and final.attempts == 2 and final.originals == 1
        assert [(seq, attempt) for kind, seq, attempt, _ in s.events if kind == 0] == [
            (7, 1),
            (7, 2),
        ]
    finally:
        s.close()


@pytest.mark.parametrize("retries", [0, 1, 2])
def test_retry_exhaustion_never_inflates_originals_and_next_frame_can_succeed(
    sender, acknowledgments, retries
):
    s = Sender(sender, acknowledgments)
    wire = data()
    try:
        assert s.start(wire, retries)
        now = 1000000
        for attempt in range(1, retries + 2):
            state = s.tick(now)
            assert state.attempts == attempt and state.originals == 1
            assert s.sent() == wire
            sender.native_radio_tx_done(s.radio)
            state = s.tick(now + 100000)
            state = s.tick(state.ack_deadline_us)
            if attempt <= retries:
                assert state.state == 3
                now = state.retry_at_us
            else:
                assert state.state == 5 and state.reason == b"retry_exhausted"
        assert s.status().attempts == retries + 1
        # Fresh original succeeds through the same initialized radio.
        assert s.start(data(sequence=8), 0)
        now += 500000
        s.tick(now)
        sender.native_radio_tx_done(s.radio)
        s.tick(now + 100000)
        assert s.memory.offer(data(sequence=8))
        ack = s.memory.take(20)
        sender.native_radio_inject(s.radio, ack, len(ack), 2)
        assert s.tick(now + 100001).state == 4
    finally:
        s.close()


def test_invalid_ack_does_not_finish_or_extend_deadline_and_cancel_prevents_retry(
    sender, acknowledgments
):
    s = Sender(sender, acknowledgments)
    try:
        source = C.create_string_buffer(data())
        assert sender.rf_sender_begin(
            s.handle, source, len(data()), 160, 2, 50000, 20000, 80000, 10000000
        )
        source[40] = b"X"
        s.tick(1000000)
        assert s.sent() == data()
        sender.native_radio_tx_done(s.radio)
        waiting = s.tick(1100000)
        assert s.memory.offer(data(sequence=8))
        bad = s.memory.take(20)
        sender.native_radio_inject(s.radio, bad, len(bad), 2)
        state = s.tick(1100001)
        assert (
            state.state == 2
            and state.rejected_acks == 1
            and state.ack_deadline_us == waiting.ack_deadline_us
        )
        sender.rf_sender_cancel(s.handle)
        state = s.tick(waiting.ack_deadline_us + 100000)
        assert state.state == 6 and state.attempts == 1
    finally:
        s.close()


def test_ack_loss_retries_exact_data_and_receiver_delivers_once(
    sender, acknowledgments, reconstruction
):
    from test_rf_reassembly_native import Reassembly

    s = Sender(sender, acknowledgments)
    receiver = Reassembly(reconstruction)
    wire = data()
    try:
        assert reconstruction.rf_reassembly_begin(
            receiver.handle, 3, 0, 2, 5, hashlib.sha256(b"hello").digest(), 0, 10000000
        )
        assert s.start(wire)
        s.tick(1000000)
        actual = s.sent()
        assert reconstruction.rf_reassembly_accept(receiver.handle, actual, len(actual), 1) == 3
        assert receiver.take()[0] == b"hello"
        assert s.memory.offer(actual)
        first_ack = s.memory.take(20)  # Deliberately lost at the RF boundary.
        sender.native_radio_tx_done(s.radio)
        wait = s.tick(1100000)
        guard = s.tick(wait.ack_deadline_us)
        s.tick(guard.retry_at_us)
        repeated = s.sent()
        assert repeated == actual
        assert (
            reconstruction.rf_reassembly_accept(receiver.handle, repeated, len(repeated), 30) == 2
        )
        assert s.memory.offer(repeated, classification=2, now=30)
        second_ack = s.memory.take(50)
        assert first_ack[16:20] != second_ack[16:20]
        sender.native_radio_tx_done(s.radio)
        s.tick(guard.retry_at_us + 100000)
        sender.native_radio_inject(s.radio, second_ack, len(second_ack), 2)
        assert s.tick(guard.retry_at_us + 100001).state == 4
        assert receiver.take() is None
    finally:
        receiver.close()
        s.close()


class Modem(C.Structure):
    _fields_ = [
        ("frequency_hz", C.c_uint32),
        ("bandwidth_hz", C.c_uint32),
        ("sf", C.c_uint8),
        ("cr", C.c_uint8),
        ("power", C.c_int8),
        ("preamble", C.c_uint8),
    ]


@pytest.mark.parametrize(
    ("sf", "bw", "cr", "length", "expected"),
    [
        (7, 125000, 5, 45, 92416),
        (7, 125000, 5, 40, 82176),
        (12, 125000, 8, 255, 14032896),
        (11, 250000, 6, 199, 1984512),
        (12, 500000, 8, 40, 624640),
    ],
)
def test_applied_modem_airtime_matches_selected_quarter_symbol_vectors(
    sender, sf, bw, cr, length, expected
):
    sender.rf_radio_airtime_us.argtypes = [C.POINTER(Modem), C.c_size_t]
    sender.rf_radio_airtime_us.restype = C.c_uint32
    modem = Modem(915000000, bw, sf, cr, 2, 8)
    assert sender.rf_radio_airtime_us(C.byref(modem), length) == expected


def test_ack_disabled_sends_once_without_waiting_or_retrying(sender, acknowledgments):
    s = Sender(sender, acknowledgments)
    wire = data()[:4] + b"\0" + data()[5:]
    try:
        assert not s.start(wire, 1)
        assert s.start(wire, 0)
        s.tick(1000000)
        sender.native_radio_tx_done(s.radio)
        final = s.tick(1100000)
        assert final.state == 4 and final.attempts == 1 and final.acks == 0
        assert s.tick(10000000).attempts == 1
    finally:
        s.close()


@pytest.mark.parametrize("phase", ["ready", "tx", "ack", "guard"])
def test_cancel_at_every_phase_stops_future_attempts_and_releases_radio(
    sender, acknowledgments, phase
):
    s = Sender(sender, acknowledgments)
    try:
        assert s.start(data())
        now = 1000000
        if phase != "ready":
            s.tick(now)
        if phase in ("ack", "guard"):
            sender.native_radio_tx_done(s.radio)
            waiting = s.tick(now + 100000)
            now += 100000
            if phase == "guard":
                now = waiting.ack_deadline_us
                assert s.tick(now).state == 3
        count = s.status().attempts
        sender.rf_sender_cancel(s.handle)
        final = s.tick(now + 1000000)
        assert final.state == 6 and final.attempts == count
        assert sender.native_radio_configure_default(s.radio)
    finally:
        s.close()


def test_preflight_rejects_excess_retries_or_short_deadline_before_radio_work(
    sender, acknowledgments
):
    s = Sender(sender, acknowledgments)
    try:
        assert not s.start(data(), 3)
        assert not sender.rf_sender_begin(
            s.handle, data(), len(data()), 160, 2, 50000, 20000, 80000, 1000001
        )
        assert s.status().attempts == 0 and s.sent() == b""
        assert s.start(data(), 0)
    finally:
        s.close()


def test_completed_or_cancelled_original_cannot_restart_with_old_sequence(sender, acknowledgments):
    s = Sender(sender, acknowledgments)
    try:
        assert s.start(data())
        sender.rf_sender_cancel(s.handle)
        s.tick(1000000)
        assert not s.start(data())
        assert s.start(data(sequence=8))
    finally:
        s.close()


def test_undrained_observations_remain_available_after_bounded_run_deadline(
    sender, acknowledgments
):
    s = Sender(sender, acknowledgments)
    try:
        assert s.start(data())
        s.tick(1000000)
        sender.native_radio_tx_done(s.radio)
        sender.native_radio_time(s.radio, 1100000)
        assert not sender.rf_sender_poll(s.handle, None)
        wait = s.status()
        assert wait.state == 2
        sender.native_radio_time(s.radio, wait.ack_deadline_us)
        assert not sender.rf_sender_poll(s.handle, None)
        sender.native_radio_time(s.radio, 10000000)
        assert not sender.rf_sender_poll(s.handle, None)
        assert s.status().state == 5 and s.status().reason == b"run_deadline"
        observed = []
        event = Observation()
        for _ in range(3):
            if sender.rf_sender_poll(s.handle, C.byref(event)):
                observed.append((event.kind, event.status))
        assert observed == [(0, 0), (1, 1)]
        assert sender.native_radio_configure_default(s.radio)
        assert sender.rf_sender_begin(
            s.handle, data(sequence=8), len(data()), 160, 0, 50000, 20000, 80000, 20000000
        )
    finally:
        s.close()
