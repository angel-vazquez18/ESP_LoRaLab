"""Offline report tests: missing/corrupt evidence must never become a pass."""
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
import wave
import zlib

SPEC = importlib.util.spec_from_file_location("consistency_report", Path(__file__).resolve().parents[2] / "tools/create_lora_consistency_pdf.py")
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)


def save_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def wav(path, pcm):
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(8000); f.writeframes(pcm)


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.run = Path(self.temp.name)
        self.source = bytes(range(240)) * 200
        wav(self.run / "source.wav", self.source)
        self.summary = {"requested_trials": 10, "requested_ports": ["COM6", "COM7"], "alternate": True,
                        "passed": True, "connections_closed": True, "trials": []}

    def tearDown(self):
        self.temp.cleanup()

    def add_trial(self, index=1):
        directory = f"trial-{index:02d}-COM6-to-COM7"
        folder = self.run / directory
        folder.mkdir()
        wav(folder / "sender-before-radio.wav", self.source)
        wav(folder / "received.wav", self.source)
        tx, rx = [], []
        for i in range(200):
            frame = b"\xf9\x01" + struct.pack("<HBBB", 456, i, 200, 240) + self.source[i*240:(i+1)*240]
            crc = f"{zlib.crc32(frame):08x}"
            tx.append({"id":456,"index":i,"attempt":1,"acked":True,"tx_radio_status":0,"data_crc32":crc})
            rx.append({"id":456,"index":i,"duplicate":False,"ack_status":0,"data_crc32":crc})
        trial = {"trial":index,"directory":directory,"id":456,"tx_port":"COM6","rx_port":"COM7",
                 "passed":True,"tx_packets":tx,"rx_packets":rx,
                 "tx_done":{"success":True,"acked_chunks":200},"rx_complete":{"received_chunks":200},
                 "rx_dump":{"complete":True},"sender_local_transfer_us":28000000}
        self.summary["trials"].append(trial)
        return trial, folder

    def collect(self):
        save_json(self.run / "summary.json", self.summary)
        return report.collect(self.run)

    def test_zero_trials_and_missing_source_are_not_success(self):
        (self.run / "source.wav").unlink()
        result = self.collect()
        self.assertEqual(result["counts"], {"requested":10,"attempted":0,"passed":0,"failed":0,"incomplete":0,"not_run":10})
        self.assertFalse(result["all_requested_trials_verified"])
        self.assertEqual(result["per_direction"]["COM7 to COM6"]["not_run"],5)

    def test_three_valid_trials_are_not_ten_passes(self):
        for i in range(1,4): self.add_trial(i)
        result = self.collect()
        self.assertEqual(result["counts"]["passed"],3)
        self.assertEqual(result["counts"]["not_run"],7)
        self.assertFalse(result["all_requested_trials_verified"])
        self.assertEqual(result["trials"][0]["packets"]["checked_crc_events"],400)

    def test_missing_receiver_file_cannot_trust_saved_pass(self):
        _,folder = self.add_trial()
        (folder / "received.wav").unlink()
        result = self.collect()
        self.assertEqual(result["counts"]["passed"],0)
        self.assertEqual(result["counts"]["incomplete"],1)

    def test_changed_pcm_and_source_derived_crc_detect_corruption(self):
        trial,folder = self.add_trial()
        damaged = bytearray(self.source); damaged[100] ^= 1
        wav(folder / "received.wav", damaged)
        trial["rx_packets"][12]["data_crc32"] = "00000000"
        result = self.collect()
        self.assertEqual(result["trials"][0]["status"],"FAIL")
        self.assertEqual(len(result["trials"][0]["packets"]["invalid_crc_events"]),1)

    def test_duplicate_index_cannot_substitute_missing_chunk(self):
        trial,_ = self.add_trial()
        trial["rx_packets"][-1] = dict(trial["rx_packets"][-2])
        self.assertEqual(self.collect()["counts"]["passed"],0)

    def test_partial_orphan_failure_recovered_without_fabricated_timing(self):
        folder = self.run / "trial-01-COM6-to-COM7"; folder.mkdir()
        save_json(folder / "summary.json", {"trial":1,"tx_port":"COM6","rx_port":"COM7","passed":False,"error":"interrupted"})
        result = self.collect()
        self.assertEqual(result["counts"]["failed"],1)
        self.assertEqual(result["counts"]["not_run"],9)
        self.assertIsNone(result["trials"][0]["timing"]["sender_local_seconds"])

    def test_unstable_clock_discards_latency_estimates(self):
        trial,_ = self.add_trial()
        trial["clock_alignment"] = {"COM6":{"stable":True},"COM7":{"stable":False}}
        trial["packet_timing"] = [{"first_attempt_to_accepted_rx":{"lower_us":10,"upper_us":20,"midpoint_us":15}}]
        self.assertIsNone(self.collect()["trials"][0]["timing"]["packet_midpoint_median_ms"])

    def test_ten_verified_trials_and_none_distance(self):
        for i in range(1,11): self.add_trial(i)
        self.summary["distance_inches"] = None
        result = self.collect()
        self.assertTrue(result["all_requested_trials_verified"])
        self.assertEqual(result["counts"]["passed"],10)
        self.assertEqual(result["distance_inches"],24)

    def test_physical_capacity_uses_reported_values_without_board_defaults(self):
        self.summary["nodes"] = [{"port":"COM6","hello":{"psram_total_bytes":2097152}},
                                 {"port":"COM7","hello":{"psram_total_bytes":2097152,"flash_total_bytes":16777216}}]
        result = self.collect()
        self.assertIsNone(result["physical_capacity"][0]["flash_total_bytes"])
        self.assertEqual(result["physical_capacity"][0]["psram_total_bytes"],2097152)
        self.assertEqual(result["physical_capacity"][1]["flash_total_bytes"],16777216)
        self.assertIn("volatile PSRAM", result["audio_storage"])


if __name__ == "__main__":
    unittest.main()
