"""Acknowledgment references and retry eligibility at the firmware packet API."""

import ctypes as C
import hashlib
import struct

import pytest
from test_node_control_native import HASH
from test_node_control_native import native_library as native_library
from test_rf_reassembly_native import ALLOC, FREE, Port
from test_rf_reassembly_native import reconstruction as reconstruction


def data(payload=b"hello", sequence=7):
    return (
        struct.pack(
            ">2sBBBBBBQIIHHIHIH",
            b"LT",
            2,
            1,
            2,
            1,
            2,
            0,
            1,
            sequence,
            3,
            0,
            1,
            len(payload),
            len(payload),
            0,
            0,
        )
        + payload
    )


class AckReceiver:
    def __init__(self, lib, first_sequence=1):
        self.lib = lib
        self.live = {}

        @ALLOC
        def alloc(_, size):
            b = C.create_string_buffer(size)
            address = C.addressof(b)
            self.live[address] = b
            return address

        @FREE
        def release(_, p):
            del self.live[p]

        @HASH
        def sha(_, p, n, out):
            C.memmove(out, hashlib.sha256(C.string_at(p, n)).digest(), 32)
            return True

        self.port = Port(None, alloc, release, sha)
        self.handle = lib.rf_ack_create(self.port, 1, 2, 1, 160, first_sequence, 20, 500)
        assert self.handle

    def offer(self, wire, classification=1, now=0):
        return self.lib.rf_ack_offer(self.handle, wire, len(wire), classification, now)

    def take(self, now):
        out = C.create_string_buffer(56)
        size = self.lib.rf_ack_take(self.handle, now, out)
        return out.raw[:size]

    def close(self):
        self.lib.rf_ack_destroy(self.handle)
        assert not self.live


@pytest.fixture
def acknowledgments(native_library):
    lib = native_library
    lib.rf_ack_create.argtypes = [
        Port,
        C.c_uint64,
        C.c_uint8,
        C.c_uint8,
        C.c_uint16,
        C.c_uint32,
        C.c_uint32,
        C.c_uint32,
    ]
    lib.rf_ack_create.restype = C.c_void_p
    lib.rf_ack_destroy.argtypes = [C.c_void_p]
    lib.rf_ack_offer.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t, C.c_int, C.c_int64]
    lib.rf_ack_offer.restype = C.c_bool
    lib.rf_ack_take.argtypes = [C.c_void_p, C.c_int64, C.c_void_p]
    lib.rf_ack_take.restype = C.c_size_t
    lib.rf_ack_matches.argtypes = [C.c_void_p, C.c_size_t, C.c_void_p, C.c_size_t, C.c_uint16]
    lib.rf_ack_matches.restype = C.c_bool
    lib.rf_ack_cancel.argtypes = [C.c_void_p]
    return lib


def test_receiver_schedules_fresh_ack_naming_exact_accepted_data(acknowledgments):
    r = AckReceiver(acknowledgments)
    wire = data()
    try:
        assert r.offer(wire)
        assert r.take(19) == b""
        ack = r.take(20)
        expected = struct.pack(
            ">2sBBBBBBQIIHHIHIH", b"LT", 2, 2, 0, 2, 1, 0, 1, 1, 3, 0, 1, 5, 0, 7, 0
        )
        assert ack == expected
        assert acknowledgments.rf_ack_matches(ack, len(ack), wire, len(wire), 160)
        assert r.take(21) == b""
    finally:
        r.close()


def test_only_cached_identical_retry_inside_horizon_gets_a_fresh_ack(acknowledgments):
    r = AckReceiver(acknowledgments)
    wire = data()
    try:
        assert not r.offer(wire, classification=2)
        assert not r.offer(wire, classification=3)
        assert r.offer(wire)
        first = r.take(20)
        assert not r.offer(data(b"wrong"), classification=2, now=30)
        assert not r.offer(data(sequence=8), classification=2, now=30)
        assert r.offer(wire, classification=2, now=30)
        second = r.take(50)
        assert first[16:20] == b"\0\0\0\1" and second[16:20] == b"\0\0\0\2"
        assert first[:16] + first[20:] == second[:16] + second[20:]
        assert not r.offer(wire, classification=2, now=500)
        assert r.take(1000) == b""
    finally:
        r.close()


def test_wrong_unknown_stale_or_malformed_ack_cannot_match_an_outstanding_frame(acknowledgments):
    r = AckReceiver(acknowledgments)
    wire = data()
    try:
        assert r.offer(wire)
        ack = r.take(20)
        for offset in [0, 2, 3, 4, 5, 6, 7, 8, 16, 20, 24, 26, 28, 32, 34, 38]:
            bad = bytearray(ack)
            bad[offset] ^= 0x80
            # Any nonzero ACK sequence is legal; sequence freshness is replay-layer work.
            if offset == 16:
                continue
            assert not acknowledgments.rf_ack_matches(bytes(bad), len(bad), wire, len(wire), 160)
        for bad in [ack[:-1], ack + b"x", ack[:16] + b"\0" * 4 + ack[20:]]:
            assert not acknowledgments.rf_ack_matches(bad, len(bad), wire, len(wire), 160)
        other = data(sequence=8)
        assert not acknowledgments.rf_ack_matches(ack, len(ack), other, len(other), 160)
    finally:
        r.close()


def test_ack_cancel_sequence_exhaustion_and_last_sixteen_cache_are_bounded(acknowledgments):
    r = AckReceiver(acknowledgments, first_sequence=2**32 - 1)
    try:
        assert r.offer(data())
        assert r.take(20)[16:20] == b"\xff" * 4
        assert not r.offer(data(), classification=2, now=30)
    finally:
        r.close()
    r = AckReceiver(acknowledgments)
    try:
        for seq in range(1, 18):
            assert r.offer(data(sequence=seq), now=seq * 22)
            assert r.take(seq * 22 + 20)
        assert not r.offer(data(sequence=1), classification=2, now=400)
        assert r.offer(data(sequence=2), classification=2, now=400)
        acknowledgments.rf_ack_cancel(r.handle)
        assert not r.take(420)
        assert not r.offer(data(sequence=2), classification=2, now=420)
    finally:
        r.close()


def test_data_retry_reacks_without_a_second_reconstruction_delivery(
    acknowledgments, reconstruction
):
    from test_rf_reassembly_native import Reassembly

    receiver = Reassembly(reconstruction)
    acks = AckReceiver(acknowledgments)
    wire = data()
    try:
        assert reconstruction.rf_reassembly_begin(
            receiver.handle, 3, 0, 2, 5, hashlib.sha256(b"hello").digest(), 0, 1000
        )
        result = reconstruction.rf_reassembly_accept(receiver.handle, wire, len(wire), 1)
        assert result == 3
        assert receiver.take()[0] == b"hello"
        assert acks.offer(wire, classification=1, now=1)
        assert acks.take(21)
        assert reconstruction.rf_reassembly_accept(receiver.handle, wire, len(wire), 30) == 2
        assert acks.offer(wire, classification=2, now=30)
        assert acks.take(50)
        assert receiver.take() is None
    finally:
        receiver.close()
        acks.close()
