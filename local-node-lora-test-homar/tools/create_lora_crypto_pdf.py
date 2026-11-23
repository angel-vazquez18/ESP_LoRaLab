"""Offline PDF comparison of fresh PLAIN and AES-128-GCM LoRa bench trials.

No ports are opened and no old run measurements are substituted. The ephemeral
key is deliberately absent from evidence; offline crypto checks reconcile saved
ciphertext/metadata with the independent expected values captured during the run.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import struct
from xml.sax.saxutils import escape
import zlib

from create_lora_consistency_pdf import (
    wav_evidence, packet_audit, processing_audit, serial_logs,
    local_folder, number, difference,
)

MODES = ("PLAIN", "GCM")
PCM_BYTES = 48000
FIRMWARE = "lora-crypto-1-gcm"


def distribution(values):
    values = [v for v in values if number(v) is not None]
    return {"n": len(values), "mean": statistics.mean(values) if values else None,
            "minimum": min(values) if values else None, "maximum": max(values) if values else None}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def elapsed_us(end, start):
    value = difference(end, start)
    return value if value is not None and value >= 0 else None


def read_binary(path):
    try:
        return path.read_bytes()
    except OSError:
        return None


def metadata_audit(trial):
    """Validate the wire envelope separately from GCM authentication claims."""
    tx, rx = trial.get("tx_metadata", []), trial.get("rx_metadata", [])
    errors = []
    mode = trial.get("mode")
    encrypted = trial.get("encrypted") or {}
    expected_hex = (trial.get("crypto_verification") or {}).get("host_expected_metadata_hex")
    expected = None
    if mode == "PLAIN":
        if tx or rx or encrypted:
            errors.append("PLAIN mode contains encryption/metadata events")
    else:
        try:
            expected = bytes.fromhex(expected_hex)
            if len(expected) != 40:
                raise ValueError("Metadata length is not 40 bytes")
            if expected[:8] != struct.pack("<BBHI", 0xfb, 1, trial["id"], PCM_BYTES):
                errors.append("Metadata AAD does not bind the message and length")
            if expected[36:] != struct.pack("<I", zlib.crc32(expected[:36])):
                errors.append("Metadata CRC is invalid")
            if encrypted.get("nonce_hex", "").lower() != expected[8:20].hex():
                errors.append("Nonce differs from encrypted event")
            if encrypted.get("tag_hex", "").lower() != expected[20:36].hex():
                errors.append("Tag differs from encrypted event")
            if encrypted.get("metadata_hex", "").lower() != expected.hex():
                errors.append("Encrypted metadata differs from host expectation")
        except (TypeError, ValueError, KeyError, struct.error) as exc:
            errors.append(f"Missing/invalid expected metadata: {exc}")
        if not tx or not rx or not any(e.get("acked") is True for e in tx):
            errors.append("Metadata delivery/acknowledgement not evidenced")
        if sum(e.get("duplicate") is False for e in rx) != 1:
            errors.append("Metadata must have exactly one unique acceptance")
        if [e.get("attempt") for e in tx] != list(range(1, len(tx) + 1)):
            errors.append("Metadata attempts are not consecutive")
        for stream, events in (("TX", tx), ("RX", rx)):
            for e in events:
                if (expected is None or e.get("id") != trial.get("id")
                        or str(e.get("metadata_hex", "")).lower() != expected.hex()
                        or str(e.get("metadata_crc32", "")).lower() != f"{zlib.crc32(expected[:36]):08x}"):
                    errors.append(f"{stream} metadata event differs from expected envelope")
    return {"valid": not errors, "errors": errors,
            "nonce_hex": expected[8:20].hex() if expected is not None and len(expected) == 40 else None,
            "tx_attempts": len(tx), "retries": max(0, len(tx) - 1),
            "tx_successful_calls": sum(e.get("tx_radio_status", e.get("radio_status")) == 0 for e in tx),
            "ack_successful_calls": sum(e.get("ack_status") == 0 for e in rx),
            "duplicates": sum(e.get("duplicate") is True for e in rx)}


def crypto_audit(trial, folder, source):
    mode = trial.get("mode")
    verification = trial.get("crypto_verification") or {}
    encrypted, decrypted = trial.get("encrypted") or {}, trial.get("decrypted") or {}
    complete, done = trial.get("rx_complete") or {}, trial.get("tx_done") or {}
    errors = []
    enc_us, dec_us = None, None
    wire = source if mode == "PLAIN" else None
    ciphertext_digest = None
    if mode == "PLAIN":
        if (encrypted or decrypted or trial.get("encrypted_events") or trial.get("decrypted_events")
                or done.get("encryption_us") != 0 or complete.get("decryption_us") != 0):
            errors.append("PLAIN mode must report disabled crypto with zero operation time")
        else:
            enc_us = dec_us = 0
    elif mode == "GCM":
        tx_cipher = read_binary(folder / "tx-ciphertext.bin")
        rx_cipher = read_binary(folder / "rx-ciphertext.bin")
        expected_hash = verification.get("host_expected_ciphertext_sha256")
        if (tx_cipher is None or rx_cipher is None or len(tx_cipher) != PCM_BYTES
                or tx_cipher != rx_cipher or digest(tx_cipher) != expected_hash):
            errors.append("Saved TX/RX ciphertext differs or expected cipher hash is missing")
        else:
            wire, ciphertext_digest = tx_cipher, digest(tx_cipher)
            if tx_cipher == source:
                errors.append("Ciphertext unexpectedly equals PCM")
        for key in ("valid", "tx_ciphertext_exact", "rx_ciphertext_exact",
                    "ciphertext_differs_from_pcm", "receiver_authenticated"):
            if verification.get(key) is not True:
                errors.append(f"Live independent crypto verification missing/failed: {key}")
        if not (decrypted.get("authenticated") is True and complete.get("authenticated") is True):
            errors.append("Receiver authentication success not evidenced")
        if decrypted.get("message_ready_us") != complete.get("message_ready_us"):
            errors.append("Authenticated message-ready timestamps disagree")
        if decrypted.get("id") != trial.get("id") or encrypted.get("id") != trial.get("id"):
            errors.append("Crypto event message identity mismatch")
        for name, event, completion, key in (
            ("Encryption", encrypted, done, "encryption_us"),
            ("Decryption", decrypted, complete, "decryption_us"),
        ):
            value = event.get(key)
            if type(value) is not int or value < 0 or completion.get(key) != value:
                errors.append(f"{name} timer missing or inconsistent")
            elif key == "encryption_us":
                enc_us = value
            else:
                dec_us = value
        for key in ("encrypted_events", "decrypted_events"):
            if len(trial.get(key, [])) != 1:
                errors.append(f"Expected exactly one {key} event")
    else:
        errors.append("Unknown mode")
    metadata = metadata_audit(trial)
    errors.extend(metadata["errors"])
    return {"valid": not errors, "errors": errors, "encryption_us": enc_us,
            "decryption_us": dec_us, "ciphertext_sha256": ciphertext_digest,
            "metadata": metadata, "verification_scope": "Offline byte/hash/envelope reconciliation plus saved live host AES-GCM comparison; ephemeral key not saved"}, wire


def memory_record(event, port, role, mode):
    base_requested = number(event.get("allocation_requested_bytes"))
    extra_requested = number(event.get("crypto_buffer_requested_bytes"))
    base_actual = number(event.get("allocation_actual_bytes"))
    extra_actual = number(event.get("crypto_buffer_actual_bytes"))
    return {"port": port, "role": role, "mode": mode,
            "base_requested_bytes": base_requested, "crypto_requested_bytes": extra_requested,
            "total_requested_bytes": base_requested + extra_requested if None not in (base_requested, extra_requested) else None,
            "base_actual_bytes": base_actual, "crypto_actual_bytes": extra_actual,
            "total_actual_bytes": base_actual + extra_actual if None not in (base_actual, extra_actual) else None,
            "psram_decrease_bytes": difference(event.get("psram_before_bytes"), event.get("psram_free_bytes")),
            **{key: number(event.get(key)) for key in (
                "packet_scratch_bytes", "crypto_context_bytes", "crypto_key_bytes", "crypto_metadata_bytes",
                "crypto_library_heap_delta_bytes", "internal_heap_free_bytes", "key_setup_us")}}


def audit_trial(run, trial, source, source_info, hellos, logs):
    reasons = []
    try:
        folder = local_folder(run, trial.get("directory", f"trial-{trial['trial']:02d}"))
        tx_info, tx_pcm = wav_evidence(folder / "sender-before-radio.wav")
        rx_info, rx_pcm = wav_evidence(folder / "received.wav")
    except (ValueError, KeyError) as exc:
        reasons.append(str(exc))
        folder, tx_info, rx_info, tx_pcm, rx_pcm = run, {}, {}, None, None
    exact_tx = tx_pcm is not None and tx_pcm == source and tx_info.get("contract_valid") is True
    exact_rx = rx_pcm is not None and rx_pcm == source and rx_info.get("contract_valid") is True
    if not exact_tx or not exact_rx or source_info.get("contract_valid") is not True:
        reasons.append("Source/sender/receiver PCM equality or format is unverified")
    crypto, wire = crypto_audit(trial, folder, source)
    reasons.extend(crypto["errors"])
    packets = packet_audit(trial, wire)
    if not packets["complete_index_sets"] or not packets["all_logged_crc_valid"]:
        reasons.append("Complete packet index/CRC evidence is missing or inconsistent")
    processing = processing_audit(trial, hellos)
    if not all(p["valid"] for p in processing.values()):
        reasons.append("Chunking/dechunking timer sums are not reconciled")
    done, complete = trial.get("tx_done") or {}, trial.get("rx_complete") or {}
    if done.get("mode") != trial.get("mode") or complete.get("mode") != trial.get("mode"):
        reasons.append("Completion mode differs from planned mode")
    if not (done.get("success") is True and done.get("acked_chunks") == 200
            and complete.get("received_chunks") == 200 and trial.get("rx_dump", {}).get("complete") is True):
        reasons.append("Firmware completion or exported-buffer status missing/failed")
    tx_times = [done.get(k) for k in ("start_us", "radio_start_us", "end_us")]
    rx_times = [complete.get(k) for k in ("first_transport_rx_us", "first_rx_us", "last_rx_us", "message_ready_us")]
    for label, times in (("TX", tx_times), ("RX", rx_times)):
        if not all(type(v) is int and v >= 0 for v in times) or times != sorted(times):
            reasons.append(f"{label} local timing boundaries missing or out of order")
    for key in ("error", "receiver_dump_error", "cleanup_errors", "clock_after_error", "processing_timing_error"):
        if trial.get(key):
            reasons.append(f"{key}: {trial[key]}")
    for port in (trial.get("tx_port"), trial.get("rx_port")):
        h = hellos.get(port, {})
        if h.get("firmware") != FIRMWARE or h.get("crypto_schema") != 1 or h.get("timing_schema") != 1:
            reasons.append(f"{port}: required fresh crypto firmware/schema not evidenced")
    h = hellos.get(trial.get("tx_port"), {})
    data_calls = packets["data_successful_call_bytes"] // 251
    ack_calls = packets["ack_successful_call_bytes"] // 14
    meta = crypto["metadata"]
    def air(calls, key):
        return calls * h[key] if number(h.get(key)) is not None else None
    airtimes = [air(data_calls, "data_airtime_us"), air(ack_calls + meta["ack_successful_calls"], "ack_airtime_us"),
                air(meta["tx_successful_calls"], "metadata_airtime_us")]
    total_air = sum(airtimes) if all(v is not None for v in airtimes) else None
    to_ack = max((p.get("ack_us", 0) for p in trial.get("tx_packets", []) if p.get("acked")), default=0)
    timing = {
        "sender_s": elapsed_us(done.get("end_us"), done.get("start_us")),
        "sender_to_final_ack_s": elapsed_us(to_ack, done.get("start_us")) if to_ack else None,
        "receiver_span_s": elapsed_us(complete.get("last_rx_us"), complete.get("first_rx_us")),
        "receiver_ready_s": elapsed_us(complete.get("message_ready_us"), complete.get("first_transport_rx_us")),
        "airtime_s": total_air,
        "chunking_ms": processing["chunking"].get("total_us"),
        "dechunking_ms": processing["dechunking"].get("total_us"),
        "encryption_ms": crypto["encryption_us"], "decryption_ms": crypto["decryption_us"],
    }
    for key, value in timing.items():
        timing[key] = value / (1000 if key.endswith("_ms") else 1e6) if value is not None else None
    timing["usb_load_s"] = trial["usb_source_load_us"] / 1e6 if number(trial.get("usb_source_load_us")) is not None else None
    timing["usb_export_s"] = trial["usb_receiver_export_us"] / 1e6 if number(trial.get("usb_receiver_export_us")) is not None else None
    timing["metadata_airtime_s"] = (air(meta["tx_successful_calls"], "metadata_airtime_us") + air(meta["ack_successful_calls"], "ack_airtime_us")) / 1e6 if total_air is not None else None
    timing["audio_data_airtime_s"] = airtimes[0] / 1e6 if airtimes[0] is not None else None
    memory = [memory_record(trial.get(f"{role.lower()}_role", {}), trial.get(f"{role.lower()}_port"), role, trial.get("mode")) for role in ("TX", "RX")]
    return {"trial": trial.get("trial"), "mode": trial.get("mode"), "tx_port": trial.get("tx_port"), "rx_port": trial.get("rx_port"),
            "status": "PASS" if not reasons else "FAIL / UNVERIFIED", "reasons": reasons,
            "sender_pcm_exact": exact_tx, "receiver_pcm_exact": exact_rx,
            "source_bytes": len(source) if source is not None else None, "received_bytes": len(rx_pcm) if rx_pcm is not None else None,
            "received_pcm_sha256": rx_info.get("pcm_sha256"), "crypto": crypto, "processing": processing,
            "packets": packets, "timing": timing, "memory": memory,
            "total_retries": packets["retries"] + meta["retries"],
            "wire_payload_bytes": packets["data_successful_call_bytes"] + packets["ack_successful_call_bytes"] + meta["tx_successful_calls"] * 40 + meta["ack_successful_calls"] * 14}


def collect(run):
    run = Path(run).resolve()
    root = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    source_info, source = wav_evidence(run / "source.wav")
    nodes = root.get("nodes", [])
    hellos = {n["port"]: n.get("hello", {}) for n in nodes}
    logs = serial_logs(run, list(hellos))
    trials = [audit_trial(run, t, source, source_info, hellos, logs) for t in root.get("trials", [])]
    warnings = []
    nonces = [t["crypto"]["metadata"]["nonce_hex"] for t in trials if t["mode"] == "GCM"]
    unique_nonces = bool(nonces) and None not in nonces and len(set(nonces)) == len(nonces)
    if nonces and not unique_nonces:
        warnings.append("Encrypted message nonces are missing or repeated")
        for t in trials:
            if t["mode"] == "GCM":
                t["status"] = "FAIL / UNVERIFIED"
                t["reasons"].append("Run-wide nonce uniqueness check failed")
    groups = {}
    for mode in MODES:
        items = [t for t in trials if t["mode"] == mode]
        valid = [t for t in items if t["status"] == "PASS"]
        groups[mode] = {"attempted": len(items), "passed": len(valid), "requested": 10,
                        "direction_counts": dict(Counter(f"{t['tx_port']} > {t['rx_port']}" for t in items)),
                        "timing": {key: distribution(t["timing"][key] for t in valid) for key in (
                            "sender_s", "sender_to_final_ack_s", "receiver_span_s", "receiver_ready_s", "airtime_s",
                            "chunking_ms", "dechunking_ms", "encryption_ms", "decryption_ms", "usb_load_s", "usb_export_s",
                            "metadata_airtime_s", "audio_data_airtime_s")},
                        "memory": {role: {key: distribution(m[key] for t in valid for m in t["memory"] if m["role"] == role)
                            for key in ("base_requested_bytes", "crypto_requested_bytes", "total_requested_bytes", "base_actual_bytes", "crypto_actual_bytes",
                                        "total_actual_bytes", "psram_decrease_bytes", "packet_scratch_bytes", "crypto_context_bytes", "crypto_key_bytes",
                                        "crypto_metadata_bytes", "crypto_library_heap_delta_bytes", "internal_heap_free_bytes", "key_setup_us")} for role in ("TX", "RX")},
                        "retries": sum(t["total_retries"] for t in items),
                        "crc_errors": sum(t["packets"]["rx_crc_errors"] for t in items),
                        "duplicates": sum(t["packets"]["receiver_duplicates"] + t["crypto"]["metadata"]["duplicates"] for t in items),
                        "wire_payload_bytes": distribution(t["wire_payload_bytes"] for t in valid)}
    expected_plan = [(i, "PLAIN" if i <= 10 else "GCM") for i in range(1, 21)]
    plan_valid = [(t["trial"], t["mode"]) for t in trials] == expected_plan
    if not plan_valid:
        warnings.append("Expected 20 ordered trials: 1-10 PLAIN, 11-20 GCM; run incomplete or different")
    if any(sorted(g["direction_counts"].values()) != [5, 5] for g in groups.values()):
        warnings.append("Each mode must contain five trials in each direction")
    selftests = root.get("crypto_selftests", {})
    selftest_keys = ("passed", "known_answer_passed", "wrong_key_rejected", "wrong_tag_rejected", "changed_ciphertext_rejected")
    selftests_valid = len(selftests) == 2 and all(all(v.get(k) is True for k in selftest_keys) for v in selftests.values())
    if not selftests_valid:
        warnings.append("Two successful preflight crypto self-tests not recorded")
    if root.get("connections_closed") is not True:
        warnings.append("Both serial connections not recorded closed")
    build_info = root.get("build_info", {})
    if not build_info and (run / "build-info.json").is_file():
        build_info = json.loads((run / "build-info.json").read_text(encoding="utf-8"))
    return {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(), "run_folder": str(run),
            "started_at": root.get("started_at"), "finished_at": root.get("finished_at"),
            "fixture": bool(root.get("historical_validation_fixture") or root.get("validation_fixture")),
            "distance_inches": root.get("distance_inches", 24), "source": source_info, "nodes": nodes,
            "trials": trials, "groups": groups, "warnings": warnings,
            "selftests": selftests, "nonce_unique": unique_nonces,
            "connections_closed": root.get("connections_closed"), "both_connections_open_together": root.get("both_connections_open_together"),
            "all_twenty_verified": len(trials) == 20 and not warnings and all(t["status"] == "PASS" for t in trials),
            "passed": sum(t["status"] == "PASS" for t in trials), "requested": 20,
            "build_info": build_info, "key_setup": root.get("key_setup", {}),
            "key_fingerprint_sha256": root.get("crypto_key_fingerprint_sha256")}


def fmt(value, digits=3):
    return "--" if number(value) is None else f"{value:,.{digits}f}"


def mean(report, mode, key):
    return report["groups"][mode]["timing"][key]["mean"]


def bytes_label(value):
    return "Not measured" if value is None else f"{value:,.0f} bytes / {value / 1024:.3f} KiB"


class Document:
    def __init__(self, path, report):
        from reportlab.pdfgen import canvas
        from reportlab.lib.colors import HexColor
        self.canvas = canvas.Canvas(str(path), pagesize=(612, 792))
        self.canvas.setTitle("Heltec LoRa: unencrypted versus AES-128-GCM - 20 physical trials")
        self.canvas.setAuthor("LoRa bench report")
        self.report, self.page_number = report, 0
        self.navy, self.gray = HexColor("#17334c"), HexColor("#51657a")
        self.teal, self.purple = HexColor("#087f86"), HexColor("#7c4ca4")
        self.light = HexColor("#f1f5f8")
        self.y = 0

    def text(self, text, size=9.3, gap=8, color=None):
        from reportlab.platypus import Paragraph
        from reportlab.lib.styles import ParagraphStyle
        p = Paragraph(text, ParagraphStyle("body", fontName="Helvetica", fontSize=size,
                      leading=size * 1.35, textColor=color or self.navy))
        _, h = p.wrap(532, 740)
        if self.y - h < 42:
            raise ValueError(f"Page {self.page_number} content exceeds footer: {text[:60]}")
        p.drawOn(self.canvas, 40, self.y - h)
        self.y -= h + gap

    def page(self, title, subtitle):
        if self.page_number:
            self.canvas.showPage()
        self.page_number += 1
        c = self.canvas
        c.setFillColor(self.teal)
        c.rect(0, 784, 612, 8, fill=1, stroke=0)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(40, 752, "HELTEC V4 / LORA ENCRYPTION COMPARISON")
        c.setFillColor(self.navy)
        c.setFont("Helvetica-Bold", 24)
        c.drawString(40, 716, title)
        c.setStrokeColor(self.light)
        c.line(40, 39, 572, 39)
        c.setFillColor(self.gray)
        c.setFont("Helvetica", 7.5)
        footer = Path(self.report["run_folder"]).name
        if self.report["fixture"]:
            footer = "OFFLINE VALIDATION FIXTURE - NOT PHYSICAL TEST RESULTS"
        c.drawString(40, 25, footer)
        c.drawRightString(572, 25, f"{self.page_number} / 7")
        self.y = 695
        self.text(subtitle, 10, 15, self.gray)
        if self.report["fixture"]:
            self.text("<b>OFFLINE VALIDATION FIXTURE - NOT A NEW HARDWARE RUN</b>", 9, 9, self.purple)

    def heading(self, title):
        self.text(f"<b>{title}</b>", 13, 8)

    def table(self, headers, rows, widths, size=8.4, pad=4):
        from reportlab.platypus import Table, TableStyle, Paragraph
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.colors import white, HexColor
        style = ParagraphStyle("cell", fontSize=size, leading=size * 1.25, fontName="Helvetica", textColor=self.navy)
        head = ParagraphStyle("head", parent=style, fontName="Helvetica-Bold", textColor=white)
        cells = [[Paragraph(escape(str(v)).replace("\n", "<br/>"), head if i == 0 else style) for v in row]
                 for i, row in enumerate([headers] + rows)]
        table = Table(cells, colWidths=widths)
        table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), self.navy),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, self.light]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), pad),
            ("RIGHTPADDING", (0, 0), (-1, -1), pad), ("TOPPADDING", (0, 0), (-1, -1), pad),
            ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
            ("LINEBELOW", (0, 1), (-1, -1), 0.3, HexColor("#d4e0e7"))]))
        _, height = table.wrap(532, 740)
        if self.y - height < 45:
            raise ValueError(f"Table on page {self.page_number} overflows: {headers}")
        table.drawOn(self.canvas, 40, self.y - height)
        self.y -= height + 12

    def chart(self, trials):
        c = self.canvas
        height, left, bottom, width = 165, 70, self.y - 185, 490
        values = [t["timing"]["sender_s"] or 0 for t in trials]
        maximum = max(values + [1]) * 1.15
        c.setFont("Helvetica", 7)
        for fraction in (0, 0.25, 0.5, 0.75, 1):
            yy = bottom + height * fraction
            c.setStrokeColor(self.light)
            c.line(left, yy, left + width, yy)
            c.setFillColor(self.gray)
            c.drawRightString(left - 5, yy - 2, f"{maximum * fraction:.0f}s")
        step = width / 20
        for i in range(20):
            t = next((t for t in trials if t["trial"] == i + 1), None)
            x = left + step * i
            value = t["timing"]["sender_s"] if t else None
            c.setFillColor(self.teal if i < 10 else self.purple)
            if value is not None:
                c.rect(x + 3, bottom, step - 6, height * value / maximum, fill=1, stroke=0)
            c.setFillColor(self.gray)
            c.drawCentredString(x + step / 2, bottom - 12, str(i + 1))
        self.y = bottom - 31
        self.text("Teal: trials 1-10, no encryption. Purple: trials 11-20, AES-128-GCM. Each bar includes processing, radio exchange, protocol waits and retries.", 8.4, 12, self.gray)


def make_pdf(path, report):
    d = Document(path, report)
    groups, source, trials = report["groups"], report["source"], report["trials"]
    d.page("20-trial encryption benchmark", f"Fresh run: {escape(str(report['started_at']))}. Voice recording: <b>{fmt(source.get('duration_seconds'),2)} seconds</b>. User-reported separation: approximately {fmt(report['distance_inches'],0)} inches.")
    d.text(f"<b>{report['passed']} / 20 independently verified transfers.</b> Each delivered recording is compared byte for byte with the source after reception and, when enabled, authenticated decryption.", 11)
    d.table(["Mode", "Attempted / planned", "Verified passes", "Retries", "Radio CRC errors"],
        [["Unencrypted", f"{groups['PLAIN']['attempted']} / 10", groups['PLAIN']['passed'], groups['PLAIN']['retries'], groups['PLAIN']['crc_errors']],
         ["AES-128-GCM", f"{groups['GCM']['attempted']} / 10", groups['GCM']['passed'], groups['GCM']['retries'], groups['GCM']['crc_errors']]], [125,112,102,73,120], 9)
    d.heading("Sender transfer duration by trial")
    d.chart(trials)
    d.heading("What stayed the same")
    d.text("Both groups use the same firmware binary, 3-second recording, 200 audio chunks, radio settings and two physical Heltec boards. Each group alternates direction, targeting five transfers each way. The computer loads only the sender; audio reaches the other board over LoRa.")
    d.heading("What encryption adds")
    d.text("AES-128-GCM seals the 48,000 audio bytes once per message. A 12-byte nonce and 16-byte authentication tag travel over LoRa in a 40-byte metadata packet. The receiver reconstructs the ciphertext and releases audio only after authentication succeeds.")
    d.text("This is stored-message delivery at a short bench distance. It is not a real-time conversation or an acoustic speaker test.", 8.5, 6, d.gray)

    d.page("Encrypted versus unencrypted", "Direct comparison from this new run only. Means use verified trials; n is the number of valid observations. Ranges appear in parentheses.")
    rows = []
    comparisons = (
        ("Sender transaction", "sender_s", "s"), ("Receiver DATA span", "receiver_span_s", "s"),
        ("Receiver first transport to ready", "receiver_ready_s", "s"), ("Calculated airtime", "airtime_s", "s"),
        ("Chunking per message", "chunking_ms", "ms"), ("Dechunking per message", "dechunking_ms", "ms"),
        ("Encryption", "encryption_ms", "ms"), ("Decryption + authentication", "decryption_ms", "ms"),
        ("USB source loading", "usb_load_s", "s"), ("USB audio export", "usb_export_s", "s"))
    for label, key, unit in comparisons:
        stats = [groups[m]["timing"][key] for m in MODES]
        entries = [f"{fmt(s['mean'])} (n={s['n']})\n({fmt(s['minimum'])}-{fmt(s['maximum'])})" if s["n"] else "Not measured" for s in stats]
        delta = stats[1]["mean"] - stats[0]["mean"] if stats[0]["n"] and stats[1]["n"] else None
        rows.append([label, *entries, fmt(delta), unit])
    d.table(["Measurement", "Unencrypted", "AES-128-GCM", "Change", "Unit"], rows, [152,133,133,76,38], 8.0, 3.5)
    d.text("Change = encrypted mean minus unencrypted mean. A negative change means the encrypted group happened to finish sooner. It does not mean encryption saved CPU work: radio errors, retries and the sequential test order also affect transfer time.", 8.7)
    d.text("<b>Do not add these times together.</b> Sender and receiver intervals overlap. Crypto and chunk processing happen inside the transfer. Airtime is calculated from successful radio calls; it is already part of elapsed transfer time.", 8.7)
    d.heading("Storage overhead at a glance")
    d.table(["Quantity", "Unencrypted", "AES-128-GCM"], [
        ["Audio / ciphertext content", "48,000 bytes", "48,000 bytes"],
        ["Transport + ACK payload, no retries", "53,000 bytes", "53,054 bytes"],
        ["Additional role buffer in this implementation", "0 bytes", "48,000 requested bytes / 46.875 KiB"],
    ], [210,139,183], 8.2, 4)
    d.text("The extra buffer preserves original and encrypted data for verification. AES-GCM does not intrinsically require a second full audio buffer. Detailed allocator readings are on page 5.", 8.3, 0, d.gray)

    d.page("Processing and crypto timing", "All values below are milliseconds (ms) per message. One millisecond equals 1,000 microseconds. Missing values are shown as --, never as zero.")
    d.table(["Trial", "Mode", "Chunking ms", "Dechunking ms", "Encrypt ms", "Decrypt / auth ms"],
        [[t["trial"], t["mode"], *[fmt(t["timing"][k]) for k in ("chunking_ms", "dechunking_ms", "encryption_ms", "decryption_ms")]] for t in trials],
        [40,54,108,116,101,113], 8.2, 3)
    d.heading("What the timers include")
    d.text("<b>Chunking:</b> sum of 200 first-attempt frame-building and CRC measurements. <b>Dechunking:</b> sum of 200 unique accepted-packet validation and reassembly measurements. Retries reuse the encoded frame; duplicate receive processing is recorded separately.", 9)
    d.text("<b>Encryption / decryption:</b> one whole-message GCM operation on the node. The receiver's timer includes authentication. Key setup is measured separately and is not repeated for every message. Zero in PLAIN means the operation was disabled.", 9)
    setups = [f"{escape(port)}: {fmt(record.get('key_setup_us'))} us" for port, record in report["key_setup"].items()]
    d.text("<b>One-time key setup:</b> " + ("; ".join(setups) + ". One observation per board, outside the 20 message timers." if setups else "No saved key-setup observation."), 8.5)
    d.text("Device timers measure elapsed time, including interrupts or scheduling inside the measured region. They are not pure CPU-cycle counts. Radio waits, ACK handling, OLED calls and serial logging are outside the processing regions. Isolated RAM-write latency was not measured.", 8.6, 0, d.gray)

    d.page("Every trial and its outcome", "Seconds (s) for transfer measurements. Retries include audio and metadata attempts. A successful final recording can include recovered radio errors.")
    d.table(["Trial / mode", "Direction", "TX s", "RX DATA s", "Airtime s", "Retry", "CRC", "Result"],
        [[f"{t['trial']} {t['mode']}", f"{t['tx_port']}>{t['rx_port']}", fmt(t["timing"]["sender_s"]), fmt(t["timing"]["receiver_span_s"]), fmt(t["timing"]["airtime_s"]), t["total_retries"], t["packets"]["rx_crc_errors"], "PASS" if t["status"] == "PASS" else "CHECK"] for t in trials],
        [62,85,73,78,77,43,42,72], 8.0, 3)
    d.heading("Timing boundaries")
    d.text("TX starts before encryption (when enabled) and ends after final radio standby. RX DATA span runs from the first to the last unique audio-packet IRQ. Receiver ready runs from its first transport IRQ (metadata for GCM) through completed reassembly and authentication.", 9)
    d.text("These are local-clock intervals. The boards are not hardware-synchronized, so subtracting their timestamps is not a reliable one-way propagation measurement. USB upload and export are outside the radio transaction.", 9)
    d.heading("Integrity evidence")
    d.text(f"Exact receiver PCM matches: <b>{sum(t['receiver_pcm_exact'] for t in trials)} / {len(trials)}</b>. "
           f"Distinct accepted audio chunks: <b>{sum(t['packets']['unique_received'] for t in trials):,}</b>. "
           f"Encrypted nonces unique within this run: <b>{report['nonce_unique']}</b>. "
           "Per-trial reasons and raw timing totals are preserved in the JSON audit.", 9)

    d.page("Memory and storage", "All memory sizes include explicit units. 1 KiB = 1,024 bytes; 1 MiB = 1,048,576 bytes. Mean values below use verified trials.")
    rows = []
    for mode in MODES:
        for role in ("TX", "RX"):
            m = groups[mode]["memory"][role]
            rows.append([f"{mode} {role}", bytes_label(m["total_requested_bytes"]["mean"]), bytes_label(m["total_actual_bytes"]["mean"]), bytes_label(m["psram_decrease_bytes"]["mean"])])
    d.table(["Mode / role", "Total role request", "Actual role blocks", "Free PSRAM decrease"], rows, [80,148,152,152], 8.1, 4)
    d.text("Total role request = original source/reassembly allocation plus the separate crypto buffer. Allocator block size and the decrease in free PSRAM are different observations; do not add them together.", 8.5)
    rows = []
    for mode in MODES:
        for role in ("TX", "RX"):
            m = groups[mode]["memory"][role]
            rows.append([f"{mode} {role}", bytes_label(m["base_requested_bytes"]["mean"]), bytes_label(m["crypto_requested_bytes"]["mean"]), bytes_label(m["crypto_actual_bytes"]["mean"])])
    d.table(["Mode / role", "Original buffer request", "Extra crypto request", "Extra actual block"], rows, [80,148,152,152], 8.1, 4)
    d.text("TX keeps original PCM plus ciphertext in GCM. RX keeps reconstructed ciphertext plus authenticated plaintext. RX's original object includes the 48,000-byte audio area, 25-byte bitmap, and state/padding. This double-buffer design makes verification straightforward; it is an implementation choice.", 8.5)
    d.heading("Shared firmware costs and board capacities")
    fixed = groups["GCM"]["memory"]["TX"]
    d.table(["Shared quantity", "Reported mean / capacity"], [
        ["Packet scratch (separate from role buffers)", bytes_label(fixed["packet_scratch_bytes"]["mean"])],
        ["GCM context object", bytes_label(fixed["crypto_context_bytes"]["mean"])],
        ["Key / metadata buffer", f"{bytes_label(fixed['crypto_key_bytes']['mean'])} / {bytes_label(fixed['crypto_metadata_bytes']['mean'])}"],
        ["Observed library heap decrease at key setup", bytes_label(fixed["crypto_library_heap_delta_bytes"]["mean"])],
    ], [260,272], 8.0, 3)
    capacity_rows = []
    for n in report["nodes"]:
        h = n.get("hello", {})
        def cap(key):
            v = h.get(key)
            return f"{v:,} bytes / {v / 1048576:g} MiB" if number(v) is not None else "Not reported"
        capacity_rows.append([n.get("port"), cap("psram_total_bytes"), cap("flash_total_bytes")])
    d.table(["Node", "PSRAM capacity", "Flash capacity"], capacity_rows, [70,231,231], 8.1, 4)
    builds = report.get("build_info", {}).get("environments", {})
    if builds:
        d.heading("Same firmware image for both modes")
        build_rows = []
        for env, values in builds.items():
            label = env.replace("heltec_crypto_", "").upper()
            build_rows.append([label] + [bytes_label(values.get(key)) for key in (
                "flash_used_bytes", "static_ram_used_bytes", "firmware_bin_bytes")])
        d.table(["Image", "Firmware flash used", "Static RAM used", "Binary file size"], build_rows,
                [60,158,156,158], 7.8, 3)
    d.text("Both modes use the same binary, so its static crypto code/context is present in both. Flash stores firmware; this test writes no recording to flash. Audio buffers are volatile and lost on reset. Heap observations are not peak RAM, stack use or a complete total of every allocation.", 8.3, 0, d.gray)

    d.page("Audio, packets and protection", "The audio format stays unchanged. Encryption hides the radio audio payload; it does not compress the recording.")
    d.table(["Source property", "Value"], [
        ["Duration / sample count", f"{fmt(source.get('duration_seconds'),2)} seconds / {fmt(source.get('samples'),0)} samples"],
        ["Audio encoding / codec", "Uncompressed signed 16-bit little-endian PCM; 8,000 samples/s; mono. No speech-compression codec."],
        ["Original WAV / raw PCM", f"{fmt(source.get('wav_file_bytes'),0)} bytes / {fmt(source.get('pcm_bytes'),0)} bytes"],
        ["Encryption", "PLAIN: none. GCM: AES-128-GCM; 128-bit key, 96-bit nonce, 128-bit authentication tag."],
    ], [158,374], 9, 5)
    d.heading("Bytes that cross the radio, before retries")
    d.table(["Layer", "Unencrypted", "AES-128-GCM"], [
        ["Audio or encrypted audio content", "48,000 bytes", "48,000 bytes"],
        ["200 DATA frames: 240 content + 7 header + 4 CRC", "50,200 bytes", "50,200 bytes"],
        ["200 DATA acknowledgements", "2,800 bytes", "2,800 bytes"],
        ["Metadata: 8 AAD + 12 nonce + 16 tag + 4 CRC", "0 bytes", "40 bytes"],
        ["Metadata acknowledgement", "0 bytes", "14 bytes"],
        ["Total unique radio payload", "53,000 bytes", "53,054 bytes (+54 bytes)"],
        ["Observed mean payload, including retries", f"{fmt(groups['PLAIN']['wire_payload_bytes']['mean'],1)} bytes", f"{fmt(groups['GCM']['wire_payload_bytes']['mean'],1)} bytes"],
    ], [288,112,132], 8.2, 3.5)
    d.text("Payload counts exclude LoRa preamble, PHY headers, PHY CRC and coding. Calculated airtime includes those radio costs. The additional 54 bytes are metadata plus its ACK; retransmissions can add more.", 8.5)
    d.text(f"<b>Mean airtime components:</b> audio DATA calls: {fmt(mean(report, 'PLAIN', 'audio_data_airtime_s'))} s PLAIN / {fmt(mean(report, 'GCM', 'audio_data_airtime_s'))} s GCM. Metadata plus its ACK: {fmt(mean(report, 'PLAIN', 'metadata_airtime_s'))} s PLAIN / {fmt(mean(report, 'GCM', 'metadata_airtime_s'))} s GCM. The total on page 2 also includes audio DATA acknowledgements.", 8.5)
    d.heading("Source identity is not encryption")
    d.text("PCM SHA-256: <font name='Courier' size='7.4'>" + escape(source.get("pcm_sha256", "Unavailable")) + "</font>", 8.3)
    d.text(f"PCM CRC32: <b>{escape(source.get('pcm_crc32', 'Unavailable'))}</b>. These identify/check the audio; neither hides it. Encryption uses AES-GCM. Clear packet headers and ACKs remain visible; their CRCs are error checks, not authentication.", 8.5)
    d.text("The 8-byte metadata prefix is authenticated as additional data (AAD). The nonce and tag are sent over LoRa. The receiver does not release PCM unless the complete message authenticates. Keys are provisioned over USB for this bench; automatic field key exchange and persistent replay protection are not implemented.", 8.5, 0)

    d.page("Evidence and interpretation", "The report is generated from this run's files. Previous ten-trial results are preserved separately and are not pooled into these averages.")
    d.table(["Node", "Hardware MAC", "Firmware"], [[n.get("port"), n.get("hello", {}).get("mac", "Unknown"), n.get("hello", {}).get("firmware", "Unknown")] for n in report["nodes"]], [70,210,252], 9, 5)
    d.heading("Checks behind a verified result")
    d.text("The computer rereads source, sender and receiver WAV samples and both saved ciphertext buffers. It checks complete packet indices, source/cipher-derived CRCs, metadata envelope bytes and timing sums. During the live run, an independent host AES-GCM implementation computes the expected ciphertext and tag before comparing exported node data.")
    d.text("The ephemeral key is kept out of logs and files. The host key is not retained after the runner exits; STOP leaves the node keys in volatile RAM until reset. Therefore the offline report can recheck the saved bytes/hashes and live verification record, but cannot independently decrypt again without that key. Before the measured trials, each board runs known-answer and rejection checks; these are not counted as radio trials.")
    d.table(["Node self-test", "Saved result"], [[port, "PASS" if result.get("passed") is True else "FAILED / UNVERIFIED"] for port, result in report["selftests"].items()] or [["No saved self-test", "UNVERIFIED"]], [266,266], 9, 5)
    d.heading("Limits on the comparison")
    d.text("Trials 1-10 are unencrypted; trials 11-20 use GCM. The order is blocked, not randomized. Radio conditions and retry counts may change between blocks, so the difference in average transfer time cannot be attributed only to cryptography. The directly measured encryption and decryption timers isolate those operations more closely.")
    d.text("Ten trials per mode at approximately 24 inches demonstrate this bench result. They do not establish long-range reliability, a security audit, or production key management. AES-GCM is a standard authenticated-encryption algorithm; this experiment is a measurement prototype.")
    d.heading("Run record")
    d.text(escape(report["run_folder"]), 8.2)
    d.text(f"UTC: {escape(str(report['started_at']))} to {escape(str(report['finished_at']))}. Both USB handles open together: {report['both_connections_open_together']}. Both closed afterward: {report['connections_closed']}.", 8.5)
    d.text("Raw serial logs, per-trial summaries, WAVs, ciphertext files and the matching JSON audit retain detailed counters, timings, allocation readings and failure reasons. Report generation time (UTC): " + escape(report["generated_at"]), 8.5)
    issues = report["warnings"] + [f"Trial {t['trial']}: " + "; ".join(t["reasons"]) for t in trials if t["status"] != "PASS"]
    d.text("<b>Audit status:</b> " + escape("No audit gaps in the complete twenty-trial dataset." if not issues else "; ".join(issues)[:800]), 8.5)
    d.text("Algorithm reference: <link href='https://mbed-tls.readthedocs.io/projects/api/en/v3.6.7/api/file/gcm_8h/' color='#087f86'>Mbed TLS AES-GCM API documentation</link>. Local firmware and build records identify the actual installed implementation.", 8.2, 0)
    d.canvas.save()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_folder", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = collect(args.run_folder)
    output = args.output or args.run_folder / "crypto-comparison-report.pdf"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    make_pdf(output, report)
    print(json.dumps({"pdf": str(output.resolve()), "audit_json": str(output.with_suffix('.json').resolve()),
                      "passed": report["passed"], "all_twenty_verified": report["all_twenty_verified"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
