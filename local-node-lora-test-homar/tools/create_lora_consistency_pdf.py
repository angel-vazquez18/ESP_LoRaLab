"""Offline consistency report for saved LoRa trials; never opens serial ports.

Usage: python tools/create_lora_consistency_pdf.py RUN_FOLDER [--output FILE.pdf]
Requires reportlab for PDF rendering. Collection/auditing uses the standard
library. Writes a PDF and a same-stem JSON audit, including partial/failed runs.
The existing three-trial results report is deliberately independent of this tool.
"""
from pathlib import Path
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import statistics
import struct
import wave
from xml.sax.saxutils import escape
import zlib

PCM_BYTES, CHUNKS, CHUNK_BYTES = 48000, 200, 240
STATUS_NAMES = ("PASS", "FAIL", "INCOMPLETE", "NOT RUN")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def wav_evidence(path):
    """Read immutable evidence; an absent/bad file is reported, never synthesized."""
    try:
        with wave.open(str(path), "rb") as handle:
            fmt = {"channels": handle.getnchannels(), "bits_per_sample": handle.getsampwidth() * 8,
                   "sample_rate_hz": handle.getframerate(), "samples": handle.getnframes(),
                   "compression": handle.getcomptype()}
            pcm = handle.readframes(handle.getnframes())
        info = {"file": path.name, "wav_file_bytes": path.stat().st_size, **fmt,
                "pcm_bytes": len(pcm), "pcm_sha256": hashlib.sha256(pcm).hexdigest(),
                "pcm_crc32": f"{zlib.crc32(pcm):08x}",
                "duration_seconds": fmt["samples"] / fmt["sample_rate_hz"]}
        info["contract_valid"] = (fmt["channels"], fmt["bits_per_sample"], fmt["sample_rate_hz"],
                                  fmt["samples"], fmt["compression"], len(pcm)) == (1, 16, 8000, 24000, "NONE", PCM_BYTES)
        return info, pcm
    except (OSError, EOFError, wave.Error, ZeroDivisionError) as exc:
        return {"file": path.name, "error": str(exc)}, None


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def seconds(value):
    return number(value) / 1e6 if number(value) is not None else None


def difference(after, before):
    return after - before if number(after) is not None and number(before) is not None else None


def local_folder(run, relative):
    folder = (run / relative).resolve()
    if not folder.is_relative_to(run.resolve()):
        raise ValueError("Trial evidence directory is outside the run folder")
    return folder


def serial_logs(run, ports):
    result = {}
    for port in ports:
        entries = []
        path = run / f"serial-{port}.log"
        if path.is_file():
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    entry = json.loads(line)
                    if isinstance(entry, dict):
                        entries.append(entry)
                except json.JSONDecodeError:
                    pass  # A truncated serial-log tail is not a fabricated event.
        result[port] = entries
    return result


def host_interval(log, trial, first, last):
    if not trial.get("started_at") or not trial.get("finished_at"):
        return None
    events = [e for e in log if trial["started_at"] <= e.get("utc", "") <= trial["finished_at"]
              and isinstance(e.get("message"), dict)]
    starts = [e.get("host_monotonic_ns") for e in events if e["message"].get("event") == first]
    ends = [e.get("host_monotonic_ns") for e in events if e["message"].get("event") == last]
    if starts and ends and number(starts[0]) is not None and number(ends[-1]) is not None and ends[-1] >= starts[0]:
        return (ends[-1] - starts[0]) / 1e9
    return None


def packet_audit(trial, source):
    tx, rx = trial.get("tx_packets", []), trial.get("rx_packets", [])
    bad, checked = [], 0
    for kind, packets in (("TX", tx), ("RX", rx)):
        for ordinal, event in enumerate(packets):
            index = event.get("index")
            valid_header = (isinstance(index, int) and not isinstance(index, bool)
                            and 0 <= index < CHUNKS and event.get("id") == trial.get("id")
                            and isinstance(event.get("id"), int) and 0 <= event["id"] <= 65535)
            if not valid_header:
                bad.append({"stream": kind, "event": ordinal, "reason": "invalid index/message id"})
            elif source is not None:
                frame = b"\xf9\x01" + struct.pack("<HBBB", event["id"], index, CHUNKS, CHUNK_BYTES)
                expected = f"{zlib.crc32(frame + source[index * CHUNK_BYTES:(index + 1) * CHUNK_BYTES]):08x}"
                checked += 1
                if str(event.get("data_crc32", "")).lower() != expected:
                    bad.append({"stream": kind, "event": ordinal, "index": index, "reason": "source-derived CRC mismatch"})
    tx_indices = {e.get("index") for e in tx if isinstance(e.get("index"), int)}
    acked = {e.get("index") for e in tx if e.get("acked") is True}
    received = {e.get("index") for e in rx}
    tx_ok = sum(e.get("tx_radio_status", e.get("radio_status")) == 0 for e in tx)
    ack_ok = sum(e.get("ack_status") == 0 for e in rx)
    return {"tx_attempts": len(tx), "unique_acked": len(acked), "unique_received": len(received),
            "complete_index_sets": acked == received == set(range(CHUNKS)),
            "retries": max(0, len(tx) - len(tx_indices)),
            "receiver_duplicates": sum(e.get("duplicate") is True for e in rx),
            "checked_crc_events": checked, "invalid_crc_events": bad,
            "all_logged_crc_valid": source is not None and checked == len(tx) + len(rx) and not bad,
            "data_successful_call_bytes": tx_ok * 251, "ack_successful_call_bytes": ack_ok * 14,
            "acknowledged_event_count": sum(e.get("acked") is True for e in tx),
            "rx_crc_errors": sum(e.get("status") == -7 for e in trial.get("rx_errors", []))}


def processing_audit(trial, node_hello):
    """Reconcile device-local measurements independently of host pass flags."""
    result = {}
    for name, port_key, events_key, completion_key, sample_key, total_key, count_key in (
        ("chunking", "tx_port", "tx_packets", "tx_done", "chunking_us", "chunking_total_us", "chunking_count"),
        ("dechunking", "rx_port", "rx_packets", "rx_complete", "dechunking_us", "dechunking_total_us", "dechunking_count"),
    ):
        schema = node_hello.get(trial.get(port_key), {}).get("timing_schema")
        events = trial.get(events_key, [])
        completion = trial.get(completion_key) or {}
        advertised = schema == 1
        present = any(sample_key in e for e in events) or total_key in completion or count_key in completion
        audit = {"schema": schema, "status": "not_recorded", "valid": False, "count": 0,
                 "total_us": None, "mean_per_chunk_us": None, "errors": [],
                 "duplicate_count": 0, "duplicate_total_us": None}
        if not advertised and not present:
            result[name] = audit
            continue
        errors = audit["errors"]
        if not advertised:
            errors.append("Timing schema 1 not advertised by this node")
        selected, duplicates = [], []
        def duration_ok(value):
            return isinstance(value, int) and not isinstance(value, bool) and value >= 0
        for event in events:
            value = event.get(sample_key)
            if not duration_ok(value):
                errors.append(f"Missing/invalid {sample_key} at index {event.get('index')}")
            if name == "chunking":
                if event.get("attempt") == 1:
                    selected.append(event)
                elif isinstance(event.get("attempt"), int) and event["attempt"] > 1:
                    if value != 0:
                        errors.append("TX retry repeats a chunking measurement")
                else:
                    errors.append("Invalid TX attempt number")
            elif event.get("duplicate") is False:
                selected.append(event)
            elif event.get("duplicate") is True:
                duplicates.append(event)
            else:
                errors.append("RX duplicate flag missing or invalid")
        indices = [e.get("index") for e in selected]
        if len(selected) != CHUNKS or set(indices) != set(range(CHUNKS)):
            errors.append("Timing requires all 200 distinct first/unique chunk events")
        values = [e[sample_key] for e in selected if duration_ok(e.get(sample_key))]
        observed_total = sum(values) if len(values) == len(selected) and values else None
        if completion.get(count_key) != len(selected) or not duration_ok(completion.get(count_key)):
            errors.append("Firmware processing count does not match event count")
        if not duration_ok(completion.get(total_key)) or completion.get(total_key) != observed_total:
            errors.append("Firmware processing total does not match event sum")
        audit.update(count=len(selected), firmware_count=completion.get(count_key),
                     firmware_total_us=completion.get(total_key), observed_total_us=observed_total,
                     duplicate_count=len(duplicates),
                     duplicate_total_us=sum(e[sample_key] for e in duplicates) if duplicates and all(duration_ok(e.get(sample_key)) for e in duplicates) else (0 if advertised and not duplicates else None))
        audit["valid"] = not errors
        audit["status"] = "verified" if audit["valid"] else "invalid"
        if audit["valid"]:
            audit.update(total_us=observed_total, mean_per_chunk_us=observed_total / len(selected))
        result[name] = audit
    return result


def audit_trial(run, trial, source, source_info, logs, node_hello=None):
    relative = trial.get("directory", f"trial-{trial['trial']:02d}-{trial.get('tx_port', 'unknown')}-to-{trial.get('rx_port', 'unknown')}")
    reasons = []
    try:
        folder = local_folder(run, relative)
        rx_info, rx_pcm = wav_evidence(folder / "received.wav")
        tx_info, tx_pcm = wav_evidence(folder / "sender-before-radio.wav")
    except ValueError as exc:
        rx_info = tx_info = {"error": str(exc)}
        rx_pcm = tx_pcm = None
    exact_rx = source is not None and rx_pcm is not None and rx_pcm == source and rx_info.get("contract_valid", False)
    exact_tx = source is not None and tx_pcm is not None and tx_pcm == source and tx_info.get("contract_valid", False)
    packets = packet_audit(trial, source if source_info.get("contract_valid") else None)
    flags = (trial.get("tx_done", {}).get("success") is True
             and trial.get("tx_done", {}).get("acked_chunks") == CHUNKS
             and (trial.get("rx_complete") or {}).get("received_chunks") == CHUNKS
             and trial.get("rx_dump", {}).get("complete") is True)
    for key in ("error", "receiver_dump_error", "cleanup_errors"):
        if trial.get(key):
            reasons.append(f"{key}: {trial[key]}")
    if not source_info.get("contract_valid"):
        reasons.append("Original source WAV unavailable or outside the 48,000-byte PCM contract")
    if not exact_tx:
        reasons.append("Sender buffer exact match not verified")
    if not exact_rx:
        reasons.append("Receiver PCM exact match not verified")
    if not packets["complete_index_sets"]:
        reasons.append("All 200 unique receiver/ACK indices not verified")
    if not packets["all_logged_crc_valid"]:
        reasons.append("Source-derived packet CRC verification incomplete or failed")
    if not flags:
        reasons.append("Completed sender/receiver/dump status not verified")
    verified = trial.get("passed") is True and not reasons
    mismatch = (source is not None and any(p is not None and p != source for p in (rx_pcm, tx_pcm))) or bool(packets["invalid_crc_events"])
    explicit_fail = (trial.get("passed") is False and bool(trial.get("finished_at") or trial.get("error")))
    status = "PASS" if verified else "FAIL" if mismatch or explicit_fail or trial.get("error") else "INCOMPLETE"
    done = trial.get("tx_done", {})
    duration = trial.get("sender_local_transfer_us", difference(done.get("end_us"), done.get("start_us")))
    align = trial.get("clock_alignment", {})
    stable = all(align.get(port, {}).get("stable") is True for port in (trial.get("tx_port"), trial.get("rx_port")))
    bounds = [e.get("first_attempt_to_accepted_rx") for e in trial.get("packet_timing", [])]
    bounds = [b for b in bounds if isinstance(b, dict) and all(number(b.get(k)) is not None for k in ("lower_us", "upper_us", "midpoint_us"))]
    if not stable:
        bounds = []
    processing = processing_audit(trial, node_hello or {})
    timing = {"sender_local_seconds": seconds(duration),
              "receiver_span_seconds": seconds(trial.get("receiver_local_span_us")),
              "chunking_processing_seconds": seconds(processing["chunking"]["total_us"]),
              "dechunking_processing_seconds": seconds(processing["dechunking"]["total_us"]),
              "calculated_airtime_seconds": seconds(trial.get("accounting", {}).get("estimated_airtime_successful_radio_calls_us")),
              "usb_upload_host_seconds": host_interval(logs.get(trial.get("tx_port"), []), trial, "load_ready", "loaded"),
              "usb_export_host_seconds": host_interval(logs.get(trial.get("rx_port"), []), trial, "dump_begin", "dump_end"),
              "eligible_packet_estimates": len(bounds),
              "packet_midpoint_median_ms": statistics.median(b["midpoint_us"] for b in bounds) / 1000 if bounds else None,
              "packet_lower_min_ms": min(b["lower_us"] for b in bounds) / 1000 if bounds else None,
              "packet_upper_max_ms": max(b["upper_us"] for b in bounds) / 1000 if bounds else None}
    hello = node_hello or {}
    for role, port_key, packet_key, status_key, unit_key in (
        ("data", "tx_port", "tx_packets", "tx_radio_status", "data_airtime_us"),
        ("ack", "rx_port", "rx_packets", "ack_status", "ack_airtime_us"),
    ):
        unit = number(hello.get(trial.get(port_key), {}).get(unit_key))
        events = trial.get(packet_key)
        calls = sum(e.get(status_key, e.get("radio_status") if role == "data" else None) == 0
                    for e in events) if isinstance(events, list) else None
        timing[f"calculated_{role}_airtime_seconds"] = seconds(calls * unit) if calls is not None and unit is not None else None
    final_acks = [e["ack_us"] for e in trial.get("tx_packets", [])
                  if e.get("acked") is True and number(e.get("ack_us")) is not None]
    timing["sender_to_final_ack_seconds"] = seconds(difference(max(final_acks), done.get("start_us"))) if final_acks and done.get("success") is True else None
    memories = []
    for role, key in (("TX", "tx_role"), ("RX", "rx_role")):
        item = trial.get(key, {})
        if item:
            memories.append({"role": role, "port": trial.get("tx_port" if role == "TX" else "rx_port"),
                             "requested_bytes": item.get("allocation_requested_bytes"),
                             "actual_bytes": item.get("allocation_actual_bytes"),
                             "psram_free_delta_bytes": difference(item.get("psram_before_bytes"), item.get("psram_free_bytes")),
                             "internal_heap_free_delta_bytes": difference(item.get("internal_heap_before_bytes"), item.get("internal_heap_free_bytes")),
                             "scratch_bytes": item.get("packet_scratch_bytes"),
                             "bitmap_bytes": item.get("chunker_bitmap_bytes"), "storage": item.get("allocation_storage")})
    rssis = [e["rssi_dbm"] for e in trial.get("rx_packets", []) if number(e.get("rssi_dbm")) is not None]
    snrs = [e["snr_db"] for e in trial.get("rx_packets", []) if number(e.get("snr_db")) is not None]
    for name, audit in processing.items():
        if audit['status'] == 'invalid':
            reasons.append(f"{name} timing invalid: " + '; '.join(audit['errors']))
            if status == 'PASS':
                status = 'INCOMPLETE'
    return {"trial": trial["trial"], "directory": relative, "tx_port": trial.get("tx_port", "?"),
            "rx_port": trial.get("rx_port", "?"), "status": status, "recorded_passed": trial.get("passed"),
            "reasons": reasons, "sender_pcm_exact": exact_tx, "received_pcm_exact": exact_rx,
            "sender_wav": tx_info, "received_wav": rx_info, "packets": packets, "timing": timing, "memory": memories,
            "oled_test": trial.get("oled_test", {}), "processing": processing,
            "rssi_dbm_range": [min(rssis), max(rssis)] if rssis else None,
            "snr_db_range": [min(snrs), max(snrs)] if snrs else None}


def distribution(values):
    """Equal-weight observations; missing measurements are never zero-imputed."""
    values = [v for v in values if number(v) is not None]
    return {"n": len(values), "mean": statistics.mean(values) if values else None,
            "minimum": min(values) if values else None, "maximum": max(values) if values else None}


def aggregate(trials):
    timing_keys = ("sender_local_seconds", "receiver_span_seconds", "sender_to_final_ack_seconds",
                   "calculated_airtime_seconds", "calculated_data_airtime_seconds", "calculated_ack_airtime_seconds",
                   "usb_upload_host_seconds", "usb_export_host_seconds",
                   "chunking_processing_seconds", "dechunking_processing_seconds")
    memory_keys = ("requested_bytes", "actual_bytes", "psram_free_delta_bytes", "scratch_bytes")
    return {
        "basis": "Arithmetic mean per attempted trial with an available measurement; missing values excluded; n gives each denominator.",
        "attempted_trials": len(trials),
        "timing": {key: distribution(t["timing"].get(key) for t in trials) for key in timing_keys},
        "memory_by_role": {role: {key: distribution(m.get(key) for t in trials for m in t["memory"] if m["role"] == role)
                                  for key in memory_keys} for role in ("TX", "RX")},
        "packet_bytes": {key: distribution(t["packets"].get(key) for t in trials)
                         for key in ("data_successful_call_bytes", "ack_successful_call_bytes")},
    }


def collect(run):
    run = Path(run).resolve()
    warnings = []
    try:
        summary = read_json(run / "summary.json")
    except (OSError, json.JSONDecodeError) as exc:
        summary = {}
        warnings.append(f"Run summary unavailable: {exc}")
    requested = summary.get("requested_trials", 10)
    if not isinstance(requested, int) or isinstance(requested, bool) or requested < 1:
        requested = 10
        warnings.append("Invalid requested trial count; displayed preparation default of 10")
    entries = {}
    for entry in summary.get("trials", []):
        if isinstance(entry, dict) and isinstance(entry.get("trial"), int) and entry["trial"] > 0 and not entry.get("negative_control"):
            entries[entry["trial"]] = entry
    for path in sorted(run.glob("trial-*/summary.json")):
        try:
            entry = read_json(path)
            idx = entry.get("trial")
            if isinstance(idx, int) and idx > 0 and not entry.get("negative_control") and idx not in entries:
                entries[idx] = {**entry, "directory": path.parent.name}
                warnings.append(f"Recovered trial {idx} from its folder summary")
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"Unreadable trial summary {path.parent.name}: {exc}")
    if len(entries) > requested or any(i > requested for i in entries):
        warnings.append("Saved trial numbering exceeds requested count; retained all evidence in JSON")
    source_info, source = wav_evidence(run / "source.wav")
    ports = summary.get("requested_ports") or sorted({e.get(k) for e in entries.values() for k in ("tx_port", "rx_port") if e.get(k)})
    logs = serial_logs(run, ports)
    hello = {node.get("port"): node.get("hello", {}) for node in summary.get("nodes", [])}
    trials = [audit_trial(run, entries[i], source, source_info, logs, hello) for i in sorted(entries)]
    required = summary.get('processing_timing_required') is True
    for trial in trials:
        if required and not all(a['valid'] for a in trial['processing'].values()):
            trial['reasons'].append('This run requires verified chunking and dechunking timing')
            if trial['status'] == 'PASS':
                trial['status'] = 'INCOMPLETE'
    tally = Counter(t["status"] for t in trials)
    counts = {"requested": requested, "attempted": len(trials), "passed": tally["PASS"], "failed": tally["FAIL"],
              "incomplete": tally["INCOMPLETE"], "not_run": max(0, requested - len(trials))}
    per_direction = {}
    plan = []
    for i in range(1, requested + 1):
        pair = ports[:2] if len(ports) >= 2 else ["?", "?"]
        if summary.get("alternate") and i % 2 == 0:
            pair = pair[::-1]
        actual = next((t for t in trials if t["trial"] == i), None)
        tx, rx = (actual["tx_port"], actual["rx_port"]) if actual else pair
        status = actual["status"] if actual else "NOT RUN"
        plan.append({"trial": i, "tx_port": tx, "rx_port": rx, "status": status})
        key = f"{tx} to {rx}"
        bucket = per_direction.setdefault(key, {"requested": 0, "attempted": 0, "passed": 0, "failed": 0, "incomplete": 0, "not_run": 0})
        bucket["requested"] += 1
        bucket[{"PASS": "passed", "FAIL": "failed", "INCOMPLETE": "incomplete", "NOT RUN": "not_run"}[status]] += 1
        bucket["attempted"] += status != "NOT RUN"
    errors = [f"{k}: {summary[k]}" for k in ("error", "close_errors") if summary.get(k)]
    passed = (counts["passed"] == requested == counts["attempted"] and not warnings and not errors
              and summary.get("passed") is True and summary.get("connections_closed") is True)
    distance = number(summary.get("distance_inches"))
    if distance is None or distance <= 0:
        distance = 24
    return {"schema_version": 3, "generated_at": datetime.now(timezone.utc).isoformat(),
            "run_folder": str(run), "historical_validation_fixture": summary.get("historical_validation_fixture", False),
            "fixture_note": summary.get("fixture_note"), "requested_trials": requested,
            "counts": counts, "per_direction": per_direction, "plan": plan, "trials": trials,
            "averages": aggregate(trials),
            "processing_timing_required": required,
            "all_processing_timing_verified": len(trials) == requested and all(t['processing'][name]['valid'] for t in trials for name in ('chunking','dechunking')),
            "all_requested_trials_verified": passed, "recorded_run_passed": summary.get("passed"),
            "distance_inches": distance, "distance_basis": "User-reported; not measured from radio signal strength",
            "source": source_info, "nodes": summary.get("nodes", []),
            "physical_capacity": [{"port": node.get("port", "?"),
                                   "flash_total_bytes": number(node.get("hello", {}).get("flash_total_bytes")),
                                   "psram_total_bytes": number(node.get("hello", {}).get("psram_total_bytes"))}
                                  for node in summary.get("nodes", [])],
            "audio_storage": "PCM is held in volatile PSRAM; device flash is not used to store the recording in this bench.",
            "run_errors": errors, "warnings": warnings,
            "negative_control": {"requested": summary.get("negative_control_requested", False),
                                 "recorded_passed": (summary.get("negative_control") or {}).get("passed"),
                                 "meaning": "Receiver-off control is separate from the positive trial count; passing it means expected failure, not audio delivery."},
            "connections_closed": summary.get("connections_closed"),
            "both_connections_open_together": summary.get("both_connections_open_together"),
            "started_at": summary.get("started_at"), "finished_at": summary.get("finished_at"),
            "measurement_limits": ["Processing timing uses device-local elapsed microseconds around instrumented chunking/reassembly code. It includes timer and scheduling overhead; it is not pure CPU-cycle time. Missing or inconsistent measurements are excluded.",
                "TX duration uses the sender's local clock; RX span uses the receiver's local clock.",
                "USB host intervals include serial transport, buffering and acknowledgements, not pure memory-write time.",
                "Cross-device packet estimates assume the device-to-host offset stays inside pre/post calibration envelopes; they are not guaranteed one-way latency or pure RF propagation.",
                "Configured airtime is calculated, not directly measured on air; successful TX calls alone do not prove reception.",
                "OLED firmware status does not prove visible screen content. Acoustic playback and long-distance reliability are outside this test."]}


def fmt(value, places=3):
    return "--" if number(value) is None else f"{value:,.{places}f}"


def bytes_kib(value):
    return "Unknown" if number(value) is None else f"{value:,.0f} bytes / {value / 1024:.3f} KiB"


def make_pdf(path, report):
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfgen import canvas
    from reportlab.platypus import Paragraph, Table, TableStyle

    navy, teal, red = (colors.HexColor(x) for x in ("#17324D", "#087F82", "#B54137"))
    amber, gray, light, grid = (colors.HexColor(x) for x in ("#B77916", "#56697A", "#F1F5F8", "#D9E2EA"))
    palette = {"PASS": teal, "FAIL": red, "INCOMPLETE": amber, "NOT RUN": colors.HexColor("#AAB6C2")}
    W, H, M, CW = 612, 792, 40, 532
    c = canvas.Canvas(str(path), pagesize=(W, H), pageCompression=1)
    c.setTitle("Heltec LoRa consistency - saved evidence")
    c.setAuthor("ESP32 audio chunker bench")
    page_count = 6 if report["trials"] else 2
    page_no = 0

    def text(value, y, size=10, x=M, width=CW, bold=False, color=navy):
        p = Paragraph(value, ParagraphStyle("body", fontName="Helvetica-Bold" if bold else "Helvetica",
                      fontSize=size, leading=size * 1.36, textColor=color))
        _, h = p.wrap(width, H)
        if y-h < 47:
            raise ValueError(f"Report page {page_no} overflow: {value[:100]}")
        p.drawOn(c, x, y-h)
        return y-h

    def page(title, subtitle):
        nonlocal page_no
        if page_no:
            c.showPage()
        page_no += 1
        c.setFillColor(teal); c.rect(0, H-8, W, 8, fill=1, stroke=0)
        text("HELTEC V4  /  LORA CONSISTENCY", 760, 9, color=teal, bold=True)
        text(title, 738, 24, bold=True)
        y = text(subtitle, 700, 10, color=gray) - 18
        if report["historical_validation_fixture"]:
            c.setFillColor(colors.HexColor("#FFF3DA")); c.rect(M, y-28, CW, 28, fill=1, stroke=0)
            text("HISTORICAL VALIDATION FIXTURE - no new radio measurements", y-7, 9, x=M+9, width=CW-18, color=amber, bold=True)
            y -= 41
        c.setStrokeColor(grid); c.line(M, 40, W-M, 40)
        c.setFillColor(gray); c.setFont("Helvetica", 8)
        name = Path(report["run_folder"]).name
        c.drawString(M, 26, name[:64])
        c.drawRightString(W-M, 26, f"{page_no} / {page_count}")
        return y

    def heading(value, y):
        return text(value, y, 13, bold=True) - 8

    def table(headers, rows, widths, y, size=9, padding=6):
        if abs(sum(widths)-CW) > .01:
            raise ValueError("Table columns exceed report width")
        def cell(value, head=False):
            return Paragraph(escape(str(value)), ParagraphStyle("cell", fontName="Helvetica-Bold" if head else "Helvetica",
                             fontSize=size, leading=size*1.25, textColor=colors.white if head else navy))
        t = Table([[cell(v, True) for v in headers]] + [[cell(v) for v in row] for row in rows], colWidths=widths)
        t.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), navy), ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white,light]),
                              ("VALIGN", (0,0), (-1,-1), "TOP"), ("LEFTPADDING", (0,0),(-1,-1),7),
                              ("RIGHTPADDING", (0,0),(-1,-1),7), ("TOPPADDING",(0,0),(-1,-1),padding),
                              ("BOTTOMPADDING",(0,0),(-1,-1),padding), ("LINEBELOW",(0,1),(-1,-1),.4,grid)]))
        _, h = t.wrap(CW,H)
        if y-h < 47:
            raise ValueError(f"Report table on page {page_no} overflows")
        t.drawOn(c,M,y-h)
        return y-h-14

    def note(value, y):
        return text(value,y,9.5,color=gray)-13

    def count_chart(y):
        counts=report["counts"]
        mapping=(("PASS","passed"),("FAIL","failed"),("INCOMPLETE","incomplete"),("NOT RUN","not_run"))
        x=M; total=max(1,counts["requested"],counts["attempted"])
        for status,key in mapping:
            width=CW*counts[key]/total
            if width:
                c.setFillColor(palette[status]);c.rect(x,y-24,width,24,fill=1,stroke=0)
                if width>22:
                    c.setFillColor(colors.white);c.setFont("Helvetica-Bold",11);c.drawCentredString(x+width/2,y-17,str(counts[key]))
                x+=width
        for i,(status,key) in enumerate(mapping):
            x=M+i*(CW/4);c.setFillColor(palette[status]);c.rect(x,y-44,7,7,fill=1,stroke=0)
            text(f"{status}: {counts[key]}",y-35,8.4,x=x+12,width=CW/4-14)
        return y-62

    def duration_chart(y):
        height=157; bottom=y-height+25; left=M+35; width=CW-45; plot_h=height-44
        values={t["trial"]:t for t in report["trials"]}
        durations=[t["timing"]["sender_local_seconds"] for t in values.values() if t["timing"]["sender_local_seconds"] is not None]
        maximum=max(durations)*1.18 if durations and max(durations)>0 else 1
        c.setFont("Helvetica",8);c.setStrokeColor(grid)
        for fraction in (0,.5,1):
            yy=bottom+fraction*plot_h;c.line(left,yy,left+width,yy)
            c.setFillColor(gray);c.drawRightString(left-7,yy-3,f"{fraction*maximum:.1f}")
        n=min(report["requested_trials"],10)
        for i in range(1,n+1):
            t=values.get(i);v=t["timing"]["sender_local_seconds"] if t else None
            xx=left+(i-.5)*width/max(n,1); bw=min(28,width/max(n,1)*.58)
            if v is not None:
                c.setFillColor(palette[t["status"]]);c.rect(xx-bw/2,bottom,bw,v/maximum*plot_h,fill=1,stroke=0)
                c.setFillColor(navy);c.drawCentredString(xx,bottom+v/maximum*plot_h+5,f"{v:.2f}")
            else:
                c.setStrokeColor(palette[t["status"] if t else "NOT RUN"]);c.line(xx-4,bottom+3,xx+4,bottom+3)
            c.setFillColor(gray);c.drawCentredString(xx,bottom-13,str(i))
        text("Seconds",y,8,color=gray)
        return y-height-3

    counts=report["counts"]
    y=page("Consistency results", f"Run started: {escape(str(report['started_at']))}. Saved evidence from this run only.")
    verdict="All requested trials verified" if report["all_requested_trials_verified"] else "Requested run is not fully verified"
    y=text(verdict,y,16,bold=True,color=teal if report["all_requested_trials_verified"] else amber)-7
    y=text(f"<b>{counts['requested']} requested / {counts['attempted']} attempted / {counts['passed']} passed</b>. "
           f"{counts['failed']} failed, {counts['incomplete']} incomplete or unverified, {counts['not_run']} not run.",y)-16
    y=count_chart(y)
    y=table(["Direction","Requested","Attempted","Pass","Fail","Incomplete","Not run"],
            [[key]+[v[k] for k in ("requested","attempted","passed","failed","incomplete","not_run")] for key,v in report["per_direction"].items()],
            [142,62,62,44,44,99,79],y,8.5)
    y=heading("Sender transfer duration by trial",y)
    y=duration_chart(y)
    y=note("Bars use the sender's local start-to-end duration, including protocol waits and retries. A dash means no saved duration, not zero seconds. Bar colors use the audited outcome above.",y)
    y=heading("Bench context",y)
    source=report["source"]
    y=text(f"Distance: approximately <b>{report['distance_inches']:g} inches</b> ({report['distance_inches']*2.54:.2f} cm), user-reported. "
           "The computer loads the sender and exports the receiver; it does not relay the audio between boards. "
           "This report cannot independently prove physical separation from files.",y)-10
    y=text(f"Source: {fmt(source.get('duration_seconds'))} s; {fmt(source.get('pcm_bytes'),0)} PCM bytes. "
           f"Both USB connections recorded open together: {report['both_connections_open_together']}. "
           f"Connections recorded closed: {report['connections_closed']}.",y,9.5)

    if report["trials"]:
        averages = report["averages"]
        y=page("Average values at a glance", f"<b>Voice recording: {fmt(source.get('duration_seconds'),2)} seconds per message.</b> "
               f"{counts['attempted']} attempted trials; ~{report['distance_inches']:g} inches; n = sample count.")
        y=text("<b>Airtime is included in TX time.</b> TX and RX overlap; do not add these intervals.",y,10)-12
        rows=[]
        for label,key,meaning in (
            ("Sender transaction", "sender_local_seconds", "Sender start to completion; includes waits and retries."),
            ("Receiving interval", "receiver_span_seconds", "First to last unique accepted packet; excludes initial packet airtime and final ACK."),
            ("Delivery confirmed", "sender_to_final_ack_seconds", "Sender start to receipt of the last acknowledgement (ACK)."),
            ("Combined airtime", "calculated_airtime_seconds", "Calculated DATA + ACK radio time, including retries and duplicate ACKs."),
            ("DATA airtime", "calculated_data_airtime_seconds", "Configured packet airtime x successful data transmit calls."),
            ("ACK airtime", "calculated_ack_airtime_seconds", "Configured packet airtime x successful ACK transmit calls."),
            ("USB source loading", "usb_upload_host_seconds", "Host-observed load_ready to loaded; before radio transmission."),
            ("USB receiver export", "usb_export_host_seconds", "Host-observed dump_begin to dump_end; after radio reception."),
            ("Chunking total", "chunking_processing_seconds", "Sum of 200 first-attempt packet-building measurements per message."),
            ("Dechunking total", "dechunking_processing_seconds", "Sum of 200 unique accepted-packet reassembly measurements; duplicates excluded."),
        ):
            stats=averages["timing"][key]
            scale,unit=(1000,"ms") if key in ("chunking_processing_seconds","dechunking_processing_seconds") else (1,"s")
            mean=f"{fmt(stats['mean']*scale)} {unit}" if stats['n'] else "Not measured"
            span=f"{fmt(stats['minimum']*scale)} - {fmt(stats['maximum']*scale)} {unit}" if stats['n'] else "Not available"
            rows.append([label, mean, span, f"n={stats['n']}. {meaning}"])
        y=table(["Measurement", "Mean", "Range / unit", "What it measures"],rows,[112,72,109,239],y,8.4,padding=2.5)
        y=text("<b>Processing values use milliseconds (ms); transfer values use seconds (s).</b> Means use only verified measurements, with n as their denominator. Missing does not mean zero. See the Processing measurements page for scope and per-trial values.",y,8.6,color=gray)-8
        y=heading("Average memory reserved per message",y)
        rows=[]
        for role,label in (("TX","Transmitter"),("RX","Receiver")):
            values=averages["memory_by_role"][role]
            rows.append([label]+[f"{bytes_kib(values[key]['mean'])} (n={values[key]['n']})" for key in ("requested_bytes","actual_bytes","psram_free_delta_bytes","scratch_bytes")])
        y=table(["Role", "Requested", "Allocated block", "PSRAM decrease", "Scratch"],rows,[70,114,116,122,110],y,8.1,padding=4)
        y=text("1 KiB = 1,024 bytes. RX includes PCM, a 25-byte bitmap and state/padding. Requested size, allocator block and free-memory decrease are separate readings; scratch is separate from the audio buffer.",y,8.6,color=gray)-8
        capacities=report['physical_capacity']
        y=text("Board capacities are reported on the Timing and memory page. Audio is held in volatile PSRAM; device flash is not used for the recording.",y,8.6)-10
        total_unique=sum(t['packets']['unique_received'] for t in report['trials'])
        retries=sum(t['packets']['retries'] for t in report['trials'])
        errors=sum(t['packets']['rx_crc_errors'] for t in report['trials'])
        duplicates=sum(t['packets']['receiver_duplicates'] for t in report['trials'])
        exact=sum(t['received_pcm_exact'] for t in report['trials'])
        y=text(f"<b>{counts['passed']}/{counts['requested']} verified passes; {exact} exact PCM matches.</b> {total_unique:,} unique chunks; {retries} retries; {errors} receiver CRC errors; {duplicates} duplicates.",y,8.6)-8
        y=text("<b>Audio encoding: uncompressed linear PCM.</b> 16-bit, 8 kHz, mono; 128 kbit/s of audio. No speech-compression codec; WAV container. See the next page for format details.",y,8.6)
        y-=6
        y=text("<b>Encryption: none.</b> These trials sent audio without encryption. CRC32 checks detect errors; they do not encrypt data.",y,8.6)

        y=page("Audio and packet integrity", "A pass requires saved completion status, exact WAV payloads and independently checked packet CRCs.")
        y=table(["Trial / direction","Outcome","RX / ACK","Retry","Data / ACK bytes","PCM exact"],
                [[f"{t['trial']}  {t['tx_port']} > {t['rx_port']}",t['status'],f"{t['packets']['unique_received']} / {t['packets']['unique_acked']}",t['packets']['retries'],
                  f"{t['packets']['data_successful_call_bytes']:,} / {t['packets']['ack_successful_call_bytes']:,}","Yes" if t['received_pcm_exact'] else "No / unverified"] for t in report["trials"][:10]],
                [142,74,65,44,119,88],y,8.6,padding=4)
        crc_errors=sum(t['packets']['rx_crc_errors'] for t in report['trials'])
        bad_crcs=sum(len(t['packets']['invalid_crc_events']) for t in report['trials'])
        y=note(f"RX / ACK are unique indices out of 200. Byte counts use successful radio calls and exclude PHY overhead. Logged RX radio CRC errors: {crc_errors}; source-derived packet CRC failures: {bad_crcs}. A retry may recover a radio error without changing the final PCM.",y)
        y=heading("Stored audio versus transmitted bytes",y)
        y=table(["Layer","Size / meaning"],[
                ["Original WAV file",f"{fmt(source.get('wav_file_bytes'),0)} bytes including its WAV header"],
                ["Audio PCM payload",f"{fmt(source.get('pcm_bytes'),0)} bytes; 24,000 mono 16-bit samples at 8 kHz when contract valid"],
                ["Audio encoding / codec", "Uncompressed linear PCM: signed 16-bit little-endian, 8 kHz, mono. No speech-compression codec. Audio rate: 128 kbit/s (16,000 bytes/s), excluding protocol overhead."],
                ["Data framing", "200 x (240 PCM + 7 header + 4 application CRC) = 50,200 bytes before retries"],
                ["ACK framing", "200 x 14 = 2,800 ACK bytes before retries; PHY preamble, coding and CRC are additional"]],
                [150,382],y,9)
        y=heading("Source identity",y)
        y=text("PCM SHA-256: <font name='Courier' size='8'>"+escape(source.get("pcm_sha256","unavailable"))+"</font>",y,9)-7
        y=text(f"PCM CRC32: <b>{escape(source.get('pcm_crc32','unavailable'))}</b>. SHA-256 and byte equality apply to PCM, not the WAV container header.",y,9.5)-14
        cinfo=report["negative_control"]
        y=note(f"Receiver-off control: requested={cinfo['requested']}, recorded result={cinfo['recorded_passed']}. Separate from positive trials; a passing control means expected failure, not audio delivery. Control evidence is not re-audited here.",y)

        y=page("Timing and memory", "Measured intervals, calculated airtime and estimates are deliberately kept separate.")
        y=table(["Trial","TX local s","RX span s","Airtime s","USB in / out s","Packet est. ms"],
                [[t['trial'],fmt(t['timing']['sender_local_seconds']),fmt(t['timing']['receiver_span_seconds']),fmt(t['timing']['calculated_airtime_seconds']),
                  f"{fmt(t['timing']['usb_upload_host_seconds'])} / {fmt(t['timing']['usb_export_host_seconds'])}",fmt(t['timing']['packet_midpoint_median_ms'])] for t in report['trials'][:10]],
                [44,78,78,78,135,119],y,8.7,padding=3)
        y=note("TX: sender start to completion. RX: first to last accepted packet, not whole transfer. Airtime is calculated. USB host intervals include transport and buffering; see Traceability and limits.",y)
        y=note("Packet estimate: median eligible first-attempt-to-accepted-RX midpoint, including retries. See Traceability and limits for clock assumptions. Bounds and eligibility counts are in JSON.",y)
        y=heading("Physical storage capacity reported by the boards",y)
        def capacity(value):
            return "Unknown (not reported)" if value is None else f"{value:,.0f} bytes ({value / 1048576:g} MiB)"
        y=table(["Port","Flash total","PSRAM total"],
                [[node['port'],capacity(node['flash_total_bytes']),capacity(node['psram_total_bytes'])] for node in report['physical_capacity']] or [["--","Unknown (not reported)","Unknown (not reported)"]],
                [70,231,231],y,8.7,padding=4)
        y=note("PCM is held in volatile PSRAM, lost when powered off. Flash stores firmware, not this recording. Capacities are reported by HELLO; absent values remain unknown.",y)
        y=heading("Memory allocation evidence",y)
        grouped={}
        for trial in report['trials']:
            for m in trial['memory']:
                grouped.setdefault((m['port'],m['role']),[]).append(m)
        def memory_range(items,key):
            values=[m[key] for m in items if number(m.get(key)) is not None]
            return '--' if not values else fmt(min(values),0) if min(values)==max(values) else f"{fmt(min(values),0)} - {fmt(max(values),0)}"
        rows=[[port,role]+[memory_range(items,key) for key in ('requested_bytes','actual_bytes','psram_free_delta_bytes','scratch_bytes')] for (port,role),items in sorted(grouped.items())]
        y=table(["Port","Role","Requested bytes","Actual block bytes","PSRAM delta bytes","Scratch bytes"],rows[:8] or [["--"]*6],[66,42,98,110,116,100],y,8.7,padding=4)
        y=note("Per-role ranges across attempted trials. RX size includes PCM and bitmap. Allocation and free-PSRAM change are separate readings. Scratch is not total RAM or stack usage; full readings are in JSON.",y)

        y=page("Processing measurements", "Device-local elapsed time for chunking and dechunking. No historical values are substituted.")
        y=table(["Trial", "Chunking total ms", "Dechunking total ms", "Chunk mean us", "Dechunk mean us", "Verified counts TX / RX"],
                [[t['trial'],fmt(seconds(t['processing']['chunking']['total_us'])*1000 if t['processing']['chunking']['valid'] else None),
                  fmt(seconds(t['processing']['dechunking']['total_us'])*1000 if t['processing']['dechunking']['valid'] else None),
                  fmt(t['processing']['chunking']['mean_per_chunk_us']),fmt(t['processing']['dechunking']['mean_per_chunk_us']),
                  f"{t['processing']['chunking']['count'] if t['processing']['chunking']['valid'] else '--'} / {t['processing']['dechunking']['count'] if t['processing']['dechunking']['valid'] else '--'}"] for t in report['trials'][:10]],
                [42,93,101,89,95,112],y,8.8,padding=4)
        y=note("ms = milliseconds; us = microseconds. 1 ms = 1,000 us. Each total sums 200 measured chunk operations. The per-chunk mean is that trial's total divided by 200. A dash denotes missing or inconsistent evidence, not zero elapsed time.",y)
        y=heading("What is included",y)
        y=text("<b>Chunking:</b> PCM copying, header/frame construction and application CRC creation, plus the existing CRC used to bind the ACK. Retry attempts reuse the frame and report zero additional chunking time.<br/><br/><b>Dechunking:</b> frame/header/message/CRC validation and copying, reassembly acceptance and bitmap/count updates, plus duplicate classification/checking. Only the first accepted copy contributes to the message total; duplicate processing is excluded.",y,10)-14
        y=heading("Measurement boundaries",y)
        y=text("These are elapsed intervals from the ESP32's local microsecond timer. They include timer calls and any scheduling/interruption overhead inside the measured region; they are not pure CPU cycles. The timed regions exclude radio transmission/reception waits, ACK handling/delay, OLED rendering and serial logging. USB transport and isolated memory-write latency are separate and are not inferred from these totals.",y,10)-14
        y=heading("Independent consistency checks",y)
        y=text("A processing total is accepted only when the node advertises timing schema 1, all 200 distinct first/unique packet timings are present, and their sum and count exactly match the completion event. Zero microseconds is valid at timer resolution. Legacy runs without these fields remain unmeasured. Detailed audit reasons and duplicate-processing totals are preserved in JSON.",y,10)-12

    y=page("Traceability and limits", "Keep this report with the run summary, serial logs and unchanged WAV evidence.")
    y=heading("Hardware and firmware reported by the nodes",y)
    node_rows=[]
    for node in report["nodes"][:4]:
        h=node.get("hello",{})
        oled={k:v for k,v in h.items() if k in ("oled_ready","oled_layout_ok")}
        node_rows.append([node.get("port","?"),node.get("label","?"),h.get("firmware","unavailable"),
                          h.get("mac",node.get("usb_serial","unavailable")),
                          "; ".join(f"{key.replace('oled_', '')}: {value}" for key,value in oled.items()) if oled else "No saved OLED field"])
    y=table(["Port","Label","Firmware","MAC / USB ID","OLED firmware evidence"],node_rows or [["--","--","No node evidence","--","Not measured"]],
            [47,63,103,137,182],y,8.2)
    oled_trials=sum(bool(t['oled_test']) for t in report['trials'])
    y=note(f"Saved OLED TEST-command replies: {oled_trials} trial(s). Initialization/progress fields describe firmware behavior, not human-confirmed screen content. Acoustic speaker playback is outside this test.",y)
    y=heading("Errors and incomplete evidence",y)
    issues=report['run_errors']+report['warnings']
    for trial in report['trials']:
        if trial['status'] != 'PASS':
            issues.append(f"Trial {trial['trial']} ({trial['status']}): "+'; '.join(trial['reasons']))
    if not issues:
        issues=["No saved run errors or audit gaps in attempted trials." if report['trials'] else "No trials have been attempted. There are no radio results to validate."]
    for issue in issues[:3]:
        y=text(escape(issue[:200]+("..." if len(issue)>200 else "")),y,9.2)-8
    if len(issues)>3:
        y=note(f"{len(issues)-3} additional issue entries are preserved in the JSON audit.",y)
    y=heading("How to interpret this report",y)
    for limit in report['measurement_limits'][0:5]:
        y=text(escape(limit),y,9.2)-8
    y=heading("Evidence location and status",y)
    y=text(escape(report['run_folder']),y,8.6)-7
    y=text(f"Run timestamps: {escape(str(report['started_at']))} to {escape(str(report['finished_at']))}. "
           f"Source contract valid: {source.get('contract_valid',False)}. "
           "The same-stem JSON contains source/receiver hashes, trial reasons, packet audit counts, timing bounds and memory records.",y,9.2)-10
    if report.get('fixture_note'):
        y=text(escape(report['fixture_note']),y,9.2,color=amber)
    c.save()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_folder",type=Path)
    parser.add_argument("--output",type=Path,help="PDF destination; default RUN_FOLDER/consistency-report.pdf")
    args=parser.parse_args(argv)
    report=collect(args.run_folder)
    output=args.output or args.run_folder/"consistency-report.pdf"
    output.parent.mkdir(parents=True,exist_ok=True)
    audit=output.with_suffix(".json")
    audit.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    make_pdf(output,report)
    print(json.dumps({"pdf":str(output.resolve()),"audit_json":str(audit.resolve()),"counts":report["counts"],
                      "all_requested_trials_verified":report["all_requested_trials_verified"]}))
    return 0  # Report creation succeeded; trial failure is data, not a renderer crash.


if __name__ == "__main__":
    raise SystemExit(main())
