"""Create report.md and packets.csv from a saved LoRa run; never opens serial ports.

Usage: python tools/report_lora_transfer.py captures/<run-folder>
Uses only the standard library and independently compares the saved WAV PCM.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
import struct
from urllib.parse import quote
import wave
import zlib


CHUNKS, CHUNK_BYTES, DATA_BYTES, ACK_BYTES = 200, 240, 251, 14
CSV_FIELDS = (
    "trial", "negative_control", "tx_port", "rx_port", "message_id", "chunk_index",
    "attempt_count", "first_tx_device_us", "first_accepted_rx_device_us",
    "acked_attempt", "acked_tx_start_us", "acked_tx_end_us", "ack_received_tx_device_us",
    "ack_turnaround_us", "first_tx_to_rx_lower_us", "first_tx_to_rx_upper_us",
    "timing_bounds_eligible", "expected_data_crc32", "tx_data_crc32", "rx_data_crc32",
    "logged_crcs_match_source", "rx_rssi_dbm", "rx_snr_db", "rx_duplicate_count",
)


def crc32(data):
    return f"{zlib.crc32(data):08x}"


def within(folder, relative):
    path = (folder / relative).resolve()
    if not path.is_relative_to(folder.resolve()):
        raise ValueError(f"Evidence path leaves run folder: {relative}")
    return path


def read_pcm(path):
    with wave.open(str(path), "rb") as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (1, 2, 8000, "NONE"):
            raise ValueError(f"Expected 8 kHz mono signed 16-bit PCM: {path}")
        declared = audio.getnframes() * 2
        pcm = audio.readframes(audio.getnframes())
    if len(pcm) != declared or len(pcm) % 2:
        raise ValueError(f"Truncated or incomplete PCM samples: {path}")
    return pcm


def compare_wave(source, path):
    try:
        pcm = read_pcm(path)
    except (OSError, ValueError, EOFError, wave.Error) as exc:
        return {"error": str(exc), "exact": False}
    pairs = list(zip(struct.iter_unpack("<h", source), struct.iter_unpack("<h", pcm)))
    return {
        "exact": pcm == source, "bytes": len(pcm), "crc32": crc32(pcm),
        "sha256": hashlib.sha256(pcm).hexdigest(),
        "different_bytes": sum(a != b for a, b in zip(source, pcm)) + abs(len(source) - len(pcm)),
        "different_samples": sum(a != b for a, b in pairs),
        "missing_or_extra_samples": abs(len(source) - len(pcm)) // 2,
        "max_abs_sample_difference": max((abs(a[0] - b[0]) for a, b in pairs), default=0),
        "all_zero": not any(pcm),
    }


def clock_envelope(trial, port, device_us):
    """Require the recorded eligibility checks and recompute the raw brackets."""
    try:
        recorded = trial["clock_alignment"][port]
        before = trial["clock_before"][port]["selected_min_rtt"]
        after = trial["clock_after"][port]["selected_min_rtt"]
        if not all(recorded.get(key) is True for key in ("stable", "same_boot", "calibration_intervals_overlap")):
            return None
        if not before["boot_id"] or before["boot_id"] != after["boot_id"]:
            return None
        if not before["device_us"] <= device_us <= after["device_us"] or after["device_us"] <= before["device_us"]:
            return None
        brackets = []
        for sample in (before, after):
            low = sample["sent_host_ns"] / 1000 - sample["device_us"]
            high = sample["received_host_ns"] / 1000 - sample["device_us"]
            if not math.isfinite(low) or not math.isfinite(high) or high < low:
                return None
            brackets.append((low, high))
        if max(low for low, _ in brackets) > min(high for _, high in brackets):
            return None
        return min(low for low, _ in brackets), max(high for _, high in brackets)
    except (KeyError, TypeError):
        return None


def packet_rows(trial, source):
    tx_packets, rx_packets = trial.get("tx_packets", []), trial.get("rx_packets", [])
    observed = {p["index"] for p in tx_packets + rx_packets if 0 <= p.get("index", -1) < CHUNKS}
    indices = sorted(observed) if trial.get("negative_control") else range(CHUNKS)
    rows = []
    for index in indices:
        tx = sorted((p for p in tx_packets if p.get("index") == index), key=lambda p: p["start_us"])
        rx = sorted((p for p in rx_packets if p.get("index") == index), key=lambda p: p["rx_us"])
        accepted = next((p for p in rx if not p.get("duplicate")), None)
        acked = next((p for p in tx if p.get("acked") and p.get("ack_us", 0) >= p["end_us"]), None)
        header = struct.pack("<BBHBBB", 0xF9, 1, trial["id"], index, CHUNKS, CHUNK_BYTES)
        expected_crc = crc32(header + source[index * CHUNK_BYTES:(index + 1) * CHUNK_BYTES])
        row = dict.fromkeys(CSV_FIELDS)
        row.update({
            "trial": trial["trial"], "negative_control": bool(trial.get("negative_control")),
            "tx_port": trial["tx_port"], "rx_port": trial["rx_port"], "message_id": trial["id"],
            "chunk_index": index, "attempt_count": len(tx), "timing_bounds_eligible": False,
            "first_tx_device_us": tx[0]["start_us"] if tx else None,
            "first_accepted_rx_device_us": accepted["rx_us"] if accepted else None,
            "expected_data_crc32": expected_crc,
            "tx_data_crc32": tx[0].get("data_crc32") if tx else None,
            "rx_data_crc32": accepted.get("data_crc32") if accepted else None,
            "logged_crcs_match_source": all(str(p.get("data_crc32", "")).lower() == expected_crc for p in tx + rx) if tx or rx else None,
            "rx_rssi_dbm": accepted.get("rssi_dbm") if accepted else None,
            "rx_snr_db": accepted.get("snr_db") if accepted else None,
            "rx_duplicate_count": sum(bool(p.get("duplicate")) for p in rx),
        })
        if acked:
            row.update({"acked_attempt": acked["attempt"], "acked_tx_start_us": acked["start_us"],
                        "acked_tx_end_us": acked["end_us"], "ack_received_tx_device_us": acked["ack_us"],
                        "ack_turnaround_us": acked["ack_us"] - acked["end_us"]})
        if tx and accepted:
            first_tx, first_rx = tx[0]["start_us"], accepted["rx_us"]
            tx_clock = clock_envelope(trial, trial["tx_port"], first_tx)
            rx_clock = clock_envelope(trial, trial["rx_port"], first_rx)
            if tx_clock and rx_clock:
                lower = (first_rx - first_tx) + (rx_clock[0] - tx_clock[1])
                upper = (first_rx - first_tx) + (rx_clock[1] - tx_clock[0])
                row.update({"first_tx_to_rx_lower_us": round(lower, 3),
                            "first_tx_to_rx_upper_us": round(upper, 3), "timing_bounds_eligible": True})
        rows.append(row)
    return rows


def label(value):
    return "PASS" if value is True else "FAIL" if value is False else "unavailable"


def number(value, divisor=1, digits=3):
    return "—" if value is None else f"{value / divisor:.{digits}f}"


def link(path, title):
    return f"[{title}]({quote(path.as_posix())})"


def table(lines, headings, rows):
    lines.extend(["| " + " | ".join(headings) + " |", "| " + " | ".join("---" for _ in headings) + " |"])
    lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
    lines.append("")


def build_report(folder, summary, source):
    trials = summary.get("trials", [])
    control = summary.get("negative_control")
    comparisons, all_rows, issues = {}, [], []
    for trial in trials + ([control] if control else []):
        directory = Path(trial["directory"])
        local = within(folder, directory)
        sender = compare_wave(source, within(local, trial.get("tx_dump", {}).get("wav_file", "sender-before-radio.wav")))
        received = compare_wave(source, within(local, trial.get("rx_dump", {}).get("wav_file", "received.wav")))
        comparisons[str(directory)] = (sender, received)
        if not trial.get("negative_control"):
            all_rows.extend(packet_rows(trial, source))
        for kind, comparison in (("sender", sender), ("received", received)):
            if comparison.get("error"):
                issues.append(f"{directory} {kind}: {comparison['error']}")
    independent = bool(trials) and all(all(c["exact"] for c in comparisons[t["directory"]]) for t in trials)
    source_crc, source_sha = crc32(source), hashlib.sha256(source).hexdigest()
    source_record = summary.get("source", {})
    source_matches_record = (source_record.get("pcm_bytes") == len(source) and
                             source_record.get("pcm_crc32") == source_crc and
                             source_record.get("pcm_sha256") == source_sha)
    lines = ["# LoRa buffered-audio transfer report", "",
             f"Recorded run result: **{label(summary.get('passed'))}**. "
             f"Independent saved-WAV PCM comparison: **{label(independent)}**. "
             f"Source PCM agrees with recorded size/CRC/SHA: **{label(source_matches_record)}**.", "",
             f"UTC: {summary.get('started_at', 'unknown')} to {summary.get('finished_at', 'unfinished')}. "
             f"Both connections open together: {summary.get('both_connections_open_together')}; "
             f"closed afterward: {summary.get('connections_closed')}.", "",
             "This verifies buffered PCM delivery over the radio. It does not test microphone capture, "
             "speaker playback, range, or real-time voice. Recorded PASS flags come from summary.json; "
             "PCM comparisons below are recomputed from the WAV files by this offline report.", "",
             f"Source: {link(Path('source.wav'), 'source.wav')}, {len(source):,} PCM bytes / "
             f"{len(source) // 2:,} samples, mono signed 16-bit at 8,000 Hz "
             f"({len(source) / 16000:.3f} seconds). WAV container bytes are excluded from RF payload accounting.", "",
             f"PCM CRC32: `{source_crc}`. PCM SHA-256: `{source_sha}`.", ""]
    transfer_rows, integrity_rows, memory_rows, accounting_rows, timing_rows = [], [], [], [], []
    for trial in trials:
        key, directory = trial["directory"], Path(trial["directory"])
        sender, received = comparisons[key]
        account, done = trial.get("accounting", {}), trial.get("tx_done", {})
        status = trial.get(f"status_{trial['rx_port']}", {})
        transfer_rows.append([trial["trial"], f"{trial['tx_port']} → {trial['rx_port']}", label(trial.get("passed")),
                              number(trial.get("sender_local_transfer_us"), 1e6, 6),
                              number(trial.get("receiver_local_span_us"), 1e6, 6),
                              account.get("unique_chunks_received", "—"), done.get("acked_chunks", "—"),
                              account.get("tx_attempts_observed", "—"), account.get("retries_observed", "—"),
                              account.get("receiver_duplicate_packets", "—"),
                              f"{status.get('crc_errors', '—')} / {status.get('app_errors', '—')}"])
        integrity_rows.append([trial["trial"], label(sender["exact"]), label(received["exact"]),
                               received.get("bytes", "—"), received.get("different_bytes", "—"),
                               received.get("different_samples", "—"), received.get("missing_or_extra_samples", "—"),
                               received.get("max_abs_sample_difference", "—"), received.get("crc32", "—"),
                               link(directory / "received.wav", "received WAV")])
        for role in ("tx", "rx"):
            memory = trial.get(f"{role}_role", {})
            delta = memory.get("psram_before_bytes", 0) - memory.get("psram_free_bytes", 0)
            memory_rows.append([trial["trial"], trial[f"{role}_port"], role.upper(),
                                memory.get("payload_capacity_bytes", "—"), memory.get("allocation_requested_bytes", "—"),
                                memory.get("allocation_actual_bytes", "—"), delta,
                                memory.get("packet_scratch_bytes", "—"), memory.get("internal_heap_free_bytes", "—")])
        accounting_rows.append([trial["trial"], account.get("data_rf_payload_bytes_attempted", "—"),
                                account.get("data_rf_payload_bytes_successful_tx_calls", "—"),
                                account.get("ack_rf_payload_bytes_successful_tx_calls", "—"),
                                account.get("ack_rf_payload_bytes_received_by_sender", "—"),
                                number(account.get("estimated_airtime_successful_radio_calls_us"), 1e6, 6),
                                len(account.get("invalid_logged_data_crc_events", []))])
        rows = [row for row in all_rows if row["trial"] == trial["trial"] and not row["negative_control"]]
        bounded = [row for row in rows if row["timing_bounds_eligible"]]
        ack_times = [row["ack_turnaround_us"] for row in rows if row["ack_turnaround_us"] is not None]
        timing_rows.append([trial["trial"], f"{len(bounded)}/{len(rows)}",
                            number(min((r['first_tx_to_rx_lower_us'] for r in bounded), default=None), 1000),
                            number(max((r['first_tx_to_rx_upper_us'] for r in bounded), default=None), 1000),
                            number(statistics.median(ack_times) if ack_times else None, 1000)])
    lines.extend(["**Transfer results**", ""])
    table(lines, ["Trial", "Direction", "Recorded", "TX elapsed s", "RX span s", "Chunks RX", "ACKed", "Attempts", "Retries", "Duplicates", "RX PHY CRC / app errors"], transfer_rows)
    for trial in trials:
        errors = trial.get(f"status_{trial['rx_port']}", {}).get("crc_errors", 0)
        if errors:
            exact = comparisons[trial["directory"]][1]["exact"]
            lines.extend([f"Trial {trial['trial']} recorded **{errors} PHY CRC error(s)** and "
                          f"{trial.get('accounting', {}).get('retries_observed', 'unknown')} retry/retries. "
                          f"Its final PCM exact-match check is **{label(exact)}**; final byte integrity "
                          "does not mean every RF packet arrived without corruption.", ""])
    lines.extend(["TX elapsed uses one sender clock and includes retries, ACK waits, processing, and logging. "
                  "RX span runs from the first accepted packet-completion interrupt to the last; it excludes the first packet's airtime.", "",
                  "**Independent PCM checks**", ""])
    table(lines, ["Trial", "Sender exact", "Receiver exact", "RX PCM bytes", "Different bytes", "Different samples", "Missing/extra samples", "Max sample delta", "RX CRC32", "Audio"], integrity_rows)
    for trial in trials:
        sender, received = comparisons[trial["directory"]]
        lines.append(f"- Trial {trial['trial']} receiver PCM SHA-256: `{received.get('sha256', 'unavailable')}`; "
                     f"{link(Path(trial['directory']) / 'sender-before-radio.wav', 'sender buffer before RF')} "
                     f"({sender.get('bytes', 'unavailable')} bytes, CRC32 `{sender.get('crc32', 'unavailable')}`).")
    lines.extend(["", "Different-sample and maximum-delta counts compare samples present in both files; "
                  "missing/extra samples are counted separately. Exact matching includes every PCM byte.", "",
                  "**Packet bytes and airtime**", "",
                  "Without retries, 200 data frames carry 48,000 PCM + 1,400 voice-header + 800 application-CRC bytes "
                  "= **50,200 data payload bytes**. Two hundred 14-byte ACKs add **2,800 bytes**: "
                  "**53,000 total LoRa payload bytes**, excluding PHY preamble, header, CRC and FEC.", ""])
    table(lines, ["Trial", "Data attempted B", "Data successful TX calls B", "ACK successful TX calls B", "ACK received B", "Configured airtime of successful calls s", "Logged CRC mismatches"], accounting_rows)
    nodes = summary.get("nodes", [])
    if nodes:
        hello = nodes[0].get("hello", {})
        lines.extend([f"Configured radio: {hello.get('frequency_mhz', '—')} MHz, BW {hello.get('bw_khz', '—')} kHz, "
                      f"SF{hello.get('sf', '—')}, CR 4/{hello.get('cr', '—')}. "
                      f"Per-frame PHY airtime: data {number(hello.get('data_airtime_us'), 1000)} ms; "
                      f"ACK {number(hello.get('ack_airtime_us'), 1000)} ms.", ""])
    lines.extend(["Configured airtime includes PHY overhead and is calculated, not a scope measurement. "
                  "Successful TX calls do not alone prove reception; failed-call airtime is unknown. "
                  "Do not add payload-byte counts to airtime or treat them as complete over-air bit counts.", "",
                  "**Memory at role allocation (bytes)**", ""])
    table(lines, ["Trial", "Port", "Role", "PCM capacity", "Requested", "Allocator block", "PSRAM free decrease", "Static packet scratch", "Internal heap free"], memory_rows)
    lines.extend(["TX requests only the 48,000-byte PCM buffer. RX's 48,036-byte chunker includes PCM, "
                  "the 25-byte receipt bitmap, and object fields/alignment. Allocator block size and PSRAM free decrease "
                  "include different allocator overheads. The 767-byte static packet scratch is separate; it is not total "
                  "firmware RAM, stack usage, or a peak-memory measurement.", "",
                  "**Packet timing**", ""])
    table(lines, ["Trial", "Eligible bounds", "Minimum lower bound ms", "Maximum upper bound ms", "Median sender-local ACK turnaround ms"], timing_rows)
    lines.extend(["Clock-aligned bounds are emitted only when pre/post calibrations have the same boot, "
                  "advance in device time, overlap in offset, and enclose the packet timestamp. They assume the "
                  "offset stays inside that envelope throughout the trial. They cover the first TX software timestamp "
                  "to the first accepted RX interrupt, including radio setup, airtime, retries, and ISR timing; "
                  "**they are not RF propagation latency or a hard one-way timing guarantee**. "
                  "ACK turnaround uses one sender clock, from the acknowledged attempt's blocking TX completion "
                  "to ACK reception, and includes receiver delay plus ACK airtime. Individual rows are in "
                  f"{link(Path('packets.csv'), 'packets.csv')}; unavailable bounds are empty.", ""])
    if control:
        _, received = comparisons[control["directory"]]
        done = control.get("tx_done", {})
        independent_zero = received.get("bytes") == len(source) and received.get("all_zero") is True
        lines.extend(["**Negative control**", "",
                      f"Recorded result: **{label(control.get('passed'))}** (expected delivery failure). "
                      f"Receiver radio was intentionally stopped; TX success={done.get('success')}, "
                      f"attempts={done.get('attempts')}, retries={done.get('retries')}, ACKed chunks={done.get('acked_chunks')}. "
                      f"Independent receiver size/all-zero check: **{label(independent_zero)}**. "
                      f"{link(Path(control['directory']) / 'received.wav', 'Control receiver WAV')}. "
                      "The control is excluded from the data-trial tables and packet CSV.", ""])
    lines.extend(["**Evidence**", "",
                  f"- {link(Path('summary.json'), 'Full machine-readable run summary')}."])
    for node in nodes:
        for suffix in ("log", "bin"):
            path = Path(f"serial-{node['port']}.{suffix}")
            if within(folder, path).is_file():
                title = f"{node['port']} serial {suffix}"
                lines.append(f"- {link(path, title)}")
    for trial in trials:
        title = f"Trial {trial['trial']} summary"
        lines.append(f"- {link(Path(trial['directory']) / 'summary.json', title)}")
    if issues:
        lines.extend(["", "**Evidence-reading errors**", ""] + [f"- {issue}" for issue in issues])
    return "\n".join(lines) + "\n", all_rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_folder", type=Path)
    args = parser.parse_args(argv)
    folder = args.run_folder.resolve()
    try:
        summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
        source = read_pcm(folder / "source.wav")
        if len(source) != CHUNKS * CHUNK_BYTES:
            raise ValueError("This bench requires exactly 48,000 source PCM bytes")
        report, rows = build_report(folder, summary, source)
        with (folder / "packets.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        (folder / "report.md").write_text(report, encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError, EOFError, wave.Error) as exc:
        parser.exit(1, f"Cannot generate report: {exc}\n")
    print(f"Wrote {folder / 'report.md'} and {folder / 'packets.csv'} ({len(rows)} packet rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
