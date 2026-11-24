# Isolated LoRa voice test: 10 plain plus 10 encrypted messages

This folder packages the standalone `esp32-audio-chunker-test` experiment from
[lora-walkie-talkie](https://github.com/homarrodriguez/lora-walkie-talkie), source
commit `918bf14`. It contains the firmware, source recording, command-driven test
runner, offline analysis and frozen evidence for **20 physical LoRa transfers**:
ten unencrypted followed by ten using **AES-128-GCM**. Each group alternates
direction, giving five transfers from each node. It is retained separately for
future integration; it does not connect to ESP_LoRaLab's application or build.

## Results already recorded

The physical run on 2026-11-23 passed **20/20 transfers** between Heltec-A / COM6
and Heltec-B / COM7 at a user-reported separation of approximately **24 inches
(60.96 cm)**. All 4,000 unique DATA chunks were reconstructed. Every received
recording matched the source byte for byte. All ten encrypted messages passed
authentication and independent computer-side ciphertext verification.

The source is **3.00 seconds** of uncompressed linear PCM: 8,000 samples/second,
16-bit signed little-endian, mono. It contains 24,000 samples / **48,000 audio
bytes**; its WAV file occupies **48,044 bytes**. No speech-compression codec is
used. The WAV header is not sent over LoRa.

| Average per message | Unencrypted | AES-128-GCM |
| --- | ---: | ---: |
| Sender transaction | 29.461 s | 29.537 s |
| Receiver first transport arrival to ready | 29.322 s | 29.458 s |
| Calculated DATA, metadata and ACK airtime | 22.202 s | 22.214 s |
| Chunking, sum for 200 unique chunks | 116.745 ms | 116.630 ms |
| Dechunking, sum for 200 unique chunks | 72.517 ms | 72.483 ms |
| Encryption | Not used | 17.598 ms |
| Authenticated decryption | Not used | 17.662 ms |
| Allocated message buffers per node | 48,116 bytes | 96,232 bytes |

One KiB is 1,024 bytes. The additional 48,000-byte requested crypto buffer is a
choice in this implementation; it is not an inherent AES requirement. The
allocator reserves 48,116 bytes for that extra buffer. All audio remains in
volatile PSRAM. The board has 2 MiB PSRAM and 16 MiB flash; no audio is written
to flash. The same firmware image supports both modes.

The groups logged 16 and 14 DATA retries respectively, and 12 and nine receiver
radio CRC errors. Retry recovery left zero changed audio bytes. Whole-transfer
differences also reflect retry variation and sequential group order, so the
observed 76 ms difference does not isolate encryption cost. Processing values
are local elapsed intervals, including scheduling overhead; transfer intervals
overlap and must not be added together. Airtime is calculated from the successful
radio calls and configured modem settings, rather than measured with RF equipment.

Read the [seven-page comparison PDF](20-lora-encryption-comparison-tests/20261123-run01/Heltec_LoRa_20_Trial_Encryption_Comparison_Report.pdf),
[independent audit](20-lora-encryption-comparison-tests/20261123-run01/validation/lora-crypto-run01-independent-audit.json),
and [frozen archive index](20-lora-encryption-comparison-tests/20261123-run01/README.md).
The archive manifest preserves 130 files, including raw serial logs, recovered
WAVs, ciphertext exports, per-trial summaries, build/upload evidence and the
exact measured source snapshot. Those are historical physical observations;
local software tests do not establish a new radio result. Do not overwrite them.

## Package layout

- `src/lora_crypto_bench.cpp`: measured `lora-crypto-1-gcm` radio firmware.
- `include/` and `lib/`: framing, chunk assembly, CRC, OLED and format constants.
- `input/source.wav`: original recorded source, preserved byte-for-byte.
- `tools/lora_crypto_bench.py`: 20-trial physical runner, also supporting a local
  check and an explicitly requested readiness-only hardware check.
- `tools/run_lora_crypto_comparison.ps1`: command gate for exactly ten trials
  per mode. Calling it with no flags describes the plan only.
- `tools/create_lora_crypto_pdf.py`: offline audit and PDF generator.
- `tools/lora_transfer_bench.py` and `tools/create_lora_consistency_pdf.py`:
  shared runner and report dependencies. The transfer module's legacy standalone
  CLI is disabled in this package; use the crypto comparison entry point.
- `tools/verify_heltec_bench.py`: USB identity helpers only, with no audio CLI.
- `test/host/`: mocked-device Python checks and portable C++ protocol tests.
- `20-lora-encryption-comparison-tests/`: the requested frozen physical run.
- `SNAPSHOT_MANIFEST.json`: packaged-file hashes and source provenance.

The firmware, headers and libraries are copied verbatim. Packaging adaptations
are confined to the LoRa-only PlatformIO configuration, portable interpreter and
WAV defaults, dependency declarations, the USB helper extraction, the disabled
legacy transfer CLI, portable temporary-file handling in report tests, host
test launcher, documentation and manifest. No compiled
firmware, environment, dependency cache, microphone/speaker driver or old
ten-trial archive is added as a top-level runnable component. Files under the
frozen archive retain the original paths and context of the measured source;
they are evidence, not the package's active build configuration.

## Hardware and local setup

This bench targets the standard Heltec WiFi LoRa 32 V4.3 / ESP32-S3R2 / SX1262
boards used by the source project, not V4-R8. The onboard OLED and radio need no
additional display or radio wiring. Keep matching LoRa antennas attached. Audio
capture, physical speaker playback and PTT are inactive. This package does not
change ESP_LoRaLab's hardware assignments or validate its external audio wiring.

| Node | Recorded port | Hardware MAC / USB identity |
| --- | --- | --- |
| Heltec-A | COM6 | `8C:FD:49:B5:B7:8C` |
| Heltec-B | COM7 | `44:1B:F6:6F:99:E4` |

Windows can reassign port numbers. The runner matches USB identity and firmware
identity before a test. The display shows the assigned node/port, role, status
and `Test n of 20`; short chunking phases remain visible as the last phase.

The fixed radio profile is 915 MHz, bandwidth 500 kHz, SF7, coding rate 4/5,
sync word `0x12`, preamble eight symbols and SX1262 chip power -9 dBm. Chip power
is not a calibrated radiated-power measurement; the board includes an RF front
end. The measured onboard pin configuration is preserved in `config.h`.

Run the following commands **from this folder**, using Python 3.11 or newer:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\pio.exe run -e heltec_crypto_com6 -e heltec_crypto_com7
```

PlatformIO is pinned to `espressif32@8.0.0`, RadioLib to `7.6.0`, and the
ThingPulse OLED driver to `4.6.2`. A first dependency install needs network access.
Python dependencies are installed in the chosen environment, without searching
another user's runtime directories.

On Windows, use a short checkout path if dependency extraction reports a path
length error. PlatformIO also accepts `PLATFORMIO_LIBDEPS_DIR` and
`PLATFORMIO_BUILD_DIR` environment variables pointing to short local paths;
these relocate dependency/build caches without changing the firmware source.

Upload only when deliberately preparing these two identified boards and after
closing their serial monitors. These commands replace installed firmware:

```powershell
.\.venv\Scripts\pio.exe run -e heltec_crypto_com6 -t upload
.\.venv\Scripts\pio.exe run -e heltec_crypto_com7 -t upload
```

Booting the firmware does not start a transmission. Both modes use the same
binary on each node; there is no reflashing between groups.

## Local checks and explicit test start

These commands do not open or enumerate physical serial ports:

```powershell
# Description only; does not even invoke Python.
powershell -NoProfile -ExecutionPolicy Bypass -File tools/run_lora_crypto_comparison.ps1
# Source and host cryptography checks only.
powershell -NoProfile -ExecutionPolicy Bypass -File tools/run_lora_crypto_comparison.ps1 -Check
# Offline tests with generated temporary evidence and mocked devices.
.\.venv\Scripts\python.exe -B -m unittest discover -s test/host -p '*_test.py'
powershell -NoProfile -ExecutionPolicy Bypass -File test/host/run.ps1 -Compiler 'C:\msys64\ucrt64\bin\g++.exe'
```

When the identified devices are ready and a new physical run is intended:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/run_lora_crypto_comparison.ps1 -Start
```

The launcher accepts `-Python`, `-Wav`, `-TxPort`, `-RxPort` and `-OutputDir`
overrides. Default inputs are this folder's `.venv\Scripts\python.exe` and
`input\source.wav`. Default results go into a fresh timestamped `captures/`
directory. A specified output directory must not already exist. The runner
keeps both USB readers active, sends source PCM only to the transmitter, stops
on a failed trial without replacing it, and closes both serial ports afterward.

The optional readiness command below **does open both ports**. It checks
identity, OLED, radio readiness and cryptographic self-tests, but does not load
source audio, arm reception or transmit a LoRa message:

```powershell
.\.venv\Scripts\python.exe tools/lora_crypto_bench.py --wav input/source.wav --prepare-only
```

Each completed run automatically generates a PDF and JSON audit. To regenerate
an offline report from new saved evidence without opening devices:

```powershell
.\.venv\Scripts\python.exe tools/create_lora_crypto_pdf.py captures/NEW-RUN-FOLDER
```

## Encryption and evidence boundaries

The computer provisions one fresh 128-bit session key over USB to both nodes.
KEY commands are redacted and no secret key is saved. Each encrypted message
gets a new 12-byte nonce, supplied only to the transmitter over USB. The sender
encrypts all 48,000 PCM bytes once, then sends a 40-byte metadata payload with
an eight-byte authenticated header, nonce, 16-byte tag and CRC32. Its ACK is 14
bytes. The ciphertext is split into the same 200 DATA frames as unencrypted
PCM: each contains 240 content bytes, a seven-byte voice header and four-byte
CRC32, for a 251-byte radio payload. A DATA ACK is 14 bytes.

Without retries, encryption adds **54 radio payload bytes** and **32.128 ms**
of calculated metadata-plus-ACK airtime. Ciphertext is still 48,000 bytes;
ciphertext plus nonce and tag occupies 48,028 bytes. The receiver reconstructs
it, verifies the tag, and decrypts before releasing the message and acknowledging
the final DATA frame. Retries reuse the same sealed message.

The host computes an independent expected AES-GCM result while the live key is
available and compares both nodes' exported ciphertext. It also compares the
final PCM byte-for-byte with the source. The discarded host key is unavailable
for repeating the historical AES calculation offline; retained bytes, hashes,
metadata and authentication events can still be audited. STOP leaves a node's
key in volatile RAM until reset or replacement. This bench does not implement
production key management, persistent replay protection or authenticated ACKs.

CRC32 detects accidental corruption, and SHA-256 identifies saved content;
neither is encryption. GCM supplies encryption and authentication for the audio
and its bound header. Preflight known-answer and tamper rejection self-tests are
separate from the twenty physical radio trials.

## Future integration boundary

ESP_LoRaLab's selected baseline uses ESP-IDF 6, modular C firmware, bounded
NDJSON v2 control, a different RF framing/fragment contract, planned per-frame
protection and replay/ACK rules, and Codec 2 speech coding. This package uses
Arduino/PlatformIO, its existing text/JSON plus binary USB protocol, 240-byte
content chunks and whole-message GCM over uncompressed PCM. Those interfaces
are not interchangeable. The package adds no application imports, build hooks,
shared-schema changes or hardware qualification claims for ESP_LoRaLab.

The requested work is only to retain this separate folder for review. Integration
and any physical test of ESP_LoRaLab remain future work.
