"""Opaque reconstruction API with real bytes and a tracked heap boundary."""

import ctypes as C
import hashlib

import pytest
from test_node_control_native import HASH
from test_node_control_native import native_library as native_library

from lora_testbed.frames_v2 import data_frame

ALLOC = C.CFUNCTYPE(C.c_void_p, C.c_void_p, C.c_size_t)
FREE = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p)


class Port(C.Structure):
    _fields_ = [("context", C.c_void_p), ("allocate", ALLOC), ("release", FREE), ("hash", HASH)]


class Reassembly:
    def __init__(self, lib, fragment=160):
        self.lib = lib
        self.fragment = fragment
        self.allocations = 0
        self.live = {}
        self.fail = False

        @ALLOC
        def allocate(_, size):
            self.allocations += 1
            if self.fail:
                return None
            buffer = C.create_string_buffer(size)
            address = C.addressof(buffer)
            self.live[address] = buffer
            return address

        @FREE
        def release(_, address):
            assert address in self.live
            del self.live[address]

        @HASH
        def digest(_, source, length, target):
            C.memmove(target, hashlib.sha256(C.string_at(source, length)).digest(), 32)
            return True

        self.port = Port(None, allocate, release, digest)
        self.handle = lib.rf_reassembly_create(self.port, 1, 1, 2, fragment)
        assert self.handle

    def close(self):
        self.lib.rf_reassembly_destroy(self.handle)
        assert not self.live

    def begin(self, data, message=1, now=0, deadline=1000):
        return self.lib.rf_reassembly_begin(
            self.handle, message, 0, 0, len(data), hashlib.sha256(data).digest(), now, deadline
        )

    def feed(self, data, index, message=1, total=None, count=None, now=1):
        wire = data_frame(
            "0000000000000001",
            index + 1,
            message,
            index,
            count if count is not None else (len(data) + self.fragment - 1) // self.fragment,
            len(data) if total is None else total,
            "A",
            "B",
            data[index * self.fragment : (index + 1) * self.fragment],
        )
        return self.lib.rf_reassembly_accept(self.handle, wire, len(wire), now)

    def take(self):
        pointer, size, digest = C.c_void_p(), C.c_size_t(), C.create_string_buffer(32)
        ok = self.lib.rf_reassembly_take(self.handle, C.byref(pointer), C.byref(size), digest)
        return (C.string_at(pointer, size.value), digest.raw) if ok else None


@pytest.fixture
def reconstruction(native_library):
    lib = native_library
    lib.rf_reassembly_create.argtypes = [Port, C.c_uint64, C.c_uint8, C.c_uint8, C.c_uint16]
    lib.rf_reassembly_create.restype = C.c_void_p
    lib.rf_reassembly_destroy.argtypes = [C.c_void_p]
    lib.rf_reassembly_begin.argtypes = [
        C.c_void_p,
        C.c_uint32,
        C.c_uint8,
        C.c_uint8,
        C.c_uint32,
        C.c_void_p,
        C.c_int64,
        C.c_int64,
    ]
    lib.rf_reassembly_begin.restype = C.c_bool
    lib.rf_reassembly_accept.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t, C.c_int64]
    lib.rf_reassembly_accept.restype = C.c_int
    lib.rf_reassembly_take.argtypes = [
        C.c_void_p,
        C.POINTER(C.c_void_p),
        C.POINTER(C.c_size_t),
        C.c_void_p,
    ]
    lib.rf_reassembly_take.restype = C.c_bool
    lib.rf_reassembly_poll.argtypes = [C.c_void_p, C.c_int64]
    lib.rf_reassembly_poll.restype = C.c_int
    lib.rf_reassembly_cancel.argtypes = [C.c_void_p]
    lib.rf_reassembly_missing.argtypes = [C.c_void_p, C.c_uint16, C.c_void_p, C.c_size_t]
    lib.rf_reassembly_missing.restype = C.c_size_t
    return lib


def test_reordered_duplicate_fragments_deliver_exact_bytes_once(reconstruction):
    r = Reassembly(reconstruction)
    data = bytes(range(256)) + b"ending" * 11
    try:
        assert r.begin(data)
        assert r.feed(data, 2) == 1
        assert r.take() is None
        assert r.feed(data, 0) == 1
        assert r.feed(data, 0) == 2
        assert r.feed(data, 1) == 3
        assert r.take() == (data, hashlib.sha256(data).digest())
        assert r.take() is None
        assert r.feed(data, 1) == 2
        assert not r.begin(data)
    finally:
        r.close()


def test_missing_deadline_releases_bytes_and_cannot_restart_failed_message(reconstruction):
    r = Reassembly(reconstruction)
    data = b"a" * 321
    try:
        baseline = len(r.live)
        assert r.begin(data)
        assert r.feed(data, 2) == 1 and r.feed(data, 0) == 1
        missing = (C.c_uint16 * 8)()
        assert reconstruction.rf_reassembly_missing(r.handle, 0, missing, 8) == 1
        assert list(missing)[:1] == [1]
        assert reconstruction.rf_reassembly_poll(r.handle, 999) == 1
        assert reconstruction.rf_reassembly_poll(r.handle, 1000) == 6
        assert len(r.live) == baseline and r.take() is None
        assert reconstruction.rf_reassembly_missing(r.handle, 0, missing, 8) == 1
        assert not r.begin(data)
        assert r.begin(data, message=2, now=1000, deadline=2000)
        for i, expected in [(0, 1), (1, 1), (2, 3)]:
            assert r.feed(data, i, message=2, now=1001) == expected
        assert r.take()[0] == data
    finally:
        r.close()


@pytest.mark.parametrize("failure", ["metadata", "duplicate", "hash", "cancel"])
def test_conflicting_or_cancelled_message_never_exposes_partial_bytes(reconstruction, failure):
    r = Reassembly(reconstruction)
    data = b"a" * 321
    try:
        baseline = len(r.live)
        assert r.begin(data)
        assert r.feed(data, 0) == 1
        if failure == "metadata":
            assert r.feed(data, 1, total=322) == 4
        elif failure == "duplicate":
            assert r.feed(b"b" * 321, 0) == 4
        elif failure == "hash":
            assert r.feed(b"b" * 321, 1) == 1
            assert r.feed(data, 2) == 7
        else:
            reconstruction.rf_reassembly_cancel(r.handle)
        assert r.take() is None and len(r.live) == baseline
        assert r.feed(data, 1) == 5
        assert r.begin(b"new", message=2)
        assert r.feed(b"new", 0, message=2) == 3
        assert r.take()[0] == b"new"
    finally:
        r.close()


def test_completed_delivery_stays_valid_after_late_conflicting_duplicate(reconstruction):
    r = Reassembly(reconstruction)
    try:
        assert r.begin(b"good")
        assert r.feed(b"good", 0) == 3
        assert r.take()[0] == b"good"
        before = set(r.live)
        assert r.feed(b"evil", 0) == 4
        assert set(r.live) == before
        assert r.feed(b"good", 0) == 2
        assert r.take() is None
    finally:
        r.close()


@pytest.mark.parametrize("fragment", [16, 160, 215])
def test_maximum_reconstruction_and_paged_missing_indexes(reconstruction, fragment):
    r = Reassembly(reconstruction, fragment)
    source = bytes(range(256)) * 256
    try:
        assert r.begin(source)
        count = (65536 + fragment - 1) // fragment
        missing = (C.c_uint16 * 3)()
        assert reconstruction.rf_reassembly_missing(r.handle, 100, missing, 3) == 3
        assert list(missing) == [100, 101, 102]
        for i in reversed(range(count)):
            assert r.feed(source, i) == (3 if i == 0 else 1)
        assert reconstruction.rf_reassembly_missing(r.handle, 0, missing, 3) == 0
        assert r.take() == (source, hashlib.sha256(source).digest())
    finally:
        r.close()


def test_invalid_preflight_and_allocation_failure_leave_no_partial_delivery(reconstruction):
    r = Reassembly(reconstruction)
    try:
        allocations = r.allocations
        for data, now, deadline in [
            (b"x" * 65537, 0, 1000),
            (b"", 0, 1000),
            (b"x", -1, 1000),
            (b"x", 1000, 1000),
            (b"x", 0, 3600000001),
        ]:
            assert not r.begin(data, now=now, deadline=deadline)
            assert r.allocations == allocations
        r.fail = True
        assert not r.begin(b"good")
        assert r.take() is None and len(r.live) == 1
        r.fail = False
        assert r.begin(b"good")
        assert r.feed(b"good", 0) == 3 and r.take()[0] == b"good"
    finally:
        r.close()


def test_wrong_session_role_protection_and_truncated_bytes_do_not_insert(reconstruction):
    r = Reassembly(reconstruction)
    source = b"a" * 321
    try:
        assert r.begin(source)
        wire = data_frame("0000000000000001", 1, 1, 0, 3, 321, "A", "B", source[:160])
        for changed in [
            wire[:-1],
            wire[:8] + b"\0" * 8 + wire[16:],
            wire[:5] + b"\x02\x01" + wire[7:],
            wire[:4] + b"\x01" + wire[5:],
        ]:
            assert reconstruction.rf_reassembly_accept(r.handle, changed, len(changed), 1) in (0, 4)
            assert r.take() is None
        reconstruction.rf_reassembly_cancel(r.handle)
        assert r.begin(b"new", message=2)
        assert r.feed(b"new", 0, message=2) == 3
        assert r.take()[0] == b"new"
    finally:
        r.close()
