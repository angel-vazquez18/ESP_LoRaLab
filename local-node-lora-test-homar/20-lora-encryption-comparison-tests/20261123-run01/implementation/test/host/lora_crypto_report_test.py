"""Offline report evidence tests. Generated fixtures are never hardware results."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import wave
import zlib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import create_lora_crypto_pdf as report


def wav(path, pcm):
    with wave.open(str(path), "wb") as f:
        f.setparams((1, 2, 8000, 24000, "NONE", "not compressed"))
        f.writeframes(pcm)


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def fixture(directory, count=20):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    directory.mkdir(parents=True, exist_ok=True)
    pcm = bytes(range(256)) * 187 + bytes(range(128))
    assert len(pcm) == 48000
    wav(directory / "source.wav", pcm)
    hello = {"firmware": report.FIRMWARE, "crypto_schema": 1, "timing_schema": 1,
             "data_airtime_us": 98624, "ack_airtime_us": 11584, "metadata_airtime_us": 23040,
             "flash_total_bytes": 16777216, "psram_total_bytes": 2097152,
             "mac": "00:00:00:00:00:00"}
    checks = {k: True for k in ("passed", "known_answer_passed", "wrong_key_rejected", "wrong_tag_rejected", "changed_ciphertext_rejected")}
    root = {"validation_fixture": True, "started_at": "2026-01-01T00:00:00+00:00",
            "finished_at": "2026-01-01T00:20:00+00:00", "distance_inches": 24,
            "nodes": [{"port": port, "hello": copy.deepcopy(hello)} for port in ("COM6", "COM7")],
            "crypto_selftests": {port: checks.copy() for port in ("COM6", "COM7")},
            "connections_closed": True, "both_connections_open_together": True, "trials": []}
    for n in range(1, count + 1):
        mode = "PLAIN" if n <= 10 else "GCM"
        folder = directory / f"trial-{n:02d}"
        folder.mkdir()
        wav(folder / "sender-before-radio.wav", pcm)
        wav(folder / "received.wav", pcm)
        t = {"trial": n, "id": n, "mode": mode, "directory": folder.name,
             "tx_port": "COM6" if n % 2 else "COM7", "rx_port": "COM7" if n % 2 else "COM6",
             "tx_packets": [], "rx_packets": [], "tx_metadata": [], "rx_metadata": [],
             "rx_errors": [], "encrypted_events": [], "decrypted_events": [],
             "usb_source_load_us": 335000, "usb_receiver_export_us": 98000,
             "tx_done": {"mode": mode, "success": True, "acked_chunks": 200, "start_us": 1000000,
                         "end_us": 30000000 + (100000 if mode == "GCM" else 0), "radio_start_us": 1002000, "encryption_us": 0,
                         "chunking_count": 200, "chunking_total_us": 118000},
             "rx_complete": {"mode": mode, "received_chunks": 200, "first_rx_us": 1100000,
                             "last_rx_us": 29900000, "first_transport_rx_us": 1000000,
                             "message_ready_us": 29900100, "decryption_us": 0,
                             "dechunking_count": 200, "dechunking_total_us": 72000},
             "rx_dump": {"complete": True}, "encrypted": None, "decrypted": None}
        for role in ("tx", "rx"):
            t[f"{role}_role"] = {"allocation_requested_bytes": 48000 if role == "tx" else 48036,
                "allocation_actual_bytes": 48116, "crypto_buffer_requested_bytes": 48000 if mode == "GCM" else 0,
                "crypto_buffer_actual_bytes": 48116 if mode == "GCM" else 0,
                "psram_before_bytes": 2093472, "psram_free_bytes": 2093472 - 48132 * (2 if mode == "GCM" else 1),
                "packet_scratch_bytes": 767, "crypto_context_bytes": 392, "crypto_key_bytes": 16,
                "crypto_metadata_bytes": 40, "crypto_library_heap_delta_bytes": 32,
                "internal_heap_free_bytes": 331000, "key_setup_us": 40}
        wire = pcm
        if mode == "GCM":
            nonce = n.to_bytes(12, "big")
            aad = struct.pack("<BBHI", 0xfb, 1, n, 48000)
            sealed = AESGCM(bytes(16)).encrypt(nonce, pcm, aad)
            wire, tag = sealed[:-16], sealed[-16:]
            prefix = aad + nonce + tag
            metadata = prefix + struct.pack("<I", zlib.crc32(prefix))
            for side in ("tx", "rx"):
                (folder / f"{side}-ciphertext.bin").write_bytes(wire)
            t["encrypted"] = {"id": n, "encryption_us": 1200, "nonce_hex": nonce.hex(), "tag_hex": tag.hex(), "metadata_hex": metadata.hex()}
            t["decrypted"] = {"id": n, "decryption_us": 1400, "authenticated": True, "message_ready_us": 29901400}
            t["encrypted_events"] = [t["encrypted"]]
            t["decrypted_events"] = [t["decrypted"]]
            t["tx_done"]["encryption_us"] = 1200
            t["rx_complete"].update(decryption_us=1400, authenticated=True, message_ready_us=29901400)
            t["crypto_verification"] = {"valid": True, "host_expected_ciphertext_sha256": hashlib.sha256(wire).hexdigest(),
                "host_expected_metadata_hex": metadata.hex(), "tx_ciphertext_exact": True, "rx_ciphertext_exact": True,
                "ciphertext_differs_from_pcm": True, "receiver_authenticated": True}
            common = {"id": n, "metadata_hex": metadata.hex(), "metadata_crc32": f"{zlib.crc32(prefix):08x}"}
            t["tx_metadata"] = [{**common, "attempt": 1, "tx_radio_status": 0, "acked": True}]
            t["rx_metadata"] = [{**common, "duplicate": False, "ack_status": 0}]
        for index in range(200):
            frame = struct.pack("<BBHBBB", 0xf9, 1, n, index, 200, 240) + wire[index * 240:(index + 1) * 240]
            crc = f"{zlib.crc32(frame):08x}"
            t["tx_packets"].append({"id": n, "index": index, "attempt": 1, "data_crc32": crc,
                                    "chunking_us": 590, "acked": True, "tx_radio_status": 0, "ack_us": 1100000 + index * 140000})
            t["rx_packets"].append({"id": n, "index": index, "duplicate": False, "data_crc32": crc,
                                    "dechunking_us": 360, "ack_status": 0})
        root["trials"].append(t)
    write_json(directory / "summary.json", root)
    return root


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.path = Path(self.temp.name)
        self.root = fixture(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        write_json(self.path / "summary.json", self.root)

    def test_valid_fixture_checks_both_modes_and_units(self):
        result = report.collect(self.path)
        self.assertTrue(result["all_twenty_verified"])
        self.assertTrue(result["fixture"])
        self.assertEqual(result["groups"]["PLAIN"]["timing"]["encryption_ms"]["mean"], 0)
        self.assertEqual(result["groups"]["GCM"]["timing"]["encryption_ms"]["mean"], 1.2)
        self.assertEqual(result["groups"]["GCM"]["timing"]["dechunking_ms"]["mean"], 72)
        self.assertEqual(result["groups"]["GCM"]["wire_payload_bytes"]["mean"], 53054)
        self.assertEqual(result["groups"]["GCM"]["memory"]["RX"]["total_requested_bytes"]["mean"], 96036)
        self.assertEqual(result["groups"]["GCM"]["memory"]["TX"]["total_actual_bytes"]["mean"], 96232)

    def test_changed_ciphertext_fails_even_when_saved_flags_claim_pass(self):
        p = self.path / "trial-11/rx-ciphertext.bin"
        data = bytearray(p.read_bytes()); data[0] ^= 1; p.write_bytes(data)
        result = report.collect(self.path)
        self.assertFalse(result["all_twenty_verified"])
        self.assertEqual(result["groups"]["GCM"]["passed"], 9)

    def test_changed_plaintext_fails(self):
        p = self.path / "trial-01/received.wav"
        data = bytearray(p.read_bytes()); data[-1] ^= 1; p.write_bytes(data)
        self.assertFalse(report.collect(self.path)["all_twenty_verified"])

    def test_missing_processing_not_zero_or_included_in_mean(self):
        del self.root["trials"][10]["rx_packets"][0]["dechunking_us"]
        self.save()
        result = report.collect(self.path)
        self.assertFalse(result["all_twenty_verified"])
        self.assertEqual(result["groups"]["GCM"]["timing"]["dechunking_ms"]["n"], 9)

    def test_metadata_must_match_and_arrive(self):
        self.root["trials"][10]["rx_metadata"] = []
        self.save()
        self.assertFalse(report.collect(self.path)["all_twenty_verified"])

    def test_authentication_failure_is_not_a_pass(self):
        self.root["trials"][10]["decrypted"]["authenticated"] = False
        self.save()
        self.assertFalse(report.collect(self.path)["all_twenty_verified"])

    def test_reused_crypto_operation_is_not_counted_once(self):
        self.root["trials"][10]["encrypted_events"].append(copy.deepcopy(self.root["trials"][10]["encrypted"]))
        self.save()
        self.assertFalse(report.collect(self.path)["all_twenty_verified"])

    def test_incomplete_run_never_becomes_twenty_passes(self):
        self.root["trials"] = self.root["trials"][:2]
        self.save()
        result = report.collect(self.path)
        self.assertFalse(result["all_twenty_verified"])
        self.assertEqual(result["groups"]["GCM"]["timing"]["encryption_ms"]["n"], 0)

    def test_wrong_selftest_key_rejection_blocks_complete_validation(self):
        self.root["crypto_selftests"]["COM6"]["wrong_key_rejected"] = False
        self.save()
        self.assertFalse(report.collect(self.path)["all_twenty_verified"])

    def test_clock_boundary_reversal_is_not_averaged(self):
        self.root["trials"][0]["tx_done"]["radio_start_us"] = 900000
        self.save()
        result = report.collect(self.path)
        self.assertFalse(result["all_twenty_verified"])
        self.assertEqual(result["groups"]["PLAIN"]["timing"]["sender_s"]["n"], 9)

    def test_repeated_nonce_invalidates_encrypted_cohort(self):
        a, b = self.root["trials"][10:12]
        metadata = bytearray.fromhex(b["crypto_verification"]["host_expected_metadata_hex"])
        metadata[8:20] = bytes.fromhex(a["encrypted"]["nonce_hex"])
        metadata[36:] = struct.pack("<I", zlib.crc32(metadata[:36]))
        b["encrypted"].update(nonce_hex=metadata[8:20].hex(), metadata_hex=metadata.hex())
        b["crypto_verification"]["host_expected_metadata_hex"] = metadata.hex()
        for key in ("tx_metadata", "rx_metadata"):
            for e in b[key]:
                e.update(metadata_hex=metadata.hex(), metadata_crc32=f"{zlib.crc32(metadata[:36]):08x}")
        self.save()
        result = report.collect(self.path)
        self.assertFalse(result["nonce_unique"])
        self.assertEqual(result["groups"]["GCM"]["passed"], 0)

    def test_pdf_has_seven_pages_and_units(self):
        from pypdf import PdfReader
        path = self.path / "fixture-report.pdf"
        report.make_pdf(path, report.collect(self.path))
        pages = PdfReader(path).pages
        self.assertEqual(len(pages), 7)
        text = "\n".join(p.extract_text() for p in pages)
        for word in ("AES-128-GCM", "milliseconds", "KiB", "48,000 bytes", "OFFLINE VALIDATION FIXTURE"):
            self.assertIn(word, text)


if __name__ == "__main__":
    unittest.main()
