"""Run fresh PLAIN and AES-128-GCM trials on two physical Heltec LoRa radios.

The ephemeral key stays in process/device RAM and KEY commands are redacted.
Only the active transmitter receives source PCM or the per-message nonce by USB.
Ciphertext, nonce and tag reach the receiver through LoRa, never through the host.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import secrets
import struct
import subprocess
import sys
import time

# Use the installed serial dependency without shadowing the primary runtime's
# cryptography/report packages. This fallback only supplies a missing pyserial.
if importlib.util.find_spec("serial") is None:
    sys.path.append(str(Path.home() / ".platformio/penv/Lib/site-packages"))

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
import lora_transfer_bench as base

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = "lora-crypto-1-gcm"
METADATA_BYTES = 40
NONCE_BYTES = 12
TAG_BYTES = 16
KEY_BYTES = 16


class CryptoConnection(base.Connection):
    def send(self, command):
        if not command.startswith("KEY "):
            return super().send(command)
        # Do not pass the secret to the inherited command logger.
        key_hex = command[4:]
        if len(key_hex) != 32 or any(c not in "0123456789abcdefABCDEF" for c in key_hex):
            raise ValueError("KEY requires exactly 32 hexadecimal characters")
        self.log_record("TX", {"command": "KEY [REDACTED]", "key_bytes": KEY_BYTES})
        wire = (command + "\n").encode("ascii")
        stamp = time.perf_counter_ns()
        if self.serial.write(wire) != len(wire):
            raise RuntimeError(f"{self.node['port']}: short key command write")
        return stamp


def nonnegative_int(value):
    return type(value) is int and value >= 0


def trial_plan(per_mode=10):
    if type(per_mode) is not int or not 1 <= per_mode <= 50:
        raise ValueError("Trials per mode must be an integer from 1 to 50")
    return [{"trial": group * per_mode + i + 1, "mode": mode,
             "mode_trial": i + 1, "reverse": bool(i % 2)}
            for group, mode in enumerate(("PLAIN", "GCM")) for i in range(per_mode)]


def validate_hello(node, hello):
    base.validate_hello(node, hello, False)
    required = {"firmware": FIRMWARE, "timing_schema": 1, "crypto_schema": 1,
                "crypto_algorithm": "AES-128-GCM", "metadata_packet_bytes": METADATA_BYTES,
                "nonce_bytes": NONCE_BYTES, "tag_bytes": TAG_BYTES,
                "oled_ready": True, "oled_layout_ok": True}
    for field, expected in required.items():
        actual = hello.get(field)
        if actual != expected or type(actual) is not type(expected):
            raise RuntimeError(f"{node['port']}: unexpected {field}={actual!r}, expected {expected!r}")
    if not nonnegative_int(hello.get("metadata_airtime_us")) or hello["metadata_airtime_us"] == 0:
        raise RuntimeError("Invalid metadata airtime")


def seal_expected(source, key, nonce, message_id):
    if len(source) != base.PCM_BYTES or len(key) != KEY_BYTES or len(nonce) != NONCE_BYTES:
        raise ValueError("Invalid AES-GCM benchmark input lengths")
    if not 1 <= message_id <= 65535:
        raise ValueError("Invalid message identity")
    aad = struct.pack("<BBHI", 0xfb, 1, message_id, base.PCM_BYTES)
    sealed = AESGCM(key).encrypt(nonce, source, aad)
    ciphertext, tag = sealed[:-TAG_BYTES], sealed[-TAG_BYTES:]
    prefix = aad + nonce + tag
    metadata = prefix + struct.pack("<I", int(base.crc32_hex(prefix), 16))
    return ciphertext, metadata


def decode_metadata(raw, expected_id=None):
    if len(raw) != METADATA_BYTES:
        raise ValueError("Metadata must be 40 bytes")
    magic, version, message_id, length = struct.unpack("<BBHI", raw[:8])
    if magic != 0xfb or version != 1 or length != base.PCM_BYTES or message_id == 0:
        raise ValueError("Invalid metadata header")
    if expected_id is not None and message_id != expected_id:
        raise ValueError("Metadata message identity mismatch")
    if struct.unpack("<I", raw[36:])[0] != int(base.crc32_hex(raw[:36]), 16):
        raise ValueError("Metadata CRC mismatch")
    return {"id": message_id, "pcm_bytes": length, "nonce_hex": raw[8:20].hex(),
            "tag_hex": raw[20:36].hex(), "metadata_crc32": base.crc32_hex(raw[:36]),
            "aad_hex": raw[:8].hex()}


def host_crypto_selftest():
    # NIST GCM: zero key, 96-bit zero IV, one all-zero block, no AAD.
    key, nonce, plain = bytes(16), bytes(12), bytes(16)
    expected = bytes.fromhex("0388dace60b6a392f328c2b971b2fe78ab6e47d42cec13bdf53a67b21257bddf")
    aes = AESGCM(key)
    sealed = aes.encrypt(nonce, plain, b"")
    results = {"known_answer_passed": sealed == expected,
               "round_trip_passed": aes.decrypt(nonce, sealed, b"") == plain}
    for name, trial_key, trial_sealed in (
        ("wrong_key_rejected", b"\x01" + key[1:], sealed),
        ("wrong_tag_rejected", key, sealed[:-1] + bytes([sealed[-1] ^ 1])),
        ("changed_ciphertext_rejected", key, bytes([sealed[0] ^ 1]) + sealed[1:]),
    ):
        try:
            AESGCM(trial_key).decrypt(nonce, trial_sealed, b"")
            results[name] = False
        except InvalidTag:
            results[name] = True
    results["passed"] = all(results.values())
    return results


def validate_device_selftest(record):
    fields = ("passed", "known_answer_passed", "wrong_key_rejected",
              "wrong_tag_rejected", "changed_ciphertext_rejected")
    if any(record.get(field) is not True for field in fields):
        raise RuntimeError(f"Device AES-GCM self-test failed: {record}")


def dump_cipher(connection, destination):
    cursor = connection.cursor()
    connection.send("DUMP CIPHER")
    header = connection.wait("dump_begin", cursor, timeout=15,
                             predicate=lambda m: m.get("role") == "CIPHER")["message"]
    binary = connection.wait("host_dump_binary", cursor, timeout=20)
    payload = binary["payload"]
    destination.write_bytes(payload)
    trailer = connection.wait("dump_end", cursor, timeout=5,
                              predicate=lambda m: m.get("role") == "CIPHER")["message"]
    if (header.get("bytes") != base.PCM_BYTES or trailer.get("bytes") != base.PCM_BYTES
            or base.crc32_hex(payload) != str(header.get("crc32", "")).lower()):
        raise RuntimeError("Ciphertext serial export length/CRC mismatch")
    return payload, {**header, "file": destination.name,
                     "sha256": hashlib.sha256(payload).hexdigest()}


def metadata_accounting(tx_packets, rx_packets, hello, expected_metadata, required):
    errors = []
    expected_hex = expected_metadata.hex() if expected_metadata is not None else None
    expected_crc = base.crc32_hex(expected_metadata[:36]) if expected_metadata is not None else None
    if not required and (tx_packets or rx_packets):
        errors.append("PLAIN trial unexpectedly transmitted encryption metadata")
    if required:
        if not tx_packets or not rx_packets or not any(p.get("acked") is True for p in tx_packets):
            errors.append("Encrypted metadata was not sent, received and acknowledged")
        if sum(p.get("duplicate") is False for p in rx_packets) != 1:
            errors.append("Expected one unique accepted metadata frame")
        for side, packets in (("TX", tx_packets), ("RX", rx_packets)):
            for p in packets:
                if p.get("metadata_hex") != expected_hex or p.get("metadata_crc32") != expected_crc:
                    errors.append(f"{side} metadata does not match the independent AES-GCM envelope")
        if [p.get("attempt") for p in tx_packets] != list(range(1, len(tx_packets) + 1)):
            errors.append("Metadata attempts are not consecutive")
    tx_ok = sum(p.get("tx_radio_status") == 0 for p in tx_packets)
    ack_ok = sum(p.get("ack_status") == 0 for p in rx_packets)
    ack_received = sum(p.get("acked") is True for p in tx_packets)
    return {"required": required, "valid": not errors, "errors": errors,
            "tx_attempts": len(tx_packets), "retries": max(0, len(tx_packets) - 1),
            "successful_transmits": tx_ok, "ack_successful_transmits": ack_ok,
            "ack_received": ack_received,
            "rx_duplicates": sum(p.get("duplicate") is True for p in rx_packets),
            "data_rf_payload_bytes_attempted": len(tx_packets) * METADATA_BYTES,
            "data_rf_payload_bytes_successful_tx_calls": tx_ok * METADATA_BYTES,
            "ack_rf_payload_bytes_successful_tx_calls": ack_ok * base.ACK_PACKET_BYTES,
            "estimated_airtime_successful_radio_calls_us":
                tx_ok * hello["metadata_airtime_us"] + ack_ok * hello["ack_airtime_us"]}


def merge_accounting(data, metadata):
    result = dict(data)
    result["data_only_estimated_airtime_successful_radio_calls_us"] = data["estimated_airtime_successful_radio_calls_us"]
    result["metadata_rf_payload_bytes_attempted"] = metadata["data_rf_payload_bytes_attempted"]
    result["metadata_rf_payload_bytes_successful_tx_calls"] = metadata["data_rf_payload_bytes_successful_tx_calls"]
    result["metadata_ack_rf_payload_bytes_successful_tx_calls"] = metadata["ack_rf_payload_bytes_successful_tx_calls"]
    result["total_rf_payload_bytes_attempted_data_and_metadata"] = data["data_rf_payload_bytes_attempted"] + metadata["data_rf_payload_bytes_attempted"]
    result["total_rf_payload_bytes_successful_tx_calls"] = (
        data["data_rf_payload_bytes_successful_tx_calls"] + data["ack_rf_payload_bytes_successful_tx_calls"]
        + metadata["data_rf_payload_bytes_successful_tx_calls"] + metadata["ack_rf_payload_bytes_successful_tx_calls"])
    result["estimated_airtime_successful_radio_calls_us"] += metadata["estimated_airtime_successful_radio_calls_us"]
    result["total_retries_observed"] = data["retries_observed"] + metadata["retries"]
    result["total_receiver_duplicate_packets"] = data["receiver_duplicate_packets"] + metadata["rx_duplicates"]
    result["crypto_transport_overhead_bytes_no_retries"] = 54 if metadata["required"] else 0
    result["ciphertext_bytes"] = base.PCM_BYTES if metadata["required"] else 0
    result["sealed_message_bytes"] = base.PCM_BYTES + NONCE_BYTES + TAG_BYTES if metadata["required"] else base.PCM_BYTES
    result["airtime_note"] += " Crypto-mode airtime additionally includes metadata and its ACK, including their retries."
    return result


def audit_crypto_events(trial, expected_metadata):
    """Validate local crypto measurements; no missing timing becomes a zero."""
    mode = trial["mode"]
    done, complete = trial.get("tx_done", {}), trial.get("rx_complete") or {}
    enc, dec = trial.get("encrypted_events", []), trial.get("decrypted_events", [])
    errors = []
    for side, event in (("TX", done), ("RX", complete)):
        if event.get("mode") != mode:
            errors.append(f"{side} completion mode mismatch")
    if mode == "GCM":
        if len(enc) != 1 or len(dec) != 1:
            errors.append("Expected exactly one encryption and one authenticated decryption")
        else:
            e, d = enc[0], dec[0]
            parsed = decode_metadata(expected_metadata, trial["id"])
            for key in ("nonce_hex", "tag_hex"):
                if e.get(key) != parsed[key]:
                    errors.append(f"Encryption event {key} differs from host AES-GCM")
            if e.get("metadata_hex") != expected_metadata.hex():
                errors.append("Encryption metadata differs from host AES-GCM")
            if d.get("authenticated") is not True or complete.get("authenticated") is not True:
                errors.append("Receiver has not authenticated the reconstructed ciphertext")
            for field, event, completed in (("encryption_us", e, done), ("decryption_us", d, complete)):
                if not nonnegative_int(event.get(field)) or completed.get(field) != event.get(field):
                    errors.append(f"Missing/invalid/unreconciled {field}")
            if not nonnegative_int(d.get("message_ready_us")) or d.get("message_ready_us") != complete.get("message_ready_us"):
                errors.append("Message-ready timestamps disagree")
        for side in ("tx", "rx"):
            role = trial.get(f"{side}_role", {})
            if role.get("crypto_buffer_requested_bytes") != base.PCM_BYTES or role.get("crypto_buffer_actual_bytes", -1) < base.PCM_BYTES:
                errors.append(f"{side.upper()} crypto buffer allocation is missing")
    else:
        if enc or dec:
            errors.append("PLAIN trial contains crypto-operation events")
        if done.get("encryption_us") != 0 or complete.get("decryption_us") != 0:
            errors.append("PLAIN encryption/decryption measurements must explicitly be disabled (zero)")
        for side in ("tx", "rx"):
            if trial.get(f"{side}_role", {}).get("crypto_buffer_requested_bytes") != 0:
                errors.append(f"{side.upper()} PLAIN mode allocated a crypto buffer")
    return {"valid": not errors, "errors": errors,
            "encryption_us": done.get("encryption_us"), "decryption_us": complete.get("decryption_us"),
            "measurement_scope": "Device-local elapsed GCM operation, outside chunk/dechunk timers; key setup is separate"}


def audit_transport_completion(trial):
    errors = []
    done, complete = trial.get("tx_done", {}), trial.get("rx_complete") or {}
    metadata = trial["metadata_accounting"]
    for field, value in (("metadata_attempts", metadata["tx_attempts"]),
                         ("metadata_successful_transmits", metadata["successful_transmits"]),
                         ("metadata_ack_received", metadata["ack_received"])):
        if type(done.get(field)) is not int or done[field] != value:
            errors.append(f"Metadata counter mismatch: {field}")
    sender_times = [done.get(name) for name in ("start_us", "radio_start_us", "end_us")]
    receiver_times = [complete.get(name) for name in
                      ("first_transport_rx_us", "first_rx_us", "last_rx_us", "message_ready_us")]
    for side, timestamps in (("TX", sender_times), ("RX", receiver_times)):
        if not all(nonnegative_int(stamp) for stamp in timestamps) or timestamps != sorted(timestamps):
            errors.append(f"Missing/invalid {side} local timing boundaries")
    first_transport = trial["tx_metadata"] if trial["mode"] == "GCM" else trial["tx_packets"]
    if not first_transport or done.get("radio_start_us") != first_transport[0].get("start_us"):
        errors.append("First radio timestamp disagrees with the packet log")
    status = trial.get(f"status_{trial['rx_port']}", {})
    if status.get("auth_failures") != 0 or (trial["mode"] == "GCM" and status.get("authenticated") is not True):
        errors.append("Receiver authentication status is inconsistent")
    return {"valid": not errors, "errors": errors}


def run_trial(tx, rx, source, key, nonce, folder, plan, message_id, timeout, total_trials):
    mode = plan["mode"]
    trial = {"trial": plan["trial"], "mode_trial": plan["mode_trial"], "mode": mode,
             "id": message_id, "tx_port": tx.node["port"], "rx_port": rx.node["port"],
             "started_at": base.utc_now(), "passed": False, "negative_control": False}
    wire_source, expected_metadata = seal_expected(source, key, nonce, message_id) if mode == "GCM" else (source, None)
    trial["wire_payload_source_sha256"] = hashlib.sha256(wire_source).hexdigest()
    trial["expected_ciphertext_crc32"] = base.crc32_hex(wire_source) if mode == "GCM" else None
    trial["nonce_hex"] = nonce.hex() if nonce else None
    trial["expected_metadata_hex"] = expected_metadata.hex() if expected_metadata else None
    tx_cursor, rx_cursor = tx.cursor(), rx.cursor()
    armed = False
    tx_cipher = rx_cipher = None
    try:
        for conn in (tx, rx):
            conn.request("STOP", "stopped")
            conn.request(f"MODE {mode}", "mode", predicate=lambda m: m.get("mode") == mode)
            conn.request(f"TEST {plan['trial']} {total_trials}", "test",
                         predicate=lambda m: m.get("current") == plan["trial"] and m.get("total") == total_trials)
        trial["tx_role"] = tx.request("ROLE TX", "role", predicate=lambda m: m.get("role") == "TX")["message"]
        trial["rx_role"] = rx.request("ROLE RX", "role", predicate=lambda m: m.get("role") == "RX")["message"]
        cursor = tx.cursor()
        load_start = time.perf_counter_ns()
        tx.send(f"LOAD {base.crc32_hex(source)}")
        ready = tx.wait("load_ready", cursor)["message"]
        if ready.get("bytes") != base.PCM_BYTES or ready.get("block_bytes") != 512:
            raise RuntimeError("Wrong USB loading contract")
        tx.write_pcm(source, 512)
        trial["loaded"] = tx.wait("loaded", cursor, timeout=20)["message"]
        trial["usb_source_load_us"] = (time.perf_counter_ns() - load_start) / 1000
        if trial["loaded"].get("bytes") != base.PCM_BYTES or trial["loaded"].get("crc32") != base.crc32_hex(source):
            raise RuntimeError("Source LOAD length/CRC mismatch")
        sender_pcm, trial["tx_dump"] = base.dump_buffer(tx, "TX", folder / "sender-before-radio.wav")
        trial["sender_serial_upload_comparison"] = base.compare_pcm(source, sender_pcm)
        if sender_pcm != source:
            raise RuntimeError("Sender buffer differs before RF")
        if mode == "GCM":
            trial["nonce_set"] = tx.request(f"NONCE {nonce.hex()}", "nonce",
                                            predicate=lambda m: m.get("nonce_hex") == nonce.hex())["message"]
        trial["clock_before"] = {c.node["port"]: base.calibrate_clock(c) for c in (tx, rx)}
        trial["armed"] = rx.request(f"ARM {message_id}", "armed", predicate=lambda m: m.get("id") == message_id)["message"]
        armed = True
        cursor = tx.cursor()
        tx.send(f"TX {message_id}")
        def progress(message):
            if message.get("event") == "tx_packet" and message.get("id") == message_id and message.get("acked") and (message.get("index", -1) + 1) % 25 == 0:
                print(f"  {mode} {tx.node['port']} -> {rx.node['port']}: {message['index'] + 1}/200 chunks acknowledged", flush=True)
        trial["tx_done"] = tx.wait("tx_done", cursor, timeout=timeout,
                                    predicate=lambda m: m.get("id") == message_id, progress=progress)["message"]
    except KeyboardInterrupt:
        trial.update(error="Interrupted by user", interrupted=True)
    except Exception as exc:
        trial.update(error=str(exc), error_type=type(exc).__name__)
    finally:
        if armed and "tx_done" in trial and not trial.get("interrupted"):
            try:
                trial["clock_after"] = {c.node["port"]: base.calibrate_clock(c) for c in (tx, rx)}
            except (Exception, KeyboardInterrupt) as exc:
                trial["clock_after_error"] = str(exc) or type(exc).__name__
        for conn in (tx, rx):
            try:
                conn.request("STOP", "stopped", timeout=5)
                trial[f"status_{conn.node['port']}"] = conn.request("STATUS", "status", timeout=5)["message"]
            except (Exception, KeyboardInterrupt) as exc:
                trial.setdefault("cleanup_errors", []).append(str(exc) or type(exc).__name__)
        if "rx_role" in trial:
            try:
                export_start = time.perf_counter_ns()
                received, trial["rx_dump"] = base.dump_buffer(rx, "RX", folder / "received.wav")
                trial["usb_receiver_export_us"] = (time.perf_counter_ns() - export_start) / 1000
                trial["receiver_comparison"] = base.compare_pcm(source, received)
            except (Exception, KeyboardInterrupt) as exc:
                trial["receiver_dump_error"] = str(exc) or type(exc).__name__
        if mode == "GCM" and "tx_done" in trial:
            for side, conn in (("tx", tx), ("rx", rx)):
                try:
                    payload, trial[f"{side}_cipher_dump"] = dump_cipher(conn, folder / f"{side}-ciphertext.bin")
                    if side == "tx": tx_cipher = payload
                    else: rx_cipher = payload
                except (Exception, KeyboardInterrupt) as exc:
                    trial[f"{side}_cipher_dump_error"] = str(exc) or type(exc).__name__

    for field, conn, cursor, event in (
        ("tx_packets", tx, tx_cursor, "tx_packet"), ("rx_packets", rx, rx_cursor, "rx_packet"),
        ("tx_metadata", tx, tx_cursor, "tx_metadata"), ("rx_metadata", rx, rx_cursor, "rx_metadata"),
        ("encrypted_events", tx, tx_cursor, "encrypted"), ("decrypted_events", rx, rx_cursor, "decrypted"),
    ):
        trial[field] = conn.messages_since(cursor, event, message_id)
    trial["encrypted"] = trial["encrypted_events"][-1] if trial["encrypted_events"] else None
    trial["decrypted"] = trial["decrypted_events"][-1] if trial["decrypted_events"] else None
    trial["rx_errors"] = rx.messages_since(rx_cursor, "rx_error")
    trial["rejected_packets"] = rx.messages_since(rx_cursor, "reject")
    completions = rx.messages_since(rx_cursor, "rx_complete", message_id)
    trial["rx_complete"] = completions[-1] if completions else None
    done, complete = trial.get("tx_done", {}), trial.get("rx_complete") or {}
    trial["processing_timing"] = base.audit_processing_timing(trial["tx_packets"], trial["rx_packets"], done, complete, True)
    trial["metadata_accounting"] = metadata_accounting(trial["tx_metadata"], trial["rx_metadata"], tx.hello, expected_metadata, mode == "GCM")
    data_account = base.packet_accounting(trial["tx_packets"], trial["rx_packets"], tx.hello, wire_source, message_id)
    trial["accounting"] = merge_accounting(data_account, trial["metadata_accounting"])
    trial["crypto_timing"] = audit_crypto_events(trial, expected_metadata)
    trial["transport_completion_audit"] = audit_transport_completion(trial)
    verification = {"mode": mode, "host_expected_ciphertext_sha256": hashlib.sha256(wire_source).hexdigest() if mode == "GCM" else None,
                    "host_expected_metadata_hex": expected_metadata.hex() if expected_metadata else None,
                    "tx_ciphertext_exact": tx_cipher == wire_source if mode == "GCM" else None,
                    "rx_ciphertext_exact": rx_cipher == wire_source if mode == "GCM" else None,
                    "ciphertext_differs_from_pcm": wire_source != source if mode == "GCM" else None,
                    "receiver_authenticated": complete.get("authenticated") if mode == "GCM" else None,
                    "key_saved": False}
    verification["valid"] = mode == "PLAIN" or all(verification[field] is True for field in (
        "tx_ciphertext_exact", "rx_ciphertext_exact", "ciphertext_differs_from_pcm", "receiver_authenticated"))
    verification["errors"] = [] if verification["valid"] else ["Host AES-GCM ciphertext/readback/authentication verification failed"]
    trial["crypto_verification"] = verification
    if nonnegative_int(done.get("start_us")) and nonnegative_int(done.get("end_us")) and done["end_us"] >= done["start_us"]:
        trial["sender_local_transfer_us"] = done["end_us"] - done["start_us"]
    if nonnegative_int(done.get("radio_start_us")) and done.get("end_us", 0) >= done["radio_start_us"]:
        trial["sender_radio_window_us"] = done["end_us"] - done["radio_start_us"]
    if all(nonnegative_int(complete.get(field)) for field in ("last_rx_us", "first_rx_us")):
        trial["receiver_local_span_us"] = complete["last_rx_us"] - complete["first_rx_us"]
        if nonnegative_int(complete.get("message_ready_us")) and nonnegative_int(complete.get("first_transport_rx_us")):
            trial["receiver_ready_span_us"] = complete["message_ready_us"] - complete["first_transport_rx_us"]
    if "clock_before" in trial and "clock_after" in trial:
        trial["clock_alignment"] = {c.node["port"]: base.clock_alignment(
            trial["clock_before"][c.node["port"]]["selected_min_rtt"],
            trial["clock_after"][c.node["port"]]["selected_min_rtt"]) for c in (tx, rx)}
    trial["passed"] = (
        not any(trial.get(field) for field in ("error", "cleanup_errors", "clock_after_error", "receiver_dump_error", "tx_cipher_dump_error", "rx_cipher_dump_error", "interrupted"))
        and done.get("success") is True and done.get("acked_chunks") == base.CHUNKS
        and complete.get("received_chunks") == base.CHUNKS
        and trial.get("rx_dump", {}).get("complete") is True
        and trial.get("receiver_comparison", {}).get("byte_exact") is True
        and trial["accounting"]["unique_chunks_received"] == base.CHUNKS
        and trial["accounting"]["unique_chunks_acked"] == base.CHUNKS
        and not trial["accounting"]["invalid_logged_data_crc_events"]
        and trial["processing_timing"]["valid"] and trial["metadata_accounting"]["valid"]
        and trial["crypto_timing"]["valid"] and trial["crypto_verification"]["valid"]
        and trial["transport_completion_audit"]["valid"])
    if mode == "GCM":
        trial["passed"] = trial["passed"] and done.get("metadata_acked") is True
    trial["finished_at"] = base.utc_now()
    (folder / "summary.json").write_text(json.dumps(trial, indent=2) + "\n", encoding="utf-8")
    if not trial["passed"]:
        (folder / "failure.json").write_text(json.dumps(trial, indent=2) + "\n", encoding="utf-8")
    return trial


def preflight(wav):
    _, source = base.read_source(wav)
    firmware = (ROOT / "src/lora_crypto_bench.cpp").read_text(encoding="utf-8")
    if FIRMWARE not in firmware:
        raise RuntimeError("Crypto benchmark firmware source is missing")
    check = host_crypto_selftest()
    if not check["passed"]:
        raise RuntimeError("Host AES-GCM known-answer/tamper self-test failed")
    return {"local_only": True, "ports_opened": False, "source": source,
            "host_crypto_selftest": check, "firmware_required": FIRMWARE}


def save_summary(folder, summary):
    (folder / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wav", type=Path, required=True)
    parser.add_argument("--tx-port", default="COM6")
    parser.add_argument("--rx-port", default="COM7")
    parser.add_argument("--trials-per-mode", type=int, default=10)
    parser.add_argument("--distance-inches", type=float, default=24)
    parser.add_argument("--timeout", type=float, default=240)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--prepare-only", action="store_true", help="Identity/OLED/crypto self-tests only; no LOAD, ARM or TX")
    parser.add_argument("--skip-report", action="store_true", help="Preserve raw results; generate PDF separately")
    args = parser.parse_args(argv)
    if not 1 <= args.trials_per_mode <= 50 or not 0 < args.timeout <= 240 or args.distance_inches <= 0:
        parser.error("Invalid trial count, timeout or separation")
    if args.tx_port.upper() == args.rx_port.upper():
        parser.error("Two distinct serial ports are required")
    if args.check_only:
        print(json.dumps(preflight(args.wav), indent=2))
        return 0
    plan = trial_plan(args.trials_per_mode)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    folder = args.output_dir or ROOT / "captures" / f"{stamp}-heltec-lora-crypto"
    folder.mkdir(parents=True, exist_ok=False)
    summary = {"schema_version": 1, "purpose": "readiness_only" if args.prepare_only else "fresh_plain_vs_aes128gcm_physical_trials",
               "started_at": base.utc_now(), "requested_trials": 0 if args.prepare_only else len(plan),
               "trials_per_mode": args.trials_per_mode, "plan": [] if args.prepare_only else plan,
               "group_order": ["PLAIN", "GCM"], "direction_policy": "Alternate direction within each mode block",
               "distance_inches": args.distance_inches, "distance_basis": "user-reported; not software-measured",
               "physical_radio_only": True, "source_sent_only_to_transmitter": True,
               "nonce_sent_only_to_transmitter": True, "processing_timing_required": True,
               "crypto_algorithm": "AES-128-GCM", "key_bytes": KEY_BYTES, "nonce_bytes": NONCE_BYTES, "tag_bytes": TAG_BYTES,
               "key_handling": "Fresh session key provisioned through USB, commands redacted; key retained in RAM only and not saved",
               "metadata_rf_bytes": METADATA_BYTES, "both_connections_open_together": False,
               "passed": False, "nodes": [], "trials": [], "crypto_selftests": {}}
    connections, result = [], 1
    key = None
    try:
        summary["preflight"] = preflight(args.wav)
        source, summary["source"] = base.read_source(args.wav)
        base.save_wav(folder / "source.wav", source)
        summary["nodes"] = base.discover_nodes([args.tx_port, args.rx_port])
        for node in summary["nodes"]:
            conn = CryptoConnection(node, folder)
            connections.append(conn)
            conn.open()
        summary["both_connections_open_together"] = all(c.serial.is_open for c in connections)
        for conn in connections:
            conn.hello = conn.request("HELLO", "hello")["message"]
            validate_hello(conn.node, conn.hello)
            conn.node["hello"] = conn.hello
            conn.request("STOP", "stopped")
            check = conn.request("CRYPTOSELFTEST", "crypto_selftest", timeout=30)["message"]
            validate_device_selftest(check)
            summary["crypto_selftests"][conn.node["port"]] = check
            conn.request(f"TEST 0 {len(plan)}", "test")
            print(f"{conn.node['label']} / {conn.node['port']}: identity, radio, OLED and AES-GCM self-tests passed", flush=True)
        if args.prepare_only:
            summary["passed"] = True
            result = 0
        else:
            key = secrets.token_bytes(KEY_BYTES)
            summary["crypto_key_fingerprint_sha256"] = hashlib.sha256(key).hexdigest()
            summary["key_setup"] = {}
            for conn in connections:
                record = conn.request(f"KEY {key.hex()}", "key")["message"]
                if record.get("key_ready") is not True or not nonnegative_int(record.get("key_setup_us")):
                    raise RuntimeError("Key setup failed or lacked timing")
                summary["key_setup"][conn.node["port"]] = record
            used_ids, used_nonces = set(), set()
            for entry in plan:
                message_id = secrets.randbelow(65535) + 1
                while message_id in used_ids:
                    message_id = secrets.randbelow(65535) + 1
                used_ids.add(message_id)
                nonce = None
                if entry["mode"] == "GCM":
                    nonce = secrets.token_bytes(NONCE_BYTES)
                    while nonce in used_nonces:
                        nonce = secrets.token_bytes(NONCE_BYTES)
                    used_nonces.add(nonce)
                tx, rx = connections[::-1] if entry["reverse"] else connections
                destination = folder / f"trial-{entry['trial']:02d}-{entry['mode']}-{tx.node['port']}-to-{rx.node['port']}"
                destination.mkdir()
                print(f"Trial {entry['trial']}/{len(plan)} {entry['mode']}: {tx.node['port']} -> {rx.node['port']}, message {message_id}", flush=True)
                trial = run_trial(tx, rx, source, key, nonce, destination, entry, message_id, args.timeout, len(plan))
                trial["directory"] = destination.name
                summary["trials"].append(trial)
                save_summary(folder, summary)
                print(f"  {'PASS' if trial['passed'] else 'FAIL'}: {trial.get('receiver_comparison', {}).get('different_bytes', 'unknown')} differing audio bytes", flush=True)
                if trial.get("interrupted"):
                    raise KeyboardInterrupt
                if not trial["passed"]:
                    raise RuntimeError(f"Trial {entry['trial']} failed; evidence preserved, no replacement trial")
            summary["unique_encryption_nonces"] = len(used_nonces)
            summary["passed"] = len(summary["trials"]) == len(plan) and all(t["passed"] for t in summary["trials"])
            result = 0 if summary["passed"] else 1
    except KeyboardInterrupt:
        summary["error"] = "Interrupted by user"
        result = 130
    except Exception as exc:
        summary["error"] = str(exc)
        print(f"FAIL: {exc}", file=sys.stderr, flush=True)
    finally:
        key = None
        for conn in connections:
            try:
                if conn.serial.is_open:
                    conn.request("STOP", "stopped", timeout=5)
                    summary.setdefault("final_status", {})[conn.node["port"]] = conn.request("STATUS", "status", timeout=5)["message"]
            except (Exception, KeyboardInterrupt) as exc:
                summary.setdefault("cleanup_errors", []).append(str(exc) or type(exc).__name__)
                summary["passed"] = False
                result = result or 1
            try:
                conn.close()
            except (Exception, KeyboardInterrupt) as exc:
                summary.setdefault("close_errors", []).append(str(exc) or type(exc).__name__)
                summary["passed"] = False
                result = result or 1
        summary.update(finished_at=base.utc_now(), connections_closed=all(not c.serial.is_open for c in connections),
                       attempted_trials=len(summary["trials"]), passed_trials=sum(t["passed"] for t in summary["trials"]),
                       not_run_trials=summary["requested_trials"] - len(summary["trials"]))
        save_summary(folder, summary)
        if not summary["passed"]:
            (folder / "failure.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        if not args.prepare_only and not args.skip_report:
            reporter = ROOT / "tools/create_lora_crypto_pdf.py"
            try:
                command = [sys.executable, str(reporter), str(folder.resolve())]
                generated = subprocess.run(command, capture_output=True, text=True, timeout=120)
                summary["report_generation"] = {"command": command, "returncode": generated.returncode,
                                                "stdout": generated.stdout, "stderr": generated.stderr}
                if generated.returncode:
                    raise RuntimeError(generated.stderr or generated.stdout)
            except (Exception, KeyboardInterrupt) as exc:
                summary["report_error"] = str(exc) or type(exc).__name__
                result = result or 1
                print(f"Report generation failed: {summary['report_error']}", file=sys.stderr, flush=True)
            save_summary(folder, summary)
        print(f"Evidence: {folder.resolve()}", flush=True)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
