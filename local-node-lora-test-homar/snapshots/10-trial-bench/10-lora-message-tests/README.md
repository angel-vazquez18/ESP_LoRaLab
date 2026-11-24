# 10 LoRa message tests

Frozen evidence from the operator-authorized ten-trial voice-message consistency
run on November 23, 2026. This folder is an archive, not a new test execution.

## Result

- 10/10 transfers passed: five COM6 to COM7 and five in the reverse direction.
- User-reported separation: approximately 24 inches (60.96 cm).
- Same 3-second, 8 kHz, 16-bit mono recording in every trial: 48,000 PCM bytes
  (48,044 bytes in the WAV container). All received samples and bytes matched.
- 2,000 unique chunks; seven retries, six receiver PHY CRC errors and one
  duplicate delivery were recovered. No application-frame errors.
- Sender transaction: 28.401122 to 29.848166 seconds, mean 28.9197487 seconds.
  The complete run spanned 297.230 seconds.
- Each board reported 16 MiB flash and 2 MiB PSRAM. TX requested 48,000 PSRAM
  bytes, RX requested 48,036; actual allocation was 48,116 bytes per role.
- Final state: IDLE, Test 10 of 10; both serial ports closed. No microphone,
  physical speaker or PTT test was part of this run.

## Contents

- `Heltec_LoRa_10_Trial_Consistency_Report.pdf`: four-page beginner report.
- Matching JSON: the report's structured evidence audit.
- `run/`: unchanged original run folder, source and ten received WAVs, sender
  exports, raw USB logs/bytes, packet/timestamp summaries and code hashes.
- `readiness/`: checks performed before authorization to start, with zero RF
  transmission counters and OLED initialization/layout checks.
- `validation/`: build, upload and offline-test logs plus independent audit.
- `ARCHIVE_MANIFEST.json`: SHA-256 hashes of archived files.

The PCM SHA-256 is
`1f658cb596716d1b0d34426dd0d0a9f3aa561f8eee385b1788d4e438b44ba2ac`;
CRC32 is `46248425`. Local paths and port identities in original logs are
historical provenance. Copied files are preserved byte for byte.

Firmware and repeatable tooling live in the containing project's `src/`,
`include/`, `lib/`, `tools/` and `test/host/` directories. Start a new run only
through the explicit command described in its README. Do not overwrite this
archive or treat offline fixtures as additional hardware results.

Chunking, individual RAM writes and reassembly CPU time were not separately
instrumented. TX and RX intervals overlap; clock-alignment estimates are not
precise RF propagation measurements. These results establish stored-message
integrity at this bench separation, not real-time audio or long-range reliability.
