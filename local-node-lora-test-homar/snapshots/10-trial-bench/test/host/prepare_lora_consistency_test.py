"""Offline readiness checks: all device discovery and connections are mocked."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location("prepare_lora_consistency", TOOLS / "prepare_lora_consistency.py")
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)

ALLOWED = {"HELLO", "STOP", "TEST 0 10", "ROLE TX", "ROLE RX", "STATUS"}
NODES = [{"port": "COM6", "label": "Heltec-A", "mac_normalized": "8CFD49B5B78C"},
         {"port": "COM7", "label": "Heltec-B", "mac_normalized": "441BF66F99E4"}]


class PreparationTests(unittest.TestCase):
    def exercise(self, *, hello_overrides=None, status_overrides=None, counter=None,
                 discovery_error=None, open_error_port=None, stop_error_port=None,
                 nodes=None):
        hello_overrides = hello_overrides or {}
        status_overrides = status_overrides or {}
        events, connections = [], []
        owner = self

        class FakeConnection:
            def __init__(self, node, folder):
                self.node = node
                self.serial = SimpleNamespace(is_open=False)
                self.role = "TX" if node["label"] == "Heltec-A" else "RX"
                connections.append(self)

            def open(self):
                events.append((self.node["port"], "OPEN"))
                if self.node["port"] == open_error_port:
                    raise RuntimeError("simulated open failure")
                self.serial.is_open = True

            def request(self, command, event, **kwargs):
                # Any accidental transfer-capable command fails this test before
                # a response can be fabricated. No real serial object exists.
                owner.assertIn(command, ALLOWED)
                events.append((self.node["port"], command))
                port = self.node["port"]
                if command == "STOP" and port == stop_error_port:
                    raise RuntimeError("simulated STOP failure")
                message = {"event": event}
                if command == "HELLO":
                    message.update({
                        "mac": self.node["mac_normalized"], "boot_id": "mock-boot",
                        "firmware": "lora-integrity-2-oled", "radio_ready": True,
                        "frequency_mhz": 915, "bw_khz": 500, "sf": 7, "cr": 5,
                        "sync_word": 18, "chip_power_dbm": -9,
                        "data_packet_bytes": 251, "ack_packet_bytes": 14,
                        "data_airtime_us": 98624, "ack_airtime_us": 11584,
                        "oled_ready": True, "oled_layout_ok": True,
                        "tx_runs_started": 0, "rf_tx_calls_total": 0,
                    })
                    message.update(hello_overrides.get(port, {}))
                elif command == "TEST 0 10":
                    message.update(counter or {"current": 0, "total": 10})
                elif command.startswith("ROLE "):
                    self.role = command.split()[1]
                    message["role"] = self.role
                elif command == "STATUS":
                    message.update({
                        "role": self.role, "state": "IDLE", "test_current": 0, "test_total": 10,
                        "armed": False, "transmitting": False, "loaded": False,
                        "tx_runs_started": 0, "rf_tx_calls_total": 0,
                        "oled_ready": True, "oled_layout_ok": True,
                    })
                    message.update(status_overrides.get(port, {}))
                if "predicate" in kwargs:
                    owner.assertTrue(kwargs["predicate"](message))
                return {"message": message}

            def close(self):
                events.append((self.node["port"], "CLOSE"))
                self.serial.is_open = False

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "ready"
            with patch.object(prepare, "discover_nodes", return_value=nodes or NODES,
                              side_effect=discovery_error) as discover, \
                    patch.object(prepare, "Connection", FakeConnection), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = prepare.main(["--ports", "COM6", "COM7", "--output-dir", str(output)])
            discover.assert_called_once_with(["COM6", "COM7"])
            result = json.loads((output / "summary.json").read_text(encoding="utf-8"))
        self.assertFalse(result["test_started"])
        self.assertTrue(result["connections_closed"])
        self.assertTrue(all(not connection.serial.is_open for connection in connections))
        self.assertFalse(any(command.split()[0] in {"LOAD", "ARM", "TX"}
                             for _, command in events))
        return code, result, events, connections

    def test_success_uses_allowlist_leaves_idle_zero_and_closes_both(self):
        code, result, events, connections = self.exercise()
        self.assertEqual(code, 0)
        self.assertTrue(result["passed"])
        self.assertEqual(len(connections), 2)
        self.assertEqual(set(result["allowed_commands"]), ALLOWED)
        for node, role in zip(NODES, ("TX", "RX")):
            commands = [command for port, command in events if port == node["port"]]
            self.assertEqual(commands, ["OPEN", "HELLO", "STOP", "TEST 0 10",
                                        f"ROLE {role}", "STATUS", "STOP", "CLOSE"])
        self.assertTrue(all(row["status"]["rf_tx_calls_total"] == 0 for row in result["nodes"]))
        self.assertTrue(all(row["status"]["tx_runs_started"] == 0 for row in result["nodes"]))

    def test_role_follows_known_board_identity_when_ports_are_swapped(self):
        nodes = [{**NODES[1], "port": "COM6"}, {**NODES[0], "port": "COM7"}]
        code, _, events, _ = self.exercise(nodes=nodes)
        self.assertEqual(code, 0)
        self.assertIn(("COM6", "ROLE RX"), events)
        self.assertIn(("COM7", "ROLE TX"), events)

    def test_oled_failure_on_second_board_aborts_before_roles_and_closes_both(self):
        for field in ("oled_ready", "oled_layout_ok"):
            with self.subTest(field=field):
                code, result, events, connections = self.exercise(hello_overrides={"COM7": {field: False}})
                self.assertEqual(code, 1)
                self.assertFalse(result["passed"])
                self.assertIn("OLED readiness/layout", result["error"])
                self.assertEqual(len(connections), 2)
                self.assertFalse(any(command.startswith(("TEST", "ROLE")) for _, command in events))
                self.assertEqual(events[-4:], [("COM6", "STOP"), ("COM6", "CLOSE"),
                                               ("COM7", "STOP"), ("COM7", "CLOSE")])

    def test_initial_rf_counters_must_both_be_zero(self):
        for field in ("tx_runs_started", "rf_tx_calls_total"):
            with self.subTest(field=field):
                code, result, events, _ = self.exercise(hello_overrides={"COM6": {field: 1}})
                self.assertEqual(code, 1)
                self.assertIn("RF counters are nonzero", result["error"])
                self.assertFalse(any(command.startswith(("TEST", "ROLE")) for _, command in events))

    def test_final_status_rejects_nonidle_nonzero_or_unready_state(self):
        for field, value in (("role", "TX"), ("state", "RECEIVING"), ("test_current", 1),
                             ("test_total", 9), ("armed", True), ("transmitting", True),
                             ("loaded", True), ("tx_runs_started", 1), ("rf_tx_calls_total", 1),
                             ("oled_ready", False), ("oled_layout_ok", False)):
            with self.subTest(field=field):
                code, result, _, _ = self.exercise(status_overrides={"COM7": {field: value}})
                self.assertEqual(code, 1)
                self.assertIn("unexpected readiness status", result["error"])

    def test_wrong_counter_ack_aborts_without_role_or_transfer(self):
        code, result, events, _ = self.exercise(counter={"current": 1, "total": 10})
        self.assertEqual(code, 1)
        self.assertIn("Wrong test-counter", result["error"])
        self.assertFalse(any(command.startswith("ROLE") for _, command in events))

    def test_wrong_firmware_or_identity_aborts_safely(self):
        for change in ({"firmware": "lora-integrity-1"}, {"mac": "000000000000"},
                       {"radio_ready": False}):
            with self.subTest(change=change):
                code, result, events, _ = self.exercise(hello_overrides={"COM6": change})
                self.assertEqual(code, 1)
                self.assertFalse(result["passed"])
                self.assertFalse(any(command.startswith(("TEST", "ROLE")) for _, command in events))

    def test_open_failure_closes_first_port_and_does_not_send_setup(self):
        code, result, events, _ = self.exercise(open_error_port="COM7")
        self.assertEqual(code, 1)
        self.assertIn("open failure", result["error"])
        self.assertEqual(events, [("COM6", "OPEN"), ("COM7", "OPEN"),
                                  ("COM6", "STOP"), ("COM6", "CLOSE"), ("COM7", "CLOSE")])

    def test_stop_failure_does_not_prevent_either_close(self):
        code, result, _, _ = self.exercise(stop_error_port="COM6")
        self.assertEqual(code, 1)
        self.assertIn("STOP failure", result["error"])
        self.assertTrue(result["cleanup_errors"])

    def test_discovery_failure_opens_nothing_and_saves_failure_summary(self):
        code, result, events, connections = self.exercise(discovery_error=RuntimeError("unknown board"))
        self.assertEqual(code, 1)
        self.assertEqual(result["error"], "unknown board")
        self.assertFalse(events)
        self.assertFalse(connections)


if __name__ == "__main__":
    unittest.main()
