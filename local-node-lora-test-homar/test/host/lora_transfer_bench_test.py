import importlib.util
import contextlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import threading
import subprocess
import shutil
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location("lora_transfer_bench", TOOLS / "lora_transfer_bench.py")
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


class AnalysisTests(unittest.TestCase):
    source = (bytes(range(256)) * 188)[:48000]

    def hello(self):
        return {"mac": "8C:FD:49:B5:B7:8C", "boot_id": "testboot", "node": 6,
                "firmware": "lora-transfer", "radio_ready": True,
                "frequency_mhz": 915, "bw_khz": 500, "sf": 7, "cr": 5,
                "sync_word": 18, "chip_power_dbm": -9, "data_packet_bytes": 251,
                "ack_packet_bytes": 14, "data_airtime_us": 100000, "ack_airtime_us": 10000}

    def test_identity_rejects_wrong_board_and_radio(self):
        node = {"port": "COM6", "mac_normalized": "8CFD49B5B78C"}
        bench.validate_hello(node, self.hello())
        for change in ({"mac": "44:1B:F6:6F:99:E4"}, {"radio_ready": False},
                       {"chip_power_dbm": 22}, {"data_packet_bytes": 247}):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                bench.validate_hello(node, {**self.hello(), **change})

    def test_exact_pcm_and_signed_sample_difference(self):
        same = bench.compare_pcm(self.source, self.source)
        self.assertTrue(same["byte_exact"])
        self.assertEqual(same["different_samples"], 0)
        changed = bench.compare_pcm(struct.pack("<hh", -32768, 10), struct.pack("<hh", 32767, 9))
        self.assertEqual(changed["max_abs_sample_difference"], 65535)
        self.assertEqual(changed["different_samples"], 2)
        missing = bench.compare_pcm(b"\x00\x00\x01\x00", b"\x00\x00")
        self.assertFalse(missing["byte_exact"])
        self.assertEqual(missing["missing_or_extra_samples"], 1)

    def test_missing_packet_zero_fill_is_detected(self):
        received = bytearray(self.source)
        received[17 * 240:18 * 240] = bytes(240)
        result = bench.compare_pcm(self.source, received)
        self.assertFalse(result["byte_exact"])
        self.assertNotEqual(result["source_crc32"], result["received_crc32"])
        self.assertNotEqual(result["source_sha256"], result["received_sha256"])

    def test_accounting_counts_retries_and_ack_loss_without_claiming_phy_bytes(self):
        tx = [{"index": 0, "attempt": 1, "radio_status": 0, "acked": False},
              {"index": 0, "attempt": 2, "radio_status": 0, "acked": True},
              {"index": 1, "attempt": 1, "radio_status": -1, "acked": False}]
        rx = [{"index": 0, "duplicate": False, "ack_status": 0},
              {"index": 0, "duplicate": True, "ack_status": 0}]
        result = bench.packet_accounting(tx, rx, self.hello())
        self.assertEqual(result["data_rf_payload_bytes_no_retries"], 50200)
        self.assertEqual(result["ack_rf_payload_bytes_no_retries"], 2800)
        self.assertEqual(result["data_rf_payload_bytes_attempted"], 753)
        self.assertEqual(result["ack_rf_payload_bytes_received_by_sender"], 14)
        self.assertEqual(result["ack_rf_payload_bytes_successful_tx_calls"], 28)
        self.assertEqual(result["retries_observed"], 1)
        self.assertEqual(result["receiver_duplicate_packets"], 1)
        self.assertEqual(result["missing_chunk_indices"], list(range(1, 200)))
        self.assertEqual(result["estimated_airtime_successful_radio_calls_us"], 220000)

    def test_packet_crc_includes_voice_header_and_source(self):
        crc = bench.expected_data_crc(self.source, 9, 0)
        tx = [{"index": 0, "radio_status": 0, "acked": True, "data_crc32": crc}]
        rx = [{"index": 0, "duplicate": False, "ack_status": 0, "data_crc32": "00000000"}]
        result = bench.packet_accounting(tx, rx, self.hello(), self.source, 9)
        self.assertEqual(result["invalid_logged_data_crc_events"],
                         [{"side": "RX", "index": 0, "reported_crc32": "00000000"}])
        self.assertNotEqual(crc, bench.expected_data_crc(self.source, 10, 0))

    def test_actual_tx_status_survives_later_receive_start_failure(self):
        tx = [{"index": 0, "tx_radio_status": 0, "radio_status": -1, "acked": False}]
        result = bench.packet_accounting(tx, [], self.hello())
        self.assertEqual(result["tx_successful_radio_calls"], 1)
        self.assertEqual(result["data_rf_payload_bytes_successful_tx_calls"], 251)
        self.assertEqual(result["estimated_airtime_successful_radio_calls_us"], 100000)

    def test_clock_bounds_and_reboot_rejection(self):
        before = bench.clock_sample(1_000_000, 1_020_000, 100, "boot1")
        after = bench.clock_sample(2_000_000, 2_020_000, 1100, "boot1")
        self.assertEqual((before["offset_lower_us"], before["offset_upper_us"]), (900, 920))
        alignment = bench.clock_alignment(before, after)
        self.assertTrue(alignment["stable"])
        bounds = bench.latency_bounds(200, 300, alignment, alignment)
        self.assertEqual((bounds["lower_us"], bounds["upper_us"]), (80, 120))
        reboot = bench.clock_alignment(before, {**after, "boot_id": "boot2"})
        self.assertFalse(reboot["stable"])
        self.assertIsNone(bench.latency_bounds(200, 300, alignment, reboot))
        shifted = bench.clock_alignment(before, bench.clock_sample(3_000_000, 3_020_000, 1100, "boot1"))
        self.assertFalse(shifted["stable"])

    def test_source_wav_validation_and_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.wav"
            bench.save_wav(path, self.source)
            pcm, metadata = bench.read_source(path)
            self.assertEqual(pcm, self.source)
            self.assertEqual(metadata["pcm_bytes"], 48000)
            self.assertEqual(metadata["wav_file_bytes"], 48044)
            bench.save_wav(path, b"\x00\x00")
            with self.assertRaises(RuntimeError):
                bench.read_source(path)

    def test_negative_control_requires_empty_receiver_and_bounded_sender_failure(self):
        trial = {
            "rx_port": "COM7", "receiver_intentionally_stopped": {"event": "stopped"},
            "tx_done": {"success": False, "cancelled": False, "acked_chunks": 0,
                        "attempts": 6, "retries": 5, "successful_transmits": 6},
            "tx_packets": [{"index": 0, "attempt": n, "acked": False} for n in range(1, 7)],
            "accounting": {"unique_chunks_received": 0, "unique_chunks_acked": 0,
                           "invalid_logged_data_crc_events": [], "tx_successful_radio_calls": 6},
            "status_COM7": {"received_chunks": 0, "rx_packets": 0},
            "rx_complete": None, "rx_dump": {"complete": False},
            "receiver_zero_comparison": {"byte_exact": True},
        }
        self.assertTrue(bench.negative_control_passed(trial, 6))
        for change in ({"receiver_zero_comparison": {"byte_exact": False}},
                       {"status_COM7": {"received_chunks": 1, "rx_packets": 1}},
                       {"tx_done": {**trial["tx_done"], "attempts": 1}},
                       {"tx_done": {**trial["tx_done"], "cancelled": True}},
                       {"clock_after_error": "serial disconnected"},
                       {"interrupted": True},
                       {"tx_done": {**trial["tx_done"], "successful_transmits": 0},
                        "accounting": {**trial["accounting"], "tx_successful_radio_calls": 0}},
                       {"tx_done": {**trial["tx_done"], "successful_transmits": 5}},
                       {"accounting": {**trial["accounting"], "tx_successful_radio_calls": 5}}):
            with self.subTest(change=change):
                self.assertFalse(bench.negative_control_passed({**trial, **change}, 6))

    def test_binary_dump_parser_survives_fragmented_json_and_binary_newlines(self):
        # Construct only the parser state: no Serial object, discovery or ports.
        connection = bench.Connection.__new__(bench.Connection)
        connection.pending = bytearray()
        connection.binary_pending = None
        connection.binary_expected = 0
        connection.condition = threading.Condition()
        connection.events = []
        connection.log_record = lambda *args: None
        header = json.dumps({"event": "dump_begin", "bytes": 48000, "role": "RX"}).encode() + b"\n"
        trailer = b'\n{"event":"dump_end","role":"RX"}\n{"event":"status"}\n'
        wire = header + self.source + trailer
        for start in range(0, len(wire), 137):
            connection._parse(wire[start:start + 137], start + 1)
        self.assertEqual([e["message"]["event"] for e in connection.events],
                         ["dump_begin", "host_dump_binary", "dump_end", "status"])
        self.assertEqual(connection.events[1]["payload"], self.source)
        self.assertFalse(connection.pending)

    def test_pcm_load_waits_for_each_acknowledged_usb_block(self):
        # Exercise host framing with fake writes/events only; no ports exist.
        connection = bench.Connection.__new__(bench.Connection)
        connection.node = {"port": "COM-test"}
        connection.log_record = lambda *args: None
        writes = []
        acknowledged = 0
        connection.cursor = lambda: len(writes)

        def write(block):
            self.assertEqual(sum(map(len, writes)), acknowledged,
                             "Host must await the previous block before writing more PCM")
            writes.append(block)
            return len(block)

        def wait(event_name, after, timeout, predicate):
            nonlocal acknowledged
            self.assertEqual(event_name, "load_block")
            self.assertEqual(after, len(writes) - 1)
            acknowledged = sum(map(len, writes))
            self.assertTrue(predicate({"received": acknowledged}))
            self.assertFalse(predicate({"received": acknowledged - 1}))
            return {"message": {"event": "load_block", "received": acknowledged}}

        connection.serial = SimpleNamespace(write=write)
        connection.wait = wait
        connection.write_pcm(self.source)
        self.assertEqual(b"".join(writes), self.source)
        self.assertEqual(len(writes), 94)
        self.assertTrue(all(len(block) == 512 for block in writes[:-1]))
        self.assertEqual(len(writes[-1]), 384)
        self.assertEqual(acknowledged, 48000)
        with self.assertRaises(RuntimeError):
            connection.write_pcm(self.source, 4096)

    def rf_failure(self):
        return {
            "passed": False,
            "tx_done": {"success": False, "cancelled": False, "attempts": 6},
            "tx_packets": [{"tx_radio_status": 0}] * 6,
            "accounting": {"invalid_logged_data_crc_events": []},
            "sender_serial_upload_comparison": {"byte_exact": True},
            "rx_dump": {"bytes": 48000, "complete": False},
        }

    def test_continuation_rejects_serial_buffer_and_radio_initialization_faults(self):
        failed = self.rf_failure()
        self.assertTrue(bench.can_continue_after_trial(failed))
        for change in ({"error": "serial disconnected"}, {"receiver_dump_error": "CRC mismatch"},
                       {"clock_after_error": "TIME timeout"}, {"cleanup_errors": ["STOP timeout"]},
                       {"tx_packets": [{"tx_radio_status": -1}]},
                       {"tx_packets": [{"tx_radio_status": 0, "radio_status": -2}]},
                       {"sender_serial_upload_comparison": {"byte_exact": False}},
                       {"rx_dump": {"bytes": 48000, "complete": True},
                        "receiver_comparison": {"byte_exact": False}},
                       {"accounting": {"invalid_logged_data_crc_events": [{"index": 5}]}}):
            with self.subTest(change=change):
                self.assertFalse(bench.can_continue_after_trial({**failed, **change}))

    def run_mocked_main(self, folder, trial_callback, extra=(), discovery_error=None,
                        final_stop_error=False):
        wav = folder / "input.wav"
        bench.save_wav(wav, self.source)
        output = folder / "run"
        nodes = [{"port": "COM6", "label": "Heltec-A", "mac_normalized": "8CFD49B5B78C"},
                 {"port": "COM7", "label": "Heltec-B", "mac_normalized": "441BF66F99E4"}]
        connections = []
        hello = self.hello()

        class FakeConnection:
            def __init__(self, node, _folder):
                self.node = node
                self.serial = SimpleNamespace(is_open=False)
                self.commands = []
                connections.append(self)

            def open(self):
                self.serial.is_open = True

            def request(self, command, _event, **_kwargs):
                self.commands.append(command)
                if command == "STOP" and final_stop_error:
                    raise RuntimeError("cleanup STOP disconnected")
                return {"message": {**hello, "mac": self.node["mac_normalized"],
                                    "firmware": "lora-integrity-2-oled",
                                    "oled_ready": True, "oled_layout_ok": True}}

            def close(self):
                self.commands.append("CLOSE")
                self.serial.is_open = False

        report_seen = []

        def report(run_folder, _python):
            recorded = json.loads((run_folder / "summary.json").read_text())
            self.assertTrue(recorded["connections_closed"])
            report_seen.append(recorded)
            return {"returncode": 0}

        with patch.object(bench, "Connection", FakeConnection), \
                patch.object(bench, "discover_nodes", side_effect=discovery_error, return_value=nodes), \
                patch.object(bench, "preflight", return_value={"local_only": True}), \
                patch.object(bench, "run_trial", side_effect=trial_callback), \
                patch.object(bench, "generate_reports", side_effect=report), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = bench.main(["--wav", str(wav), "--output-dir", str(output), *extra])
        return result, json.loads((output / "summary.json").read_text()), connections, report_seen

    def test_ten_trial_sequence_continues_after_clean_rf_failure_and_reports(self):
        observed = []

        def trial(tx, rx, _source, _folder, number, *_args, **kwargs):
            observed.append((tx.node["port"], rx.node["port"], number, kwargs))
            return {"trial": number, **(self.rf_failure() if number == 2 else {"passed": True})}

        with tempfile.TemporaryDirectory() as temporary:
            result, summary, connections, reports = self.run_mocked_main(
                Path(temporary), trial, ["--trials", "10", "--alternate", "--oled-progress",
                                         "--continue-on-failure", "--distance-inches", "24"])
        self.assertEqual(result, 1)
        self.assertEqual(summary["attempted_trials"], 10)
        self.assertEqual(summary["passed_trials"], 9)
        self.assertEqual(summary["not_run_trials"], 0)
        self.assertEqual(summary["distance_inches"], 24)
        self.assertEqual([item[:2] for item in observed], [("COM6", "COM7"), ("COM7", "COM6")] * 5)
        self.assertTrue(all(item[3] == {"oled_progress": True, "total_trials": 10} for item in observed))
        self.assertEqual(len(reports), 1)
        self.assertTrue(all(conn.commands[-2:] == ["STOP", "CLOSE"] for conn in connections))

    def test_critical_failure_aborts_remaining_trials_and_generates_partial_report(self):
        def trial(*args, **kwargs):
            number = args[4]
            return {"trial": number, "passed": number == 1,
                    **({"error": "serial disconnected"} if number == 2 else {})}

        with tempfile.TemporaryDirectory() as temporary:
            result, summary, _, reports = self.run_mocked_main(
                Path(temporary), trial, ["--trials", "10", "--continue-on-failure"])
        self.assertEqual(result, 1)
        self.assertEqual(summary["attempted_trials"], 2)
        self.assertEqual(summary["not_run_trials"], 8)
        self.assertEqual(len(reports), 1)

    def test_interrupt_retains_original_error_and_stops_closes_reports(self):
        def interrupted(*args, **kwargs):
            raise KeyboardInterrupt

        with tempfile.TemporaryDirectory() as temporary:
            result, summary, connections, reports = self.run_mocked_main(
                Path(temporary), interrupted, final_stop_error=True)
        self.assertEqual(result, 130)
        self.assertEqual(summary["error"], "Interrupted by user")
        self.assertEqual(len(summary["final_stop_errors"]), 2)
        self.assertEqual(len(reports), 1)
        self.assertTrue(all(conn.commands[-2:] == ["STOP", "CLOSE"] for conn in connections))

    def test_default_remains_three_alternating_trials(self):
        observed = []
        def trial(*args, **kwargs):
            observed.append((args[0].node["port"], args[1].node["port"]))
            return {"trial": args[4], "passed": True}
        with tempfile.TemporaryDirectory() as temporary:
            result, summary, _, _ = self.run_mocked_main(Path(temporary), trial)
        self.assertEqual(result, 0)
        self.assertEqual(summary["requested_trials"], 3)
        self.assertEqual(observed, [("COM6", "COM7"), ("COM7", "COM6"), ("COM6", "COM7")])

    def test_initialization_failure_still_produces_report_without_opening_ports(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, summary, connections, reports = self.run_mocked_main(
                Path(temporary), lambda *a, **k: self.fail("must not run trial"),
                discovery_error=RuntimeError("unknown USB identity"))
        self.assertEqual(result, 1)
        self.assertEqual(summary["error"], "unknown USB identity")
        self.assertFalse(connections)
        self.assertEqual(len(reports), 1)

    def test_check_only_never_discovers_or_opens_ports_or_creates_output(self):
        with patch.object(bench, "preflight", return_value={"local_only": True}), \
                patch.object(bench, "discover_nodes", side_effect=AssertionError("no device enumeration")), \
                patch.object(bench, "Connection", side_effect=AssertionError("no port")), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(bench.main(["--wav", "unused.wav", "--check-only"]), 0)

    def test_launcher_requires_explicit_start_before_invoking_python(self):
        launcher = TOOLS / "run_lora_consistency.ps1"
        powershell = os.environ.get("LORA_TEST_POWERSHELL") or shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            self.skipTest("PowerShell is required to exercise the Windows launcher gate")
        completed = subprocess.run([str(powershell), "-NoProfile", "-File", str(launcher),
                                    "-RunnerPython", "C:/does-not-exist/never-run.exe"],
                                   capture_output=True, text=True, timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("No hardware actions performed", completed.stdout)

    def test_oled_counter_follows_both_stops_and_precedes_roles(self):
        commands = []
        hello = self.hello()
        class LocalConnection:
            def __init__(self, port):
                self.node = {"port": port}
                self.hello = hello
            def cursor(self):
                return 0
            def request(self, command, event, **kwargs):
                commands.append((self.node["port"], command))
                if command.startswith("ROLE"):
                    raise RuntimeError("Intentional test stop before any loading/radio")
                message = {"event": event, "current": 1, "total": 10}
                if "predicate" in kwargs:
                    assert kwargs["predicate"](message)
                return {"message": message}
            def messages_since(self, *args):
                return []
        with tempfile.TemporaryDirectory() as temporary:
            trial = bench.run_trial(LocalConnection("COM6"), LocalConnection("COM7"),
                                    self.source, Path(temporary), 1, 123, 1,
                                    oled_progress=True, total_trials=10)
        self.assertEqual(commands[:5], [("COM6", "STOP"), ("COM7", "STOP"),
                                        ("COM6", "TEST 1 10"), ("COM7", "TEST 1 10"),
                                        ("COM6", "ROLE TX")])
        self.assertEqual(set(trial["oled_test"]), {"COM6", "COM7"})
        self.assertEqual(trial["failure_class"], "critical_bench_error")

    def test_transfer_timeout_stops_without_post_transfer_clock_requests(self):
        hello = self.hello()
        source_crc = bench.crc32_hex(self.source)
        commands = []
        class LocalConnection:
            def __init__(self, port):
                self.node = {"port": port}
                self.hello = hello
            def cursor(self):
                return 0
            def send(self, command):
                commands.append((self.node["port"], command))
            def request(self, command, event, **kwargs):
                commands.append((self.node["port"], command))
                return {"message": {"event": event, "role": command.split()[-1], "id": 123}}
            def wait(self, event, *args, **kwargs):
                if event == "tx_done":
                    raise RuntimeError("simulated transfer timeout")
                return {"message": {"event": event, "bytes": 48000, "block_bytes": 512,
                                    "crc32": source_crc}}
            def write_pcm(self, *args):
                pass
            def messages_since(self, *args):
                return []
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(bench, "calibrate_clock", return_value={"selected_min_rtt": {}}) as clock, \
                patch.object(bench, "dump_buffer", return_value=(self.source, {"bytes": 48000, "complete": False})):
            trial = bench.run_trial(LocalConnection("COM6"), LocalConnection("COM7"),
                                    self.source, Path(temporary), 1, 123, 1)
        self.assertEqual(clock.call_count, 2)  # Pre-transfer only, one call per board.
        self.assertNotIn("clock_after", trial)
        tx_position = commands.index(("COM6", "TX 123"))
        self.assertEqual(commands[tx_position + 1:tx_position + 5],
                         [("COM6", "STOP"), ("COM6", "STATUS"),
                          ("COM7", "STOP"), ("COM7", "STATUS")])
        self.assertIn("transfer timeout", trial["error"])


if __name__ == "__main__":
    unittest.main()
