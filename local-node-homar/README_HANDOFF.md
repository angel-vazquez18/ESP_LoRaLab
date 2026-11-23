# ESP32 audio chunker: project snapshot and integration handoff

Snapshot date: **2026-11-05 (America/New_York)**. This package captures the files
saved in the project directory at packaging time, including local recordings.
The firmware identifies itself as `audio-bench-3-pcm-export`.

For integration into another repository, copy the prompt in
[INTEGRATION_PROMPT.md](INTEGRATION_PROMPT.md) and set its source and target paths.
The existing [README.md](README.md) retains the detailed development history,
console instructions, and evidence. [BENCH_VALIDATION.md](BENCH_VALIDATION.md)
contains wiring and hardware acceptance procedures; some entries describe earlier
bench states rather than the latest result.

## Project scope

This is a PlatformIO/Arduino bench project for an ESP-WROOM-32, an INMP441 I2S
microphone, and a MAX98357A I2S amplifier. It establishes the audio and packet
handling foundation for a future store-and-forward, half-duplex voice/PTT system.

The current firmware can:

- Record exactly 24,000 mono samples: three seconds at nominal 8 kHz, signed
  16-bit PCM, occupying 48,000 bytes.
- Play captured PCM directly, or generate a one-second 1 kHz speaker test tone.
- Split a recording into 200 indexed packets, simulate delivery in RAM, reassemble
  it, verify the reconstructed bytes, and play the result.
- Exercise out-of-order delivery, duplicate handling, malformed packet rejection,
  and deliberate packet loss. Missing chunks remain zero PCM (silence).
- Report I2S readiness, firmware/reset information, amplitude and raw-word
  diagnostics, and export a completed recording over serial with CRC-32.
- Save recordings on the PC as WAV, JSON measurements, SVG waveforms, and text
  logs using the supplied Python recording console.

There is no radio transport, live streaming, codec/compression, firmware file
storage, or completed asynchronous PTT service. The default firmware leaves PTT
disabled. If enabled, a press records one fixed three-second clip. Audio operations
and the serial command harness are synchronous and block the calling task.

## Package contents

| Path | Purpose |
| --- | --- |
| `platformio.ini` | Pinned platform and full/speaker-only/serial-only build environments |
| `src/main.cpp` | Standalone bench entry point, command handling, simulation and PCM export |
| `lib/audio/` | Microphone capture, speaker playback, amplifier startup and diagnostics |
| `lib/chunking/` | Packet creation and indexed receive assembly |
| `include/` | Audio constants, board pins, packet layout and CRC helper |
| `tools/` | PC recording/export utilities and PowerShell launcher |
| `test/host/` | C++ tests with peripheral stubs and Python capture/console tests |
| `captures/` | Existing recordings and failed-attempt logs retained as bench evidence |
| `README.md`, `BENCH_VALIDATION.md` | Existing operating instructions and hardware checks |
| `INTEGRATION_PROMPT.md` | Copyable instructions for an agent working in the destination repo |
| `SNAPSHOT_MANIFEST.json` | Archive-only file inventory with byte counts and SHA-256 hashes |

Generated `.pio/` builds, downloaded toolchains, `.host-test/` executables, Python
bytecode/cache directories, Git internals, generated VS Code IntelliSense/debug
files, and `exports/` are excluded. `.vscode/extensions.json` and `.gitignore` are
included. The archive is a source snapshot and requires its build tools to be
installed separately. Unsaved editor buffers are not part of the snapshot.

At the 2026-11-05 snapshot, `captures/` was Git-ignored even though it was included
in the ZIP. The current private repository includes `captures/` and `exports/`
by request; the archived ZIP itself is unchanged. A folder
containing `error.json` is a failed attempt, not a completed recording. Capture
labels and filenames are preserved as saved.

## Build and operate the standalone snapshot

Extract the ZIP, then open the enclosed `esp32-audio-chunker-test` directory.
Install PlatformIO Core or the PlatformIO IDE extension. The project pins
`espressif32@8.0.0`, selects `esp32dev`, uses the Arduino framework, and selects
`huge_app.csv`. The existing README records Arduino-ESP32 3.3.12 / ESP-IDF 5.5.5
as the installed baseline. Dependency downloads are not bundled.

```powershell
pio run -e esp32dev
pio run -e speaker_only
pio run -e serial_only
```

If `pio` is not on PATH, substitute
`& "$env:USERPROFILE\.platformio\penv\Scripts\pio.exe"` on a typical Windows
PlatformIO installation. Upload only after reviewing the bench wiring and selecting
the board's actual port; COM4 in the old examples is a local historical setting.
The serial baud rate is 115200.

| Firmware command | Action |
| --- | --- |
| `s` | Speaker test tone |
| `m` | Record and print statistics |
| `r` | Record and play directly |
| `p` | Record, simulate packet transfer, verify, and play |
| `t` | Deterministic reverse-order packet integrity test; invalidates the recorded buffer |
| `l` | Toggle loss simulation: none or 11 missing chunks |
| `i`, `x`, `h` | System information, protocol information, heartbeat toggle |
| `d` | Binary export of the last valid recording; use the PC tools |

The PC tools require Python 3 and `pyserial`. With the regular serial monitor
closed, use `tools/record-monitor.ps1 -Port <actual-port>` on Windows, or
`python tools/record_monitor.py --port <actual-port>` with a suitable Python
environment. Commands such as `m quiet` and `r playback_check` record and save
captures; `d saved-earlier` exports the retained recording, and `q` exits.
Wait for `SAVED` before sending the next recording command.

Existing checks can be run from the extracted project root:

```powershell
.\test\host\run.ps1
# Or pass -Compiler 'C:\path\to\g++.exe' (C++17-capable MinGW).
python .\test\host\capture_audio_test.py
python .\test\host\record_monitor_test.py
```

The C++ runner defaults to `C:\msys64\ucrt64\bin\g++.exe`. Use the intended
Python environment if `python` is not on PATH. These commands are provided for
reproduction; firmware builds, host tests and physical bench tests were not rerun
as part of this packaging task. Archive integrity and per-file hashes were checked.

## Integration contracts

- **Memory and lifetime:** the TX buffer is 48,000 bytes; each `VoiceChunker`
  contains another 48,000-byte RX buffer plus bookkeeping. Keep both off small
  task stacks. `beginTransmit()` borrows its PCM pointer, so the source must remain
  valid and unchanged until all packets are made. `receiveBuffer()` is internal
  storage that is cleared or changed by reset, a new message, or incoming packets.
  Account separately for runtime I2S DMA and other destination firmware memory.
- **Packet version 1:** exactly 247 bytes: a packed seven-byte header followed by
  240 PCM bytes. Header fields are magic `0xF9`, version `0x01`, a two-byte message
  ID, chunk index 0-199, total chunks 200, and payload length 240. The present
  ESP32 packed message ID is little-endian. CRC-32 belongs to the serial PCM export;
  there is no CRC field in `VoicePacket`.
- **Receiver ownership:** any differing message ID resets the current assembly.
  There is no sender identity, stale-message rejection, receive timeout, retry, or
  concurrency protection. Define those boundaries before connecting a real
  transport. Preserve packet validation, first-duplicate retention, and silent
  missing chunks unless deliberately changing the protocol.
- **Peripheral ownership:** capture uses legacy I2S port 0; playback uses port 1
  with identical mono samples in both 16-bit stereo slots. GPIO mapping is in
  `include/pins.h`: mic BCLK/WS/data = 26/25/33; amplifier BCLK/WS/data/SD =
  14/16/17/27; PTT = 4. These are the current WROOM bench assignments, not portable
  defaults for another board.
- **Amplifier sequencing:** preserve the GPIO27 SD pulldown/wiring requirement,
  shutdown, stopped-clock setup, silent DMA initialization, idle-level check,
  20-microsecond enable-to-clock delay, and continuous clocks after startup.
  `stopSpeaker()` clears queued audio; it does not shut off the clocks. Consult the
  bench guide before changing the sequence or power arrangement.
- **Application ownership:** reuse the libraries through the target's application
  lifecycle. Do not create a second `setup()`/`loop()` or initialize I2S twice.
  Serialize access to audio, buffers and chunker state. Do not run blocking audio
  calls in ISRs, radio callbacks, or time-critical application handlers.
- **Compatibility:** the audio code uses the legacy I2S driver and low-level
  `hal/i2s_ll.h`. Check the destination chip, framework/IDF, I2S resources, pins,
  memory and partition requirements before merging build settings. A Heltec V4
  or another ESP32-family board needs its own verified mapping and porting work.

## Current evidence and next work

The existing README records an audible test tone after cabling was reconnected.
It also records unresolved microphone capture symptoms and that amplifier
first-edge timing has not been physically captured. Included WAVs/logs preserve
measurements; they do not establish clean speech quality or a completed system.
Host tests use peripheral substitutes and cannot verify electrical timing or sound.

First reproduce the standalone build and complete the audio bench checks. Then
integrate the audio/chunker modules with the destination's state machine and
resource ownership. A future radio phase needs a transport adapter, explicit
receive-message ownership and completion/timeout policy, measured airtime, and
board-specific validation. RadioLib/SX1262, compression, and driver migration are
deferred work, not dependencies or implemented capabilities of this snapshot.
