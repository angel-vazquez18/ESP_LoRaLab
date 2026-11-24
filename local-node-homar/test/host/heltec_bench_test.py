"""Regressions for the dual-Heltec checker; never opens serial hardware."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import verify_heltec_bench as bench


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeConnection:
    def __init__(self, port, mac, batches):
        self.node = {"port": port, "mac_normalized": mac, "label": "Fake Heltec"}
        self.batches = batches
        self.pending = []
        self.commands = []

    def send(self, command, stage):
        self.commands.append(command)
        self.pending = [list(batch) for batch in self.batches]
        return bench.utc_now()

    def read_lines(self):
        return self.pending.pop(0) if self.pending else []


def diagnostics(mac, speaker_ready):
    formatted_mac = ":".join(mac[index:index + 2] for index in range(0, 12, 2))
    return [
        "[SYSTEM]",
        "[BOARD] MAC=" + formatted_mac,
        f"[I2S] MIC requested=1 ready=1, SPK requested=1 ready={speaker_ready}",
        "[I2S] MIC BCLK=4 WS=6 SD=38, left 32-bit",
        "[I2S] SPK BCLK=40 LRC=41 DIN=47, stereo",
        f"[AMP] SD/MODE=GPIO48; ready={speaker_ready}",
        bench.DIAGNOSTICS_END,
    ]


class HeltecBenchTests(unittest.TestCase):
    def test_probe_error_keeps_both_measurement_reports(self):
        first = FakeConnection("COM6", "8CFD49B5B78C", [[
            "[PINS] BEGIN", "[PINS] SD GPIO48=1", "[PINS] END",
        ]])
        second = FakeConnection("COM7", "441BF66F99E4", [[
            "[PINS] BEGIN", "[PINS] ERROR: counter unavailable", "[PINS] END",
        ]])
        summary = {"stages": []}
        with self.assertRaisesRegex(RuntimeError, "counter unavailable"):
            self.run_stage([first, second], "v", summary)
        states = summary["stages"][0]["ports"]
        self.assertTrue(all(state["finished"] for state in states.values()))
        self.assertTrue(states["COM6"]["passed"])
        self.assertFalse(states["COM7"]["passed"])
        self.assertIn("[PINS] SD GPIO48=1", states["COM6"]["diagnostics"])

    def setUp(self):
        # This guard also protects future changes to Connection.__init__.
        self.serial_open = patch.object(
            bench.serial.Serial, "open",
            side_effect=AssertionError("Tests must never open serial hardware"),
        )
        self.serial_open.start()
        self.addCleanup(self.serial_open.stop)

    def run_stage(self, connections, command, summary):
        clock = FakeClock()
        with patch.object(bench, "drain"), \
                patch.object(bench.time, "monotonic", clock.monotonic), \
                patch.object(bench.time, "sleep", clock.sleep), \
                redirect_stdout(io.StringIO()):
            bench.run_stage(connections, connections, command, "regression", summary, timeout=0.05)

    def test_logs_are_real_files_not_windows_com_devices(self):
        # Path.open is guarded before performing filesystem I/O: a regression
        # to COM6.log must fail here instead of accidentally touching COM6.
        real_path_open = Path.open

        def open_safe_log(path, *args, **kwargs):
            self.assertRegex(path.name, r"^serial-[A-Za-z0-9_-]+\.log$")
            return real_path_open(path, *args, **kwargs)

        with tempfile.TemporaryDirectory(prefix="heltec-bench-test-") as temp:
            folder = Path(temp)
            for port in ("COM6", "COM7", "../COM9", r"\\.\COM10"):
                with self.subTest(port=port):
                    node = {"port": port, "label": "Fake Heltec"}
                    with patch.object(Path, "open", new=open_safe_log):
                        connection = bench.Connection(node, folder)
                    try:
                        self.assertFalse(connection.port.is_open)
                        connection.note("disk log regression marker")
                    finally:
                        connection.close()
                    log_path = folder / node["log_file"]
                    self.assertEqual(log_path.parent, folder)
                    self.assertTrue(log_path.is_file())
                    self.assertIn("disk log regression marker", log_path.read_text(encoding="utf-8"))
            self.assertTrue((folder / "serial-COM6.log").is_file())
            self.assertTrue((folder / "serial-COM7.log").is_file())

    def test_both_diagnostic_responses_survive_first_board_readiness_failure(self):
        failed_lines = diagnostics("441BF66F99E4", 0)
        healthy_lines = diagnostics("8CFD49B5B78C", 1)
        failed = FakeConnection("COM7", "441BF66F99E4", [failed_lines])
        # The healthy board responds in two reads, after COM7 has already
        # failed. The checker must continue polling rather than exit early.
        healthy = FakeConnection("COM6", "8CFD49B5B78C", [healthy_lines[:1], healthy_lines[1:]])
        summary = {"stages": []}
        with self.assertRaisesRegex(RuntimeError, "COM7: missing expected diagnostic"):
            self.run_stage([failed, healthy], "i", summary)
        ports = summary["stages"][0]["ports"]
        self.assertTrue(ports["COM7"]["finished"])
        self.assertFalse(ports["COM7"]["passed"])
        self.assertEqual(ports["COM7"]["diagnostics"], failed_lines)
        self.assertTrue(ports["COM6"]["finished"])
        self.assertTrue(ports["COM6"]["passed"])
        self.assertEqual(ports["COM6"]["diagnostics"], healthy_lines)
        self.assertEqual(failed.commands, ["i"])
        self.assertEqual(healthy.commands, ["i"])

    def test_old_tone_completion_without_new_start_is_rejected(self):
        stale = FakeConnection("COM6", "8CFD49B5B78C", [[bench.TONE_COMPLETE, "[STATE] IDLE"]])
        summary = {"stages": []}
        with self.assertRaisesRegex(RuntimeError, "timed out waiting for: COM6"):
            self.run_stage([stale], "s", summary)
        state = summary["stages"][0]["ports"]["COM6"]
        self.assertFalse(state["started"])
        self.assertFalse(state["transfer_complete"])
        self.assertFalse(state["passed"])

    def test_paired_tones_require_both_transfers_and_return_to_idle(self):
        first = FakeConnection("COM6", "8CFD49B5B78C", [
            [bench.TONE_START, bench.TONE_COMPLETE, "[STATE] IDLE"],
        ])
        second = FakeConnection("COM7", "441BF66F99E4", [
            [bench.TONE_START], [bench.TONE_COMPLETE], ["[STATE] IDLE"],
        ])
        summary = {"stages": []}
        self.run_stage([first, second], "s", summary)
        self.assertTrue(all(state["passed"] for state in summary["stages"][0]["ports"].values()))
        self.assertEqual(first.commands, ["s"])
        self.assertEqual(second.commands, ["s"])

    def test_cli_preserves_short_tone_and_allows_time_for_long_tones(self):
        class MainConnection:
            def __init__(self, node, folder):
                self.node = node
                self.port = SimpleNamespace(is_open=False)

            def open(self):
                self.port.is_open = True

            def close(self):
                self.port.is_open = False

        nodes = [
            {"port": port, "label": "Fake", "usb_serial": "Fake", "port_matches_assignment": True}
            for port in ("COM6", "COM7")
        ]
        with tempfile.TemporaryDirectory(prefix="heltec-tone-cli-") as temp:
            for seconds, command in ((1, "s"), (15, "b")):
                with self.subTest(seconds=seconds):
                    folder = Path(temp) / str(seconds)
                    args = ["--output-dir", str(folder)]
                    if seconds == 15:
                        args += ["--tone-seconds", "15"]
                    with patch.object(bench, "discover_nodes", return_value=nodes), \
                            patch.object(bench, "Connection", MainConnection), \
                            patch.object(bench, "drain"), \
                            patch.object(bench, "run_stage") as stages, \
                            redirect_stdout(io.StringIO()):
                        self.assertEqual(bench.main(args), 0)
                    calls = stages.call_args_list
                    self.assertEqual([call.args[2] for call in calls], ["i", command, command, command])
                    self.assertNotIn("timeout", calls[0].kwargs)
                    self.assertTrue(all(call.kwargs["timeout"] == seconds + 8 for call in calls[1:]))
                    result = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
                    self.assertEqual(result["tone_seconds"], seconds)


if __name__ == "__main__":
    unittest.main()
