"""Independent read-only evidence audit. Does not import bench code or serial."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import struct
import wave
import zlib


def pcm(path):
    with wave.open(str(path), "rb") as wav:
        fmt = (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes(), wav.getcomptype())
        if fmt != (1, 2, 8000, 24000, "NONE"):
            raise ValueError(f"Unexpected PCM format {path}: {fmt}")
        data = wav.readframes(24001)
    if len(data) != 48000:
        raise ValueError(f"Wrong PCM length: {path}")
    return data


def digest(data):
    return {"bytes": len(data), "crc32": f"{zlib.crc32(data) & 0xffffffff:08x}",
            "sha256": hashlib.sha256(data).hexdigest()}


def audit(folder):
    summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    issues, checks = [], 0
    def check(condition, description):
        nonlocal checks
        checks += 1
        if not condition:
            issues.append(description)

    check(bool(summary.get("finished_at")), "Run has no final completion timestamp")
    check(summary.get("connections_closed") is True, "Both ports not recorded closed")
    check(summary.get("requested_trials") == 10, "Requested count is not ten")
    check(summary.get("alternate") is True, "Run was not configured to alternate")
    check(summary.get("distance_inches") == 24, "Recorded user-reported distance is not 24 inches")
    check(summary.get("both_connections_open_together") is True, "Both concurrent connections not recorded")
    source = pcm(folder / "source.wav")
    source_digest = digest(source)
    check(source_digest["crc32"] == "46248425", "Source CRC differs from selected unchanged recording")
    check(source_digest["sha256"] == "1f658cb596716d1b0d34426dd0d0a9f3aa561f8eee385b1788d4e438b44ba2ac",
          "Source SHA256 differs from selected unchanged recording")
    check(summary["source"]["pcm_crc32"] == source_digest["crc32"], "Source summary CRC differs")
    check(summary["source"]["pcm_sha256"] == source_digest["sha256"], "Source summary SHA256 differs")
    nodes = {node["port"]: node for node in summary["nodes"]}
    expected_macs = {"COM6": "8CFD49B5B78C", "COM7": "441BF66F99E4"}
    for port, expected in expected_macs.items():
        hello = nodes[port]["hello"]
        check(hello["mac"].replace(":", "").upper() == expected, f"{port}: wrong board identity")
        check(hello["firmware"] == "lora-integrity-2-oled", f"{port}: wrong firmware")
        check(hello["radio_ready"] and hello["oled_ready"] and hello["oled_layout_ok"], f"{port}: readiness false")

    completed = summary.get("trials", [])
    check(len(completed) == 10, f"Expected ten saved trials, found {len(completed)}")
    check(len(list(folder.glob("trial-*/summary.json"))) == 10, "Expected ten trial summary files")
    ids = [trial["id"] for trial in completed]
    check(len(set(ids)) == len(ids) and all(1 <= item <= 65535 for item in ids), "Invalid/reused message IDs")
    reports, memory = [], defaultdict(list)
    directions = Counter()
    cumulative_rf = {port: node["hello"]["rf_tx_calls_total"] for port, node in nodes.items()}
    cumulative_runs = {port: node["hello"]["tx_runs_started"] for port, node in nodes.items()}
    for number, saved in enumerate(completed, 1):
        prefix = f"Trial {number}: "
        start_issues = len(issues)
        def expect(condition, text):
            check(condition, prefix + text)
        directory = (folder / saved["directory"]).resolve()
        expect(directory.is_relative_to(folder.resolve()), "directory escapes evidence root")
        trial = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
        expect({k: v for k, v in saved.items() if k != "directory"} == trial,
               "root and per-trial summaries disagree")
        tx, rx = trial["tx_port"], trial["rx_port"]
        expected_direction = ("COM6", "COM7") if number % 2 else ("COM7", "COM6")
        expect((tx, rx) == expected_direction, "direction not alternating as planned")
        directions[f"{tx}->{rx}"] += 1
        expect(trial["trial"] == number and trial["passed"] is True, "wrong index or recorded failure")
        sender = pcm(directory / "sender-before-radio.wav")
        receiver = pcm(directory / "received.wav")
        expect(sender == source, "sender upload differs from source")
        expect(receiver == source, "receiver PCM differs from source")
        for key, data in (("tx_dump", sender), ("rx_dump", receiver)):
            expect(trial[key]["bytes"] == len(data) and trial[key]["crc32"] == digest(data)["crc32"], key + " metadata differs")
            expect(trial[key]["complete"] is True, key + " incomplete")
        differences = [abs(a - b) for a, b in zip(struct.unpack("<24000h", source), struct.unpack("<24000h", receiver))]
        expect(trial["receiver_comparison"]["max_abs_sample_difference"] == max(differences), "sample-difference metadata differs")
        expect(trial["receiver_comparison"]["received_sha256"] == digest(receiver)["sha256"], "receiver SHA256 metadata differs")
        expect(trial["receiver_comparison"]["different_samples"] == sum(bool(d) for d in differences), "different-sample count differs")

        packets, received = trial["tx_packets"], trial["rx_packets"]
        done, rx_status = trial["tx_done"], trial[f"status_{rx}"]
        unique_tx, unique_rx = {p["index"] for p in packets if p["acked"]}, {p["index"] for p in received}
        expect(unique_tx == set(range(200)), "not all 200 chunks acknowledged")
        expect(unique_rx == set(range(200)), "not all 200 chunks received")
        tx_success = sum(p["tx_radio_status"] == 0 for p in packets)
        ack_rx = sum(p["acked"] for p in packets)
        ack_tx = sum(p["ack_status"] == 0 for p in received)
        retries = len(packets) - len({p["index"] for p in packets})
        expect(done["attempts"] == len(packets) and done["retries"] == retries, "attempt/retry counters differ")
        expect(done["successful_transmits"] == tx_success, "successful TX counter differs")
        expect(done["data_bytes_sent"] == tx_success * 251, "data-byte counter differs")
        expect(done["ack_bytes_received"] == ack_rx * 14, "ACK-byte counter differs")
        expect(done["acked_chunks"] == 200 and done["success"] and not done["cancelled"], "sender completion invalid")
        expect(rx_status["rx_packets"] == len(received), "RX packet count differs")
        expect(rx_status["ack_packets"] == ack_tx, "ACK transmit count differs")
        expect(rx_status["duplicates"] == sum(p["duplicate"] for p in received), "duplicate count differs")
        expect(rx_status["received_chunks"] == 200, "receiver chunk count differs")
        cumulative_rf[tx] += len(packets)
        cumulative_rf[rx] += len(received)
        cumulative_runs[tx] += 1
        for port in (tx, rx):
            expect(trial[f"status_{port}"]["rf_tx_calls_total"] == cumulative_rf[port], port + " cumulative RF-call count differs")
            expect(trial[f"status_{port}"]["tx_runs_started"] == cumulative_runs[port], port + " cumulative TX-run count differs")
        expect(not trial["accounting"]["invalid_logged_data_crc_events"], "reported invalid packet CRC")
        expected_crc = {index: f"{zlib.crc32(struct.pack('<BBHBBB', 0xf9, 1, trial['id'], index, 200, 240) + source[index * 240:(index + 1) * 240]) & 0xffffffff:08x}"
                        for index in range(200)}
        attempt_number = Counter()
        for packet in packets:
            index = packet["index"]
            attempt_number[index] += 1
            expect(packet["id"] == trial["id"] and packet["data_crc32"] == expected_crc.get(index), "TX packet ID/CRC mismatch")
            expect(packet["attempt"] == attempt_number[index], "TX attempt sequence mismatch")
            expect(done["start_us"] <= packet["start_us"] <= packet["end_us"] <= done["end_us"], "TX timestamp outside transaction")
            expect(packet["acked"] == (packet["ack_us"] != 0), "ACK flag/timestamp disagree")
            if packet["acked"]:
                expect(packet["end_us"] <= packet["ack_us"] <= done["end_us"], "ACK timestamp outside transaction")
        for packet in received:
            expect(packet["id"] == trial["id"] and packet["data_crc32"] == expected_crc.get(packet["index"]), "RX packet ID/CRC mismatch")
        first_rx = min(p["rx_us"] for p in received if not p["duplicate"])
        last_rx = max(p["rx_us"] for p in received if not p["duplicate"])
        expect((rx_status["first_rx_us"], rx_status["last_rx_us"]) == (first_rx, last_rx), "RX status timestamps differ")
        expect((trial["rx_complete"]["first_rx_us"], trial["rx_complete"]["last_rx_us"]) == (first_rx, last_rx), "RX completion timestamps differ")
        local_us = done["end_us"] - done["start_us"]
        last_ack_us = max(p["ack_us"] for p in packets)
        expect(trial["sender_local_transfer_us"] == local_us, "sender local duration differs")
        expect(trial["receiver_local_span_us"] == last_rx - first_rx, "receiver local span differs")
        started = datetime.fromisoformat(trial["started_at"])
        finished = datetime.fromisoformat(trial["finished_at"])
        expect(finished > started, "host trial timestamps reversed")

        stable = {}
        for port in (tx, rx):
            expect(trial["oled_test"][port]["current"] == number and trial["oled_test"][port]["total"] == 10, port + " OLED counter mismatch")
            selected = []
            for phase in ("clock_before", "clock_after"):
                samples = trial[phase][port]["samples"]
                pick = trial[phase][port]["selected_min_rtt"]
                expect(len(samples) == 8, port + " clock sample count differs")
                expect(pick == min(samples, key=lambda value: value["rtt_us"]), port + " clock selection not minimum RTT")
                for sample in samples:
                    expect(sample["boot_id"] == nodes[port]["hello"]["boot_id"], port + " reboot during calibration")
                    expect(sample["received_host_ns"] >= sample["sent_host_ns"], port + " negative clock RTT")
                    expect(abs(sample["rtt_us"] - (sample["received_host_ns"] - sample["sent_host_ns"]) / 1000) < 0.001, port + " RTT arithmetic differs")
                    expect(abs(sample["offset_lower_us"] - (sample["sent_host_ns"] / 1000 - sample["device_us"])) < 0.001, port + " clock offset arithmetic differs")
                selected.append(pick)
            before, after = selected
            start, end = (done["start_us"], done["end_us"]) if port == tx else (first_rx, last_rx)
            expect(before["device_us"] < start <= end < after["device_us"], port + " calibration does not enclose transaction")
            overlap = max(before["offset_lower_us"], after["offset_lower_us"]) <= min(before["offset_upper_us"], after["offset_upper_us"])
            stable[port] = overlap and before["boot_id"] == after["boot_id"] and after["device_us"] > before["device_us"]
            expect(trial["clock_alignment"][port]["stable"] == stable[port], port + " stability flag differs")

            role = "TX" if port == tx else "RX"
            allocation = trial["tx_role" if role == "TX" else "rx_role"]
            status = trial[f"status_{port}"]
            expect(allocation["allocation_storage"] == "PSRAM" and allocation["payload_capacity_bytes"] == 48000, port + " wrong payload allocation")
            expected_request = 48000 if role == "TX" else allocation["chunker_object_bytes"]
            expect(allocation["allocation_requested_bytes"] == expected_request, port + " role allocation mismatch")
            expect(allocation["allocation_actual_bytes"] >= expected_request, port + " actual allocation too small")
            expect(allocation["psram_before_bytes"] - allocation["psram_free_bytes"] >= allocation["allocation_actual_bytes"], port + " PSRAM delta smaller than allocation")
            expect(allocation["chunker_bitmap_bytes"] == (0 if role == "TX" else 25), port + " incorrect bitmap size")
            expect(allocation["psram_total_bytes"] == 2097152 and allocation["flash_total_bytes"] == 16777216, port + " unexpected memory capacity")
            for field in ("allocation_requested_bytes", "allocation_actual_bytes", "payload_capacity_bytes", "chunker_object_bytes", "chunker_bitmap_bytes", "packet_scratch_bytes", "psram_free_bytes"):
                expect(status[field] == allocation[field], port + " allocation/status differs for " + field)
            expect(status["armed"] is False and status["transmitting"] is False, port + " radio not stopped at status")
            memory[port].append({"trial": number, "role": role, **{key: allocation[key] for key in (
                "allocation_requested_bytes", "allocation_actual_bytes", "psram_before_bytes", "psram_free_bytes",
                "internal_heap_before_bytes", "internal_heap_free_bytes", "internal_heap_min_free_bytes")}})
        if not all(stable.values()):
            expect(all(p["first_attempt_to_accepted_rx"] is None for p in trial["packet_timing"]), "unstable calibration still reports cross-device latency")
        reports.append({"trial": number, "id": trial["id"], "direction": f"{tx}->{rx}",
                        "audit_passed": len(issues) == start_issues, "source_equals_sender": source == sender,
                        "source_equals_receiver": source == receiver, "receiver_pcm": digest(receiver),
                        "different_samples": sum(bool(d) for d in differences), "max_abs_sample_difference": max(differences),
                        "chunks_received": len(unique_rx), "chunks_acked": len(unique_tx), "attempts": len(packets),
                        "retries": retries, "receiver_duplicates": rx_status["duplicates"],
                        "sender_transaction_seconds": local_us / 1e6,
                        "sender_start_to_final_ack_seconds": (last_ack_us - done["start_us"]) / 1e6,
                        "receiver_span_seconds": (last_rx - first_rx) / 1e6,
                        "host_trial_seconds": (finished - started).total_seconds(), "clock_stable": stable,
                        "rssi_min_dbm": min(p["rssi_dbm"] for p in received), "rssi_max_dbm": max(p["rssi_dbm"] for p in received),
                        "snr_min_db": min(p["snr_db"] for p in received), "snr_max_db": max(p["snr_db"] for p in received)})

    logs = {}
    for port in expected_macs:
        records = [json.loads(line) for line in (folder / f"serial-{port}.log").read_text(encoding="utf-8").splitlines()]
        commands = [entry["message"]["command"] for entry in records if entry["direction"] == "TX"]
        role = None
        for command in commands:
            if command.startswith("ROLE "):
                role = command.split()[1]
            elif command.startswith(("LOAD ", "TX ")):
                check(role == "TX", f"{port}: source/transfer command sent while not in TX role")
            elif command.startswith("ARM "):
                check(role == "RX", f"{port}: ARM sent while not in RX role")
        counts = Counter(command.split()[0] for command in commands)
        check(counts["TX"] == 5 and counts["ARM"] == 5 and counts["LOAD"] == 5, f"{port}: transfer/arm/load command counts differ")
        check(counts["TEST"] == 10, f"{port}: wrong number of OLED TEST commands")
        check(records[-1]["direction"] == "HOST" and records[-1]["message"]["event"] == "closed", f"{port}: missing final close log")
        logs[port] = {"records": len(records), "command_counts": dict(counts), "serial_bytes": (folder / f"serial-{port}.bin").stat().st_size}
    check(directions == Counter({"COM6->COM7": 5, "COM7->COM6": 5}), "Directions not five each")
    final_states = {}
    if completed:
        for port in expected_macs:
            state = completed[-1][f"status_{port}"]
            check(state["state"] == "IDLE" and state["test_current"] == 10 and state["test_total"] == 10,
                  port + " final state is not IDLE/Test10of10")
            check(not state["armed"] and not state["transmitting"] and state["oled_ready"] and state["oled_layout_ok"],
                  port + " final radio/OLED readiness mismatch")
            final_states[port] = {key: state[key] for key in (
                "role", "state", "test_current", "test_total", "armed", "transmitting", "oled_ready", "oled_layout_ok",
                "tx_runs_started", "rf_tx_calls_total", "allocation_requested_bytes", "allocation_actual_bytes",
                "payload_capacity_bytes", "packet_scratch_bytes", "internal_heap_free_bytes", "internal_heap_min_free_bytes",
                "psram_free_bytes", "psram_total_bytes", "flash_total_bytes")}
    totals = {
        "data_tx_attempts": sum(len(t["tx_packets"]) for t in completed),
        "successful_data_tx_calls": sum(t["tx_done"]["successful_transmits"] for t in completed),
        "accepted_rx_packets_including_duplicates": sum(len(t["rx_packets"]) for t in completed),
        "receiver_duplicates": sum(t[f"status_{t['rx_port']}"]["duplicates"] for t in completed),
        "successful_ack_tx_calls": sum(t[f"status_{t['rx_port']}"]["ack_packets"] for t in completed),
        "acks_received": sum(t["tx_done"]["ack_bytes_received"] // 14 for t in completed),
        "data_rf_payload_bytes_sent": sum(t["tx_done"]["data_bytes_sent"] for t in completed),
        "ack_rf_payload_bytes_sent": sum(t[f"status_{t['rx_port']}"]["ack_packets"] * 14 for t in completed),
        "ack_rf_payload_bytes_received": sum(t["tx_done"]["ack_bytes_received"] for t in completed),
        "receiver_phy_crc_errors": sum(t[f"status_{t['rx_port']}"]["crc_errors"] for t in completed),
        "receiver_application_errors": sum(t[f"status_{t['rx_port']}"]["app_errors"] for t in completed),
    }
    memory_ranges = {}
    for port, observations in memory.items():
        memory_ranges[port] = {key: {"min": min(row[key] for row in observations),
                                    "max": max(row[key] for row in observations),
                                    "last_minus_first": observations[-1][key] - observations[0][key]}
                               for key in ("psram_before_bytes", "psram_free_bytes", "internal_heap_free_bytes", "internal_heap_min_free_bytes")}
        check(len({row["psram_before_bytes"] for row in observations}) == 1, port + " PSRAM allocation baseline changed between trials")
        check(all(row["internal_heap_min_free_bytes"] <= row["internal_heap_free_bytes"] for row in observations), port + " internal heap minimum exceeds free value")
    duration = [row["sender_transaction_seconds"] for row in reports]
    return {"audited_at": datetime.now(timezone.utc).isoformat(), "run_folder": str(folder.resolve()),
            "scope": "Independent saved-evidence audit; no serial access or imports from bench/report code",
            "checks": checks, "passed": not issues, "issues": issues, "source_pcm": source_digest,
            "direction_counts": dict(directions), "trial_count": len(reports),
            "total_retries": sum(row["retries"] for row in reports),
            "total_received_audio_bytes": 48000 * sum(row["source_equals_receiver"] for row in reports),
            "sender_duration_seconds": {"min": min(duration), "max": max(duration), "mean": statistics.mean(duration)},
            "memory_observations": dict(memory), "memory_ranges": memory_ranges,
            "traffic_totals": totals, "final_states": final_states,
            "run_recorded_duration_seconds": (datetime.fromisoformat(summary["finished_at"]) - datetime.fromisoformat(summary["started_at"])).total_seconds(),
            "cumulative_rf_calls": cumulative_rf, "cumulative_tx_runs": cumulative_runs,
            "serial_log_audit": logs, "trials": reports,
            "limits": ["Distance is user-reported; OLED readiness is firmware evidence, not a visual inspection.",
                       "CRC/SHA and byte equality verify this recording's transfer, not range or real-time speech quality.",
                       "Cross-device clocks are unsynchronized; only local durations are reported as exact device-clock intervals."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.folder)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("passed", "checks", "issues", "trial_count", "direction_counts", "total_retries", "sender_duration_seconds")}, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
