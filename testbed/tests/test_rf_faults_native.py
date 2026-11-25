"""Portable protected-wire faults use exact copies and never invoke encryption."""

import ctypes as C
import hashlib
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from test_node_control_native import HASH
from test_node_control_native import native_library as native_library
from test_rf_fragments_native import Plan
from test_rf_reassembly_native import ALLOC, FREE, Port
from test_secure_replay_native import KEY_A

from lora_testbed.frames_v2 import data_frame


class Spec(C.Structure):
    _fields_ = [
        ("id", C.c_char * 37),
        ("message", C.c_uint32),
        ("fragment", C.c_uint16),
        ("offset", C.c_uint16),
        ("attempt", C.c_uint8),
        ("action", C.c_uint8),
        ("mask", C.c_uint8),
        ("block_size", C.c_uint8),
    ]


class View(C.Structure):
    _fields_ = [
        ("spec", Spec),
        ("state", C.c_uint8),
        ("sequence", C.c_uint32),
        ("frame_bytes", C.c_uint16),
        ("before", C.c_uint8 * 32),
        ("after", C.c_uint8 * 32),
        ("applied_us", C.c_int64),
        ("arrived_us", C.c_int64),
    ]


class Faults:
    def __init__(self, lib):
        self.lib, self.live = lib, {}

        @ALLOC
        def allocate(_, size):
            value = C.create_string_buffer(size)
            self.live[C.addressof(value)] = value
            return C.addressof(value)

        @FREE
        def free(_, address):
            assert not any(self.live[address].raw), "Fault owner must be wiped before release"
            del self.live[address]

        @HASH
        def digest(_, source, length, target):
            C.memmove(target, hashlib.sha256(C.string_at(source, length)).digest(), 32)
            return True

        self.port = Port(None, allocate, free, digest)
        self.handle = lib.rf_faults_create(self.port, 1, 1)
        assert self.handle

    def configure(self, specs, replace=True):
        return self.lib.rf_faults_configure(
            self.handle, (Spec * len(specs))(*specs), len(specs), replace
        )

    def prepare(self):
        plan = Plan(1, 7, 1, 32, 64, 1, 1, 2, 0, 1)
        return self.lib.rf_faults_prepare(self.handle, C.byref(plan), 3)

    def transform(self, wire, attempt=1):
        pointer = self.lib.rf_faults_transform(self.handle, wire, len(wire), attempt, 123)
        return C.string_at(pointer, len(wire)) if pointer else None

    def replay(self, identifier):
        size = C.c_size_t()
        pointer = self.lib.rf_faults_replay(self.handle, identifier, C.byref(size))
        return C.string_at(pointer, size.value) if pointer else None

    def pop(self):
        view = View()
        return view if self.lib.rf_faults_pop(self.handle, C.byref(view)) else None

    def close(self):
        self.lib.rf_faults_destroy(self.handle)
        assert not self.live


@pytest.fixture
def fault_library(native_library):
    lib = native_library
    signatures = {
        "create": ([Port, C.c_uint64, C.c_uint8], C.c_void_p),
        "destroy": ([C.c_void_p], None),
        "configure": ([C.c_void_p, C.POINTER(Spec), C.c_size_t, C.c_bool], C.c_bool),
        "prepare": ([C.c_void_p, C.POINTER(Plan), C.c_uint8], C.c_bool),
        "transform": ([C.c_void_p, C.c_void_p, C.c_size_t, C.c_uint8, C.c_int64], C.c_void_p),
        "replay": ([C.c_void_p, C.c_char_p, C.POINTER(C.c_size_t)], C.c_void_p),
        "fired": ([C.c_void_p, C.c_char_p, C.c_int64], C.c_bool),
        "pop": ([C.c_void_p, C.POINTER(View)], C.c_bool),
        "disable": ([C.c_void_p], None),
        "count": ([C.c_void_p], C.c_uint),
        "view": ([C.c_void_p, C.c_uint, C.POINTER(View)], C.c_bool),
    }
    for name, (args, result) in signatures.items():
        function = getattr(lib, "rf_faults_" + name)
        function.argtypes, function.restype = args, result
    return lib


def spec(action=1, **changes):
    values = dict(
        id=str(uuid4()).encode(),
        message=1,
        fragment=0,
        offset=40 if action == 1 else 0,
        attempt=1,
        action=action,
        mask=1 if action == 1 else 0,
    )
    return Spec(**(values | changes))


def wire():
    header = bytearray(
        data_frame("0000000000000001", 7, 1, 0, 1, 32, "A", "B", bytes(range(32)))[:40]
    )
    header[4] = 1
    return bytes(header) + AESGCM(KEY_A).encrypt(
        bytes(header[8:20]), bytes(range(32)), bytes(header)
    )


def test_selected_post_protect_mutation_preserves_original_and_later_attempt(fault_library):
    owner = Faults(fault_library)
    try:
        injection = spec()
        assert owner.configure([injection]) and owner.prepare()
        original = wire()
        changed = owner.transform(original)
        assert changed[:40] == original[:40]
        assert changed[40] == original[40] ^ 1 and changed[41:] == original[41:]
        applied = owner.pop()
        assert applied and applied.sequence == 7 and applied.applied_us == 123
        assert bytes(applied.before) == hashlib.sha256(original).digest()
        assert bytes(applied.after) == hashlib.sha256(changed).digest()
        assert owner.transform(original, 2) == original and owner.pop() is None
        assert original == wire()
    finally:
        owner.close()


def test_retained_replay_is_exact_once_and_cleared_on_disable(fault_library):
    owner = Faults(fault_library)
    try:
        injection = spec(2)
        assert owner.configure([injection]) and owner.prepare()
        original = wire()
        assert owner.transform(original) == original and owner.pop() is None
        assert owner.replay(injection.id) == original
        assert fault_library.rf_faults_fired(owner.handle, injection.id, 456)
        applied = owner.pop()
        assert (
            applied.applied_us == 456
            and bytes(applied.before) == bytes(applied.after) == hashlib.sha256(original).digest()
        )
        assert owner.replay(injection.id) is None
        assert not fault_library.rf_faults_fired(owner.handle, injection.id, 457)
        fault_library.rf_faults_disable(owner.handle)
        assert all(original not in value.raw for value in owner.live.values())
        assert owner.replay(injection.id) is None
    finally:
        owner.close()


@pytest.mark.parametrize("change", [{"offset": 39}, {"mask": 0}, {"attempt": 0}, {"action": 255}])
def test_invalid_configuration_is_atomic_and_keeps_previous_target(fault_library, change):
    owner = Faults(fault_library)
    try:
        original = spec()
        assert owner.configure([original])
        assert not owner.configure([spec(**change)])
        assert fault_library.rf_faults_count(owner.handle) == 1
        assert owner.prepare()
        assert owner.transform(wire()) != wire()
    finally:
        owner.close()


@pytest.mark.parametrize("offset", [40, 71, 72, 87])
def test_ciphertext_and_tag_changes_fail_authentication_but_keep_valid_control(
    fault_library, offset
):
    from cryptography.exceptions import InvalidTag

    owner = Faults(fault_library)
    try:
        assert owner.configure([spec(offset=offset)]) and owner.prepare()
        original = wire()
        changed = owner.transform(original)
        with pytest.raises(InvalidTag):
            AESGCM(KEY_A).decrypt(changed[8:20], changed[40:], changed[:40])
        assert AESGCM(KEY_A).decrypt(original[8:20], original[40:], original[:40]) == bytes(
            range(32)
        )
        assert owner.configure([]) and owner.prepare()
        assert owner.transform(original) == original
    finally:
        owner.close()


@pytest.mark.parametrize(
    "change", [{"offset": 88}, {"fragment": 1}, {"message": 2}, {"attempt": 3}]
)
def test_actual_geometry_and_attempt_budget_reject_wrong_targets_before_transform(
    fault_library, change
):
    owner = Faults(fault_library)
    try:
        assert owner.configure([spec(**change)])
        plan = Plan(1, 7, 1, 32, 64, 1, 1, 2, 0, 1)
        assert not fault_library.rf_faults_prepare(owner.handle, C.byref(plan), 2)
        assert owner.transform(wire()) is None and owner.pop() is None
    finally:
        owner.close()


def test_configuration_and_pending_observations_remain_bounded(fault_library):
    owner = Faults(fault_library)
    try:
        for offset in range(40, 72, 8):
            assert owner.configure(
                [spec(offset=i) for i in range(offset, offset + 8)], replace=offset == 40
            )
        assert fault_library.rf_faults_count(owner.handle) == 32
        assert not owner.configure([spec(offset=72)], replace=False)
        assert owner.prepare() and owner.transform(wire()) != wire()
        seen = []
        while row := owner.pop():
            seen.append(row.spec.id)
        assert len(seen) == len(set(seen)) == 32
        assert owner.transform(wire(), 2) == wire() and owner.pop() is None
        assert owner.configure([]) and owner.prepare() and owner.transform(wire()) == wire()
    finally:
        owner.close()


def test_retained_slots_and_duplicate_ids_reject_atomically(fault_library):
    owner = Faults(fault_library)
    try:
        first = spec(2)
        assert owner.configure([first])
        assert not owner.configure([first], replace=False)
        assert fault_library.rf_faults_count(owner.handle) == 1
        assert owner.configure([spec(2) for _ in range(8)])
        assert owner.configure([spec(2) for _ in range(8)], replace=False)
        assert not owner.configure([spec(2)], replace=False)
        assert fault_library.rf_faults_count(owner.handle) == 16
        assert owner.prepare() and owner.transform(wire()) == wire()
        fault_library.rf_faults_disable(owner.handle)
        assert wire() not in next(iter(owner.live.values())).raw
    finally:
        owner.close()
