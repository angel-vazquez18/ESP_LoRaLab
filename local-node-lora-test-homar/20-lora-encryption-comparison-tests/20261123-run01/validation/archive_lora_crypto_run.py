"""Freeze the new 20-trial comparison without overwriting historical evidence."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "captures/20261123-lora-crypto-comparison-run01"
DEST = ROOT / "20-lora-encryption-comparison-tests/20261123-run01"
REPORT = "Heltec_LoRa_20_Trial_Encryption_Comparison_Report"


def record(path):
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def verify_archive(path):
    manifest = json.loads((path / "ARCHIVE_MANIFEST.json").read_text())
    for name, expected in manifest["files"].items():
        assert record(path / name) == expected, f"Historical file changed: {path / name}"
    return len(manifest["files"])


def copy(source, relative):
    target = DEST / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    assert record(source) == record(target)


def main():
    previous = [ROOT / "10-lora-message-tests", ROOT / "10-lora-message-tests/20261123-processing-run01"]
    old_counts = {p.relative_to(ROOT).as_posix(): verify_archive(p) for p in previous}
    summary = json.loads((RUN / "summary.json").read_text())
    assert summary["passed_trials"] == summary["requested_trials"] == summary["attempted_trials"] == 20
    assert summary["connections_closed"] is True
    audit_path = ROOT / "output/validation/lora-crypto-run01-independent-audit.json"
    audit = json.loads(audit_path.read_text())
    assert audit["passed"] and audit["mode_counts"] == {"PLAIN": 10, "GCM": 10}
    report_audit = json.loads((ROOT / f"output/pdf/{REPORT}.json").read_text())
    assert report_audit["all_twenty_verified"] is True
    assert not DEST.exists(), "Refusing to overwrite the archive"
    shutil.copytree(RUN, DEST / "run")
    shutil.copytree(ROOT / "captures/20261123-lora-crypto-ready01", DEST / "readiness")
    for ext in ("pdf", "json"):
        copy(ROOT / f"output/pdf/{REPORT}.{ext}", f"{REPORT}.{ext}")
    for name in (
        "lora-crypto-build.log", "lora-crypto-upload.log", "lora-crypto-host-tests.log",
        "lora-crypto-run01-independent-audit.json", "audit_lora_crypto_run.py",
        "lora-crypto-report-qa.json",
        "snapshot_lora_crypto_implementation.py", "archive_lora_crypto_run.py",
        "lora-crypto-initial-build-failure.log", "lora-crypto-macro-build-failure.log",
    ):
        copy(ROOT / "output/validation" / name, Path("validation") / name)
    manifest = json.loads((RUN / "implementation-manifest.json").read_text())
    for name, expected in manifest["files"].items():
        assert record(ROOT / name) == expected, f"Implementation changed during run: {name}"
        if not name.startswith(".pio/"):
            copy(ROOT / name, Path("implementation") / name)
    for name in ("tools/create_lora_crypto_pdf.py", "test/host/lora_crypto_report_test.py",
                 "docs/LORA_ENCRYPTION_COMPARISON.md"):
        copy(ROOT / name, Path("implementation") / name)
    lines = ["# Twenty LoRa trials: plain audio versus AES-128-GCM", "",
             "New physical run on 2026-11-23: ten PLAIN transfers followed by ten AES-128-GCM transfers, five in each direction per group. All twenty received recordings matched the source exactly.", "",
             "Same source: 3.00 seconds of uncompressed 8 kHz, 16-bit mono PCM; 48,000 audio bytes (48,044 WAV bytes). User-reported distance: approximately 24 inches. No microphone, physical speaker or PTT test was performed.", "",
             "| Mean per message | PLAIN | AES-128-GCM |", "| --- | ---: | ---: |"]
    for key, label, unit in (
        ("tx_seconds", "Sender transaction", "s"),
        ("rx_data_span_seconds", "Receiver DATA span", "s"),
        ("airtime_seconds", "Calculated DATA + metadata + ACK airtime", "s"),
        ("chunking_ms", "Chunking", "ms"), ("dechunking_ms", "Dechunking", "ms"),
        ("encryption_ms", "Encryption", "ms"), ("decryption_ms", "Authenticated decryption", "ms"),
        ("tx_total_allocated_bytes", "TX allocated PSRAM blocks", "bytes"),
        ("rx_total_allocated_bytes", "RX allocated PSRAM blocks", "bytes"),
    ):
        values = [audit["groups"][mode]["means"][key]["mean"] for mode in ("PLAIN", "GCM")]
        cells = [f"{value:,.0f}" if unit == "bytes" else f"{value:,.3f}" for value in values]
        lines.append(f"| {label} | {cells[0]} {unit} | {cells[1]} {unit} |")
    lines += ["", "One KiB is 1,024 bytes. Allocation totals sum the original role buffer and the separate crypto buffer, excluding shared static state. The extra 48,000-byte crypto buffer is an implementation choice. Audio is held in volatile PSRAM and is not written to flash.", "",
              "The run uses one fresh session key, unique 12-byte nonces per encrypted message and 16-byte authentication tags. A 40-byte metadata packet and its 14-byte ACK carry the envelope through LoRa before the unchanged 200 DATA packets. Keys were kept only in RAM and command logs were redacted. Stopped nodes retain their session key in volatile RAM until reset or replacement. Offline evidence can recheck saved audio/ciphertext hashes and raw firmware authentication events; independent AES comparison was performed on the computer during the live run while its key was available.", "",
              "The two groups ran in blocks. Retries and bench variability can affect transfer averages; do not attribute the entire elapsed difference to encryption. Processing timers measure local elapsed work, including scheduling overhead. Radio intervals overlap and must not be added.", "",
              "Contents: the seven-page PDF and matching audit JSON; `run/` raw logs, WAVs, ciphertext and trial summaries; `readiness/` device checks; `validation/` build/upload logs and independent audit; `implementation/` measured source and analysis tools. The initial build failures are retained alongside the final successful build log. Firmware image hashes are in the implementation manifest.", ""]
    (DEST / "README.md").write_text("\n".join(lines), encoding="utf-8")
    files = {p.relative_to(DEST).as_posix(): record(p) for p in sorted(DEST.rglob("*")) if p.is_file()}
    (DEST / "ARCHIVE_MANIFEST.json").write_text(json.dumps({
        "purpose": "twenty_new_physical_plain_vs_aes128gcm_trials",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "original_run": RUN.relative_to(ROOT).as_posix(), "file_count": len(files),
        "historical_archive_counts_unchanged": old_counts, "files": files,
    }, indent=2) + "\n", encoding="utf-8")
    assert verify_archive(DEST) == len(files)
    for p in previous:
        assert verify_archive(p) == old_counts[p.relative_to(ROOT).as_posix()]
    print(json.dumps({"archive": str(DEST), "files_verified": len(files), "old_archives_unchanged": old_counts}))


if __name__ == "__main__":
    main()
