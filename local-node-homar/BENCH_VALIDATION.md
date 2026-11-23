# ESP32 audio validation

## Saved checkpoint: 2026-11-22

- Saved the Heltec V4.3 R2 firmware port, dual-port tooling, host tests,
  recordings, wiring references, build/upload logs, and scope analysis.
- Hardware status remains unresolved: the original ESP-WROOM-32 audio bench
  passed listening tests, but neither Heltec speaker has yet been confirmed
  audible. COM7 last received `audio-bench-7-scope-tone`; COM6 last received
  revision 6. No new upload or hardware test was performed for this checkpoint.
- The latest requested next step is a simple physical connection check before
  further scope troubleshooting. The current firmware and Rev B schematic
  agree on amplifier GPIO40/41/47/48 and microphone GPIO4/6/38. Existing photos
  hide some wire endpoints and amplifier header solder joints; no pin swap
  has been confirmed. PTT is disabled and real LoRa transport is not implemented.
- Use `output/schematics/Heltec_V4_R2_Wiring_RevB.svg` or its PNG for the
  current pin assignment. The original Heltec PDF and earlier schematic
  drafts are retained as historical work and do not supersede Rev B.
- Checkpoint validation: CRC/chunker host checks, all five audio variants,
  and all 27 Python host tests passed. The two original `COM6.log` and
  `COM7.log` files in the first Heltec capture were renamed to
  `serial-COM6.log` and `serial-COM7.log` for Windows portability, with their
  contents verified unchanged by SHA-256.

## Heltec V4.3 R2 bring-up: 2026-11-16

| Node | Assigned Windows port | Base MAC | Verified memory |
| --- | --- | --- | --- |
| Heltec-A | COM6 | 8C:FD:49:B5:B7:8C | 16 MB flash, 2 MB PSRAM |
| Heltec-B | COM7 | 44:1B:F6:6F:99:E4 | 16 MB flash, 2 MB PSRAM |

- Identified both ESP32-S3 revision 0.2 chips with the ROM bootloader, then
  confirmed MAC, flash and PSRAM sizes from the running firmware. Both OLEDs
  acknowledged at 0x3C; firmware writes the node/COM label and audio readiness.
- Added separate `heltec_v4_com6` and `heltec_v4_com7` build/upload targets using
  the Rev B pin map. PTT is disabled and GPIO39 remains unconfigured. Radio
  transport is not implemented: the SX1262 is held in reset and FEM disabled.
- Initial 16-bit stereo playback startup failed on both S3 boards because WS
  idles high after routing I2S, while the MAX98357A's 256 kHz mode requires low
  starting clocks. A diagnostic on COM6 confirmed GPIO-held BCLK/WS = 0/0,
  I2S-stopped = 0/1; explicitly latching registers and adding pull-downs did not
  change that peripheral-driven WS level.
- Corrected S3 playback to 32-bit stereo I2S slots / nominal 512 kHz BCLK, with
  silent clocks started before amplifier enable. Signed 16-bit PCM is promoted
  into the upper 16 bits of each wire sample; recordings and packet format stay
  unchanged. Original ESP32 playback retains 256 kHz enable-before-clock startup.
  See the [MAX98357A startup specification, page 18](https://www.analog.com/media/en/technical-documentation/data-sheets/max98357a-max98357b.pdf).
- Final `esp32dev`, `heltec_v4_com6`, and `heltec_v4_com7` builds succeeded with
  no errors. Both Heltec uploads succeeded with flash hash verification. The
  initial clean OLED dependency build emitted an overloaded-virtual warning;
  the final incremental build emitted no compiler warnings.
- Host checks passed for CRC/diagnostics, chunking, four original audio modes,
  and the Heltec/S3 mode. S3 checks cover signed/full-scale wire conversion,
  1 kHz sample values, silent tails, partial I/O, clocks-before-enable startup,
  and shutdown on failures. Four Python dual-port regression tests also passed.
- In the [successful dual-port run](captures/20261116-205545-624582-heltec-speaker-bench/summary.json),
  COM6 and COM7 stayed open together at 115200 baud. Both returned the expected
  MAC, Rev B pins, MIC ready=1 and SPK ready=1. Individual one-second 1 kHz
  tones on COM6 and COM7, then tones requested on both together, each produced
  transfer-complete and IDLE responses. The handles were closed afterward.
- The user subsequently reported not hearing the tones; audible speaker output
  is therefore unresolved despite successful digital transfers. External
  waveform amplitude and first-edge timing have not been measured with a scope.
  Microphone readiness does not yet establish recording quality on these nodes.
- Follow-up identity/readiness checks still passed on both nodes. A requested
  three-tone repeat could not run because COM6 was occupied by another program.
  Speaker-pin diagnostic firmware (`v`) was subsequently built successfully for
  both Heltec targets and `esp32dev`. COM6 received it first; COM7 disconnected
  before its initial upload, then was reconnected and successfully uploaded.
- The user measured **COM7 amplifier VIN = 4.9 V and SD/MODE = 3.19 V** at the
  amplifier terminals. These are user-reported meter readings, not firmware
  measurements. They are consistent with a powered, enabled amplifier.
- The [dual-board pin measurements](captures/20261116-231454-328071-heltec-speaker-bench/summary.json)
  completed with both serial connections open. COM6: BCLK 511659.7 Hz,
  LRC 8004.7 Hz, SD GPIO48 HIGH. COM7: BCLK 511727.9 Hz, LRC 7968.3 Hz,
  SD GPIO48 HIGH. PCNT counted rising edges over approximately 20.5 ms;
  these short-window estimates are consistent with nominal 512 kHz / 8 kHz.
  Both ports closed afterward. GPIO output rates are now measured at the MCU;
  the DIN waveform during playback remains unverified. No playback-format
  change was made for these measurements.
- The user subsequently reported continuity beeps on all four requested COM7
  paths: GPIO40 to BCLK, GPIO41 to LRC/WS, GPIO47 to DIN, and board GND to
  amplifier GND. This establishes reported continuity along those paths; it
  does not establish the absence of shorts or a valid signal at the amplifier.
- DIN activity diagnostic revision `audio-bench-5-speaker-pin-probe` built
  successfully for both Heltec targets and `esp32dev`, then uploaded to both
  Heltecs with flash hash verification. The existing OLED-library warning
  appeared during compilation; there were no build errors. Audio format and
  tone amplitude were unchanged.
- In the [DIN diagnostic run](captures/20261117-022321-778840-heltec-speaker-bench/summary.json),
  both ports stayed open together and all tone transfers completed. Each node
  reported DIN rising-edge counts of **32,000, 31,744, and 32,000** for its first
  individual, second individual, and paired tone respectively. The intact
  8,000-frame pattern predicts 32,000 edges. These measurements establish active
  data output, not correct I2S timing or sound. BCLK/LRC remained approximately 512 kHz / 8 kHz
  and SD read HIGH on both. Logs use UTC; this was still November 16 locally.
- The user reported hearing neither speaker during that run and confirmed an
  oscilloscope is available. Requested COM7 BCLK and LRC frequency/high/low
  voltages at the amplifier terminals.
- The short repeated-tone count exposed a separate DMA boundary issue. The
  [ESP-IDF legacy driver](https://raw.githubusercontent.com/espressif/esp-idf/v5.5.5/components/driver/deprecated/i2s_legacy.c)
  clears DMA memory without resetting its partial-buffer write cursor. An
  8,000-frame tone plus the existing silent tail left that cursor halfway
  through a descriptor. Revision `audio-bench-6-dma-boundary` pads the final
  tone/PCM block with silence to finish the descriptor, preserving all audio
  samples and continuous clocks. Host tests verify exact samples, zero padding,
  descriptor alignment, partial I/O, and repeated/short tones. All five host
  audio configurations and all three firmware builds passed; both Heltec
  uploads passed flash hash verification.
- In the [post-fix run](captures/20261117-022722-755056-heltec-speaker-bench/summary.json),
  **all eight tone measurements were exactly 32,000 DIN rising edges**: three
  individual tones per board plus one paired tone on each. Both connections
  remained open and were closed afterward. This resolves the observed short
  repeat count. It does not establish audible output or explain complete
  speaker silence; external waveform checks remain necessary.
- The user's scope photo showed BCLK at 512.1 kHz. Both channels initially
  displayed that frequency, but the user corrected the LRC result after
  measuring it separately: **approximately 8 kHz and 3.45 V**. The precise
  voltage metric was not specified. This resolves the apparent LRC frequency
  mismatch; the first dual-channel display is not evidence of a confirmed
  BCLK-to-LRC short. A [fresh COM7 MCU probe](captures/20261117-023709-154920-heltec-speaker-bench/summary.json)
  also measured BCLK 511760.7 Hz, LRC 8006.6 Hz, and SD HIGH. Amplifier-terminal
  DIN capture during a tone is the next requested check; no firmware change
  was made in response to the scope photo.
- At the user's request, revision `audio-bench-7-scope-tone` adds command `b`
  for a continuous 15-second 1 kHz tone; `s` remains one second. The host tool
  adds `--tone-seconds 15` with a matching response timeout. All five host audio
  configurations and six Python checker regressions passed. `esp32dev` and
  `heltec_v4_com7` builds passed; COM7 was uploaded with hash verification.
  COM6 remains on revision 6. The [15-second COM7 run](captures/20261117-024625-636529-heltec-speaker-bench/summary.json)
  completed with **480,000 DIN rising edges over 15.032 seconds**, matching
  120,000 stereo frames. The serial handle closed afterward. Scope capture
  and audible-output interpretation remain pending.
- The user subsequently reported amplifier DIN at **32 kHz and 2.52 V** during
  the extended tone. The frequency is consistent with the test pattern's
  32,000 rising transitions per second, but an automatic DIN frequency reading
  does not decode the I2S words or establish clock/data alignment. Whether
  2.52 V is Vmax, Vp-p, RMS, or average is awaiting clarification. The
  MAX98357A specifies digital-input HIGH >= 1.3 V and LOW <= 0.6 V; checking
  these requires waveform levels, not an unspecified voltage reading. The
  amplifier/speaker fault remains unresolved.
- Reviewed eight one-second-spaced frames from the user's 7.3-second
  `MicrosoftTeams-video.mp4`; extracted frames and metadata are under
  `output/validation/scope-video-20261116/`. Yellow/CH1 consistently reports
  511.9-512.1 kHz and approximately 50% duty. The blue/CH2 trace is nearly flat
  at 0, 1, 5, and 7 seconds, with pulse activity at 2, 3, 4, and 6 seconds.
  Its automatic frequency and amplitude values vary and sometimes persist
  while the trace is flat, so they are not accepted as stable clock/level
  measurements. The scope is at 50 us/div with both channels at 2 V/div,
  x10, DC coupling. Probe tips are not visible: the user describes LRC/WS
  being measured while DIN is active, but exact channel-to-terminal assignment
  needs confirmation. The traces resemble BCLK plus DIN; the clip does not
  independently establish the expected continuous 8 kHz WS at the amplifier.
- The user clarified that the video's yellow probe is BCLK and blue is
  amplifier LRC/WS, and supplied five repeated one-second tone logs. DIN counts
  were 32,000 / 31,964 / 32,000 / 32,000 / 32,000; all returned to IDLE. The
  36-edge shortfall in one run remains unexplained. These are GPIO47 data
  measurements, not measurements of LRC/WS. Reinspection of the current source
  confirms that tone playback/probing does not stop clocks or change GPIO41:
  the tone probe samples GPIO47, and completion clears DMA data while clocks
  continue. Therefore pressing the tone command explains data activity but
  should not make LRC/WS disappear. Next check: compare board GPIO41 and the
  amplifier LRC terminal while IDLE with common-ground scope probes; both
  should show the same continuous 8 kHz waveform. No wiring fault or amplifier
  failure is yet confirmed, and no firmware change was made for this report.
- The follow-up simultaneous scope capture labels yellow as board GPIO41 and
  blue as amplifier LRC/WS. Both show **8.00 kHz, 50.33% duty, and Vmax 3.45 V**,
  with corresponding edges aligned at the displayed resolution. Vp-p is
  3.61 V at GPIO41 and 3.72 V at LRC. This verifies delivery of the expected
  word clock at the amplifier in this capture and supersedes the concern that
  LRC is presently absent. It does not explain the earlier video discrepancy
  or prove DIN framing. The next check compares GPIO47 with amplifier DIN
  during command `b`; no firmware or wiring change is indicated by this image.
- Reviewed the 8.03-second second video (`MicrosoftTeams-video (2).mp4`), with
  yellow identified as GPIO47 and blue as amplifier DIN. Frames sampled every
  0.5 seconds are under `output/validation/scope-video-2-20261116/`, alongside
  the supplied `serial-user.txt`. Both traces show matching activity near
  video seconds 1, 4, and 7 and return low together between bursts. Example
  yellow/blue Vmax readings are 2.60/2.59 V at 1 second, 3.57/3.67 V at 4
  seconds, and 3.66/3.68 V at 7 seconds. This supports DIN reaching the
  amplifier without an obvious endpoint mismatch. The scope remains at
  50 us/div, so this is not a bit-level I2S timing/word decode.
- The supplied log contains five one-second tone windows starting at
  23:16:11.421, 23:16:12.921, 23:16:45.985, 23:16:48.542, and 23:16:51.536
  (timestamps as supplied). Counts are 32,000 / 32,000 / 32,000 / 31,964 /
  32,000. Every transfer completed, uptime increased without a visible reset,
  and reported heap remained 239,872 bytes. The 36-edge deficit is 0.1125%
  and remains unexplained; it does not account for total silence. The video
  has no visible wall clock, so exact frame-to-log synchronization is not
  established. Speaker/lead resistance is the next requested check before
  diagnosing the amplifier itself. No firmware or wiring change was made.
- The user confirmed that isolating a speaker lead would require desoldering.
  Leave the soldered speaker connected and defer the isolated resistance test.
  Next check the amplifier outputs with CH1 tip on SPK+, CH2 tip on SPK-, and
  both probe ground clips on amplifier GND (neither ground clip on a speaker
  output). Compare idle with the 15-second `b` tone, using x10/DC, 2 V/div and
  approximately 1 us/div to resolve the class-D switching. Raw switching
  activity alone is not proof of differential 1 kHz audio or a good speaker.
- The user supplied `Image (20).jpg` and `Image (19).jpg`, reporting busy
  output traces with and without a tone. The scope still shows 50 us/div,
  x10/DC and 2 V/div, with automatic readings around 1 MHz and 10.8 Vp-p.
  These readings are not accepted as the actual output frequency or swing:
  probe reference/contact, ringing and the compressed time scale remain
  unresolved. The close-up partly obscures the output contacts and does not
  show where the probe ground clips connect; it proves neither a short nor
  an absent ground connection. Before another output capture, validate each
  probe separately with its ground clip on amplifier GND: tip on the same
  GND should be nearly flat at 0 V; tip on VIN should be approximately 4.9 V
  DC. Match physical probe and scope attenuation, use short ground leads,
  then retry one speaker output at 1 us/div. Keep all probe ground clips off
  SPK+ and SPK-. No desoldering or firmware change is indicated by these
  photos, and amplifier/speaker operation remains unresolved.
- The first diagnostic run also exposed Windows reserved-name handling:
  `COM6.log` and `COM7.log` are not safe filenames. The verifier now writes
  `serial-COM6.log` / `serial-COM7.log`; regression tests check actual file
  creation and preserve both responses when either board fails readiness.

To repeat: close other serial monitors, then run
`python tools/verify_heltec_bench.py --ports COM6 COM7`. Add `--identify-only`
to query both boards without playing tones. COM labels can change in Windows;
the tool checks USB serial/MAC identity rather than trusting the port name.

## Previous ESP-WROOM-32 checkpoint: 2026-11-16

- Added the `mic_only` diagnostic environment and host-test coverage. It records
  with amplifier SD held low and no speaker I2S driver. The default remains
  `esp32dev`, with microphone and speaker enabled.
- Built and uploaded both `mic_only` and `esp32dev` on COM4. The restored full
  build reported both audio devices ready, and the user confirmed clear recorded
  speech and working hardware speaker playback after checking the connections.
  The exact physical correction was not recorded; no audio-driver change is
  attributed to this recovery.
- Validation before committing: C++ host tests passed for all four audio
  configurations, CRC diagnostics, and packet handling; all 21 Python capture
  and recording-console tests passed.
- Independently checked all eight saved November 16 WAV files: each contains
  24,000 mono 16-bit samples at 8 kHz, matches its firmware-export CRC and saved
  measurements, and has no clipped samples. All four direct-playback captures
  have a digital-playback completion log. Retained November 9 captures document
  the earlier near-constant data and spikes.
- The [latest speaker check](captures/20261116-042848-015538-speaker_check/recording.json)
  peaks at 15.8% of full scale and no longer shows the earlier stuck-data pattern.
  The [preceding check](captures/20261116-042836-659374-speaker_check/recording.json)
  contains a large slow baseline disturbance despite valid CRC and no clipping;
  its cause remains undetermined.
- The user subsequently reported successful packetized playback (`p`) and the
  deliberate-loss test (`l`, then `p`). These are listening reports; serial logs
  for those two tests were not saved. The loss test is designed to receive 189
  chunks, replace 11 missing chunks with silence, and verify the expected bytes.
  Return the drop interval to zero with `l` after testing.
- Radio transport is still simulated in RAM on one board. Amplifier first-edge
  timing remains unmeasured. The historical observations below are retained as
  troubleshooting context, not the current functional speaker status.

## Historical bench evidence

Before the startup-sequence change, firmware was uploaded
to COM4, but the speaker remained silent. The user measured VIN 4.995 V, SD 3.322 V
and GAIN 0 V. The FNIRSI 2C53T showed BCLK 256 kHz, LRC 8 kHz, and repeatable DIN
activity during `s`. DIN activity does not prove correctly decoded PCM. The speaker
is an Alrhso 1 W / 8 ohm cavity speaker, soldered across the output pads. Header and
speaker continuity, startup edge timing, and amplifier output remain to be checked.

## Wiring for the current ESP-WROOM-32 only

Use the GPIO number printed on the board, not the physical header position.
Power off USB and any external supply before changing connections.

| Module terminal | Connection | Check |
|---|---|---|
| MAX98357A LRC | GPIO16 | Word-select, not VIN |
| MAX98357A BCLK | GPIO14 | Bit clock |
| MAX98357A DIN | GPIO17 | Audio data from ESP32 |
| MAX98357A GAIN (row 27) | GND, as presently wired | Keep this gain setting during the startup comparison |
| MAX98357A SD (row 28) | **GPIO27**, plus 1 kOhm to GND | Remove the existing direct connection to 3V3 before upload |
| MAX98357A GND | ESP32 GND | Short, reliable common ground |
| MAX98357A VIN | Verified regulated 5 V bench/USB rail | Confirm the development board's 5V/VIN pin actually supplies this voltage |
| Speaker leads | Amplifier SPK+ and SPK− | Neither speaker lead connects to GND |
| INMP441 VDD | ESP32 3V3 | Never 5 V |
| INMP441 GND | ESP32 GND | Shared reference |
| INMP441 SCK/BCLK | GPIO26 | Microphone bit clock |
| INMP441 WS | GPIO25 | Microphone word-select |
| INMP441 SD | GPIO33 | Microphone audio output; different function from amplifier SD |
| INMP441 L/R | GND | Select left channel to match firmware |
| PTT | GPIO4 to normally-open switch to GND | Leave disabled during audio tests |

GPIO14 also has a JTAG function. GPIO16/17 are usable here on the stated WROOM
board; don't transfer this map to WROVER/PSRAM or S3 boards. Avoid changing boot
straps GPIO0/2/5/12/15 during diagnosis. GPIO1/3 are the usual UART0 serial pins;
the GPIO16/17 speaker assignment does not itself conflict with that UART.
See [Espressif's GPIO reference](https://docs.espressif.com/projects/esp-idf/en/v4.4.2/esp32/api-reference/peripherals/gpio.html)
and [WROOM-32 pin definitions](https://documentation.espressif.com/esp32-wroom-32_datasheet_en.html).

The MAX98357A accepts standard I2S; the MAX98357B uses left-justified data.
Confirm the module is A if correctly decoded I2S still produces no sound. SD is
an analog mode input. Typical boundaries are about 0.16 V (shutdown), 0.77 V and
1.4 V (channel selection); use clear margins, not boundary voltages. Identical
left/right data in this build works with any enabled channel selection.
See the [MAX98357A/B datasheet, SD_MODE and serial-interface sections](https://www.analog.com/media/en/technical-documentation/data-sheets/max98357a-max98357b.pdf).

SD is now driven by GPIO27. **Do not leave row 28 connected directly to 3V3:** the
new firmware drives it low during startup. Power off before moving that jumper.
Add a 1 kOhm resistor from SD to GND to keep the amplifier off while ESP32 reset
leaves GPIO27 undriven. With ESP32 EN/reset held low, verify SD below 0.08 V; this
also checks whether an unknown breakout pull-up defeats the resistor. A low
firmware output should be near 0 V; once initialized, SD should be about 3.3 V.
This input also selects the left channel when high; both slots contain identical
audio. The resistor draws about 3.3 mA when enabled. Do not drive amplifier inputs
while its VIN is absent. Keep the present common USB-derived supply for this test.

## MAX98357A 256 kHz startup sanity check

This build implements the software ordering for the special 256 kHz / 8 kHz
startup described in the [MAX98357A/B datasheet, Startup and Figure 6](https://www.analog.com/media/en/technical-documentation/data-sheets/max98357a-max98357b.pdf).
It preserves the existing sample format, duplicated stereo data, tone level and
record/buffer/chunk/reassemble/playback flow.

1. Hold SD low for at least 1 ms and drive BCLK/LRC/DIN low.
2. Install the I2S driver with its output pins disconnected. The legacy driver's
   automatic start therefore does not send clocks to the amplifier.
3. Stop/reset the transmitter, select the left slot first, prepare silent DMA
   buffers, and then route the stopped signals to the pins. Abort with SD low
   if BCLK or LRC reads high at this point.
4. Raise SD, wait 20 microseconds (datasheet minimum 10 microseconds), then start
   the transmitter. Allow 20 ms of startup silence before commands run.
5. Leave clocks running between commands, including playback errors. An init
   failure lowers SD before uninstalling the driver. Repeated `begin()` calls
   return the original result; resetting the board is required to retry.

This is specific to the original ESP32 and the pinned ESP-IDF 5.5.5 legacy driver.
The hardware serializer generates BCLK/LRC together; software delays do not prove
the first-edge relationship. VIN is not sensed. A successful `begin()` or `SPK
ready=1` reports software initialization, not verified MAX98357A operation.

After rewiring, build before uploading. Expect banner
`audio-bench-2-max98357-startup`. On the FNIRSI use matched physical/channel x10
settings, DC coupling, about 1 V/div for logic, and a short ground connection at
amplifier GND (row 29). Both channel ground clips go there, never to speaker pads.
Capture at the amplifier terminals, not just the breadboard jumper sockets:

- **SD versus BCLK:** CH1 on SD, CH2 on BCLK. Hold ESP32 EN/reset low, arm a single
  rising-edge trigger on CH1 around 1.5 V, then release reset. Start near 10 us/div.
  Confirm BCLK stays low until at least 10 us after SD rises. Confirm VIN is already
  stable near 5 V; startup assumes it is above 2.3 V before the delay begins.
- **First BCLK versus first LRC:** CH1 on BCLK, CH2 on LRC. Hold reset low, arm a
  single rising-edge trigger on CH1 around 1.5 V, then release reset. Use about
  10 us/div with pretrigger visible. Both must begin low and transition high;
  the first LRC rising edge must follow the first BCLK rising edge by at least
  half a BCLK period and at most half an LRC period: 1.953125 to 62.5 us.
- Then check full LRC periods of 125 us, BCLK at 256 kHz, and uninterrupted clocks
  before, during and after repeated `s` commands. If startup aborts, save the
  `[AMP]` and `[I2S]` log; do not bypass the idle-level check to force enable.

If those edge checks fail, this implementation has not satisfied the electrical
sequence and needs adjustment. If they pass but the speaker stays silent, continue
with speaker continuity and amplifier-output checks below; do not conclude that
the amp is damaged from DIN activity alone. Neither physical startup timing nor
audible output has been verified for this new build.

## Gate 1: passive checks and serial baseline

1. Unplug all power. Disconnect both audio modules completely, including signal
   wires. Inspect for misplaced breadboard rows and split power rails. Check
   continuity from each ESP32 pin to its intended module terminal with one wire
   at a time; the wire's colour is not evidence of its destination.
2. Disconnect the speaker from the amp and measure across its two leads. Expect
   a finite resistance of a few ohms for a typical 4 Ω or 8 Ω speaker; DC
   resistance is usually below rated impedance. Open circuit, near-zero after
   subtracting test-lead resistance, or intermittent readings require investigation.
3. Check the unpowered amp's VIN-to-GND resistance for a sustained short.
   Charging capacitors can make the reading change; a continuity beep alone
   neither proves nor disproves a fault. Never measure resistance on a live rail.
4. Upload `serial_only`, then run `i` and `t`. Confirm the `audio-bench-2-max98357-startup` banner,
   both audio directions disabled, the test passes and the heartbeat stays
   readable for at least 60 seconds. Record uptime and any boot/banner repetition.
5. If corruption occurs with all peripherals removed, use one serial terminal
   at 115200, 8N1, no flow control, and try a known-good data USB cable/port.
   Compare a raw terminal against PlatformIO's filtered display. Decoder notices
   alone are not evidence of an exception; preserve the actual bytes/reset log.

Optional raw serial monitor using the installed PlatformIO Python:

```powershell
& "$env:USERPROFILE\.platformio\penv\Scripts\python.exe" -m serial.tools.miniterm COM4 115200 --raw
```

Close other monitors first. Opening a serial port may reset the board through
DTR/RTS; distinguish that from unsolicited resets during steady operation.

**Pass:** stable readable serial with increasing uptime, and `t` passes. A
recurring banner or restarted uptime means a reset occurred; continuing output
after corruption alone does not rule one out.

## Gate 2: amplifier power and audible tone

1. With power off, reconnect only amplifier VIN/GND. Leave the microphone and
   speaker disconnected. Power up and measure directly at amplifier terminals:
   VIN-to-GND, SD-to-GND, and ESP32 3V3-to-GND. A powered 5 V setup should read
   near 5 V at VIN and near 3.3 V on the ESP32 rail. The amplifier IC operates
   over 2.5–5.5 V, but that does not prove a particular breakout or power route
   is wired correctly. Watch serial for another 60 seconds.
2. Power off. Wire SD to GPIO27 with the pulldown, and BCLK/LRC/DIN as above.
   Upload/use `speaker_only` only after that rewiring. Inspect
   continuity again. With the speaker still disconnected, run `i` then `s`.
   Confirm MIC disabled, SPK ready and a successful digital transfer.
3. Power off. Connect the speaker only across SPK+/SPK−. SD is enabled by firmware
   as described above. Run `s`, keeping the speaker away from your ear. Repeat it
   several times. Log whether the tone is audible, plus VIN and 3V3 idle/during
   the tone. DMM readings may miss short dips, so a stable reading is not proof
   of good transient response.
4. If adding a connection changes serial behavior, repeat that A/B experiment
   with power off between changes. Keep both supplies and common ground
   connected before attaching any driven signal; never power the amp through
   its I2S inputs. Add BCLK, then LRC, then DIN in separate powered-off steps
   if needed to locate a miswire.
5. If rail sag/noise tracks the amp load, shorten power/ground wiring and check
   existing local bypassing. A 0.1 µF ceramic plus about 100 µF bulk capacitor
   (correct polarity, rated at least 10 V) close to VIN/GND is a useful bench
   trial. If needed, supply the amp from a separate regulated 5 V source with
   common ground; remove its connection to the board's 5 V rail so the supplies
   are not tied together or backfeeding USB.

**Pass:** a repeatable audible tone, stable serial/uptime, and no power collapse.
Digital transfer success alone is insufficient. A wrong SD mode is one candidate;
the current evidence does not establish it as the cause.

## Oscilloscope / logic-analyzer checks

Probe at the ESP32 and again at the amplifier terminals during `s`.

| Signal | Nominal diagnostic-build expectation |
|---|---|
| GPIO14 → BCLK | 256 kHz, 32 bit clocks per complete stereo frame |
| GPIO16 → LRC | 8 kHz frame rate, 16 clocks per half-frame |
| GPIO17 → DIN | Standard I2S, MSB first, one-bit delay after LRC transition; 16-bit signed samples |
| Decoded L/R | Both repeat four samples +2000, four samples −2000: 1 kHz; then zeros |
| GPIO26 mic BCLK | 512 kHz, 64 clocks per frame when MIC enabled |
| GPIO25 mic WS | 8 kHz when MIC enabled |
| GPIO33 mic SD | Left-slot speech data, 24 significant bits carried in 32-bit words |

Use a shared GND reference, 3.3 V-compatible analyzer inputs, and preferably
10 MS/s or faster sampling. The firmware prints configured frequencies, not
measured ones. A basic multimeter cannot validate these clocks or decode DIN.

Absent clock at the ESP32 points toward wrong build/pin/controller setup. A
clock present there but absent at the module points toward continuity, breadboard
rows or loading. Correct clocks but incorrect decoded words point toward format
or data routing. Correct I2S at the amp plus valid VIN/SD and no output shifts
attention to the amp, speaker, solder joints or part identity.

The class-D speaker output is bridged and switches rapidly. **Never attach an
earth-grounded scope ground clip to SPK− or SPK+.** Use a suitably rated
differential probe, or two probe tips on the two outputs with both ground clips
at circuit GND and display CH1−CH2. Don't connect a grounded line input or logic
analyzer across the speaker terminals. Start with I2S and supply measurements.

For supply integrity, use a short probe ground at amplifier VIN and ESP32 3V3,
triggering on negative excursions during `s`. Capture enough detail to distinguish
rail dips from probe-loop pickup. If serial corruption persists, observe UART0
TX at GPIO1: 115200 baud has a nominal 8.68 µs bit period. Compare MCU TX with
the terminal capture before assigning the fault to firmware or USB/UART hardware.

## Gate 3: microphone, then packetized audio

1. After Gate 2 passes, power off, reconnect the INMP441 and upload `esp32dev`.
   Confirm its VDD is 3.3 V, L/R is grounded, and the port is master RX/left/32-bit.
   The INMP441 startup mute lasts 2^18 SCK cycles, approximately 512 ms at this
   clock; this build allows 600 ms at initialization and leaves clocks running.
   [TDK INMP441 datasheet](https://product.tdk.com/system/files/dam/doc/product/sw_piezo/mic/mems-mic/data_sheet/inmp441.pdf).
2. Run `m` in a quiet room, then `m` while speaking at a consistent distance.
   Save the `[MIC]` lines. Both successful captures contain exactly 24,000 PCM
   samples. Expect speech to increase AC RMS and peak range. All zeros suggest
   wiring/channel/power/startup issues; nearly constant data or large DC needs
   slot/format investigation. Persistent clipping means reduce gain after
   confirming data validity. RMS alone cannot distinguish speech from interference.
3. Capture duration should be around 3 seconds plus boundary flushing and
   diagnostics. Exactly 24,000 samples defines duration at the actual measured
   clock; a software millisecond timer does not calibrate the audio clock. The
   original 2.88–2.90 seconds is consistent with queued DMA data, not proof of
   successful fresh capture. The change drains that queue without zeroing it.
4. Run `r`. Require intelligible recorded speech and a complete ending. Keep the
   existing `raw >> 16`, gain 2 conversion until level and raw-word measurements
   justify a change. Do not amplify a disconnected/floating input to hide a fault.
5. Set loss to zero with `l` if necessary, then run `p`. Require 200 received,
   zero missing, byte-for-byte PCM verification and intelligible playback.
6. Toggle `l` to 17 and repeat `p`. Require 189 received / 11 missing, verified
   zeros at those indices, and short gaps rather than displaced/corrupt audio.
   Each missing chunk is 120 samples = 15 ms at 8 kHz; total silence is 165 ms.
7. Repeat `t` and the tone after these operations. Use `h` to disable heartbeat
   after serial is stable. Re-enable only for a specific diagnostic comparison.

**Pass:** all three gates, including human listening and saved measurements.
Only then proceed to SX1262 transport; no real-time or full-duplex LoRa voice is
assumed. No final Heltec V4 pin assignment is established by this bench map.

Record the next evidence in this form:

```text
Environment/banner:
Speaker nominal impedance and measured unpowered resistance:
Amp VIN idle / during s:
Amp SD-to-GND:
ESP32 3V3 idle / during s:
s result / audible yes-no:
Serial-only vs amplifier-connected corruption:
i output and any complete reset log:
Quiet m statistics / speaking m statistics (after tone passes):
Available instruments / I2S measurements:
```
