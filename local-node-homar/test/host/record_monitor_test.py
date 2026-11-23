import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import record_monitor as monitor


class FakeDevice:
    port = "TEST-PORT"
    payload = (bytes(range(256)) * 188)[:48000]

    def __init__(self, *, fail_record=False, corrupt=False, playback_reply=None):
        self.pending = io.BytesIO()
        self.commands = []
        self.fail_record = fail_record
        self.corrupt = corrupt
        self.playback_reply = (b"[STATE] PLAYBACK\n[AUDIO] Direct PCM playback...\n"
                               b"[AUDIO] Direct playback complete (digital path)\n[STATE] IDLE\n"
                               if playback_reply is None else playback_reply)
        self.playback_requested = False
        self.is_open = False

    def open(self):
        self.is_open = True

    def close(self):
        self.is_open = False

    def reset_input_buffer(self):
        self.pending = io.BytesIO()

    def write(self, data):
        self.commands.append(data)
        if data in (b"m\n", b"r\n"):
            self.playback_requested = data == b"r\n"
            if self.fail_record:
                response = b"[AUDIO] Recording failed\r\n"
            else:
                response = (b"[AUDIO] Speak now. Recording for 3 seconds...\r\n"
                            b"[MIC] samples=24000 min=-32768 max=32767 mean=12.3 AC_RMS=99.1 zero=12 clipped=7\n"
                            b"[MIC] First raw 32-bit slots: 00000001 fffffffe\n"
                            b"[MIC RAW] zero_words=9 all_one_words=11 longest_identical_run=4 / 24000\n"
                            b"[AUDIO] Recording complete in 3037 ms\n")
                response += self.playback_reply if self.playback_requested else b"[STATE] IDLE\n"
        elif data == b"d\n":
            if self.playback_requested:
                # Export must wait for both playback completion and the IDLE line.
                assert not self.pending.read(), "Export requested before playback finished"
            response = (f"[PCM_BEGIN] bytes=48000 rate=8000 bits=16 channels=1 crc32={zlib.crc32(self.payload):08x}\n".encode()
                        + (bytes([self.payload[0] ^ 1]) + self.payload[1:] if self.corrupt else self.payload)
                        + b"\n[PCM_END]\r\n")
        else:
            raise AssertionError(f"Unexpected device command {data!r}")
        self.pending = io.BytesIO(self.pending.read() + response)
        return len(data)

    def readline(self, count):
        return self.pending.readline(count)

    def read(self, count):
        return self.pending.read(min(13, count))


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "captures"
        self.output = []

    def capture(self, device=None, label="normal voice", record=True, playback=False):
        return monitor.capture_once(device or FakeDevice(), self.root, label,
                                    record=record, playback=playback, report=self.output.append)

    def test_record_export_saves_original_pcm_and_firmware_diagnostics(self):
        device = FakeDevice()
        stem, metrics = self.capture(device)
        self.assertEqual(device.commands, [b"m\n", b"d\n"])
        with wave.open(str(stem.with_suffix(".wav")), "rb") as recording:
            self.assertEqual((recording.getnchannels(), recording.getsampwidth(), recording.getframerate(),
                              recording.getnframes()), (1, 2, 8000, 24000))
            self.assertEqual(recording.readframes(24000), device.payload)
        saved = json.loads(stem.with_suffix(".json").read_text())
        self.assertEqual(saved["crc32"], f"{zlib.crc32(device.payload):08x}")
        self.assertEqual(saved["capture"]["label"], "normal voice")
        self.assertEqual(saved["capture"]["firmware"]["pcm"]["clipped_samples"], 7)
        self.assertEqual(saved["capture"]["firmware"]["raw"]["all_one_words"], 11)
        self.assertEqual(metrics["samples"], 24000)
        self.assertIn("[MIC RAW]", stem.with_suffix(".serial.txt").read_text())
        self.assertTrue(stem.with_suffix(".svg").is_file())

    def test_export_existing_does_not_record_and_has_no_stale_firmware_metrics(self):
        device = FakeDevice()
        stem, metrics = self.capture(device, record=False)
        self.assertEqual(device.commands, [b"d\n"])
        self.assertEqual(metrics["capture"]["mode"], "export_existing")
        self.assertFalse(metrics["capture"]["recording_time_known"])
        self.assertNotIn("pcm", metrics["capture"]["firmware"])

    def test_direct_playback_exports_identical_pcm_after_completion_and_idle(self):
        device = FakeDevice()
        stem, metrics = self.capture(device, label="playback check", playback=True)
        self.assertEqual(device.commands, [b"r\n", b"d\n"])
        with wave.open(str(stem.with_suffix(".wav")), "rb") as recording:
            self.assertEqual(recording.readframes(24000), device.payload)
        self.assertEqual(metrics["capture"]["mode"], "new_recording_direct_playback")
        self.assertEqual(metrics["capture"]["playback_status"], "digital_path_complete")
        self.assertIn("pcm", metrics["capture"]["firmware"])
        self.assertIn("[AUDIO] Direct playback complete", stem.with_suffix(".serial.txt").read_text())
        finished = self.output.index("[AUDIO] Direct playback complete (digital path)")
        saving = self.output.index("Saving recording from ESP32... (about five seconds)")
        self.assertLess(finished, saving)

    def test_direct_record_failure_does_not_export_stale_audio(self):
        device = FakeDevice(fail_record=True)
        with self.assertRaisesRegex(RuntimeError, "recording failed"):
            self.capture(device, playback=True)
        self.assertEqual(device.commands, [b"r\n"])
        self.assertEqual(list(self.root.rglob("*.wav")), [])

    def test_playback_failure_does_not_claim_success_or_export(self):
        device = FakeDevice(playback_reply=b"[AUDIO] Direct playback FAILED\n[STATE] IDLE\n")
        with self.assertRaisesRegex(RuntimeError, "Speaker playback failed"):
            self.capture(device, playback=True)
        self.assertEqual(device.commands, [b"r\n"])
        self.assertEqual(list(self.root.rglob("*.wav")), [])
        error_file, = self.root.rglob("error.json")
        self.assertIn("Speaker playback failed", json.loads(error_file.read_text())["error"])
        self.assertFalse(any(line.startswith("SAVED:") for line in self.output))

    def test_playback_idle_without_completion_is_not_success(self):
        device = FakeDevice(playback_reply=b"[STATE] IDLE\n")
        with self.assertRaisesRegex(RuntimeError, "without confirming direct playback"):
            self.capture(device, playback=True)
        self.assertEqual(device.commands, [b"r\n"])

    def test_playback_timeout_or_missing_idle_never_exports(self):
        for reply in (b"", b"[AUDIO] Direct playback complete (digital path)\n"):
            with self.subTest(reply=reply):
                device = FakeDevice(playback_reply=reply)
                with patch.object(monitor.time, "monotonic", side_effect=range(100)):
                    with self.assertRaisesRegex(RuntimeError, "Playback did not complete"):
                        self.capture(device, playback=True)
                self.assertEqual(device.commands, [b"r\n"])
        self.assertEqual(list(self.root.rglob("*.wav")), [])

    def test_direct_playback_still_checks_export_crc(self):
        with self.assertRaisesRegex(RuntimeError, "CRC mismatch"):
            self.capture(FakeDevice(corrupt=True), playback=True)
        self.assertEqual(list(self.root.rglob("*.wav")), [])

    def test_console_r_records_plays_saves_and_releases_port_on_quit(self):
        device = FakeDevice()
        serial_stub = SimpleNamespace(Serial=lambda **kwargs: device, SerialException=OSError)
        with patch.dict(sys.modules, {"serial": serial_stub}), \
                patch("builtins.input", side_effect=["r playback_check", "q"]), \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            result = monitor.main(["--port", "TEST-PORT", "--folder", str(self.root)])
        self.assertEqual(result, 0)
        self.assertEqual(device.commands, [b"r\n", b"d\n"])
        self.assertEqual(len(list(self.root.rglob("*.wav"))), 1)
        self.assertIn("SAVED:", output.getvalue())
        self.assertFalse(device.is_open)
        self.assertFalse(device.dtr)
        self.assertFalse(device.rts)

    def test_repeated_labels_preserve_previous_recording(self):
        first, _ = self.capture()
        original = first.with_suffix(".wav").read_bytes()
        second, _ = self.capture()
        self.assertNotEqual(first, second)
        self.assertEqual(first.with_suffix(".wav").read_bytes(), original)

    def test_collision_and_path_like_labels_stay_under_root(self):
        with patch.object(monitor, "datetime") as clock:
            clock.now.return_value.strftime.return_value = "same-time"
            first = monitor.new_capture_folder(self.root, "../../outside\\CON: ?")
            second = monitor.new_capture_folder(self.root, "../../outside\\CON: ?")
        self.assertNotEqual(first, second)
        self.assertEqual(first.parent, self.root)
        self.assertEqual(second.parent, self.root)

    def test_failed_capture_never_exports_old_audio(self):
        device = FakeDevice(fail_record=True)
        with self.assertRaisesRegex(RuntimeError, "recording failed"):
            self.capture(device)
        self.assertEqual(device.commands, [b"m\n"])
        self.assertEqual(list(self.root.rglob("*.wav")), [])
        self.assertEqual(len(list(self.root.rglob("error.json"))), 1)

    def test_crc_failure_has_log_and_error_but_no_wav_or_saved_message(self):
        with self.assertRaisesRegex(RuntimeError, "CRC mismatch"):
            self.capture(FakeDevice(corrupt=True))
        self.assertEqual(list(self.root.rglob("*.wav")), [])
        self.assertEqual(len(list(self.root.rglob("recording.serial.txt"))), 1)
        self.assertEqual(len(list(self.root.rglob("error.json"))), 1)
        self.assertFalse(any(line.startswith("SAVED:") for line in self.output))

    def test_timeout_never_requests_export(self):
        device = FakeDevice()
        with patch.object(monitor.time, "monotonic", side_effect=range(100)):
            with self.assertRaisesRegex(RuntimeError, "did not complete"):
                monitor.wait_for_recording(device, bytearray(), self.output.append)
        self.assertEqual(device.commands, [])

    def test_commands(self):
        self.assertEqual(monitor.parse_command("m"), ("m", "unlabelled"))
        self.assertEqual(monitor.parse_command(" M whisper 20cm "), ("m", "whisper 20cm"))
        self.assertEqual(monitor.parse_command("d retry"), ("d", "retry"))
        self.assertEqual(monitor.parse_command(" R playback_check "), ("r", "playback_check"))
        self.assertEqual(monitor.parse_command("r"), ("r", "unlabelled"))
        self.assertEqual(monitor.parse_command(""), (None, ""))
        with self.assertRaises(ValueError):
            monitor.parse_command("t")
        with self.assertRaises(ValueError):
            monitor.parse_command("q extra")


if __name__ == "__main__":
    unittest.main()
