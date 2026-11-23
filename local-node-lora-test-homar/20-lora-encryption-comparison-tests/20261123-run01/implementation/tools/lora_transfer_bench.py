"""Transfer an existing 3-second PCM WAV between two physical Heltec radios.

Only the transmitter receives source PCM over USB. The receiver receives ARM
metadata, reconstructs radio packets, and exports its own buffer for comparison.
There is no simulated transport or fallback. Both serial readers remain active.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import struct
import subprocess
import sys
import threading
import time
import wave
import zlib

import serial

from verify_heltec_bench import discover_nodes, normalized_mac


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PCM_BYTES = 48000
SAMPLES = 24000
SAMPLE_RATE = 8000
CHUNKS = 200
CHUNK_BYTES = 240
DATA_PACKET_BYTES = 251
ACK_PACKET_BYTES = 14
REPORT_PYTHON = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe"
TIMING_FIRMWARE = "lora-integrity-3-timing"
OLED_FIRMWARES = {"lora-integrity-2-oled", TIMING_FIRMWARE}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def crc32_hex(data):
    return f"{zlib.crc32(data) & 0xffffffff:08x}"


def read_source(path):
    with wave.open(str(path), "rb") as wav:
        actual = (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(),
                  wav.getnframes(), wav.getcomptype())
        if actual != (1, 2, SAMPLE_RATE, SAMPLES, "NONE"):
            raise RuntimeError(f"Source must be 3 s, 8 kHz, 16-bit mono PCM WAV; got {actual}")
        pcm = wav.readframes(SAMPLES + 1)
    if len(pcm) != PCM_BYTES:
        raise RuntimeError(f"Source PCM is truncated: {len(pcm)}/{PCM_BYTES} bytes")
    return pcm, {
        "path": str(path.resolve()), "wav_file_bytes": path.stat().st_size,
        "wav_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "pcm_bytes": len(pcm), "pcm_crc32": crc32_hex(pcm),
        "pcm_sha256": hashlib.sha256(pcm).hexdigest(),
        "sample_rate_hz": SAMPLE_RATE, "samples": SAMPLES, "channels": 1,
        "bits_per_sample": 16, "duration_seconds": 3,
    }


def save_wav(path, pcm):
    # Preserve a partial reconstruction exactly, including firmware zero fill.
    if len(pcm) % 2:
        raise RuntimeError("Cannot save an incomplete 16-bit sample")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm)


def compare_pcm(source, received):
    common = min(len(source), len(received))
    byte_differences = sum(a != b for a, b in zip(source, received))
    byte_differences += abs(len(source) - len(received))
    common -= common % 2
    first = struct.unpack(f"<{common // 2}h", source[:common])
    second = struct.unpack(f"<{common // 2}h", received[:common])
    differences = [abs(a - b) for a, b in zip(first, second)]
    missing_samples = abs(len(source) // 2 - len(received) // 2)
    return {
        "byte_exact": source == received,
        "source_bytes": len(source), "received_bytes": len(received),
        "different_bytes": byte_differences,
        "compared_samples": len(differences),
        "different_samples": sum(d != 0 for d in differences) + missing_samples,
        "missing_or_extra_samples": missing_samples,
        "max_abs_sample_difference": max(differences, default=0),
        "max_abs_sample_difference_scope": "Samples present in both buffers",
        "source_crc32": crc32_hex(source), "received_crc32": crc32_hex(received),
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "received_sha256": hashlib.sha256(received).hexdigest(),
    }


def validate_hello(node, hello, require_processing_timing=False):
    if normalized_mac(hello.get("mac")) != node["mac_normalized"]:
        raise RuntimeError(f"{node['port']}: firmware MAC does not match USB identity")
    if hello.get("radio_ready") is not True:
        raise RuntimeError(f"{node['port']}: radio is not ready")
    if not hello.get("firmware") or hello.get("boot_id") is None:
        raise RuntimeError(f"{node['port']}: missing firmware/boot identity")
    expected = {
        "frequency_mhz": 915, "bw_khz": 500, "sf": 7, "cr": 5,
        "sync_word": 18, "chip_power_dbm": -9,
        "data_packet_bytes": DATA_PACKET_BYTES, "ack_packet_bytes": ACK_PACKET_BYTES,
    }
    for key, value in expected.items():
        if hello.get(key) != value:
            raise RuntimeError(f"{node['port']}: unexpected {key}={hello.get(key)!r}, expected {value}")
    for key in ("data_airtime_us", "ack_airtime_us"):
        if not isinstance(hello.get(key), (int, float)) or hello[key] <= 0:
            raise RuntimeError(f"{node['port']}: invalid {key}")
    if require_processing_timing and (
            hello.get("firmware") != TIMING_FIRMWARE
            or type(hello.get("timing_schema")) is not int or hello["timing_schema"] != 1):
        raise RuntimeError(f"{node['port']}: processing timing requires {TIMING_FIRMWARE} with timing_schema=1")


def clock_sample(sent_ns, received_ns, device_us, boot_id):
    if received_ns < sent_ns:
        raise ValueError("Host receive timestamp precedes request")
    lower = sent_ns / 1000 - device_us
    upper = received_ns / 1000 - device_us
    return {
        "sent_host_ns": sent_ns, "received_host_ns": received_ns,
        "device_us": device_us, "boot_id": boot_id,
        "rtt_us": (received_ns - sent_ns) / 1000,
        "offset_midpoint_us": (lower + upper) / 2,
        "offset_lower_us": lower, "offset_upper_us": upper,
    }


def clock_alignment(before, after):
    # A consistency check, not hardware synchronization. Envelope bounds assume
    # offset stays within the measured brackets during the enclosed trial.
    overlap = max(before["offset_lower_us"], after["offset_lower_us"]) <= min(
        before["offset_upper_us"], after["offset_upper_us"])
    same_boot = before["boot_id"] == after["boot_id"]
    forward = after["device_us"] > before["device_us"]
    return {
        "stable": same_boot and forward and overlap,
        "same_boot": same_boot, "calibration_intervals_overlap": overlap,
        "offset_lower_us": min(before["offset_lower_us"], after["offset_lower_us"]),
        "offset_upper_us": max(before["offset_upper_us"], after["offset_upper_us"]),
        "offset_midpoint_change_us": after["offset_midpoint_us"] - before["offset_midpoint_us"],
        "assumption": "Device-to-host clock offset remains within pre/post calibration envelope; unsynchronized clocks, not a hard one-way timing guarantee",
    }


def latency_bounds(tx_us, rx_us, tx_alignment, rx_alignment):
    if not tx_alignment["stable"] or not rx_alignment["stable"]:
        return None
    lower = rx_us + rx_alignment["offset_lower_us"] - tx_us - tx_alignment["offset_upper_us"]
    upper = rx_us + rx_alignment["offset_upper_us"] - tx_us - tx_alignment["offset_lower_us"]
    return {"lower_us": lower, "upper_us": upper,
            "midpoint_us": (lower + upper) / 2,
            "meaning": "First TX attempt software timestamp to first accepted RX software timestamp; includes retries, not pure RF propagation"}


def expected_data_crc(source, message_id, index):
    if not 0 <= index < CHUNKS:
        raise ValueError("Invalid chunk index")
    header = struct.pack("<BBHBBB", 0xf9, 1, message_id, index, CHUNKS, CHUNK_BYTES)
    return crc32_hex(header + source[index * CHUNK_BYTES:(index + 1) * CHUNK_BYTES])


def packet_accounting(tx_packets, rx_packets, hello, source=None, message_id=None):
    attempted_indices = {p["index"] for p in tx_packets if 0 <= p.get("index", -1) < CHUNKS}
    acked_indices = {p["index"] for p in tx_packets if p.get("acked") and 0 <= p.get("index", -1) < CHUNKS}
    received_indices = {p["index"] for p in rx_packets if 0 <= p.get("index", -1) < CHUNKS}
    tx_ok = sum(p.get("tx_radio_status", p.get("radio_status")) == 0 for p in tx_packets)
    ack_tx_ok = sum(p.get("ack_status") == 0 for p in rx_packets)
    ack_rx = sum(bool(p.get("acked")) for p in tx_packets)
    bad_crc_events = []
    if source is not None and message_id is not None:
        for side, packets in (("TX", tx_packets), ("RX", rx_packets)):
            for p in packets:
                index = p.get("index", -1)
                if not 0 <= index < CHUNKS or str(p.get("data_crc32", "")).lower() != expected_data_crc(source, message_id, index):
                    bad_crc_events.append({"side": side, "index": index, "reported_crc32": p.get("data_crc32")})
    data_airtime = hello["data_airtime_us"]
    ack_airtime = hello["ack_airtime_us"]
    return {
        "source_pcm_bytes": PCM_BYTES,
        "unique_data_packets_expected": CHUNKS,
        "audio_payload_bytes_per_packet": CHUNK_BYTES,
        "voice_header_bytes_total_no_retries": CHUNKS * 7,
        "application_crc_bytes_total_no_retries": CHUNKS * 4,
        "data_rf_payload_bytes_no_retries": CHUNKS * DATA_PACKET_BYTES,
        "ack_rf_payload_bytes_no_retries": CHUNKS * ACK_PACKET_BYTES,
        "tx_attempts_observed": len(tx_packets),
        "retries_observed": len(tx_packets) - len(attempted_indices),
        "tx_successful_radio_calls": tx_ok,
        "unique_chunks_acked": len(acked_indices),
        "unique_chunks_received": len(received_indices),
        "missing_chunk_indices": sorted(set(range(CHUNKS)) - received_indices),
        "receiver_duplicate_packets": sum(bool(p.get("duplicate")) for p in rx_packets),
        "data_rf_payload_bytes_attempted": len(tx_packets) * DATA_PACKET_BYTES,
        "data_rf_payload_bytes_successful_tx_calls": tx_ok * DATA_PACKET_BYTES,
        "ack_successful_tx_calls": ack_tx_ok,
        "ack_rf_payload_bytes_successful_tx_calls": ack_tx_ok * ACK_PACKET_BYTES,
        "ack_packets_received_by_sender": ack_rx,
        "ack_rf_payload_bytes_received_by_sender": ack_rx * ACK_PACKET_BYTES,
        "invalid_logged_data_crc_events": bad_crc_events,
        "nominal_no_retry_airtime_us": CHUNKS * (data_airtime + ack_airtime),
        "estimated_airtime_successful_radio_calls_us": tx_ok * data_airtime + ack_tx_ok * ack_airtime,
        "airtime_note": "Configured LoRa airtime includes preamble, PHY header, PHY CRC and FEC. Payload byte counts exclude those PHY costs. Failed radio calls have unknown actual airtime; successful calls are not proof of reception.",
    }


def audit_processing_timing(tx_packets, rx_packets, done, complete, required=False):
    """Audit local CPU intervals separately from radio delivery or clock alignment.

    Firmware counts encoding once per chunk (attempt 1), and decoding/acceptance
    once per unique RX chunk. Duplicate RX work is measured but summed separately.
    A partial RF failure may have consistent observations without a complete
    200-chunk timing result. Missing fields are never interpreted as zero time.
    """
    errors, tx_values, rx_values, duplicate_values = [], {}, {}, []
    present = (any("chunking_us" in p for p in tx_packets)
               or any("dechunking_us" in p for p in rx_packets)
               or "chunking_total_us" in done or "dechunking_total_us" in complete)
    inspect = present or required

    def nonnegative_int(value):
        return type(value) is int and value >= 0

    if inspect:
        for ordinal, packet in enumerate(tx_packets):
            index, attempt, elapsed = packet.get("index"), packet.get("attempt"), packet.get("chunking_us")
            if type(index) is not int or not 0 <= index < CHUNKS:
                errors.append(f"TX packet {ordinal}: invalid chunk index")
                continue
            if type(attempt) is not int or attempt < 1 or not nonnegative_int(elapsed):
                errors.append(f"TX packet {ordinal}: missing/invalid attempt or chunking_us")
                continue
            if attempt == 1:
                if index in tx_values:
                    errors.append(f"TX chunk {index}: repeated first-attempt timing")
                else:
                    tx_values[index] = elapsed
            elif elapsed != 0 or index not in tx_values:
                errors.append(f"TX chunk {index}: retry must reuse a measured first attempt and report chunking_us=0")
        for ordinal, packet in enumerate(rx_packets):
            index, duplicate, elapsed = packet.get("index"), packet.get("duplicate"), packet.get("dechunking_us")
            if type(index) is not int or not 0 <= index < CHUNKS:
                errors.append(f"RX packet {ordinal}: invalid chunk index")
                continue
            if type(duplicate) is not bool or not nonnegative_int(elapsed):
                errors.append(f"RX packet {ordinal}: missing/invalid duplicate flag or dechunking_us")
                continue
            if duplicate:
                duplicate_values.append(elapsed)
                if index not in rx_values:
                    errors.append(f"RX chunk {index}: duplicate precedes unique measured acceptance")
            elif index in rx_values:
                errors.append(f"RX chunk {index}: repeated unique-acceptance timing")
            else:
                rx_values[index] = elapsed

    def totals(values, firmware, prefix):
        measured = sum(values.values()) if values else None
        count = firmware.get(f"{prefix}_count")
        elapsed = firmware.get(f"{prefix}_total_us")
        matches = (nonnegative_int(count) and nonnegative_int(elapsed)
                   and count == len(values) and elapsed == sum(values.values()))
        if inspect and firmware:
            if not nonnegative_int(count) or not nonnegative_int(elapsed):
                errors.append(f"{prefix}: missing/invalid firmware count or total")
            elif not matches:
                errors.append(f"{prefix}: firmware count/total differs from packet measurements")
        return {"count": len(values), "total_us": measured,
                "mean_per_packet_us": measured / len(values) if values else None,
                "firmware_count": count, "firmware_total_us": elapsed,
                "totals_match": matches}

    tx = totals(tx_values, done, "chunking")
    rx = totals(rx_values, complete, "dechunking")
    rx.update({"duplicate_count": len(duplicate_values),
               "duplicate_total_us": sum(duplicate_values) if inspect else None,
               "duplicate_mean_per_packet_us": (sum(duplicate_values) / len(duplicate_values)
                                                if duplicate_values else None)})
    full = set(tx_values) == set(range(CHUNKS)) and set(rx_values) == set(range(CHUNKS))
    if required and not present:
        errors.append("Processing timing measurements are missing")
    return {"schema": 1, "required": required, "available": bool(tx_values or rx_values),
            "complete": full, "valid": full and tx["totals_match"] and rx["totals_match"] and not errors,
            "errors": errors, "tx": tx, "rx": rx,
            "scope": "Device-local chunk encoding/CRC and accepted packet decode/reassembly; excludes RF/ACK waits, rejected packets and PHY errors. Duplicate RX processing is separate. Zero microseconds is valid at timer resolution."}


class Connection:
    """One continuous reader, including framed raw DUMP data, per serial port."""

    def __init__(self, node, folder):
        self.node = node
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", node["port"])[:80] or "port"
        self.log = (folder / f"serial-{safe}.log").open("x", encoding="utf-8")
        self.raw = (folder / f"serial-{safe}.bin").open("xb")
        self.log_lock = threading.Lock()
        self.condition = threading.Condition()
        self.events = []
        self.error = None
        self.stop_reader = threading.Event()
        self.thread = None
        self.pending = bytearray()
        self.binary_pending = None
        self.binary_expected = 0
        self.serial = serial.Serial(port=None, baudrate=115200, timeout=0.05, write_timeout=10)
        self.serial.dtr = False
        self.serial.rts = False
        self.serial.port = node["port"]

    def log_record(self, direction, message, host_ns=None):
        entry = {"utc": utc_now(), "host_monotonic_ns": host_ns or time.perf_counter_ns(),
                 "port": self.node["port"], "direction": direction, "message": message}
        with self.log_lock:
            self.log.write(json.dumps(entry, separators=(",", ":")) + "\n")
            self.log.flush()
        return entry

    def open(self):
        self.serial.open()
        self.log_record("HOST", {"event": "opened", "baud": 115200, "dtr": False, "rts": False})
        self.thread = threading.Thread(target=self._read_loop, name=self.node["port"], daemon=True)
        self.thread.start()

    def _append(self, message, host_ns, payload=None):
        event = {"message": message, "host_ns": host_ns}
        if payload is not None:
            event["payload"] = payload
        with self.condition:
            self.events.append(event)
            self.condition.notify_all()

    def _parse(self, data, host_ns):
        self.pending.extend(data)
        while self.pending:
            if self.binary_pending is not None:
                count = min(self.binary_expected - len(self.binary_pending), len(self.pending))
                self.binary_pending.extend(self.pending[:count])
                del self.pending[:count]
                if len(self.binary_pending) < self.binary_expected:
                    return
                payload = bytes(self.binary_pending)
                message = {"event": "host_dump_binary", "bytes": len(payload), "crc32": crc32_hex(payload)}
                self.log_record("RX_BINARY", message, host_ns)
                self._append(message, host_ns, payload)
                self.binary_pending = None
                continue
            position = self.pending.find(b"\n")
            if position < 0:
                if len(self.pending) > 32768:
                    raise RuntimeError("Unterminated serial JSON line exceeds limit")
                return
            raw_line = bytes(self.pending[:position]).rstrip(b"\r")
            del self.pending[:position + 1]
            if not raw_line:
                continue
            text = raw_line.decode("utf-8", errors="replace")
            try:
                message = json.loads(text)
                if not isinstance(message, dict):
                    raise ValueError("Expected JSON object")
            except (ValueError, json.JSONDecodeError):
                self.log_record("RX_TEXT", text, host_ns)
                continue
            self.log_record("RX", message, host_ns)
            self._append(message, host_ns)
            if message.get("event") == "dump_begin":
                if message.get("bytes") != PCM_BYTES:
                    raise RuntimeError(f"Unexpected binary dump length: {message.get('bytes')}")
                self.binary_expected = PCM_BYTES
                self.binary_pending = bytearray()

    def _read_loop(self):
        try:
            while not self.stop_reader.is_set():
                data = self.serial.read(min(max(self.serial.in_waiting, 1), 8192))
                if data:
                    host_ns = time.perf_counter_ns()
                    self.raw.write(data)
                    self.raw.flush()
                    self._parse(data, host_ns)
        except Exception as exc:
            if not self.stop_reader.is_set():
                with self.condition:
                    self.error = exc
                    self.condition.notify_all()

    def cursor(self):
        with self.condition:
            return len(self.events)

    def send(self, command):
        self.log_record("TX", {"command": command})
        data = (command + "\n").encode("ascii")
        sent_ns = time.perf_counter_ns()
        if self.serial.write(data) != len(data):
            raise RuntimeError(f"{self.node['port']}: short command write")
        return sent_ns

    def write_pcm(self, pcm, block_bytes=512):
        if block_bytes != 512:
            raise RuntimeError(f"Unsupported acknowledged LOAD block size: {block_bytes}")
        self.log_record("TX_BINARY", {"bytes": len(pcm), "crc32": crc32_hex(pcm)})
        for start in range(0, len(pcm), block_bytes):
            block = pcm[start:start + block_bytes]
            end = start + len(block)
            cursor = self.cursor()
            self.log_record("TX_BINARY_BLOCK", {"start": start, "received_target": end, "bytes": len(block)})
            if self.serial.write(block) != len(block):
                raise RuntimeError(f"{self.node['port']}: short PCM write")
            self.wait("load_block", cursor, timeout=10,
                      predicate=lambda message: message.get("received") == end)

    def wait(self, event_name, after, timeout=10, predicate=None, progress=None):
        deadline = time.monotonic() + timeout
        progress_cursor = after
        with self.condition:
            while True:
                if progress is not None:
                    for event in self.events[progress_cursor:]:
                        progress(event["message"])
                    progress_cursor = len(self.events)
                for event in self.events[after:]:
                    message = event["message"]
                    if message.get("event") == "error":
                        raise RuntimeError(f"{self.node['port']}: firmware error {message}")
                    if message.get("event") == event_name and (predicate is None or predicate(message)):
                        return event
                if self.error is not None:
                    raise RuntimeError(f"{self.node['port']}: serial reader failed: {self.error}")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError(f"{self.node['port']}: timeout waiting for {event_name}")
                self.condition.wait(min(remaining, 0.25))

    def request(self, command, event_name, timeout=10, predicate=None):
        cursor = self.cursor()
        self.send(command)
        return self.wait(event_name, cursor, timeout, predicate)

    def messages_since(self, cursor, event_name=None, message_id=None):
        with self.condition:
            return [dict(e["message"]) for e in self.events[cursor:]
                    if (event_name is None or e["message"].get("event") == event_name)
                    and (message_id is None or e["message"].get("id") == message_id)]

    def close(self):
        self.stop_reader.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
        try:
            if self.serial.is_open:
                self.serial.close()
            self.log_record("HOST", {"event": "closed"})
        finally:
            self.raw.close()
            self.log.close()


def calibrate_clock(connection, samples=8):
    results = []
    for _ in range(samples):
        token = secrets.randbelow(0x7ffffffe) + 1
        cursor = connection.cursor()
        sent_ns = connection.send(f"TIME {token}")
        reply = connection.wait("time", cursor, predicate=lambda m: m.get("token") == token)
        message = reply["message"]
        results.append(clock_sample(sent_ns, reply["host_ns"], message["time_us"], message["boot_id"]))
    return {"samples": results, "selected_min_rtt": min(results, key=lambda s: s["rtt_us"])}


def dump_buffer(connection, role, destination):
    cursor = connection.cursor()
    connection.send(f"DUMP {role}")
    header = connection.wait("dump_begin", cursor, timeout=15,
                             predicate=lambda m: m.get("role") == role)["message"]
    binary = connection.wait("host_dump_binary", cursor, timeout=20)
    # Save reconstruction before validating trailer/CRC, so partial-failure
    # evidence survives even if the device's metadata is wrong.
    payload = binary["payload"]
    save_wav(destination, payload)
    metadata = dict(header)
    metadata["wav_file"] = destination.name
    metadata["comparison_crc32"] = crc32_hex(payload)
    if metadata["comparison_crc32"] != str(header.get("crc32", "")).lower():
        raise RuntimeError(f"{connection.node['port']}: serial DUMP CRC mismatch")
    connection.wait("dump_end", cursor, timeout=5, predicate=lambda m: m.get("role") == role)
    return payload, metadata


def negative_control_passed(trial, max_attempts):
    """Require bounded RF failure and an untouched, empty receiver buffer."""
    done = trial.get("tx_done", {})
    accounting = trial.get("accounting", {})
    rx_status = trial.get(f"status_{trial['rx_port']}", {})
    packets = trial.get("tx_packets", [])
    return (
        "error" not in trial and not trial.get("cleanup_errors")
        and not trial.get("receiver_dump_error")
        and not trial.get("clock_after_error") and not trial.get("interrupted")
        and "receiver_intentionally_stopped" in trial
        and done.get("success") is False and done.get("cancelled") is False
        and done.get("acked_chunks") == 0 and done.get("attempts") == max_attempts
        and done.get("successful_transmits") == max_attempts
        and done.get("retries") == max_attempts - 1
        and len(packets) == max_attempts
        and [p.get("attempt") for p in packets] == list(range(1, max_attempts + 1))
        and all(p.get("index") == 0 and p.get("acked") is False for p in packets)
        and accounting.get("unique_chunks_received") == 0
        and accounting.get("unique_chunks_acked") == 0
        and accounting.get("tx_successful_radio_calls") == max_attempts
        and not accounting.get("invalid_logged_data_crc_events")
        and rx_status.get("received_chunks") == 0 and rx_status.get("rx_packets") == 0
        and trial.get("rx_complete") is None
        and trial.get("rx_dump", {}).get("complete") is False
        and trial.get("receiver_zero_comparison", {}).get("byte_exact") is True)


def can_continue_after_trial(trial):
    """Continue only a cleanly concluded RF delivery failure, never a broken bench."""
    done = trial.get("tx_done", {})
    if any(trial.get(key) for key in ("error", "cleanup_errors", "receiver_dump_error",
                                    "clock_after_error", "interrupted", "processing_timing_error")):
        return False
    packets = trial.get("tx_packets", [])
    return (
        done.get("success") is False and done.get("cancelled") is False
        and done.get("attempts", 0) > 0 and bool(packets)
        and all(p.get("tx_radio_status", p.get("radio_status")) == 0 for p in packets)
        and all(p.get("radio_status", 0) == 0 for p in packets)
        and not trial.get("accounting", {}).get("invalid_logged_data_crc_events")
        and trial.get("sender_serial_upload_comparison", {}).get("byte_exact") is True
        and trial.get("rx_dump", {}).get("bytes") == PCM_BYTES
        and (trial["rx_dump"].get("complete") is False
             or trial.get("receiver_comparison", {}).get("byte_exact") is True))


def run_trial(tx, rx, source, folder, number, message_id, timeout, negative_control=False,
              oled_progress=False, total_trials=3, require_processing_timing=False):
    trial = {"trial": number, "id": message_id, "tx_port": tx.node["port"],
             "rx_port": rx.node["port"], "started_at": utc_now(), "passed": False,
             "negative_control": negative_control}
    tx_cursor, rx_cursor = tx.cursor(), rx.cursor()
    armed = False
    try:
        for conn in (tx, rx):
            conn.request("STOP", "stopped")
        if oled_progress:
            trial["oled_test"] = {conn.node["port"]: conn.request(
                f"TEST {number} {total_trials}", "test",
                predicate=lambda m: m.get("current") == number and m.get("total") == total_trials)["message"]
                for conn in (tx, rx)}
        trial["tx_role"] = tx.request("ROLE TX", "role", predicate=lambda m: m.get("role") == "TX")["message"]
        trial["rx_role"] = rx.request("ROLE RX", "role", predicate=lambda m: m.get("role") == "RX")["message"]
        cursor = tx.cursor()
        tx.send(f"LOAD {crc32_hex(source)}")
        ready = tx.wait("load_ready", cursor)["message"]
        if ready.get("bytes") != PCM_BYTES:
            raise RuntimeError("Transmitter requested wrong source length")
        if ready.get("block_bytes") != 512:
            raise RuntimeError("Transmitter did not advertise 512-byte acknowledged USB loading")
        tx.write_pcm(source, ready["block_bytes"])
        trial["loaded"] = tx.wait("loaded", cursor, timeout=20)["message"]
        if trial["loaded"].get("bytes") != PCM_BYTES or str(trial["loaded"].get("crc32", "")).lower() != crc32_hex(source):
            raise RuntimeError("Transmitter LOAD length/CRC mismatch")
        sender_pcm, trial["tx_dump"] = dump_buffer(tx, "TX", folder / "sender-before-radio.wav")
        trial["sender_serial_upload_comparison"] = compare_pcm(source, sender_pcm)
        if sender_pcm != source:
            raise RuntimeError("Transmitter buffer differs before any RF transfer")
        trial["clock_before"] = {conn.node["port"]: calibrate_clock(conn) for conn in (tx, rx)}
        trial["armed"] = rx.request(f"ARM {message_id}", "armed", predicate=lambda m: m.get("id") == message_id)["message"]
        armed = True
        if negative_control:
            trial["receiver_intentionally_stopped"] = rx.request("STOP", "stopped")["message"]
        cursor = tx.cursor()
        tx.send(f"TX {message_id}")
        def transfer_progress(message):
            if message.get("event") != "tx_packet" or message.get("id") != message_id:
                return
            if negative_control:
                print(f"  Control TX attempt {message.get('attempt')}: acked={message.get('acked')}", flush=True)
            elif message.get("acked") and (message["index"] + 1) % 25 == 0:
                print(f"  {tx.node['port']} -> {rx.node['port']}: {message['index'] + 1}/{CHUNKS} chunks acknowledged", flush=True)
        trial["tx_done"] = tx.wait("tx_done", cursor, timeout=timeout,
                                    predicate=lambda m: m.get("id") == message_id,
                                    progress=transfer_progress)["message"]
    except KeyboardInterrupt:
        trial["error"] = "Interrupted by user"
        trial["interrupted"] = True
    except Exception as exc:
        trial["error"] = str(exc)
        trial["error_type"] = type(exc).__name__
    finally:
        if armed and "tx_done" in trial and not trial.get("interrupted"):
            try:
                trial["clock_after"] = {conn.node["port"]: calibrate_clock(conn) for conn in (tx, rx)}
            except KeyboardInterrupt:
                trial["interrupted"] = True
                trial.setdefault("error", "Interrupted by user")
            except Exception as exc:
                trial["clock_after_error"] = str(exc)
        for conn in (tx, rx):
            try:
                conn.request("STOP", "stopped", timeout=5)
                trial[f"status_{conn.node['port']}"] = conn.request("STATUS", "status", timeout=5)["message"]
            except (Exception, KeyboardInterrupt) as exc:
                trial.setdefault("cleanup_errors", []).append(str(exc))
                if isinstance(exc, KeyboardInterrupt):
                    trial["interrupted"] = True
        if "rx_role" in trial:
            try:
                receiver_pcm, trial["rx_dump"] = dump_buffer(rx, "RX", folder / "received.wav")
                trial["receiver_comparison"] = compare_pcm(source, receiver_pcm)
                if negative_control:
                    trial["receiver_zero_comparison"] = compare_pcm(bytes(PCM_BYTES), receiver_pcm)
            except (Exception, KeyboardInterrupt) as exc:
                trial["receiver_dump_error"] = str(exc)
                if isinstance(exc, KeyboardInterrupt):
                    trial["interrupted"] = True

    tx_packets = tx.messages_since(tx_cursor, "tx_packet", message_id)
    rx_packets = rx.messages_since(rx_cursor, "rx_packet", message_id)
    trial["tx_packets"] = tx_packets
    trial["rx_packets"] = rx_packets
    trial["rx_errors"] = rx.messages_since(rx_cursor, "rx_error")
    trial["rejected_packets"] = rx.messages_since(rx_cursor, "reject")
    completions = rx.messages_since(rx_cursor, "rx_complete", message_id)
    trial["rx_complete"] = completions[-1] if completions else None
    trial["accounting"] = packet_accounting(tx_packets, rx_packets, tx.hello, source, message_id)
    done = trial.get("tx_done", {})
    complete = trial.get("rx_complete") or {}
    trial["processing_timing"] = audit_processing_timing(
        tx_packets, rx_packets, done, complete, require_processing_timing)
    processing = trial["processing_timing"]
    if require_processing_timing and (processing["errors"] or (
            done.get("success") is True and not processing["valid"])):
        trial["processing_timing_error"] = (
            "; ".join(processing["errors"]) or "A successful transfer requires 200 reconciled TX and RX timing observations")
    if done and done.get("end_us", 0) >= done.get("start_us", 0):
        trial["sender_local_transfer_us"] = done["end_us"] - done["start_us"]
    if complete:
        trial["receiver_local_span_us"] = complete["last_rx_us"] - complete["first_rx_us"]
    trial["packet_timing"] = []
    if "clock_before" in trial and "clock_after" in trial:
        alignments = {conn.node["port"]: clock_alignment(
            trial["clock_before"][conn.node["port"]]["selected_min_rtt"],
            trial["clock_after"][conn.node["port"]]["selected_min_rtt"])
            for conn in (tx, rx)}
        trial["clock_alignment"] = alignments
        for index in range(CHUNKS):
            attempts = [p for p in tx_packets if p.get("index") == index]
            accepted = [p for p in rx_packets if p.get("index") == index and not p.get("duplicate")]
            if attempts and accepted:
                first_tx = min(p["start_us"] for p in attempts)
                first_rx = min(p["rx_us"] for p in accepted)
                bounds = latency_bounds(first_tx, first_rx, alignments[tx.node["port"]], alignments[rx.node["port"]])
                trial["packet_timing"].append({"index": index, "first_attempt_to_accepted_rx": bounds})
    trial["passed"] = (
        "error" not in trial and not trial.get("cleanup_errors")
        and not trial.get("receiver_dump_error")
        and not trial.get("clock_after_error") and not trial.get("interrupted")
        and not trial.get("processing_timing_error")
        and done.get("success") is True and done.get("acked_chunks") == CHUNKS
        and complete.get("received_chunks") == CHUNKS
        and trial.get("rx_dump", {}).get("complete") is True
        and trial.get("receiver_comparison", {}).get("byte_exact") is True
        and trial["accounting"]["unique_chunks_received"] == CHUNKS
        and trial["accounting"]["unique_chunks_acked"] == CHUNKS
        and not trial["accounting"]["invalid_logged_data_crc_events"])
    if negative_control:
        trial["passed"] = negative_control_passed(trial, tx.hello.get("max_attempts", 6))
        trial["control_meaning"] = "Receiver was armed then put in radio standby before sender TX. Expected bounded failure and zero reconstructed PCM; USB never relays source PCM to the receiver."
    trial["failure_class"] = None if trial["passed"] else (
        "interrupted" if trial.get("interrupted") else
        "rf_delivery" if can_continue_after_trial(trial) else "critical_bench_error")
    trial["finished_at"] = utc_now()
    (folder / "summary.json").write_text(json.dumps(trial, indent=2) + "\n", encoding="utf-8")
    if not trial["passed"]:
        (folder / "failure.json").write_text(json.dumps(trial, indent=2) + "\n", encoding="utf-8")
    return trial


def preflight(wav_path, report_python, oled_progress=False, require_processing_timing=False):
    """Local files/dependencies only: no device enumeration, port open or commands."""
    _, source = read_source(wav_path)
    reporter = PROJECT_ROOT / "tools/create_lora_consistency_pdf.py"
    if not reporter.is_file():
        raise RuntimeError(f"Missing PDF reporter: {reporter}")
    if not Path(report_python).is_file():
        raise RuntimeError(f"Report Python is not a file: {report_python}")
    checked = subprocess.run([str(report_python), "-c", "import reportlab, numpy"],
                             capture_output=True, text=True, timeout=30)
    if checked.returncode:
        raise RuntimeError(f"Report dependencies unavailable: {checked.stderr.strip()}")
    firmware = (PROJECT_ROOT / "src/lora_bench.cpp").read_text(encoding="utf-8")
    if "load_block" not in firmware or "block_bytes" not in firmware:
        raise RuntimeError("Firmware source lacks acknowledged USB LOAD protocol")
    if oled_progress and (not any(version in firmware for version in OLED_FIRMWARES) or 'TEST ' not in firmware):
        raise RuntimeError("Firmware source lacks the requested OLED TEST protocol")
    if require_processing_timing and (TIMING_FIRMWARE not in firmware or any(field not in firmware for field in (
            "timing_schema", "chunking_us", "dechunking_us", "chunking_total_us", "dechunking_total_us"))):
        raise RuntimeError("Firmware source lacks the required schema-1 processing timing protocol")
    return {"local_only": True, "ports_opened": False, "source": source,
            "report_python": str(report_python), "oled_protocol_requested": oled_progress,
            "processing_timing_required": require_processing_timing,
            "note": "Checks local source and dependencies; flashed device identity/firmware are checked only when a run starts"}


def generate_reports(folder, report_python):
    command = [str(report_python), str(PROJECT_ROOT / "tools/create_lora_consistency_pdf.py"), str(folder.resolve())]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    record = {"command": command, "returncode": result.returncode,
              "stdout": result.stdout, "stderr": result.stderr}
    (folder / "report-generation.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"Report generation failed ({result.returncode}): {result.stderr.strip()}")
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wav", type=Path, required=True)
    parser.add_argument("--tx-port", default="COM6")
    parser.add_argument("--rx-port", default="COM7")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--alternate", action=argparse.BooleanOptionalAction, default=True,
                        help="Alternate A->B, B->A, A->B (default)")
    parser.add_argument("--negative-control", action="store_true",
                        help="First prove transfer fails with receiver radio intentionally stopped")
    parser.add_argument("--timeout", type=float, default=240,
                        help="Maximum autonomous transfer wait per trial, <=240 seconds")
    parser.add_argument("--output-dir", type=Path, help="New directory only; existing directories are refused")
    parser.add_argument("--oled-progress", action="store_true", help="Set both OLED TEST counters before each trial")
    parser.add_argument("--require-processing-timing", action="store_true",
                        help="Require schema-1 firmware and reconciled chunking/dechunking measurements for successful trials")
    parser.add_argument("--continue-on-failure", action="store_true", help="Continue after ordinary RF delivery failures only")
    parser.add_argument("--distance-inches", type=float, help="User-reported separation; not measured by the software")
    parser.add_argument("--report-python", type=Path, default=REPORT_PYTHON,
                        help="Python executable with reportlab and numpy for automatic final PDF/JSON")
    parser.add_argument("--check-only", action="store_true", help="Check local source/dependencies/protocol only; never open ports")
    args = parser.parse_args(argv)
    if not 1 <= args.trials <= 100 or not 0 < args.timeout <= 240:
        parser.error("--trials must be 1..100 and --timeout must be >0 and <=240")
    if args.distance_inches is not None and args.distance_inches <= 0:
        parser.error("--distance-inches must be positive")
    if args.check_only:
        try:
            print(json.dumps(preflight(args.wav, args.report_python, args.oled_progress,
                                       args.require_processing_timing), indent=2))
            return 0
        except Exception as exc:
            print(f"Preflight failed: {exc}", file=sys.stderr)
            return 1
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    folder = args.output_dir or PROJECT_ROOT / "captures" / f"{stamp}-heltec-lora-transfer"
    folder.mkdir(parents=True, exist_ok=False)
    summary = {"started_at": utc_now(), "requested_ports": [args.tx_port, args.rx_port],
               "requested_trials": args.trials, "alternate": args.alternate,
               "negative_control_requested": args.negative_control,
               "oled_progress": args.oled_progress, "continue_on_failure": args.continue_on_failure,
               "processing_timing_required": args.require_processing_timing,
               "distance_inches": args.distance_inches, "distance_basis": "user-reported; not software-measured",
               "physical_radio_only": True, "source_sent_only_to_transmitter": True,
               "both_connections_open_together": False, "passed": False,
               "nodes": [], "trials": []}
    connections = []
    result = 1
    try:
        summary["preflight"] = preflight(args.wav, args.report_python, args.oled_progress,
                                         args.require_processing_timing)
        source, summary["source"] = read_source(args.wav)
        save_wav(folder / "source.wav", source)
        summary["nodes"] = discover_nodes([args.tx_port, args.rx_port])
        for node in summary["nodes"]:
            connection = Connection(node, folder)
            connections.append(connection)
            connection.open()
        summary["both_connections_open_together"] = all(c.serial.is_open for c in connections)
        for connection in connections:
            hello = connection.request("HELLO", "hello")["message"]
            validate_hello(connection.node, hello, args.require_processing_timing)
            if args.oled_progress and hello.get("firmware") not in OLED_FIRMWARES:
                raise RuntimeError(f"{connection.node['port']}: OLED run requires a supported OLED firmware")
            if args.oled_progress and (hello.get("oled_ready") is not True or hello.get("oled_layout_ok") is not True):
                raise RuntimeError(f"{connection.node['port']}: OLED initialization/layout is not ready")
            connection.hello = hello
            connection.node["hello"] = hello
            print(f"{connection.node['label']} {connection.node['port']}: identity/radio configuration verified", flush=True)
        used_ids = set()
        if args.negative_control:
            message_id = secrets.randbelow(65535) + 1
            used_ids.add(message_id)
            control_folder = folder / "negative-control"
            control_folder.mkdir()
            print("Negative control: receiver radio stopped; expected no delivery", flush=True)
            control = run_trial(connections[0], connections[1], source, control_folder,
                                0, message_id, args.timeout, negative_control=True,
                                oled_progress=args.oled_progress, total_trials=args.trials)
            control["directory"] = control_folder.name
            summary["negative_control"] = control
            (folder / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
            if control.get("interrupted"):
                raise KeyboardInterrupt
            if not control["passed"]:
                raise RuntimeError("Negative control failed its expected bounded-failure/empty-receiver checks")
            print("  PASS: bounded sender failure and empty receiver buffer", flush=True)
        for index in range(args.trials):
            message_id = secrets.randbelow(65535) + 1
            while message_id in used_ids:
                message_id = secrets.randbelow(65535) + 1
            used_ids.add(message_id)
            tx, rx = connections if not (args.alternate and index % 2) else connections[::-1]
            trial_folder = folder / f"trial-{index + 1:02d}-{tx.node['port']}-to-{rx.node['port']}"
            trial_folder.mkdir()
            print(f"Trial {index + 1}/{args.trials}: {tx.node['port']} -> {rx.node['port']}, message {message_id}", flush=True)
            trial = run_trial(tx, rx, source, trial_folder, index + 1, message_id, args.timeout,
                              oled_progress=args.oled_progress, total_trials=args.trials,
                              require_processing_timing=args.require_processing_timing)
            trial["directory"] = trial_folder.name
            summary["trials"].append(trial)
            print(f"  {'PASS' if trial['passed'] else 'FAIL'}: {trial.get('receiver_comparison', {}).get('different_bytes', 'unknown')} differing bytes", flush=True)
            (folder / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
            if trial.get("interrupted"):
                raise KeyboardInterrupt
            if not trial["passed"]:
                if args.continue_on_failure and can_continue_after_trial(trial):
                    print("  RF delivery failed; evidence saved, continuing to the next planned trial", flush=True)
                else:
                    raise RuntimeError(f"Trial {index + 1} failed; receiver evidence and logs saved")
        summary["passed"] = all(trial["passed"] for trial in summary["trials"])
        result = 0 if summary["passed"] else 1
        if not summary["passed"]:
            summary["error"] = "One or more completed trials failed RF delivery"
    except KeyboardInterrupt:
        summary["error"] = "Interrupted by user"
        result = 130
    except Exception as exc:
        summary["error"] = str(exc)
        print(f"FAIL: {exc}", file=sys.stderr, flush=True)
    finally:
        for connection in connections:
            try:
                if connection.serial.is_open:
                    connection.request("STOP", "stopped", timeout=5)
            except (Exception, KeyboardInterrupt) as exc:
                summary.setdefault("final_stop_errors", []).append(f"{connection.node['port']}: {exc}")
                summary["passed"] = False
                if result == 0:
                    result = 1
            try:
                connection.close()
            except (Exception, KeyboardInterrupt) as exc:
                summary.setdefault("close_errors", []).append(str(exc))
                summary["passed"] = False
                if result == 0:
                    result = 1
        summary["finished_at"] = utc_now()
        summary["connections_closed"] = all(not c.serial.is_open for c in connections)
        summary["attempted_trials"] = len(summary["trials"])
        summary["passed_trials"] = sum(bool(trial["passed"]) for trial in summary["trials"])
        summary["not_run_trials"] = args.trials - len(summary["trials"])
        (folder / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        if not summary["passed"]:
            (folder / "failure.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        try:
            summary["report_generation"] = generate_reports(folder, args.report_python)
        except (Exception, KeyboardInterrupt) as exc:
            summary["report_error"] = str(exc) or type(exc).__name__
            if result == 0:
                result = 1
            print(f"Report generation failed: {summary['report_error']}", file=sys.stderr, flush=True)
        (folder / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        if not summary["passed"]:
            (folder / "failure.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"Evidence: {folder.resolve()}", flush=True)
    return result


if __name__ == "__main__":
    sys.exit(main())
