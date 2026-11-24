"""Independent standard-library audit of the 20 physical crypto comparison trials.

No bench/report imports and no serial access. The session key was intentionally
not saved: offline checks verify captured bytes/events and the recorded live-key
host comparison, but cannot rerun AES-GCM with the discarded session key.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import statistics
import struct
import wave
import zlib


def require(condition, description):
    if not condition:
        raise ValueError(description)


def crc(data):
    return f"{zlib.crc32(data) & 0xffffffff:08x}"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def nonnegative_int(value):
    return type(value) is int and value >= 0


def read_pcm(path):
    with wave.open(str(path), "rb") as handle:
        properties = (handle.getnchannels(), handle.getsampwidth(), handle.getframerate(),
                      handle.getnframes(), handle.getcomptype())
        require(properties == (1, 2, 8000, 24000, "NONE"), f"Unexpected WAV properties: {path}")
        data = handle.readframes(24000)
    require(len(data) == 48000, f"Wrong PCM length: {path}")
    return data


def aggregate(rows):
    return {field: {"n": len(rows), "mean": statistics.mean(row[field] for row in rows),
                    "minimum": min(row[field] for row in rows),
                    "maximum": max(row[field] for row in rows)}
            for field, value in rows[0].items()
            if type(value) in (int, float) and field != "trial"}


def audit(folder):
    folder = folder.resolve()
    summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    require(summary.get("purpose") == "fresh_plain_vs_aes128gcm_physical_trials", "Not a fresh physical crypto run")
    require(summary.get("passed") is True and summary.get("connections_closed") is True,
            "Run failed or connections did not close")
    require(summary.get("both_connections_open_together") is True, "Concurrent USB handles not established")
    require(summary.get("requested_trials") == summary.get("attempted_trials") == summary.get("passed_trials") == 20,
            "Expected exactly 20 attempted/passing trials")
    require(summary.get("not_run_trials") == 0 and len(summary["trials"]) == 20, "Incomplete cohort")
    require(summary.get("unique_encryption_nonces") == 10, "Nonce count mismatch")
    require(not summary.get("cleanup_errors") and not summary.get("close_errors"), "Cleanup error")
    source = read_pcm(folder / "source.wav")
    require(sha(source) == "1f658cb596716d1b0d34426dd0d0a9f3aa561f8eee385b1788d4e438b44ba2ac", "Different source recording")
    require(summary["source"]["pcm_sha256"] == sha(source) and summary["source"]["pcm_crc32"] == crc(source),
            "Source identity mismatch")
    nodes = {node["port"]: node["hello"] for node in summary["nodes"]}
    logs = {}
    key_commands = []
    selftest_fields = ("passed", "known_answer_passed", "wrong_key_rejected", "wrong_tag_rejected", "changed_ciphertext_rejected")
    for port, mac in (("COM6", "8C:FD:49:B5:B7:8C"), ("COM7", "44:1B:F6:6F:99:E4")):
        hello = nodes[port]
        require(hello["mac"] == mac and hello["firmware"] == "lora-crypto-1-gcm", f"Wrong identity/firmware {port}")
        require(hello["timing_schema"] == hello["crypto_schema"] == 1, f"Wrong timing schema {port}")
        require((hello["data_packet_bytes"], hello["ack_packet_bytes"], hello["metadata_packet_bytes"]) == (251, 14, 40), "Radio frame size mismatch")
        require(all(summary["crypto_selftests"][port].get(k) is True for k in selftest_fields), f"Device crypto self-test failed {port}")
        text = (folder / f"serial-{port}.log").read_text(encoding="utf-8")
        require(re.search(r"KEY\s+[0-9a-fA-F]{32}", text) is None, "Unredacted KEY command found")
        logs[port] = [json.loads(line) for line in text.splitlines() if line]
        commands = [entry["message"]["command"] for entry in logs[port]
                    if entry.get("direction") == "TX" and isinstance(entry.get("message"), dict)
                    and "command" in entry["message"]]
        keys = [command for command in commands if command.startswith("KEY ")]
        require(keys == ["KEY [REDACTED]"], f"Key provisioning was not exactly once/redacted: {port}")
        key_commands.extend(keys)
        status = summary["final_status"][port]
        require(status["state"] == "IDLE" and status["test_current"] == status["test_total"] == 20,
                f"Wrong final display state {port}")
        require(status["armed"] is False and status["transmitting"] is False, f"Radio still active {port}")
    require(all(summary["preflight"]["host_crypto_selftest"].values()), "Host crypto preflight failed")

    def raw_events(port, event, identity):
        return [entry["message"] for entry in logs[port]
                if entry.get("direction") == "RX" and isinstance(entry.get("message"), dict)
                and entry["message"].get("event") == event and entry["message"].get("id") == identity]

    rows, used_ids, used_nonces, used_ciphers = [], set(), set(), set()
    for number, trial in enumerate(summary["trials"], 1):
        label = f"Trial {number}"
        mode = "PLAIN" if number <= 10 else "GCM"
        tx, rx = ("COM6", "COM7") if number % 2 else ("COM7", "COM6")
        require((trial["trial"], trial["mode"], trial["mode_trial"], trial["tx_port"], trial["rx_port"])
                == (number, mode, (number - 1) % 10 + 1, tx, rx), f"{label}: wrong plan/roles")
        require(trial.get("passed") is True, f"{label}: recorded failure")
        identity = trial["id"]
        require(type(identity) is int and 0 < identity <= 65535 and identity not in used_ids, f"{label}: reused/invalid message ID")
        used_ids.add(identity)
        directory = (folder / trial["directory"]).resolve()
        require(directory.is_relative_to(folder), "Trial path escaped run folder")
        local = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
        require(local == {k: v for k, v in trial.items() if k != "directory"}, f"{label}: root/local summary mismatch")
        require(read_pcm(directory / "sender-before-radio.wav") == source, f"{label}: sender source altered")
        require(read_pcm(directory / "received.wav") == source, f"{label}: received audio altered")
        start, finish = map(datetime.fromisoformat, (trial["started_at"], trial["finished_at"]))
        for port in (tx, rx):
            entries = [entry for entry in logs[port] if start <= datetime.fromisoformat(entry["utc"]) <= finish]
            commands = [entry["message"].get("command", "") for entry in entries
                        if entry.get("direction") == "TX" and isinstance(entry.get("message"), dict)]
            loads = [command for command in commands if command.startswith("LOAD ")]
            nonces = [command for command in commands if command.startswith("NONCE ")]
            require(len(loads) == (1 if port == tx else 0), f"{label}: PCM upload reached wrong node")
            require(len(nonces) == (1 if port == tx and mode == "GCM" else 0), f"{label}: nonce provisioned to wrong node")
            if port == rx:
                require(not any(entry.get("direction") in ("TX_BINARY", "TX_BINARY_BLOCK") for entry in entries),
                        f"{label}: host sent binary source to receiver")
            firmware_messages = [entry["message"] for entry in entries
                                 if entry.get("direction") == "RX" and isinstance(entry.get("message"), dict)]
            role_key = "tx_role" if port == tx else "rx_role"
            require(trial[role_key] in firmware_messages and trial[f"status_{port}"] in firmware_messages,
                    f"{label}: allocation/status telemetry absent from raw log")
            if port == tx:
                require(trial["loaded"] in firmware_messages, f"{label}: source loading event absent from raw log")
            else:
                require(trial["armed"] in firmware_messages, f"{label}: ARM event absent from raw log")
        for key, port, event in (("tx_packets", tx, "tx_packet"), ("rx_packets", rx, "rx_packet"),
                                 ("tx_metadata", tx, "tx_metadata"), ("rx_metadata", rx, "rx_metadata"),
                                 ("encrypted_events", tx, "encrypted"), ("decrypted_events", rx, "decrypted")):
            require(raw_events(port, event, identity) == trial[key], f"{label}: raw log mismatch {key}")
        done, complete = trial["tx_done"], trial["rx_complete"]
        require(raw_events(tx, "tx_done", identity) == [done] and raw_events(rx, "rx_complete", identity) == [complete],
                f"{label}: completion log mismatch")
        require(done["mode"] == complete["mode"] == mode, f"{label}: completion mode mismatch")
        wire = source
        tx_meta, rx_meta = trial["tx_metadata"], trial["rx_metadata"]
        if mode == "GCM":
            nonce = bytes.fromhex(trial["nonce_hex"])
            require(len(nonce) == 12 and nonce not in used_nonces, f"{label}: invalid/reused nonce")
            used_nonces.add(nonce)
            wire = (directory / "tx-ciphertext.bin").read_bytes()
            require(len(wire) == 48000 and wire != source, f"{label}: ciphertext absent or equals PCM")
            require((directory / "rx-ciphertext.bin").read_bytes() == wire, f"{label}: ciphertext changed over RF")
            require(sha(wire) not in used_ciphers, f"{label}: ciphertext repeated across unique nonces")
            used_ciphers.add(sha(wire))
            proof = trial["crypto_verification"]
            require(proof["key_saved"] is False and proof["host_expected_ciphertext_sha256"] == sha(wire),
                    f"{label}: runtime expected ciphertext identity mismatch")
            require(all(proof.get(k) is True for k in ("valid", "tx_ciphertext_exact", "rx_ciphertext_exact",
                                                       "ciphertext_differs_from_pcm", "receiver_authenticated")),
                    f"{label}: runtime independent AES-GCM comparison failed")
            meta = bytes.fromhex(trial["expected_metadata_hex"])
            require(len(meta) == 40 and meta[:8] == struct.pack("<BBHI", 0xfb, 1, identity, 48000),
                    f"{label}: invalid metadata AAD")
            require(meta[8:20] == nonce and struct.unpack("<I", meta[36:])[0] == zlib.crc32(meta[:36]) & 0xffffffff,
                    f"{label}: metadata nonce/CRC mismatch")
            require(tx_meta and rx_meta and sum(p["duplicate"] is False for p in rx_meta) == 1,
                    f"{label}: metadata not uniquely received")
            for event in tx_meta + rx_meta:
                require(event["metadata_hex"] == meta.hex() and event["metadata_crc32"] == crc(meta[:36]),
                        f"{label}: on-radio metadata differs from expected")
            require([p["attempt"] for p in tx_meta] == list(range(1, len(tx_meta) + 1)), f"{label}: metadata attempt order")
            require(done["metadata_acked"] is True and sum(p["acked"] is True for p in tx_meta) == 1,
                    f"{label}: metadata acknowledgement missing")
            require(len(trial["encrypted_events"]) == len(trial["decrypted_events"]) == 1, f"{label}: crypto operation count")
            encrypted, decrypted = trial["encrypted_events"][0], trial["decrypted_events"][0]
            require(encrypted["nonce_hex"] == nonce.hex() and encrypted["tag_hex"] == meta[20:36].hex()
                    and encrypted["metadata_hex"] == meta.hex(), f"{label}: encryption metadata mismatch")
            require(decrypted["authenticated"] is True and complete["authenticated"] is True,
                    f"{label}: missing successful authentication")
            require(encrypted["encryption_us"] == done["encryption_us"] and
                    decrypted["decryption_us"] == complete["decryption_us"] and
                    decrypted["message_ready_us"] == complete["message_ready_us"], f"{label}: crypto timer mismatch")
        else:
            require(not tx_meta and not rx_meta and not trial["encrypted_events"] and not trial["decrypted_events"],
                    f"{label}: unexpected crypto operation or metadata in PLAIN")
            require(done["encryption_us"] == complete["decryption_us"] == 0, f"{label}: PLAIN crypto not disabled")
        require(trial["wire_payload_source_sha256"] == sha(wire), f"{label}: wire identity mismatch")

        sent, received = trial["tx_packets"], trial["rx_packets"]
        first = [p for p in sent if p["attempt"] == 1]
        unique = [p for p in received if p["duplicate"] is False]
        duplicate = [p for p in received if p["duplicate"] is True]
        require(len(first) == len(unique) == 200 and {p["index"] for p in first} == {p["index"] for p in unique} == set(range(200)),
                f"{label}: incomplete unique packet/timing sets")
        for packet in sent + received:
            index = packet["index"]
            frame = struct.pack("<BBHBBB", 0xf9, 1, identity, index, 200, 240) + wire[index * 240:(index + 1) * 240]
            require(packet["data_crc32"] == crc(frame), f"{label}: packet CRC mismatch at index {index}")
        for index in range(200):
            attempts = [p for p in sent if p["index"] == index]
            require([p["attempt"] for p in attempts] == list(range(1, len(attempts) + 1)), f"{label}: DATA retry sequence")
            require(attempts[-1]["acked"] is True and sum(p["acked"] is True for p in attempts) == 1, f"{label}: DATA ACK missing")
        for packet, field in [(p, "chunking_us") for p in sent] + [(p, "dechunking_us") for p in received]:
            require(nonnegative_int(packet[field]), f"{label}: invalid processing duration")
        require(all(p["chunking_us"] == 0 for p in sent if p["attempt"] > 1), f"{label}: retry encoded twice")
        tx_us, rx_us = sum(p["chunking_us"] for p in first), sum(p["dechunking_us"] for p in unique)
        duplicate_us = sum(p["dechunking_us"] for p in duplicate)
        tx_status, rx_status = trial[f"status_{tx}"], trial[f"status_{rx}"]
        require((done["chunking_count"], done["chunking_total_us"], tx_status["chunking_total_us"]) == (200, tx_us, tx_us),
                f"{label}: TX timing totals do not reconcile")
        require((complete["dechunking_count"], complete["dechunking_total_us"], rx_status["dechunking_total_us"]) == (200, rx_us, rx_us),
                f"{label}: RX timing totals do not reconcile")
        require((rx_status["dechunking_duplicate_count"], rx_status["dechunking_duplicate_total_us"])
                == (len(duplicate), duplicate_us), f"{label}: duplicate timings do not reconcile")
        require(rx_status["auth_failures"] == 0 and (mode == "PLAIN" or rx_status["authenticated"] is True), f"{label}: authentication failure")
        tx_ok = sum(p["tx_radio_status"] == 0 for p in sent)
        ack_ok = sum(p["ack_status"] == 0 for p in received)
        meta_ok = sum(p["tx_radio_status"] == 0 for p in tx_meta)
        meta_ack_ok = sum(p["ack_status"] == 0 for p in rx_meta)
        require(done["success"] is True and done["acked_chunks"] == complete["received_chunks"] == 200, f"{label}: completion failure")
        require((done["attempts"], done["retries"], done["successful_transmits"], done["data_bytes_sent"], done["ack_bytes_received"])
                == (len(sent), len(sent) - 200, tx_ok, tx_ok * 251, 200 * 14), f"{label}: DATA counters mismatch")
        require((done["metadata_attempts"], done["metadata_successful_transmits"], done["metadata_ack_received"])
                == (len(tx_meta), meta_ok, sum(p["acked"] is True for p in tx_meta)), f"{label}: metadata counters mismatch")
        airtime_us = tx_ok * nodes[tx]["data_airtime_us"] + ack_ok * nodes[rx]["ack_airtime_us"]
        airtime_us += meta_ok * nodes[tx]["metadata_airtime_us"] + meta_ack_ok * nodes[rx]["ack_airtime_us"]
        radio_bytes = tx_ok * 251 + ack_ok * 14 + meta_ok * 40 + meta_ack_ok * 14
        require(trial["accounting"]["estimated_airtime_successful_radio_calls_us"] == airtime_us and
                trial["accounting"]["total_rf_payload_bytes_successful_tx_calls"] == radio_bytes,
                f"{label}: radio airtime/byte accounting mismatch")
        sender_times = [done[k] for k in ("start_us", "radio_start_us", "end_us")]
        receiver_times = [complete[k] for k in ("first_transport_rx_us", "first_rx_us", "last_rx_us", "message_ready_us")]
        require(all(nonnegative_int(v) for v in sender_times + receiver_times) and sender_times == sorted(sender_times)
                and receiver_times == sorted(receiver_times), f"{label}: local clock boundary mismatch")
        require(done["radio_start_us"] == (tx_meta if mode == "GCM" else sent)[0]["start_us"], f"{label}: first radio timestamp mismatch")
        require(all(nonnegative_int(v) for v in (done["encryption_us"], complete["decryption_us"])), f"{label}: crypto duration invalid")
        require(done["encryption_us"] <= done["radio_start_us"] - done["start_us"] and
                complete["decryption_us"] <= complete["message_ready_us"] - complete["last_rx_us"], f"{label}: crypto duration exceeds containing interval")
        row = {"trial": number, "mode": mode, "direction": f"{tx}->{rx}",
               "tx_seconds": (done["end_us"] - done["start_us"]) / 1e6,
               "radio_window_seconds": (done["end_us"] - done["radio_start_us"]) / 1e6,
               "rx_data_span_seconds": (complete["last_rx_us"] - complete["first_rx_us"]) / 1e6,
               "rx_ready_span_seconds": (complete["message_ready_us"] - complete["first_transport_rx_us"]) / 1e6,
               "airtime_seconds": airtime_us / 1e6, "encryption_ms": done["encryption_us"] / 1000,
               "decryption_ms": complete["decryption_us"] / 1000,
               "chunking_ms": tx_us / 1000, "dechunking_ms": rx_us / 1000,
               "duplicate_processing_ms": duplicate_us / 1000,
               "data_retries": len(sent) - 200, "metadata_retries": max(0, len(tx_meta) - 1),
               "total_retries": len(sent) - 200 + max(0, len(tx_meta) - 1),
               "data_duplicates": len(duplicate), "metadata_duplicates": sum(p["duplicate"] is True for p in rx_meta),
               "receiver_crc_errors": rx_status["crc_errors"], "receiver_app_errors": rx_status["app_errors"],
               "successful_radio_payload_bytes": radio_bytes, "voice_pcm_bytes": 48000,
               "sealed_message_bytes": 48028 if mode == "GCM" else 48000,
               "nominal_additional_radio_payload_bytes": 54 if mode == "GCM" else 0}
        for role in ("tx", "rx"):
            memory = trial[f"{role}_role"]
            require(memory["mode"] == mode and memory["allocation_requested_bytes"] == (48000 if role == "tx" else 48036), f"{label}: role allocation contract")
            require(memory["crypto_buffer_requested_bytes"] == (48000 if mode == "GCM" else 0), f"{label}: crypto buffer request")
            require(memory["allocation_actual_bytes"] >= memory["allocation_requested_bytes"] and
                    memory["crypto_buffer_actual_bytes"] >= memory["crypto_buffer_requested_bytes"], f"{label}: allocation underreported")
            require((memory["psram_total_bytes"], memory["flash_total_bytes"]) == (2097152, 16777216), f"{label}: board capacity mismatch")
            for key in ("allocation_requested_bytes", "allocation_actual_bytes", "crypto_buffer_requested_bytes",
                        "crypto_buffer_actual_bytes", "crypto_context_bytes", "crypto_key_bytes", "crypto_metadata_bytes",
                        "packet_scratch_bytes", "internal_heap_free_bytes", "internal_heap_min_free_bytes"):
                require(nonnegative_int(memory[key]), f"{label}: missing/invalid memory units {key}")
                row[f"{role}_{key}"] = memory[key]
            row[f"{role}_total_requested_bytes"] = memory["allocation_requested_bytes"] + memory["crypto_buffer_requested_bytes"]
            row[f"{role}_total_allocated_bytes"] = memory["allocation_actual_bytes"] + memory["crypto_buffer_actual_bytes"]
            row[f"{role}_psram_decrease_bytes"] = memory["psram_before_bytes"] - memory["psram_free_bytes"]
        rows.append(row)
    groups = {}
    for mode in ("PLAIN", "GCM"):
        selected = [row for row in rows if row["mode"] == mode]
        directions = dict(Counter(row["direction"] for row in selected))
        require(directions == {"COM6->COM7": 5, "COM7->COM6": 5}, f"{mode}: direction imbalance")
        groups[mode] = {"trials": len(selected), "directions": directions, "means": aggregate(selected),
                        "retry_total": sum(row["total_retries"] for row in selected),
                        "receiver_crc_error_total": sum(row["receiver_crc_errors"] for row in selected)}
    differences = {key: groups["GCM"]["means"][key]["mean"] - groups["PLAIN"]["means"][key]["mean"]
                   for key in groups["PLAIN"]["means"]}
    return {"passed": True, "created_at": datetime.now(timezone.utc).isoformat(), "run_folder": str(folder),
            "trial_count": 20, "mode_counts": {mode: groups[mode]["trials"] for mode in groups},
            "groups": groups, "gcm_minus_plain_mean": differences, "trials": rows,
            "all_audio_byte_exact": True, "unique_message_ids": len(used_ids),
            "unique_encryption_nonces": len(used_nonces), "unique_ciphertexts": len(used_ciphers),
            "redacted_key_command_count": len(key_commands), "source_pcm_sha256": sha(source),
            "units": {"memory": "bytes; 1 KiB = 1024 bytes", "processing": "milliseconds",
                      "transfer_and_airtime": "seconds", "source_duration": "3.00 seconds"},
            "limits": ["The ephemeral session key was not retained. AES-GCM expected-ciphertext comparison was performed by the host with the live key during each trial; this independent offline audit checks saved bytes/hashes/metadata and raw firmware proof, and cannot repeat AES itself.",
                       "Configured airtime is computed from successful DATA, metadata and ACK calls, including retries; it is not a direct RF measurement.",
                       "Device-local processing intervals include timer/scheduling overhead. TX/RX/airtime intervals overlap and cannot be added.",
                       "PLAIN trials precede GCM trials; retry/environment variability affects elapsed transfer differences. Extra 48000-byte GCM buffers reflect this implementation, not a mandatory AES storage requirement."]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.folder)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "trial_count": result["trial_count"],
                      "mode_counts": result["mode_counts"], "gcm_minus_plain_mean": result["gcm_minus_plain_mean"]}, indent=2))
