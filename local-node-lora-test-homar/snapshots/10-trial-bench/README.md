# Isolated Heltec LoRa voice-transfer test

This folder contains the firmware, tools, source voice sample, and frozen evidence for the ten-trial LoRa transfer experiment on 2026-11-23. It is a standalone test snapshot inside ESP_LoRaLab. It does not integrate with ESP_LoRaLab's application, ESP-IDF build, encrypted packet format, or NDJSON protocol, and makes no compatibility or integration qualification claim.

The experiment sends the same three-second recorded voice sample over the physical SX1262 radios ten times, alternating directions: five Heltec-A to Heltec-B transfers and five Heltec-B to Heltec-A transfers. The reported board separation was **24 inches**; software does not measure that distance. The source is uploaded by USB only to the transmitter. Receiver PCM is obtained from radio packet reassembly and then downloaded by USB for comparison. Microphone capture, speaker playback, and PTT are inactive.

## Contents and evidence

- `src/lora_bench.cpp`: dedicated `lora-integrity-2-oled` firmware.
- `include/` and `lib/`: bounded packet framing, CRC, chunk assembly, and onboard OLED display dependencies.
- `input/source.wav`: the original input recording, 8,000 Hz, mono, signed 16-bit PCM, 24,000 samples / 48,000 PCM bytes. The WAV file is 48,044 bytes; its container header is not sent over LoRa.
- `tools/`: manual-start launcher, radio runner, readiness check, offline reports, and USB identity dependency.
- `test/host/`: offline protocol, chunker, OLED, runner, readiness, and report tests. Tests generate temporary evidence rather than using the frozen run as a fixture.
- [`10-lora-message-tests/`](10-lora-message-tests/): frozen ten-trial results and source provenance, supplied with this snapshot. Read its reports and `summary.json` for the actual outcomes, packet retries/errors, and timing limits. Do not overwrite this evidence with a new run.

Firmware, protocol, OLED code, and most tools/tests are copied verbatim from the source project. Packaging changes are limited to the LoRa-only PlatformIO configuration, local Python/WAV defaults, portable host-tool discovery, extraction of USB identity helpers with mocked tests, this documentation, and dependencies. No compiled firmware, build cache, old three-trial run, audio driver, microphone/speaker bench, or stored synthetic report fixture is included.

`config.h` retains shared audio-format constants and unused audio/simulated-transport settings to preserve the tested source. Those unused sections do not describe this radio firmware. `audio_diagnostics.h` supplies CRC helpers. `verify_heltec_bench.py` contains only the known-node table and USB identity helpers, preserved verbatim from the source project; the legacy audio/tone CLI has been removed. Its filename stays the same to preserve the LoRa runner's import.

## Hardware and build

Use the standard Heltec WiFi LoRa 32 V4.3 with ESP32-S3R2, 16 MB flash, 2 MB quad PSRAM, and SX1262. This snapshot is not configured for V4-R8. Keep the matching LoRa antennas connected. The OLED and radio are onboard. Keep the L76/GNSS expansion unplugged for the existing external audio wiring; external audio hardware is not exercised here.

| Node | Recorded Windows port | USB identity / MAC |
| --- | --- | --- |
| Heltec-A | COM6 | `8C:FD:49:B5:B7:8C` |
| Heltec-B | COM7 | `44:1B:F6:6F:99:E4` |

Windows may change the port assignment. The runner verifies the known USB identities and firmware identity before a run. The build labels are fixed to the two recorded assignments; verify the board before any upload.

Radio configuration: 915 MHz, bandwidth 500 kHz, SF7, coding rate 4/5, sync word `0x12`, and SX1262 chip power -9 dBm. Chip power is not a calibrated radiated-power measurement; the board has an RF front end. Onboard connections are NSS8, SCK9, MOSI10, MISO11, RESET12, BUSY13, and DIO1 14. The firmware initializes the V4 front end, 1.8 V TCXO, and DIO2 switching. OLED uses SDA17, SCL18, RESET21, and Vext36. Amplifier SD48 remains low.

From **this folder**, use Python 3.11 or newer and PowerShell 7 (`pwsh`) with local script execution permitted:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\pio.exe run -e heltec_lora_com6 -e heltec_lora_com7
```

PlatformIO is pinned to `espressif32@8.0.0`; RadioLib is `7.6.0`; the ThingPulse OLED driver is `4.6.2`. The two environments retain the source project's board, memory, USB, and compilation settings. Initial dependency installation may need network access.

Upload only when deliberately preparing these identified devices. Close their serial monitors first:

```powershell
.\.venv\Scripts\pio.exe run -e heltec_lora_com6 -t upload
.\.venv\Scripts\pio.exe run -e heltec_lora_com7 -t upload
```

These commands replace the devices' existing firmware. The firmware boots without transmitting; an explicit host test command starts each transfer.

## Verify locally, then start manually

The following commands do **not** enumerate or open serial devices and do not transmit:

```powershell
# Description only; default invocation does not launch Python.
.\tools\run_lora_consistency.ps1
# Local source, WAV, dependency, and requested protocol checks only.
.\tools\run_lora_consistency.ps1 -Check
# Python tests use mocked devices and temporary local files.
.\.venv\Scripts\python.exe -B -m unittest discover -s test\host -p '*_test.py'
# Portable C++ tests; supply a g++ path if it is not on PATH.
.\test\host\run.ps1 -Compiler 'C:\msys64\ucrt64\bin\g++.exe'
```

The launcher gate test finds `pwsh` or `powershell` on PATH. If PowerShell 7 is installed elsewhere, set `$env:LORA_TEST_POWERSHELL` to its executable path before the Python tests. This selects the test shell without changing the machine's execution policy.

The optional readiness command below **opens both devices** and checks the installed OLED/firmware state, but never loads voice PCM, arms RX, or starts RF. It expects freshly booted devices with zero prior test/transmit counters:

```powershell
.\.venv\Scripts\python.exe tools\prepare_lora_consistency.py --ports COM6 COM7
```

**Only start another radio test when explicitly intended.** With both boards identified, antennas attached, and other serial monitors closed:

```powershell
.\tools\run_lora_consistency.ps1 -Start
```

The launcher always requests ten alternating trials, OLED test counters, continuation after ordinary RF delivery failures, and the user-reported 24-inch distance. It accepts `-TxPort`, `-RxPort`, `-Wav`, and `-OutputDir` overrides; output must be a new directory. Its default Python is `.venv\Scripts\python.exe`, used for both collection and PDF reporting. Override `-RunnerPython` and `-ReportPython` when using separate existing environments. Default new results go under `captures/`, not the frozen archive.

The generic Python runner remains unchanged apart from its report-interpreter default; it also supports other trial counts. Use the PowerShell launcher for this defined ten-trial experiment. Never use a historical report as proof that a new run passed.

## What is measured

Each message is split into 200 chunks of 240 PCM bytes. Each LoRa data payload is 251 bytes: a 7-byte voice header, 240 PCM bytes, and a 4-byte application CRC32. Each ACK is 14 bytes. Stop-and-wait delivery has a 500 ms ACK timeout and a maximum of six attempts per chunk. Data and ACK byte accounting is separate from LoRa PHY airtime and overhead.

The runner compares source, transmitter dump, and receiver dump using exact PCM bytes, CRC32, SHA-256, and sample differences. A final byte-exact result can coexist with a corrupted radio packet that was recovered through retry; reports retain both facts. Memory observations include requested/actual allocations and PSRAM changes. These are scoped allocation measurements, not a complete whole-system memory profile.

Device timestamps and bounded clock alignment estimate transfer/ACK intervals when eligible. They do not measure radio propagation time. USB scheduling, firmware processing, retries, and display refresh have separate effects; consult each report's timing caveats.

Both OLEDs show the node label, Transmitter/Receiver role, current state, most recent processing phase, and `Test n of 10`. `Last: CHUNKING` / `Last: DECHUNKING` retain the last short processing phase so it remains readable. They do not claim that processing is still active. Display updates run separately from the RF-critical path.

Offline report regeneration for a **new** run:

```powershell
.\.venv\Scripts\python.exe tools\create_lora_consistency_pdf.py captures\NEW-RUN-FOLDER
.\.venv\Scripts\python.exe tools\report_lora_transfer.py captures\NEW-RUN-FOLDER
```

These report tools read saved evidence and do not access hardware. Missing, incomplete, or corrupted evidence remains distinguishable from a passing trial.
