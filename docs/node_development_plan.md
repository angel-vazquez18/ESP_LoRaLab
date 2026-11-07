# Node firmware development plan

Planning baseline: November 4, 2026. This is a capability-based development roadmap,
not implemented behavior or a claim of experiment qualification. It replaces the
proposed experiment-by-experiment order for initial node firmware development.
The full experiment catalog remains a later coverage and validation reference.
The selected v2 contract remains authoritative for interfaces unless deliberately
revised through its versioning process.

## What the finished node should do

Build one ESP-IDF image that can be assigned either A or B by the host. Each node
must support these operator workflows:

1. Connect over USB, identify the device/build/boot, inspect health and safely claim control.
2. Configure supported radio, message, security and instrumentation settings and
   report what was actually applied.
3. Send and receive finite known-data messages over the physical LoRa link in either direction.
4. Deliver complete encrypted/authenticated messages, reject tampering/replay,
   and optionally recover packet loss with bounded acknowledgments/retries.
5. Capture a finite voice clip, retrieve and inspect it, and play a known clip locally.
6. Encode a captured/reference clip, transfer it through the same message path,
   reconstruct/decode it, and play it on the other node.
7. Report enough timestamps, signal, memory, counters and errors for the host to
   assess what happened, then stop and recover predictably.

Start with store-and-forward voice clips. Sustained encoded-source feasibility is
also required, but remains a measured later capability; continuous high-quality
or simultaneous two-way voice is not an assumed deliverable.

The host is physical-only. Single-node hardware work and isolated software checks
can proceed now. Link demonstrations require a second identified physical node.
No operator simulator is added to fill a missing firmware or hardware capability.

## Current starting point

- Updated November 6: `firmware/lora_node/main/lora_node.c` logs startup, ESP-IDF
  version, eFuse-derived device ID and numeric reset reason. The user is coding
  manually in small explained steps. November 7 internal-memory and 2 MiB PSRAM
  startup readings were observed; persistent boot identity and serial commands
  remain open. See status.md for readings and remaining validation scope.
- `firmware/diagnostic` already supplies useful serial/identity/ownership/health
  behavior. Reuse verified behavior deliberately; do not confuse it with full-node firmware.
- The Python host already connects to physical diagnostic nodes and retains evidence.
  Full physical execution and audio integration are still missing.
- The user reports one ESP connected to this laptop and the microphone/amplifier
  wired to their assigned GPIOs. Microphone L/R is tied to GND; amplifier SD/MODE
  and GAIN are tied to 3.3 V. GAIN therefore selects 6 dB.
- Board revision, measured rail headroom, sample-rate accuracy and actual audible
  operation remain to be observed. Speaker and PTT connection/operation should be
  checked during bring-up rather than inferred from a GPIO wiring statement.
- The interrupted earlier five-experiment code draft was only temporary staging
  work. It is not an installed implementation, an adopted new contract, or a tested build.

## Node features and ownership

| Capability | Firmware responsibility | Host responsibility |
| --- | --- | --- |
| Board support | Correct pins, USB, RF power controls, observed RAM/PSRAM, button/display | Device enrollment, wiring/build records and operator guidance |
| Control | Bounded command parsing, ownership, replies, capabilities and operation state | One bench owner, compatibility checks and command orchestration |
| Radio | SX1262 configuration, real TX/RX, IRQ timestamps, RSSI/SNR and radio errors | Select settings, coordinate peers and compare outcomes |
| Message transport | Frame parsing, message/fragment identity, bounded reassembly, ACK/retry | Workload selection, expected contents and independent verification |
| Security | GCM, nonce/key lifecycle, authentication and replay rejection | Fresh key provisioning, selected policy and assessment; never persist run keys |
| Artifacts | Bounded immutable PCM/encoded/data objects, chunk CRC and final SHA | WAV wrapping, upload/download, durable storage, waveform/listening tools |
| Local audio/codec | I2S conversion, finite capture/playback, Codec 2, buffering | Reference selection and physical listening/quality observations |
| Run control | Finite operations, prepare/arm/start/stop, timeouts and cleanup | Receiver-first coordination, repetitions, pause/cancel and restart records |
| Measurement | Actual node-local times, stage memory, counters, errors and drop indicators | PDR/goodput/statistics, plots, validity and experiment judgments |

Do not hardcode experiment IDs into core drivers. A radio driver configures and
exchanges frames; it does not implement “RF-01.” A capture module records samples;
it does not decide whether “VOICE-01 passed.” Reuse the same operations in manual
bring-up, the dashboard, CLI, diagnostics and later complete procedures.

## Milestone 1 — A reliable board and control foundation

**Outcome:** identify and control one real node from the host without losing its
serial connection or claiming unavailable capabilities.

- Confirm printed board revision and use its correct pin/RF-front-end mapping.
  Bring up native USB, identity, persistent boot counter, actual internal/PSRAM
  statistics, reset reason and firmware/build/board-profile fingerprints.
- Preserve one image for both roles. Keep physical identity independent of A/B.
- Implement bounded v2 NDJSON framing, strict argument validation, correlated
  replies, duplicate-command handling and useful structured errors.
- Implement claim/keepalive/release with a single owner and a five-second lease.
  Boot changes invalidate old targeted commands; disconnect/reset never resumes work.
- Establish one asynchronous operation owner with progress/result, deadline,
  cancellation and bounded cleanup. Keep health/control responsive while work runs.
- Keep normal logs off the protocol stream. Use bounded telemetry queues and
  explicit drop counters. Expose only supported capabilities.

**Completion evidence:** actual hello/claim/status/release from the host; stable
advancing health; malformed/oversized-input recovery; duplicate-command behavior;
lease loss and reconnect returning to idle. Record exact scope, not full IF-01 closure.

**Small implementation slices:** board identity/health → compatible serial control
→ operation cancellation/lease cleanup. Build each slice before authorizing a flash.

## Milestone 2 — Local audio and transferable artifacts

**Outcome:** prove the wired input and output paths independently on one node.

- Add bounded artifact storage and upload/read/delete, contiguous chunks up to
  1024 raw bytes, CRC-32 and final SHA-256/length commit. Reject incomplete objects.
- First play a known quiet PCM reference through the physical amplifier/speaker.
  Report whether the driver completed separately from an operator hearing audio.
- Capture microphone samples with correct Philips I2S framing, stereo clock slots,
  left-channel selection and startup handling. Convert the microphone's actual
  sample representation to signed 16-bit little-endian mono without hidden AGC.
- Support a three-second 8 kHz clip: exactly 24,000 PCM samples / 48,000 bytes.
  Retrieve it to the host for a WAV, length/hash, waveform and silence/clipping checks.
- Then play captured PCM locally. Capture and playback remain sequential.
- Record hardware gain 6 dB and a declared initial software attenuation. Keep
  microphone conversion and playback gain explicit in the board/build metadata.
- Observe sample clock/rate and 3.3 V stability under audio load when equipment is
  available. A configured sample rate is not a measured sample rate.

**Completion evidence:** uploaded reference is heard; captured artifact has the exact
length/hash and plausible microphone response; recovered PCM is heard; cancel and
invalid/corrupt uploads recover cleanly. Driver success alone does not prove sound.

**Dependency:** milestone 1. This is a useful single-node path now. Artifact transfer
also becomes the shared foundation for codec, message and diagnostic evidence.

## Milestone 3 — A controllable physical LoRa link

**Outcome:** exchange exact finite bytes between two nodes, starting unprotected.

- Integrate SX1262 SPI/IRQ control and all required Heltec front-end power/RF controls.
- Configure 915 MHz and supported SF/BW/CR/TX power values; validate combinations
  and report applied settings. Never equate TX-power configuration with calibrated RF output.
- Add finite transmit/receive operations, explicit PHY CRC/error handling, TX-done
  and RX-done timestamps, RSSI/SNR, radio timeout and standby/stop recovery.
- Implement the selected 40-byte header and single-fragment DATA validation early,
  with device/boot/session/role/configuration attribution. Avoid a throwaway wire format.
- Add the first physical execution adapter slice alongside firmware, so the same
  host can configure, arm the receiver, start the sender and retrieve evidence.
- Verify both directions. Unprotected bring-up must be explicit in the UI/records.

**Completion evidence:** host independently compares received bytes and hashes;
radio settings match; missing/CRC-bad frames are visible; finite timeouts and stop
return both devices to idle. One board can qualify local driver/configuration work,
but cannot establish link delivery or receiver signal measurements.

**Dependency:** milestone 1 and two physical nodes for link evidence. Radio work can
proceed alongside milestone 2 once control is stable.

## Milestone 4 — Reusable message transport

**Outcome:** applications send messages, while the link handles fragmentation,
reassembly and optional reliable delivery.

- Apply fixed header/length rules and default 160-byte useful fragments, including
  final-fragment sizing and reserved overhead for the protected mode.
- Bound allocations, message length, fragment count and reassembly lifetime before
  accepting work. Preserve exact complete-message length and SHA-256.
- Handle missing, duplicate, reordered and inconsistent fragments. Deliver one
  complete validated message once; never expose partial audio/data as delivered.
- Add selectable stop-and-wait ACK/retry with explicit deadlines, retry counts,
  validated references and exact-byte retransmission. Distinguish frames from attempts.
- Keep authenticated/replay-aware duplicate re-ACK behavior as an explicit seam
  for milestone 5; do not finalize secure duplicate handling as an unprotected assumption.

**Completion evidence:** short, boundary and multi-fragment content survives
intact transport; injected loss/duplicates produce the expected delivery or bounded
failure; buffers recover after timeout/cancel; attempts reconcile with retry policy.

**Dependency:** milestone 3. Pure framing/reassembly checks can be developed before
second-node availability, without representing them as physical delivery evidence.

## Milestone 5 — Authenticated, replay-resistant messages

**Outcome:** secure messages use the same transport and remain safe across retries,
failed authentication, cancellation and resets.

- Use pinned ESP-IDF crypto facilities for AES-128-GCM, a 96-bit nonce and 128-bit tag.
- Authenticate the complete RF header. Establish fresh source-specific RAM-only
  keys per run/session; clear them at close, lease loss and reset. Never log keys.
- Enforce nonce/sequence exhaustion rules and reject wrong sessions, changed
  authenticated metadata, modified ciphertext/tags and out-of-window replay.
- Integrate the 128-packet replay window with duplicate ACK handling and exact-byte
  retries. Keep legitimate retransmission from causing a second application delivery.
- Include public known-answer checks and node-local encryption/decryption timing
  diagnostics. These diagnostics may be developed on the single node earlier;
  they do not by themselves establish secure RF behavior.

**Completion evidence:** public vectors match; legitimate protected messages arrive
exactly; wrong keys/tampering/replays do not deliver application content; retry,
lease loss, sequence limits and reset do not reuse ordinary session state.

**Dependency:** control/session foundations plus message transport for integration.
Security is the normal application mode once qualified; none remains an explicit
laboratory comparison/bring-up mode.

## Milestone 6 — Encoded local and remote voice clips

**Outcome:** a voice clip can be captured, encoded, delivered securely, decoded and
played on the receiving node through the common message/artifact path.

- Integrate Codec 2 1.2.0 mode 3200 with recorded source revision/license/build.
  Use fresh encoder/decoder state per clip and validate the library frame dimensions.
- First encode/decode a fixed PCM reference locally, then a microphone capture.
  Preserve original, encoded and decoded artifacts; lossy PCM is not byte-identical.
- Baseline accounting is 150 frames of 160 samples / eight encoded bytes:
  24,000 samples become 1,200 encoded bytes before RF overhead. Verify these counts.
- Route encoded clips through the existing message/security path, not a separate
  radio/audio protocol. Play only complete validated decoded content.
- Retrieve encoded and recovered artifacts; retain capture/encode/queue/transfer/
  reassembly/decode/playback stage times, memory, underflows and loss indicators.

**Completion evidence:** local codec round trip is physically audible; TX/RX encoded
hashes match for a secure two-node clip; receiver playback is observed; errors,
cancellation and resource preflight are explicit. Keep listening findings qualitative.

**Dependencies:** local codec work needs milestone 2; secure remote voice also needs
milestones 3–5. Local codec work can proceed alongside data-link work.

## Milestone 7 — Integrated controls, recovery and sustained-source behavior

**Outcome:** repeated host-controlled data/voice operations remain bounded and
observable, with clear operator controls and deliberate overload behavior.

- Add debounced PTT and useful OLED states when their actual connections are
  confirmed. Initial button action is a host-enabled finite operation, not an
  implicit autonomous or continuous RF mode. Stop/cancel and lease loss have priority.
- Complete operation/run preparation, resource reservation, receiver-first arming,
  finite deadlines, summaries and cleanup across data and audio workloads.
- Add stage-based named buffers, idle memory and instrumented memory histories;
  distinguish boot minima, observed workload minima and unobserved short peaks.
- Exercise disconnect, reset, host loss, bad requests, low memory, radio timeout,
  stalled artifact transfer and cancellation. Retain initiating and cleanup errors.
- Add the required fixed-rate encoded source and bounded queue: eight bytes every
  20 ms, 1,200-byte messages, 4,800-byte queue. Expose backlog and whole-message
  drops; never slow the producer to hide inadequate RF service.
- Run representative repeated/stability workloads. The host schedules campaigns
  and assessments; firmware continues to expose general finite operations.

**Completion evidence:** work stops within declared bounds, sessions are invalidated
correctly, resources recover, following operations succeed, and queue/evidence loss
is visible. A valid finding that a link cannot sustain the source is still useful.

**Dependency:** strengthen recovery at every preceding milestone; this final pass
integrates it across the complete node rather than introducing cancellation late.

## Milestone 8 — Timing quality and complete validation coverage

**Outcome:** node measurements support defensible timing/model analysis and the
remaining complete laboratory procedures.

- Add verified echo request/reply and requester-local RTT. No clock synchronization
  is necessary for RTT; preserve late/duplicate/missing reply outcomes.
- Reserve board-manifest pins for the shared pulse source and both physical capture
  inputs only after checking the full pin map. Do not guess free sync pins now.
- Add the selected wired-pulse capture/calibration interface, freshness/expiry and
  uncertainty handling. Validate capture latency/skew with the required instruments.
- Preserve one-way unavailability without valid calibration. Node ISR observations,
  host receipt times and acoustic mouth-to-ear time are distinct quantities.
- Add controlled diagnostic/fault hooks needed to exercise rejection, replay,
  missing fragments and telemetry loss; they must be observable and explicitly enabled.
- Reconcile the full experiment catalog, complete its prescribed matrices and
  retain independent content, timing, error, memory and recovery evidence.

**Dependencies:** real link, complete telemetry and the required calibration hardware.
RTT can be brought forward after milestone 3; calibrated one-way measurement remains
a separate gated milestone.

## Firmware organization and implementation method

Keep `app_main` as composition and startup. Create modules only as their first
capability is implemented; module names are not task counts or mandatory FreeRTOS tasks.

| Module | Small interface to callers |
| --- | --- |
| `board` | Initialize board resources; return observed identity/configuration/availability |
| `serial_control` | Decode and route commands; publish replies/events through one writer |
| `operation_control` | Start/query/cancel finite work; enforce ownership, deadlines and cleanup |
| `artifacts` | Reserve/write/commit/read/delete bounded immutable byte objects |
| `audio` | Capture/play PCM through supplied buffers; return counts and stage observations |
| `codec` | Encode/decode byte artifacts with declared sample counts and fresh state |
| `radio` | Apply/read settings; transmit/receive frames; stop and report physical observations |
| `packet_link` | Deliver complete messages using framing, reassembly and optional ACK/retry |
| `security` | Protect/verify with supplied session state and replay/nonce rules |
| `telemetry` | Bound and serialize actual health/stage/counter/error records |
| `clock_sync` | Capture pulses and expose calibration inputs/validity |

Keep USB processing responsive while audio/radio/crypto work runs. Interrupt
handlers capture the necessary timestamp/status and signal bounded work; they do
not parse JSON, encode speech or print. Choose task/queue counts from actual driver
needs and measured resources, rather than creating a task for every module.

For each slice: define the existing or versioned interface, implement a real vertical
path, build and run appropriate software checks, then perform the authorized physical
bring-up and retain its scope. Add just enough host integration to operate and
inspect that capability. Do not wait until firmware is complete to discover host
contract mismatches. Full passing experiment qualification is tracked separately.

## Experiment cross-check, not the development order

| Capability family | Experiment coverage it enables |
| --- | --- |
| Control / finite operations / host integration | IF-01, IF-02, IF-03 |
| Radio configuration and observations | RF-01, RF-02, RF-03, RF-04, MODEL-01 |
| Security and local crypto diagnostics | SEC-01, SEC-02, SEC-03, SEC-04 |
| Message transport and reliable delivery | PKT-01, PKT-02, PKT-03 |
| RTT and calibrated clock observations | TIME-01, TIME-02 |
| Resource tracking and recovery | MEM-01, OPS-01 |
| Local audio, codec and remote/sustained voice | VOICE-01, VOICE-02, VOICE-03, VOICE-04 |

Keep all 23 entries. A milestone demonstration enables later procedure work; it
does not automatically pass every mapped experiment or replace its evidence matrix.

## Immediate next development work

Implement milestone 1 first as three reviewable slices: (1) observed board identity,
boot and memory; (2) diagnostic-compatible bounded serial control; (3) asynchronous
operation/cancel/lease cleanup. Then use a quiet known reference to bring up speaker
output and microphone capture separately. Begin radio work alongside local audio
once a second physical node is available for actual link verification.

Do not commit to calendar dates for later milestones until first bring-up establishes
actual board support, memory/audio behavior, second-node availability and the remaining
integration effort. The first-week-of-December delivery target remains a requirement;
review progress against this capability roadmap regularly and surface schedule risks
without silently removing voice or required experiment categories.
