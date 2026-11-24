# Prompt for integrating this snapshot into another repository

Extract the ZIP somewhere separate from the destination repository. Replace the
two paths below and paste the complete prompt into an agent session that can read
the snapshot and edit the destination repo. Add the target board/revision if known.

```text
Integrate the reusable audio and voice-chunking functionality from this ESP32
snapshot into my existing project repository.

SOURCE_SNAPSHOT: <absolute path to extracted esp32-audio-chunker-test>
TARGET_REPOSITORY: <absolute path to destination repository>
TARGET_BOARD_AND_REVISION: <known board/revision, or infer from target configuration>

Inspect the destination repository and follow its applicable AGENTS.md and local
conventions. Read README_HANDOFF.md, README.md, BENCH_VALIDATION.md, platformio.ini,
the include/ headers, lib/audio/, lib/chunking/, src/main.cpp, tools/, and host
tests in the source snapshot. Treat historical hardware reports as evidence with
limits, not as proof that the destination hardware is working.

1. Identify the target framework/version, chip, board pin map, existing audio and
   radio code, I2S/SPI ownership, task model, build environments, memory budget,
   partition scheme, logging, and test commands. Summarize the integration points
   and concrete incompatibilities, then proceed with compatible work. Ask only
   for essential missing hardware/product details that cannot be inferred; do
   not invent pins or imply validation for an unverified board revision.

2. Preserve unrelated features and local changes. Integrate AudioManager,
   VoiceChunker, protocol/configuration and diagnostics using the destination's
   module layout and naming conventions. Resolve generic config.h/pins.h name
   collisions. Adapt the existing application entry point instead of copying a
   second setup()/loop() over it. Merge only required build settings; do not
   replace platformio.ini, downgrade dependencies, or copy huge_app.csv settings
   blindly. Preserve a runnable standalone bench example or document how to run
   the original snapshot separately.

3. Preserve the baseline behavior: 8 kHz signed 16-bit mono PCM, 24,000 samples per
   clip, 48,000 bytes, 200 chunks with 240-byte payloads, and exactly 247-byte
   version-1 packets. Retain strict packet-length/header checks, indexed assembly,
   duplicate retention, zero-filled missing chunks, bounded I/O, failure reporting,
   and PCM export CRC checks. Keep MIC_GAIN=2 and the existing conversion unless a
   measured incompatibility requires a documented change. Do not silently change
   the wire format, timing, gain, clip length, or introduce compression.

4. Keep the TX buffer and VoiceChunker (which owns a 48 KB RX buffer) in suitable
   long-lived storage, never on a small task stack. Account for both buffers plus
   DMA allocations in the target memory budget. Keep the borrowed TX pointer valid
   and immutable during packet generation; do not clear or mutate RX memory during
   playback. Assign a single owner or explicit synchronization for audio/chunker
   state. Current calls block; use the destination's appropriate worker/state
   machine so watchdogs, networking and UI remain responsive. Do not call them
   from ISRs or radio callbacks. Keep PTT disabled until its pin and behavior are
   configured; the baseline is one fixed three-second recording per press.

5. Verify legacy I2S and hal/i2s_ll.h compatibility and availability of both I2S
   ports. Keep microphone RX on port 0 and speaker TX on port 1 where supported,
   or implement and explain the required adaptation. Confirm the actual board's
   pins and schematic. Preserve stereo-slot duplication for mono playback,
   amplifier shutdown/startup ordering, idle check, silent DMA setup, 20 us
   enable-before-clock delay and continuous clocks after startup. Do not bypass
   readiness/error checks. Keep the original platform baseline available for
   regression comparison if the target requires a driver port.

6. Reuse an existing transport abstraction if the destination has one. If it has
   no real transport, retain a simulated adapter and make the boundary explicit;
   do not invent radio hardware or add RadioLib/SX1262 solely because the snapshot
   mentions future work. Before enabling real RX, address the current behavior
   where any differing message ID resets assembly: define sender/message ownership,
   stale-packet handling, message-ID rollover, completion/inactivity timeout and
   partial-message policy. Serialize the two-byte message ID explicitly at a wire
   boundary while preserving version-1 little-endian compatibility. Check transport
   payload capacity, packet ordering, airtime and scheduling constraints. The
   serial-export CRC is not a radio-packet CRC or an authentication mechanism.

7. Carry over useful bench diagnostics, capture tooling and host tests without
   interleaving normal logs with binary PCM export. Keep test stubs restricted to
   host builds. Adapt capture paths/default port selection to the destination and
   retain CRC/length validation and no-overwrite behavior. Treat the supplied
   captures as optional evidence; do not add them to a public repository or assume
   failed capture folders are valid recordings. Leave generated build artifacts
   and caches out of the integration.

8. Build the affected target environments and run the existing destination checks
   plus applicable source C++/Python tests. Preserve coverage for ordering,
   duplicates, malformed/truncated packets, loss silence, message reset, sample
   conversion, partial/failed I/O, startup sequencing and capture validation. Add
   focused tests only for new behavior or integration risks. Report exact commands,
   results and any checks that could not run. Validate electrical timing and sound
   only on the actual hardware; do not describe host tests as hardware validation.

Deliver the implemented integration, a concise list of changed files, documented
pin/resource ownership and configuration, build/test results, and exact remaining
hardware checks or blocked decisions. Work locally; flashing hardware, publishing,
pushing, or deploying is outside this integration request unless separately
authorized. Do not leave compatible implementation work at a plan-only stage.
```
