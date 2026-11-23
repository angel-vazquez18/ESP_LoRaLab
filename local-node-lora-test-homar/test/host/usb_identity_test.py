"""Offline USB identity checks; enumerate mocked descriptors, never real devices."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "lora_usb_identity", Path(__file__).resolve().parents[2] / "tools/verify_heltec_bench.py")
identity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(identity)


def device(port, serial, vid=0x303A, pid=0x1001):
    return SimpleNamespace(device=port, serial_number=serial, vid=vid, pid=pid,
                           description="Mock USB Serial/JTAG", hwid="MOCK")


class UsbIdentityTests(unittest.TestCase):
    def discover(self, descriptors, ports=("COM6", "COM7")):
        with patch.object(identity.list_ports, "comports", return_value=descriptors) as enumerate_ports:
            result = identity.discover_nodes(ports)
            enumerate_ports.assert_called_once_with()
            return result

    def pair(self):
        return [device("COM6", "8c:fd:49:b5:b7:8c"), device("COM7", "44:1b:f6:6f:99:e4")]

    def test_known_nodes_resolve_by_usb_identity_and_preserve_requested_order(self):
        result = self.discover(self.pair(), ("COM7", "com6"))
        self.assertEqual([node["label"] for node in result], ["Heltec-B", "Heltec-A"])
        self.assertEqual([node["port"] for node in result], ["COM7", "COM6"])
        self.assertTrue(all(node["port_matches_assignment"] for node in result))

    def test_reassigned_ports_do_not_change_hardware_identity(self):
        result = self.discover([device("COM9", "8CFD49B5B78C"), device("COM8", "441BF66F99E4")],
                               ("COM9", "COM8"))
        self.assertEqual([node["label"] for node in result], ["Heltec-A", "Heltec-B"])
        self.assertEqual([node["assigned_port"] for node in result], ["COM6", "COM7"])
        self.assertFalse(any(node["port_matches_assignment"] for node in result))

    def test_wrong_usb_vendor_or_product_is_rejected(self):
        for vid, pid in ((0x10C4, 0x1001), (0x303A, 0xEA60)):
            with self.subTest(vid=vid, pid=pid), self.assertRaisesRegex(RuntimeError, "expected Espressif"):
                self.discover([device("COM6", "8CFD49B5B78C", vid, pid)], ("COM6",))

    def test_unknown_or_missing_serial_is_rejected(self):
        for serial in ("001122334455", None):
            with self.subTest(serial=serial), self.assertRaisesRegex(RuntimeError, "unrecognized USB serial"):
                self.discover([device("COM6", serial)], ("COM6",))

    def test_same_hardware_on_two_selected_ports_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "different boards"):
            self.discover([device("COM6", "8CFD49B5B78C"), device("COM7", "8c:fd:49:b5:b7:8c")])

    def test_selecting_same_port_twice_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "different boards"):
            self.discover(self.pair(), ("COM6", "com6"))

    def test_absent_port_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "COM8 is not a connected serial device"):
            self.discover(self.pair(), ("COM6", "COM8"))

    def test_normalization_handles_usb_mac_formats_and_missing_values(self):
        for value in ("8c:fd:49:b5:b7:8c", "8c-fd-49-b5-b7-8c", "8CFD49B5B78C"):
            self.assertEqual(identity.normalized_mac(value), "8CFD49B5B78C")
        self.assertEqual(identity.normalized_mac(None), "")


if __name__ == "__main__":
    unittest.main()
