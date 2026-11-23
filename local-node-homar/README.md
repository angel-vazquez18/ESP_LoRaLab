# LoRa walkie-talkie

An ESP32 project that records a short voice message, splits it into small packets,
reassembles the packets, and plays the message through a speaker. This is the
audio foundation for a LoRa walkie-talkie.

**Current stage: bringing up two Heltec WiFi LoRa 32 V4.3 / ESP32-S3R2 nodes.**
Packet delivery is still simulated in memory; the firmware does not transmit
over LoRa yet. PTT is deferred until the radio transport works. The Heltec audio
bench holds the SX1262 in reset and disables its RF front end.

### Heltec bench targets

| Node / OLED label | Assigned port | Hardware base MAC | PlatformIO environment |
| --- | --- | --- | --- |
| Heltec-A / COM6 | COM6 | 8C:FD:49:B5:B7:8C | `heltec_v4_com6` |
| Heltec-B / COM7 | COM7 | 44:1B:F6:6F:99:E4 | `heltec_v4_com7` |

Both chips were identified through their ROM bootloader as ESP32-S3 revision
0.2 with 2 MB embedded quad PSRAM and 16 MB flash. COM names are Windows
assignments and can change; match the USB serial number to the MAC above before
uploading. The firmware's OLED label records the assigned bench port.

The default build now selects both Heltec targets. Each uses Rev B wiring:
microphone BCLK/WS/data = GPIO4/6/38; amplifier BCLK/LRC/DIN/SD = GPIO40/41/47/48.
Amplifier SD needs its 1 kOhm pulldown; VIN uses USB 5V. Leave GPS disconnected
and GPIO39/PTT unwired. The built-in OLED uses SDA17/SCL18/reset21 with Vext36;
no external display wiring is needed. These assignments are for standard R2,
not V4-R8.

Current wiring reference: [Rev B schematic](output/schematics/Heltec_V4_R2_Wiring_RevB.svg)
([PNG](output/schematics/Heltec_V4_R2_Wiring_RevB.png)). The original Heltec PDF
and earlier drawings are historical drafts. Heltec speaker output is still
unresolved; the latest checkpoint and remaining connection checks are recorded
in [BENCH_VALIDATION.md](BENCH_VALIDATION.md).

On ESP32-S3, speaker output uses 32-bit stereo I2S slots at 512 kHz BCLK,
with the same 16-bit PCM promoted into the upper 16 bits of each slot. Silent
clocks run before amplifier enable. This avoids the MAX98357A's special 256 kHz
startup mode, which conflicts with the S3 serializer's stopped WS-high state.
The original ESP32 keeps its existing 16-bit stereo / 256 kHz sequence.

```powershell
pio run -e heltec_v4_com6 -e heltec_v4_com7
pio run -e heltec_v4_com6 -t upload
pio run -e heltec_v4_com7 -t upload
python tools/verify_heltec_bench.py --ports COM6 COM7
```

The verification tool keeps both serial connections open, checks identity and
audio readiness, then plays a one-second 1 kHz tone on A, on B, and on both.
It saves per-port logs and a JSON summary under `captures/`. Successful serial
completion proves the digital transfer; listening is still needed to confirm
sound from each speaker. Close other serial monitors before running it.

For silent-speaker diagnosis, the diagnostic firmware adds `v` to report GPIO48
enable readback and measured GPIO40/41 clock-edge counts. After uploading that
build, use `python tools/verify_heltec_bench.py --identify-only --probe-pins`.
Expected clocks are approximately 512 kHz BCLK and 8 kHz LRC, with SD high.
These are measurements at the ESP32 pins; they do not prove the wires reach the
amplifier or that its VIN supply is present. `--tone-repetitions 3` repeats each
node's one-second tone three times before the paired test.

The Heltec `s` tone also reports DIN rising-edge activity on GPIO47. An intact
one-second test pattern has 32,000 rising edges (two transitions per 32-bit
word, two slots per frame, 8,000 frames). This count checks MCU output activity;
it does not decode I2S timing or verify the waveform at the amplifier terminal.
Playback pads its last DMA block with silence to keep subsequent commands on a
descriptor boundary. This avoids losing initial samples after an idle interval;
the requested audio samples and tone duration are unchanged.

For scope capture, firmware revision `audio-bench-7-scope-tone` adds `b` for a
continuous 15-second 1 kHz tone. Use
`python tools/verify_heltec_bench.py --ports COM7 --tone-seconds 15`, or send `b`
through a 115200-baud serial monitor. This revision is uploaded to COM7; COM6
still has the preceding diagnostic revision. The usual `s` remains one second.

Use `pio run -e esp32dev` for the original ESP-WROOM-32 setup described below;
its GPIO assignments remain unchanged. Never upload that binary to a Heltec.

The original hardware setup uses an **ESP-WROOM-32 development board**, an **INMP441
microphone**, and a **MAX98357A amplifier**. The firmware records three-second
clips. On 2026-11-16, the user confirmed clear recorded speech, working speaker
playback, packetized playback, and playback with simulated packet loss. Saved
captures passed format and checksum checks with no clipped samples. One capture
still contains a large low-frequency disturbance; amplifier startup timing also
remains unmeasured. See the latest checkpoint in [BENCH_VALIDATION.md](BENCH_VALIDATION.md).
Successful compilation alone does not establish that the audio hardware works.

Start with sections 1–3 for your first build. Continue with hardware when ready.

- [1. Install the tools](#1-install-the-tools)
- [2. Fork or clone the repository](#2-fork-or-clone-the-repository)
- [3. Build the firmware](#3-build-the-firmware)
- [4. Connect and check the hardware](#4-connect-and-check-the-hardware)
- [5. Upload and try the commands](#5-upload-and-try-the-commands)
- [6. Save recordings on your computer](#6-save-recordings-on-your-computer)
- [7. Run the tests](#7-run-the-tests)
- [8. Find your way around the code](#8-find-your-way-around-the-code)
- [9. Make and contribute a change](#9-make-and-contribute-a-change)
- [Troubleshooting](#troubleshooting)
- [Additional documentation](#additional-documentation)

## 1. Install the tools

You will need an internet connection for the initial downloads and these tools:

| Tool | What it is for |
| --- | --- |
| [Git](https://git-scm.com/install/) | Downloads the repository and records changes to files. |
| [Visual Studio Code](https://code.visualstudio.com/) | The editor used by this guide. |
| [PlatformIO IDE](https://marketplace.visualstudio.com/items?itemName=platformio.platformio-ide) | A VS Code extension that installs the ESP32 build tools and builds/uploads firmware. |
| A GitHub account with repository access | Lets you clone this private repository and contribute changes. |

In VS Code, open **Extensions** with **Ctrl+Shift+X**, search for **PlatformIO
IDE**, and install the extension published by PlatformIO. Allow its setup to
finish, then restart VS Code if prompted. PlatformIO Core, the `pio` command-line
tool, is included with the extension. See the
[official installation guide](https://docs.platformio.org/en/latest/integration/ide/vscode.html#installation)
if setup fails.

The detailed examples below use **Windows and PowerShell**, the environment used
for this project. The Git and `pio` commands also work on macOS/Linux after those
tools are installed. Python alternatives are provided for recording; the included
C++ test launcher is a Windows PowerShell script.

## 2. Fork or clone the repository

A **fork** is your own GitHub copy of a repository. A **clone** is a local copy on
your computer. Use a fork when contributing through your own account, or clone
the original if you are working directly as an authorized collaborator.

This repository is currently private. You must be signed into an account with
access. Forking also depends on the repository's permissions; if **Fork** is
unavailable, ask the owner about access or use an authorized collaborator branch.
[GitHub explains private forks here](https://docs.github.com/en/pull-requests/reference/forks).

1. Open [homarrodriguez/lora-walkie-talkie](https://github.com/homarrodriguez/lora-walkie-talkie).
2. To make your own copy, click **Fork**, select your account, and create the fork.
3. On the repository you will work from, click **Code → HTTPS** and copy its URL.
4. In VS Code, press **Ctrl+Shift+P**, run **Git: Clone**, paste that URL, and choose
   a local folder. Complete GitHub sign-in if prompted, then open the cloned folder.

If you prefer a terminal, the commands for a fork are below. Replace
`YOUR-GITHUB-USERNAME` with your account name before running them:

```sh
git clone https://github.com/YOUR-GITHUB-USERNAME/lora-walkie-talkie.git
cd lora-walkie-talkie
```

To clone the original repository, use `homarrodriguez` in place of the placeholder.
If you already have a local copy, open that folder instead of cloning again.

**Open the folder containing `platformio.ini` in VS Code.** This is the project
root: run the commands in this guide from that folder. A folder named
`esp32-audio-chunker-test` from an earlier local setup works too; the name of the
local folder does not affect the build.

## 3. Build the firmware

**Firmware** is the program that will run on the ESP32. Building compiles the
source files into firmware; uploading later writes it to the board. Building
does not require a board or change a connected board.

1. Open **Ctrl+Shift+P → PlatformIO: New Terminal**.
2. Confirm the terminal is in the project root.
3. Run:

```sh
pio run -e esp32dev
```

The first build downloads the platform, compiler, and framework and can take a
few minutes. A successful build ends with **`[SUCCESS]`**. Generated files go in
`.pio/`, which Git ignores. PlatformIO also generates your local VS Code settings.

An **environment** is a named build configuration in `platformio.ini`. This
project provides four:

| Environment | Enabled hardware | When to use it |
| --- | --- | --- |
| `esp32dev` | Microphone and amplifier | Full recording and playback tests on the original ESP-WROOM-32. |
| `mic_only` | Microphone only | Diagnose capture with amplifier SD held low and speaker I2S disabled. |
| `speaker_only` | Amplifier only | Check the speaker without initializing the microphone. |
| `serial_only` | Neither audio device | Check the USB serial connection and packet handling. |

To build all four:

```sh
pio run -e esp32dev -e mic_only -e speaker_only -e serial_only
```

The project pins `espressif32@8.0.0`; these original-board environments
target the `esp32dev` board with the Arduino framework. The installed baseline
uses Arduino-ESP32 3.3.12 and ESP-IDF 5.5.5. Keep the supplied `platformio.ini`
for your first build so you start from the same configuration.

If PowerShell cannot find `pio`, use PlatformIO's terminal or its full Windows
path. For example:

```powershell
& "$env:USERPROFILE\.platformio\penv\Scripts\pio.exe" run -e esp32dev
```

After a successful build, you can go straight to [the tests](#7-run-the-tests)
or [the code guide](#8-find-your-way-around-the-code) if you have no hardware yet.

## 4. Connect and check the hardware

For the full audio setup, you need an ESP-WROOM-32 development board, a USB
**data** cable, an INMP441 microphone, a MAX98357A amplifier, a suitable speaker,
jumpers, and a 1 kOhm resistor. The development bench uses an 8-ohm, 1-watt speaker.
No LoRa radio module is required for the current firmware.

**Disconnect power before wiring.** Use GPIO numbers printed on the board, not
header positions. This pin map is for the original ESP-WROOM-32 setup; other
ESP32 variants or boards need their own schematic and pin checks.
GPIO means a programmable input/output pin. Connect all module GND pins to the
ESP32's ground so the devices share the same electrical reference.

| Device | Pin | Connect to |
| --- | --- | --- |
| INMP441 microphone | VDD | ESP32 3V3 |
| INMP441 microphone | GND | Common GND |
| INMP441 microphone | SCK / BCLK | GPIO26 |
| INMP441 microphone | WS | GPIO25 |
| INMP441 microphone | SD (audio data) | GPIO33 |
| INMP441 microphone | L/R | GND, selecting the left channel |
| MAX98357A amplifier | VIN | Verified regulated 5 V supply, as described in the bench guide |
| MAX98357A amplifier | GND | Common GND |
| MAX98357A amplifier | BCLK | GPIO14 |
| MAX98357A amplifier | LRC / WS | GPIO16 |
| MAX98357A amplifier | DIN | GPIO17 |
| MAX98357A amplifier | SD / MODE (enable) | GPIO27, with a 1 kOhm resistor from SD to GND |
| MAX98357A amplifier | GAIN | GND for the documented bench setup |
| Speaker | Two leads | Amplifier SPK+ and SPK− |
| Optional push-to-talk button | Switch contacts | GPIO4 and GND; leave disabled initially |

The microphone's **SD** is its audio output; the amplifier's **SD** enables or
disables the amplifier. They have different jobs and use different GPIO pins.
Keep amplifier SD off the 3V3 rail: this firmware drives GPIO27 low during
startup. Power the microphone from 3.3 V. Neither speaker lead connects to GND.

Read [BENCH_VALIDATION.md](BENCH_VALIDATION.md) before powering the audio setup.
It includes continuity, power, and oscilloscope checks, including the required
SD pulldown check while reset is held. Some observations in that file describe
earlier firmware; the current source banner is `audio-bench-7-scope-tone`.
See the Heltec checkpoint above for the revisions last uploaded to each node.

## 5. Upload and try the commands

Work through the three environments in order so a wiring problem is easier to
locate. When changing wiring, unplug power first. A disabled driver does not
electrically disconnect a module.

### Start with the board alone

Connect the ESP32 to USB with both audio modules disconnected. Close any serial
monitor or recording console already using the board. Find its serial port:

```sh
pio device list
```

On Windows, the result is usually a name such as `COM4`; on macOS/Linux it may
look like `/dev/cu.usbserial-...` or `/dev/ttyUSB0`. **Replace `COM4` in every
example with your board's actual port.** If several devices appear, compare the
list before and after plugging in the ESP32.

Upload the serial-only build, then open the serial monitor:

```sh
pio run -e serial_only -t upload --upload-port COM4
pio device monitor -p COM4 -b 115200
```

The monitor displays text sent over USB. `115200` is the baud rate, or connection
speed, and must match the firmware. Press the board's reset button if you missed
the startup banner. Send `i` to inspect the system, then `t` to test packet
reassembly. Expect **`[TEST] PASS: 200 packets reassembled correctly`**.
Close the monitor with **Ctrl+C** before another program uses the port.

### Add the speaker, then the microphone

With power removed, connect and check the amplifier and speaker. Upload the
speaker-only build, reopen the monitor, and send `s`:

```sh
pio run -e speaker_only -t upload --upload-port COM4
pio device monitor -p COM4 -b 115200
```

Listen for a one-second tone. The digital completion message means the software
sent the audio; hearing the tone is a separate check. Follow the bench guide if
it is silent.

After the speaker checks pass, unplug power, add the microphone, and upload the
full build:

```sh
pio run -e esp32dev -t upload --upload-port COM4
pio device monitor -p COM4 -b 115200
```

Send `m`, wait for **Speak now**, and speak for three seconds. Next try `r` for
direct playback and `p` for playback after simulated packet delivery. Send one
command at a time and wait for the operation to finish.

### Firmware command reference

These are single-letter commands entered in the ordinary serial monitor.

| Command | What happens |
| --- | --- |
| `i` | Prints firmware versions, uptime, available memory, pins, and audio readiness. |
| `t` | Tests reassembly of 200 packets arriving in reverse order; replaces the saved recording buffer. |
| `s` | Plays a one-second, 1 kHz speaker test tone. |
| `m` | Records a three-second clip and prints microphone statistics. |
| `r` | Records a clip and plays it directly through the speaker. |
| `p` | Records, packetizes, simulates delivery, verifies the result, and plays it. |
| `l` | Toggles loss simulation for `p`: zero lost chunks or 11 lost chunks, replaced by silence. |
| `x` | Prints the packet format. |
| `h` | Toggles the once-per-second heartbeat/status message. |
| `d` | Sends binary audio; use the recording tools below rather than a text monitor. |

Both `esp32dev` and `mic_only` support microphone recording; use `m` and `d`
with `mic_only` because speaker playback is disabled. The optional
push-to-talk button is disabled by `Config::ENABLE_PTT = false`. Once wired and
enabled, one press triggers the same sequence as `p`, recording a fixed
three-second clip even if the button stays held.

## 6. Save recordings on your computer

The **recording console** is a Python program on your computer. It asks the ESP32
to record, retrieves the audio over USB, and saves files you can listen to or
inspect. The firmware keeps its recording in RAM (temporary memory); it does not write a WAV file
on the ESP32. Resetting the board loses that recording.

Upload `esp32dev` and close the ordinary serial monitor first. From PowerShell
in the project root, run:

```powershell
& "$env:USERPROFILE\.platformio\penv\Scripts\python.exe" -u .\tools\record_monitor.py --port COM4
```

This uses PlatformIO's Python environment, which includes the `pyserial` library
for USB serial communication. The Windows shortcut is
`.\tools\record-monitor.ps1 -Port COM4` if PowerShell permits scripts.
On macOS/Linux, use PlatformIO's Python at `~/.platformio/penv/bin/python` with
`tools/record_monitor.py` and your actual serial port.

At the `record>` prompt, enter a command and press Enter:

| Console command | Result |
| --- | --- |
| `m quiet` | Records and saves a clip labeled `quiet`, without playing it. |
| `m speech` | Records and saves a clip labeled `speech`. |
| `r playback_check` | Records, plays that clip on the ESP32 speaker, and saves the same clip. |
| `d saved-earlier` | Saves the last valid recording without recording again. |
| `q` | Exits and releases the serial port. |

Labels are optional. Wait for **Speak now**, then wait for **SAVED** before
entering the next command. Recording takes three seconds; exporting adds about
five seconds. These labeled commands belong in the Python console, not the
ordinary serial monitor.

Each successful capture creates a new folder under `captures/`:

```text
captures/<timestamp>-speech/
    recording.wav         Audio at its original volume: 8 kHz, 16-bit mono
    recording.json        Measurements, label, timestamps, and checksum
    recording.svg         Waveform you can open in a browser
    recording.serial.txt  Text diagnostics from the ESP32
```

The tool checks the expected byte count and a CRC-32 checksum, a value used to
detect transfer corruption. It never overwrites an existing capture. Failed
attempts retain an `error.json` file and a log; they do not produce a valid WAV.
Listen to the WAV at a low initial volume and compare it with speaker playback.

For a single capture that saves and exits automatically, append `--once speech`
to the Python command above. The separate `tools/capture_audio.py` utility also
supports one-shot export; run it with `--help` to see its options.

Saved recordings are included in this private repository. Review new recordings
before committing them, especially if they contain personal conversations.

## 7. Run the tests

**Host tests** run on your computer without an ESP32. They check software behavior
using substitute hardware calls. They cannot confirm wiring, sound quality, or
physical signal timing.

### Python tests

From the project root in PowerShell:

```powershell
& "$env:USERPROFILE\.platformio\penv\Scripts\python.exe" .\test\host\capture_audio_test.py
& "$env:USERPROFILE\.platformio\penv\Scripts\python.exe" .\test\host\record_monitor_test.py
& "$env:USERPROFILE\.platformio\penv\Scripts\python.exe" .\test\host\heltec_bench_test.py
```

Each should finish with **`OK`**. They cover audio export parsing, checksum
failures, incomplete transfers, recording-console behavior, and saved files.
On other operating systems, run the same files with Python 3.

### C++ tests on Windows

These need a C++ compiler that builds programs for your computer. PlatformIO's
ESP32 compiler builds programs for the board, so install a host compiler too.

Install [MSYS2](https://www.msys2.org/), follow its initial setup, then open the
**MSYS2 UCRT64** terminal from the Start menu and run:

```sh
pacman -S mingw-w64-ucrt-x86_64-gcc
```

This is the [official MinGW-w64 setup](https://www.mingw-w64.org/getting-started/msys2/).
Return to PowerShell in the project root and run:

```powershell
.\test\host\run.ps1
```

The runner expects `C:\msys64\ucrt64\bin\g++.exe`. If your compiler is installed
elsewhere, pass its path:

```powershell
.\test\host\run.ps1 -Compiler 'C:\your-compiler-folder\bin\g++.exe'
```

Expect `PASS` messages and no compilation or test failures. The runner checks
packet ordering, duplicates, invalid packets, missing-chunk silence, audio sample
conversion, partial/failed I/O, and amplifier startup/error handling. It tests
audio behavior with all four environment settings. Temporary executables go in
the Git-ignored `.host-test/` directory.

## 8. Find your way around the code

| File or folder | Start here when you want to… |
| --- | --- |
| `platformio.ini` | Change the board, build environments, or build settings. |
| `src/main.cpp` | Follow startup, serial commands, and the record/packetize/play sequence. |
| `lib/audio/audio_manager.cpp` and `.h` | Work on microphone capture, speaker playback, and amplifier initialization. |
| `lib/chunking/chunker.cpp` and `.h` | Work on packet creation and receive assembly. |
| `include/config.h` | Inspect audio format, gain, buffer sizes, protocol constants, and PTT enablement. |
| `include/pins.h` | Inspect or adapt GPIO assignments for verified hardware. |
| `include/protocol.h` | Inspect the packet header and validation rules. |
| `include/audio_diagnostics.h` | Find the CRC-32 helper used by audio export. |
| `tools/` | Work on the PC recording tools or the IDE include-path workaround. |
| `test/host/` | Run or extend software tests and hardware substitutes. |
| `captures/` | Inspect saved bench recordings and diagnostic logs. |
| `exports/` | Find the archived project ZIP and its checksum; use the checked-out source for current development. |

### How a voice message moves through the program

The microphone produces digital audio over **I2S**, the interface connecting the
audio modules to the ESP32. The firmware stores it as **PCM**, a sequence of
signed numbers representing the sound waveform.

```text
Microphone -> PCM recording -> 200 packets -> simulated delivery
           -> indexed reassembly -> speaker playback
```

At 8,000 samples per second, a three-second recording contains 24,000 samples.
Each 16-bit sample occupies two bytes, giving a 48,000-byte recording. A packet
contains a seven-byte header and 240 bytes of audio, for 247 bytes total. The
receiver places each payload at its chunk index, so packets can arrive out of
order. Missing chunks remain zeros, which play as silence.

### Constraints to preserve when changing the code

- **Buffer lifetime:** the transmit buffer uses 48,000 bytes; each `VoiceChunker`
  owns another 48,000-byte receive buffer. Keep them in long-lived storage, not
  local variables on a small ESP32 task stack. `beginTransmit()` borrows its
  buffer; keep that audio unchanged until packet creation finishes.
- **Packet compatibility:** version 1 expects exactly 200 full chunks. Changes
  to sample rate, recording duration, or payload size affect buffer sizing and
  protocol rules together. Header checks and compile-time assertions enforce
  the current format.
- **Receive ownership:** a differing message ID resets assembly. That is suitable
  for the local simulation but must be addressed before accepting packets from
  multiple or delayed senders. The packet format itself has no CRC field; the
  serial-export CRC checks a separate transfer.
- **Audio ownership:** the current operations block until finished and share
  buffers. Avoid calling them concurrently or from interrupt handlers. Capture
  uses legacy I2S port 0; playback uses port 1.
- **Amplifier timing:** preserve the SD startup sequence and continuous speaker
  clocks. `stopSpeaker()` clears queued audio while keeping the clocks running.
  Changing this behavior requires the electrical checks in the bench guide.

## 9. Make and contribute a change

Create a branch before editing. A branch keeps your work separate from `main`:

```sh
git switch -c improve-recording-docs
```

Choose a name that describes your work. If you use a fork, add the original
repository as `upstream` once so you can bring in later changes:

```sh
git remote add upstream https://github.com/homarrodriguez/lora-walkie-talkie.git
```

Use `git remote -v` to check existing remotes before adding one. `origin` normally
points to the repository you cloned; for a fork, it should point to your fork.

Make a small, focused change. For firmware changes, build the affected
environments and run the relevant tests above. For hardware changes, also record
the wiring and bench checks you performed. Review your changes before saving
them in Git:

```sh
git status
git diff
```

For example, after editing only the README:

```sh
git add README.md
git commit -m "Clarify recording setup"
git push -u origin improve-recording-docs
```

`git add` selects files, `git commit` saves a local revision, and `git push`
uploads it. Use the actual filenames and branch name for your change. If Git
asks for an author identity, set it for this repository, replacing the examples:

```sh
git config user.name "Your Name"
git config user.email "YOUR-GIT-COMMIT-EMAIL"
```

You can use the no-reply address shown in your GitHub email settings. If the
commit failed because your identity was missing, run it again after setting it. After
pushing, open GitHub and create a **pull request**: a request to review and merge
your branch into the original repository's `main`. Describe the change, the
commands you tested, and any hardware results.

Keep `.pio/`, `.host-test/`, Python caches, and generated VS Code settings out of
commits. `.gitignore` already handles those. Capture files and archived ZIPs are
tracked, so select them deliberately when they are part of your change.

## Troubleshooting

| Problem | First thing to check |
| --- | --- |
| GitHub says “Repository not found” | Sign into an account with access to this private repo and verify the clone URL. |
| `git` or `pio` is not recognized | Restart VS Code after installing Git; use **PlatformIO: New Terminal** for `pio` or the full path shown above. |
| No serial port appears | Try a USB data cable and another USB port. Check the board's USB-to-serial driver requirements. |
| Upload or recording says the port is busy | Close every other serial monitor or recording console. Only one program can use the port at a time. |
| Firmware reports that an audio device is unavailable | Check which environment was uploaded, then inspect `i` and the startup error messages. `serial_only` intentionally disables both devices. |
| Tone transfer completes but there is no sound | Follow the amplifier power, SD, wiring, and speaker checks in `BENCH_VALIDATION.md`. |
| Microphone is silent, noisy, or clipped | Check its 3.3 V supply, ground, L/R selection, and data wiring. Compare an exported WAV with speaker playback before changing gain. |
| Python reports `No module named serial` | Use PlatformIO's Python executable from section 6. A separate Python environment needs the `pyserial` package. |
| A PowerShell `.ps1` script is blocked | Use the direct Python recording command. For the trusted C++ test script, a process-only invocation is `powershell -NoProfile -ExecutionPolicy Bypass -File .\test\host\run.ps1`. |
| C++ tests cannot find `g++.exe` | Install the MSYS2 UCRT64 compiler, or pass its actual location with `-Compiler`. |
| VS Code reports missing include paths | Keep `tools/filter_ide_includes.py` and its `extra_scripts` entry in `platformio.ini`. Run **PlatformIO: Rebuild IntelliSense Index**, then reload the window if old messages remain. |

The IDE hook filters two known missing framework directories whenever PlatformIO
generates editor settings. It does not change normal compilation. Edit
`platformio.ini` and the project scripts for lasting configuration changes;
PlatformIO regenerates `.vscode/c_cpp_properties.json`.

When reporting a problem, include the command you ran, the full error text,
the selected environment, your board model, and relevant startup output. For
audio problems, include the capture label and measurements if available.

### Isolate a noisy microphone recording

The `m` command skips playback, but in the full build the amplifier remains
enabled and speaker clocks continue running. To test capture with amplifier SD
held low and the speaker I2S driver disabled, close the serial monitor and
recording tool, then upload this diagnostic build (replace `COM4` as needed):

```sh
pio run -e mic_only -t upload --upload-port COM4
```

Keep the existing wiring, including amplifier SD on GPIO27. Reopen the Python
recording tool from section 6. Run `m quiet_mic_only` while quiet, wait for
`SAVED`, then `m voice_mic_only` while speaking normally. Compare these WAV files
with the full-build recordings. A clean result implicates interaction with the
enabled speaker path; it does not by itself identify the electrical cause.
Persistent corruption still requires checking microphone power, connections,
I2S capture, and the microphone module. This build leaves the amplifier physically
connected to power, so it is not a complete electrical disconnection test.

To restore recording and speaker playback, close the recording tool and upload
`esp32dev` again with `pio run -e esp32dev -t upload --upload-port COM4`.

## Additional documentation

- [BENCH_VALIDATION.md](BENCH_VALIDATION.md): detailed electrical checks and audio
  acceptance steps, including historical bench observations.
- [README_HANDOFF.md](README_HANDOFF.md): snapshot and component-integration
  details for moving this code into another project.
- [INTEGRATION_PROMPT.md](INTEGRATION_PROMPT.md): a reusable instruction prompt
  for integrating the components into an existing repository.
