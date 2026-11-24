"""Public firmware packet planning checked against the selected v2 layout."""

import ctypes as C
import hashlib

import pytest
from test_node_control_native import native_library as native_library

from lora_testbed.frames_v2 import data_frame, parse_data


class Plan(C.Structure):
    _fields_ = [
        ("session", C.c_uint64),
        ("first_sequence", C.c_uint32),
        ("message_id", C.c_uint32),
        ("message_bytes", C.c_uint32),
        ("fragment_bytes", C.c_uint16),
        ("fragment_count", C.c_uint16),
        ("source", C.c_uint8),
        ("destination", C.c_uint8),
        ("content", C.c_uint8),
        ("flags", C.c_uint8),
    ]


@pytest.fixture
def fragments(native_library):
    lib = native_library
    lib.rf_message_plan_init.argtypes = [
        C.POINTER(Plan),
        C.c_uint64,
        C.c_uint32,
        C.c_uint32,
        C.c_uint8,
        C.c_uint8,
        C.c_uint8,
        C.c_bool,
        C.c_bool,
        C.c_uint32,
        C.c_uint16,
    ]
    lib.rf_message_plan_init.restype = C.c_bool
    lib.rf_message_fragment.argtypes = [
        C.POINTER(Plan),
        C.c_uint16,
        C.c_void_p,
        C.c_size_t,
        C.c_void_p,
    ]
    lib.rf_message_fragment.restype = C.c_size_t
    return lib


@pytest.mark.parametrize(
    ("length", "sizes"),
    [
        (1, [1]),
        (159, [159]),
        (160, [160]),
        (161, [160, 1]),
        (319, [160, 159]),
        (320, [160, 160]),
        (321, [160, 160, 1]),
    ],
)
def test_fragment_headers_and_final_remainder_reconstruct_exact_source(fragments, length, sizes):
    plan = Plan()
    assert fragments.rf_message_plan_init(
        C.byref(plan), 0x0102030405060708, 7, 9, 1, 2, 0, False, False, length, 160
    )
    assert plan.fragment_count == len(sizes)
    source = bytes((i * 37 + 11) % 256 for i in range(length))
    rebuilt = bytearray()
    for index, size in enumerate(sizes):
        out = C.create_string_buffer(255)
        n = fragments.rf_message_fragment(C.byref(plan), index, source, length, out)
        assert n == 40 + size
        wire = out.raw[:n]
        assert wire == data_frame(
            "0102030405060708",
            7 + index,
            9,
            index,
            len(sizes),
            length,
            "A",
            "B",
            source[index * 160 : index * 160 + size],
        )
        rebuilt.extend(parse_data(wire, 160)["body"])
    assert bytes(rebuilt) == source
    assert hashlib.sha256(rebuilt).digest() == hashlib.sha256(source).digest()


@pytest.mark.parametrize(
    ("fragment", "count", "final"), [(16, 4096, 16), (160, 410, 96), (215, 305, 176)]
)
def test_maximum_message_and_invalid_plans_are_bounded_before_work(
    fragments, fragment, count, final
):
    plan = Plan()
    assert fragments.rf_message_plan_init(
        C.byref(plan), 1, 1, 1, 1, 2, 0, False, False, 65536, fragment
    )
    assert plan.fragment_count == count
    source = bytes(range(256)) * 256
    rebuilt = bytearray()
    out = C.create_string_buffer(255)
    for i in range(count):
        n = fragments.rf_message_fragment(C.byref(plan), i, source, len(source), out)
        assert n == 40 + (final if i == count - 1 else fragment)
        rebuilt.extend(out.raw[40:n])
    assert bytes(rebuilt) == source
    original = bytes(plan)
    for size, cap, seq in [
        (65537, fragment, 1),
        (0, fragment, 1),
        (65536, 15, 1),
        (65536, 216, 1),
        (321, 160, 2**32 - 2),
        (321, 160, 0),
    ]:
        assert not fragments.rf_message_plan_init(
            C.byref(plan), 1, seq, 1, 1, 2, 0, False, False, size, cap
        )
        assert bytes(plan) == original
    out.raw = b"\xa5" * 255
    assert not fragments.rf_message_fragment(C.byref(plan), count, source, len(source), out)
    assert not fragments.rf_message_fragment(C.byref(plan), 0, source, len(source) - 1, out)
    assert out.raw == b"\xa5" * 255


def test_protected_plan_reserves_tag_without_emitting_unencrypted_protected_bytes(fragments):
    import struct

    fragments.rf_message_header.argtypes = [C.POINTER(Plan), C.c_uint16, C.c_void_p]
    fragments.rf_message_header.restype = C.c_size_t
    plan = Plan()
    assert fragments.rf_message_plan_init(
        C.byref(plan), 0x0102030405060708, 10, 3, 2, 1, 1, True, True, 400, 199
    )
    assert plan.fragment_count == 3
    out = C.create_string_buffer(255)
    assert fragments.rf_message_header(C.byref(plan), 2, out) == 40
    expected = struct.pack(
        ">2sBBBBBBQIIHHIHIH", b"LT", 2, 1, 3, 2, 1, 1, 0x0102030405060708, 12, 3, 2, 3, 400, 2, 0, 0
    )
    assert out.raw[:40] == expected
    assert 40 + 199 + 16 == 255
    assert not fragments.rf_message_fragment(C.byref(plan), 0, b"x" * 400, 400, out)
    assert not fragments.rf_message_plan_init(
        C.byref(plan), 1, 1, 1, 1, 2, 0, True, False, 400, 200
    )
