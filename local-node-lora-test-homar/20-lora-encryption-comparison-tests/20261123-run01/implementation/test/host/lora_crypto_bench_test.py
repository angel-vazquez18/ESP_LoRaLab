"""Offline acceptance checks for crypto bench framing and evidence validation."""
import copy
import contextlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import lora_crypto_bench as bench


class CryptoBenchTests(unittest.TestCase):
    source = (bytes(range(256)) * 188)[:48000]
    key = bytes(range(16))
    nonce = bytes(range(12))

    def expected(self):
        return bench.seal_expected(self.source, self.key, self.nonce, 13)

    def hello(self):
        return {"mac": "8C:FD:49:B5:B7:8C", "boot_id": "testboot", "node": 6,
                "firmware": bench.FIRMWARE, "timing_schema": 1, "crypto_schema": 1,
                "crypto_algorithm": "AES-128-GCM", "nonce_bytes": 12, "tag_bytes": 16,
                "radio_ready": True, "frequency_mhz": 915, "bw_khz": 500,
                "sf": 7, "cr": 5, "sync_word": 18, "chip_power_dbm": -9,
                "data_packet_bytes": 251, "ack_packet_bytes": 14,
                "data_airtime_us": 98624, "ack_airtime_us": 11584,
                "metadata_packet_bytes": 40, "metadata_airtime_us": 20000,
                "oled_ready": True, "oled_layout_ok": True}

    def crypto_trial(self):
        ciphertext, metadata = self.expected()
        parsed = bench.decode_metadata(metadata, 13)
        encrypted = {"event": "encrypted", "id": 13, "encryption_us": 70,
                     "nonce_hex": parsed["nonce_hex"], "tag_hex": parsed["tag_hex"],
                     "metadata_hex": metadata.hex()}
        decrypted = {"event": "decrypted", "id": 13, "decryption_us": 90,
                     "authenticated": True, "message_ready_us": 600}
        return {"mode": "GCM", "id": 13, "encrypted_events": [encrypted],
                "decrypted_events": [decrypted],
                "tx_done": {"mode": "GCM", "encryption_us": 70},
                "rx_complete": {"mode": "GCM", "authenticated": True,
                                "decryption_us": 90, "message_ready_us": 600},
                "expected_ciphertext_crc32": bench.base.crc32_hex(ciphertext),
                "receiver_comparison": {"source_crc32": bench.base.crc32_hex(self.source)},
                "tx_role": {"crypto_buffer_requested_bytes": 48000, "crypto_buffer_actual_bytes": 48116},
                "rx_role": {"crypto_buffer_requested_bytes": 48000, "crypto_buffer_actual_bytes": 48116}}, metadata

    def test_plan_keeps_ten_each_with_five_each_direction(self):
        plan = bench.trial_plan()
        self.assertEqual([p["trial"] for p in plan], list(range(1, 21)))
        self.assertEqual([p["mode"] for p in plan], ["PLAIN"] * 10 + ["GCM"] * 10)
        for mode in ("PLAIN", "GCM"):
            self.assertEqual(sum(p["reverse"] for p in plan if p["mode"] == mode), 5)
        for invalid in (0, 51, True, 1.5):
            with self.assertRaises(ValueError):
                bench.trial_plan(invalid)

    def test_nist_known_answer_and_tamper_rejection(self):
        checks = bench.host_crypto_selftest()
        self.assertTrue(all(checks.values()))

    def test_metadata_round_trip_has_real_aead_and_fixed_overhead(self):
        ciphertext, metadata = self.expected()
        self.assertEqual(len(ciphertext), len(self.source))
        self.assertNotEqual(ciphertext, self.source)
        self.assertEqual(len(metadata), 40)
        fields = bench.decode_metadata(metadata, 13)
        self.assertEqual(fields["nonce_hex"], self.nonce.hex())
        decoded = bench.AESGCM(self.key).decrypt(self.nonce, ciphertext + metadata[20:36], metadata[:8])
        self.assertEqual(decoded, self.source)
        self.assertEqual(struct.unpack("<I", metadata[4:8])[0], 48000)

    def test_metadata_rejects_stale_header_length_crc_and_truncation(self):
        _, metadata = self.expected()
        for mutated in (metadata[:-1], bytes([metadata[0] ^ 1]) + metadata[1:],
                        metadata[:4] + struct.pack("<I", 47999) + metadata[8:],
                        metadata[:-1] + bytes([metadata[-1] ^ 1])):
            with self.assertRaises(ValueError):
                bench.decode_metadata(mutated, 13)
        with self.assertRaises(ValueError):
            bench.decode_metadata(metadata, 14)

    def test_message_id_is_authenticated_as_aad(self):
        ciphertext, metadata = self.expected()
        aad = bytearray(metadata[:8])
        aad[2] ^= 1
        with self.assertRaises(bench.InvalidTag):
            bench.AESGCM(self.key).decrypt(self.nonce, ciphertext + metadata[20:36], bytes(aad))

    def test_hello_rejects_legacy_mismatched_crypto_and_missing_oled(self):
        node = {"port": "COM6", "mac_normalized": "8CFD49B5B78C"}
        bench.validate_hello(node, self.hello())
        for change in ({"firmware": "lora-integrity-3-timing"}, {"crypto_schema": True},
                       {"crypto_algorithm": "AES-CTR"}, {"nonce_bytes": 8},
                       {"metadata_airtime_us": 0}, {"oled_ready": False}):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                bench.validate_hello(node, {**self.hello(), **change})

    def test_device_selftest_must_include_every_negative_control(self):
        valid = {"passed": True, "known_answer_passed": True, "wrong_key_rejected": True,
                 "wrong_tag_rejected": True, "changed_ciphertext_rejected": True}
        bench.validate_device_selftest(valid)
        for field in valid:
            modified = dict(valid)
            modified.pop(field)
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                bench.validate_device_selftest(modified)

    def test_crypto_audit_requires_once_only_reconciled_authenticated_work(self):
        trial, metadata = self.crypto_trial()
        self.assertTrue(bench.audit_crypto_events(trial, metadata)["valid"])
        for mutation in ("missing", "duplicate", "tag", "auth", "timing", "memory", "metadata", "ready"):
            damaged = copy.deepcopy(trial)
            if mutation == "missing": damaged["encrypted_events"] = []
            elif mutation == "duplicate": damaged["decrypted_events"] *= 2
            elif mutation == "tag": damaged["encrypted_events"][0]["tag_hex"] = "00" * 16
            elif mutation == "auth": damaged["rx_complete"]["authenticated"] = False
            elif mutation == "timing": damaged["tx_done"]["encryption_us"] = 71
            elif mutation == "memory": damaged["rx_role"]["crypto_buffer_actual_bytes"] = 0
            elif mutation == "metadata": damaged["encrypted_events"][0]["metadata_hex"] = "00" * 40
            elif mutation == "ready": damaged["rx_complete"]["message_ready_us"] = 601
            with self.subTest(mutation=mutation):
                self.assertFalse(bench.audit_crypto_events(damaged, metadata)["valid"])

    def test_crypto_audit_missing_or_invalid_time_is_not_zero(self):
        trial, metadata = self.crypto_trial()
        for value in (None, -1, True, "70", 0.5):
            damaged = copy.deepcopy(trial)
            damaged["encrypted_events"][0]["encryption_us"] = value
            damaged["tx_done"]["encryption_us"] = value
            self.assertFalse(bench.audit_crypto_events(damaged, metadata)["valid"])
        # Zero is valid at timer resolution when both independent records say zero.
        trial["encrypted_events"][0]["encryption_us"] = 0
        trial["tx_done"]["encryption_us"] = 0
        self.assertTrue(bench.audit_crypto_events(trial, metadata)["valid"])

    def test_plain_mode_explicitly_has_no_crypto_processing_or_buffer(self):
        trial = {"mode": "PLAIN", "tx_done": {"mode": "PLAIN", "encryption_us": 0},
                 "rx_complete": {"mode": "PLAIN", "decryption_us": 0},
                 "tx_role": {"crypto_buffer_requested_bytes": 0},
                 "rx_role": {"crypto_buffer_requested_bytes": 0}}
        self.assertTrue(bench.audit_crypto_events(trial, None)["valid"])
        trial["tx_done"].pop("encryption_us")
        self.assertFalse(bench.audit_crypto_events(trial, None)["valid"])

    def test_metadata_retries_duplicates_and_airtime_counted_separately(self):
        _, metadata = self.expected()
        common = {"metadata_hex": metadata.hex(), "metadata_crc32": bench.base.crc32_hex(metadata[:36])}
        tx = [{**common, "attempt": 1, "tx_radio_status": 0, "acked": False},
              {**common, "attempt": 2, "tx_radio_status": 0, "acked": True}]
        rx = [{**common, "duplicate": False, "ack_status": 0},
              {**common, "duplicate": True, "ack_status": 0}]
        result = bench.metadata_accounting(tx, rx, self.hello(), metadata, True)
        self.assertTrue(result["valid"])
        self.assertEqual(result["retries"], 1)
        self.assertEqual(result["rx_duplicates"], 1)
        self.assertEqual(result["estimated_airtime_successful_radio_calls_us"], 2 * (20000 + 11584))
        self.assertEqual(result["data_rf_payload_bytes_attempted"], 80)
        damaged = copy.deepcopy(rx)
        damaged[1]["metadata_hex"] = "00" * 40
        self.assertFalse(bench.metadata_accounting(tx, damaged, self.hello(), metadata, True)["valid"])
        self.assertFalse(bench.metadata_accounting(tx, rx, self.hello(), None, False)["valid"])

    def test_metadata_missing_ack_or_missing_unique_cannot_pass(self):
        _, metadata = self.expected()
        common = {"metadata_hex": metadata.hex(), "metadata_crc32": bench.base.crc32_hex(metadata[:36])}
        tx = [{**common, "attempt": 1, "tx_radio_status": 0, "acked": False}]
        rx = [{**common, "duplicate": False, "ack_status": 0}]
        self.assertFalse(bench.metadata_accounting(tx, rx, self.hello(), metadata, True)["valid"])
        tx[0]["acked"] = True
        rx[0]["duplicate"] = True
        self.assertFalse(bench.metadata_accounting(tx, rx, self.hello(), metadata, True)["valid"])

    def test_key_is_sent_but_never_written_into_serial_command_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = bench.CryptoConnection({"port": "COM6"}, Path(tmp))
            sent = []
            conn.serial = SimpleNamespace(write=lambda data: sent.append(data) or len(data), is_open=False)
            secret = "ab" * 16
            conn.send("KEY " + secret)
            conn.send("NONCE " + "cd" * 12)
            conn.close()
            logs = (Path(tmp) / "serial-COM6.log").read_text()
            self.assertNotIn(secret, logs)
            self.assertIn("KEY [REDACTED]", logs)
            self.assertIn("NONCE " + "cd" * 12, logs)
            self.assertEqual(sent[0], ("KEY " + secret + "\n").encode())
            self.assertEqual((Path(tmp) / "serial-COM6.bin").read_bytes(), b"")

    def test_malformed_key_never_leaks_to_log_or_wire(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = bench.CryptoConnection({"port": "COM6"}, Path(tmp))
            sent = []
            conn.serial = SimpleNamespace(write=lambda data: sent.append(data) or len(data), is_open=False)
            with self.assertRaises(ValueError): conn.send("KEY secret")
            conn.close()
            self.assertFalse(sent)
            self.assertNotIn("secret", (Path(tmp) / "serial-COM6.log").read_text())

    def test_timing_and_metadata_completion_counters_must_match_raw_records(self):
        trial = {"mode": "GCM", "rx_port": "COM7", "tx_packets": [],
                 "tx_metadata": [{"start_us": 10}],
                 "metadata_accounting": {"tx_attempts": 1, "successful_transmits": 1, "ack_received": 1},
                 "tx_done": {"metadata_attempts": 1, "metadata_successful_transmits": 1,
                             "metadata_ack_received": 1, "start_us": 1, "radio_start_us": 10, "end_us": 1000},
                 "rx_complete": {"first_transport_rx_us": 5, "first_rx_us": 100,
                                 "last_rx_us": 800, "message_ready_us": 900},
                 "status_COM7": {"authenticated": True, "auth_failures": 0}}
        self.assertTrue(bench.audit_transport_completion(trial)["valid"])
        for branch, field, value in (("tx_done", "metadata_attempts", 2),
                                     ("tx_done", "radio_start_us", 11),
                                     ("rx_complete", "message_ready_us", 799),
                                     ("rx_complete", "last_rx_us", None),
                                     ("status_COM7", "auth_failures", 1)):
            damaged = copy.deepcopy(trial)
            damaged[branch][field] = value
            self.assertFalse(bench.audit_transport_completion(damaged)["valid"])

    def test_trial_flow_verifies_cipher_and_never_uploads_audio_or_nonce_to_receiver(self):
        test = self
        for mode in ("PLAIN", "GCM"):
            class FakeConnection:
                def __init__(self, port):
                    self.node, self.hello = {"port": port}, test.hello()
                    self.commands, self.events = [], []
                    self.mode, self.role = mode, None
                def cursor(self): return len(self.events)
                def messages_since(self, cursor, event_name=None, message_id=None):
                    return [copy.deepcopy(e) for e in self.events[cursor:]
                            if (event_name is None or e["event"] == event_name)
                            and (message_id is None or e.get("id") == message_id)]
                def request(self, command, event_name, timeout=10, predicate=None):
                    self.commands.append(command)
                    message = {"event": event_name}
                    if command.startswith("MODE "): self.mode = command.split()[1]; message["mode"] = self.mode
                    elif command.startswith("TEST "): message.update(current=1, total=20)
                    elif command.startswith("ROLE "):
                        self.role = command.split()[1]
                        message.update(role=self.role, crypto_buffer_requested_bytes=48000 if mode == "GCM" else 0,
                                       crypto_buffer_actual_bytes=48116 if mode == "GCM" else 0)
                    elif command.startswith("NONCE "): message["nonce_hex"] = command.split()[1]
                    elif command.startswith("ARM "): message["id"] = 13
                    elif command == "STATUS": message.update(authenticated=mode == "GCM", auth_failures=0)
                    if predicate is not None: test.assertTrue(predicate(message))
                    return {"message": message}
                def send(self, command):
                    self.commands.append(command)
                    if command.startswith("TX "): populate()
                    return 0
                def wait(self, event_name, cursor, timeout=10, predicate=None, progress=None):
                    if event_name == "load_ready": return {"message": {"bytes": 48000, "block_bytes": 512}}
                    if event_name == "loaded": return {"message": {"bytes": 48000, "crc32": bench.base.crc32_hex(test.source)}}
                    events = self.messages_since(cursor, event_name)
                    found = next(e for e in events if predicate is None or predicate(e))
                    return {"message": found}
                def write_pcm(self, source, block_bytes): test.assertEqual(source, test.source)

            tx, rx = FakeConnection("COM6"), FakeConnection("COM7")
            wire, metadata = self.expected() if mode == "GCM" else (self.source, None)
            def populate():
                if mode == "GCM":
                    fields = bench.decode_metadata(metadata, 13)
                    tx.events.extend([
                        {"event": "encrypted", "id": 13, "encryption_us": 70,
                         "nonce_hex": fields["nonce_hex"], "tag_hex": fields["tag_hex"], "metadata_hex": metadata.hex()},
                        {"event": "tx_metadata", "id": 13, "attempt": 1, "start_us": 10,
                         "end_us": 11, "ack_us": 12, "tx_radio_status": 0, "radio_status": 0,
                         "acked": True, "metadata_hex": metadata.hex(), "metadata_crc32": fields["metadata_crc32"]}])
                    rx.events.append({"event": "rx_metadata", "id": 13, "rx_us": 20, "duplicate": False,
                                      "ack_status": 0, "metadata_hex": metadata.hex(), "metadata_crc32": fields["metadata_crc32"]})
                for i in range(200):
                    crc = bench.base.expected_data_crc(wire, 13, i)
                    tx.events.append({"event": "tx_packet", "id": 13, "index": i, "attempt": 1,
                                      "start_us": 100 + i * 100, "end_us": 101 + i * 100,
                                      "ack_us": 102 + i * 100, "chunking_us": 10,
                                      "tx_radio_status": 0, "radio_status": 0, "acked": True, "data_crc32": crc})
                    rx.events.append({"event": "rx_packet", "id": 13, "index": i,
                                      "rx_us": 110 + i * 100, "duplicate": False,
                                      "dechunking_us": 8, "ack_status": 0, "data_crc32": crc})
                if mode == "GCM":
                    rx.events.append({"event": "decrypted", "id": 13, "decryption_us": 90,
                                      "authenticated": True, "message_ready_us": 20200})
                rx.events.append({"event": "rx_complete", "id": 13, "mode": mode,
                                  "received_chunks": 200, "first_rx_us": 110, "last_rx_us": 20010,
                                  "first_transport_rx_us": 20 if mode == "GCM" else 110,
                                  "message_ready_us": 20200, "authenticated": mode == "GCM",
                                  "dechunking_count": 200, "dechunking_total_us": 1600,
                                  "decryption_us": 90 if mode == "GCM" else 0})
                tx.events.append({"event": "tx_done", "id": 13, "mode": mode,
                                  "success": True, "acked_chunks": 200, "start_us": 1,
                                  "radio_start_us": 10 if mode == "GCM" else 100, "end_us": 20300,
                                  "chunking_count": 200, "chunking_total_us": 2000,
                                  "encryption_us": 70 if mode == "GCM" else 0,
                                  "metadata_acked": mode == "GCM", "metadata_attempts": 1 if mode == "GCM" else 0,
                                  "metadata_successful_transmits": 1 if mode == "GCM" else 0,
                                  "metadata_ack_received": 1 if mode == "GCM" else 0})
            clock = {"selected_min_rtt": {"boot_id": "same", "device_us": 100,
                                          "offset_lower_us": 0, "offset_upper_us": 1,
                                          "offset_midpoint_us": 0.5}}
            def fake_dump(conn, role, dest):
                bench.base.save_wav(dest, self.source)
                return self.source, {"complete": True, "bytes": 48000}
            def fake_cipher(conn, dest):
                dest.write_bytes(wire)
                return wire, {"complete": True, "bytes": 48000}
            with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()), \
                    patch.object(bench.base, "dump_buffer", side_effect=fake_dump), \
                    patch.object(bench.base, "calibrate_clock", return_value=clock), \
                    patch.object(bench, "dump_cipher", side_effect=fake_cipher):
                trial = bench.run_trial(tx, rx, self.source, self.key, self.nonce if mode == "GCM" else None,
                                        Path(temp), {"mode": mode, "mode_trial": 1, "trial": 1}, 13, 240, 20)
            with self.subTest(mode=mode):
                self.assertTrue(trial["passed"], trial)
                self.assertTrue(trial["crypto_verification"]["valid"])
                self.assertFalse(any(c.startswith(("LOAD", "NONCE", "TX ")) for c in rx.commands))
                self.assertEqual(sum(c.startswith("LOAD") for c in tx.commands), 1)
                self.assertEqual(sum(c.startswith("NONCE") for c in tx.commands), int(mode == "GCM"))


if __name__ == "__main__":
    unittest.main()
