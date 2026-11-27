"""Bounded SSD1315-compatible wire transactions, using an isolated I2C seam."""

import ctypes as C

import pytest
from test_node_control_native import native_library as native_library

WRITE = C.CFUNCTYPE(C.c_bool, C.c_void_p, C.c_void_p, C.c_size_t, C.c_uint)


class PanelPort(C.Structure):
    _fields_ = [("context", C.c_void_p), ("write", WRITE)]


def test_panel_initializes_and_writes_one_exact_bounded_frame(native_library):
    writes = []

    def write(_, data, length, timeout):
        writes.append((C.string_at(data, length), timeout))
        return True

    callback = WRITE(write)
    port = PanelPort(None, callback)
    native_library.oled_panel_initialize.argtypes = [PanelPort]
    native_library.oled_panel_initialize.restype = C.c_bool
    native_library.oled_panel_frame.argtypes = [PanelPort, C.c_void_p]
    native_library.oled_panel_frame.restype = C.c_bool
    assert native_library.oled_panel_initialize(port)
    assert writes[0][0][0:2] == b"\x00\xae"  # Commands, display off until a complete frame.
    assert writes[0][0][-1] != 0xAF
    writes.clear()
    frame = bytes(range(256)) * 4
    assert native_library.oled_panel_frame(port, frame)
    assert len(writes) == 10
    assert writes[0][0] == b"\x00\x21\x00\x7f\x22\x00\x07"
    assert all(data[0] == 0x40 and len(data) == 129 for data, _ in writes[1:9])
    assert b"".join(data[1:] for data, _ in writes[1:9]) == frame
    assert writes[-1][0] == b"\x00\xaf"
    assert all(timeout == 5 for _, timeout in writes)


@pytest.mark.parametrize("failure", range(10))
def test_absent_or_stalled_panel_stops_at_failed_transaction_without_retry(native_library, failure):
    calls = []

    def write(_, data, length, timeout):
        calls.append((C.string_at(data, length), timeout))
        return len(calls) - 1 != failure

    callback = WRITE(write)
    port = PanelPort(None, callback)
    native_library.oled_panel_frame.argtypes = [PanelPort, C.c_void_p]
    native_library.oled_panel_frame.restype = C.c_bool
    assert not native_library.oled_panel_frame(port, bytes(1024))
    assert len(calls) == failure + 1
    assert all(timeout == 5 for _, timeout in calls)
    if failure < 9:
        assert all(data != b"\x00\xaf" for data, _ in calls)
