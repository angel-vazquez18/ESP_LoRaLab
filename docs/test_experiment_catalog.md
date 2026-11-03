# CDR experiment catalog and host coverage

Draft: October 17, 2026. Companion to `host_testbed_design.md`.
Source: `secure_lora_comms_testbed_cdr.pdf`, especially sections 1.3, 5.4, 6,
7.1 and 7.2. Hardware evidence is still outstanding; see
`status.md` for the current physical-only host foundation.

October 26 procedure revision 2.0: `test_procedures.md` defines standalone
laboratory procedures for all 23 checks. Each test specifies prerequisites,
configuration/repetitions, numbered steps, measurements, expected results,
acceptance criteria, evidence collection and cleanup/recovery. It defines
planned validation and does not mark additional runners or hardware experiments
as implemented.

October 18 update: `testbed_contract_v2.md` supplies selected provisional
protocol, security, retry, codec and synchronization decisions. It supersedes
historical requests below to select/agree those choices before implementation;
Homar's review can revise them later. All experiment obligations remain in scope.

## Coverage matrix

Each ID becomes a selectable experiment/check with a stored specification and
results. A suite can contain several runs. Settings are constrained by advertised
hardware/firmware capabilities, not unrestricted text input.

| ID | CDR reference / obligation | Host controls and procedure | Required firmware/instrumentation | Saved measurements and evidence |
| --- | --- | --- | --- | --- |
| IF-01 | 5.4 Stage 1: serial interface | Discover/identify both nodes; known commands, valid/invalid settings, malformed input, absent reply and timeout | Versioned replies/errors, configuration readback, diagnostic mode | Reply correlation, framing validation, command latency, timeout/error outcomes |
| IF-02 | 5.4 Stage 2; 1.3 two-way exchange | Known deterministic payload A-to-B, then B-to-A | TX/RX events, payload verification, counters | Unique delivery, payload integrity, sequence handling, RSSI/SNR, faults |
| IF-03 | 5.4 Stage 3: automated experiment | Configure both nodes, execute bounded batch, collect/finalize, reopen/export | Readiness, bounded start/stop, run summaries | Full settings, run IDs, timestamps, errors, repeatable metrics and exports |
| RF-01 | 7.2: spreading-factor variation | Sweep supported SF values at fixed BW/CR/power/payload/security | Radio configuration/readback and TX/RX telemetry | PDR, useful throughput, airtime, RSSI/SNR; companion RTT runs |
| RF-02 | 7.2: bandwidth variation | Sweep supported BW values at fixed SF/CR/power and other controls | Same as RF-01 | Same metrics, compared by BW |
| RF-03 | 7.2: coding-rate variation | Sweep supported coding rates at fixed SF/BW/power and other controls | Same as RF-01 | Same metrics, compared by coding rate |
| RF-04 | 7.2: transmit-power variation | Sweep supported TX power at fixed modulation and other controls | Applied power readback and signal telemetry | PDR, throughput, RSSI/SNR and delay comparisons; note bench saturation/placement |
| SEC-01 | 7.1 legitimate secure exchange; 7.2 encryption on/off | Paired protected/unprotected runs with identical useful payload/configuration | Shared security profile, key readiness indicator, actual overhead/packet lengths, valid-payload check | Successful protected recovery, delivery/throughput/delay, byte and airtime overhead; never save secret keys |
| SEC-02 | 7.1 altered-packet rejection; 7.2 injection | Send a valid control and a deliberately altered protected frame | Controlled mutation after protection, valid radio CRC, receiver rejection stage/reason | Injection ID, transmitted count, received/rejected/accepted count; no altered application delivery |
| SEC-03 | 7.1 replay rejection; 7.2 repeated packets | Accept a valid protected frame, resend that exact frame within the same defined security session/window | Retained-frame injection and replay-decision telemetry | Initial acceptance, replay rejection, unchanged delivered-message count, rejection reason |
| SEC-04 | 7.1 encryption/decryption overhead | Repeat operations for selected payload sizes/modes; paired no-security baseline | On-node monotonic timing directly around crypto operations | Sample counts, encryption/decryption distributions, clock resolution, per-byte/size comparisons |
| PKT-01 | 7.1 reconstruction; 7.2 message size | Vary known message size around fragment boundaries and through supported buffer sizes | Message/fragment IDs, total length, reconstructed-payload digest | Complete-message ratio, content match, latency, PDR vs message size |
| PKT-02 | 7.2 fragmentation settings | Vary useful fragment size; exercise complete, missing, duplicate and reordered fragments | Configurable fragment sizes, controlled logical fault hooks, receive indexes, reassembly timeout | Expected/received/missing fragments, deduplication, bounded timeout, reassembly correctness |
| PKT-03 | 7.1 retry behavior; 7.2 ACK/retry strategies | Compare ACK disabled/enabled and agreed retry policies/limits under matched loss conditions | ACK events, original packet ID retained across attempts, retry/timeout counters | Original/attempt counts, eventual delivery, retransmission cost, latency, useful throughput |
| TIME-01 | 7.1 initial round-trip delay | Echo known payloads in each direction across selected configurations | Sender-local send and echoed-reply times; matching IDs | RTT median/p95/distribution, successful/missing replies, timeout count, timing definition |
| TIME-02 | 7.1 later synchronized one-way delay | Calibrate clocks, record uncertainty/drift, then collect paired TX/RX events | Documented synchronization method and timestamp points, calibrated clocks | One-way delay with uncertainty, calibration evidence, validity interval and invalid samples |
| MEM-01 | 6 memory risk; 7.1 SRAM/PSRAM chunking | Sample stages across message/fragment sizes and raw/encoded voice | Free/minimum heap, largest free block, allocated capture/codec/reassembly buffers; separate SRAM/PSRAM if present | Baseline/peak usage, stage allocation footprint, failures, reset cause, bytes and fragment count |
| VOICE-01 | 6 audio path isolation; 1.3 local recording | Capture/play a three-second 8 kHz/16-bit mono clip locally on each node before RF integration | I2S capture, exact sample counts, local codec/playback, stage timing, PCM retrieval | 24,000 samples / 48,000 raw bytes excluding headers, local listening observations, capture/codec/playback errors |
| VOICE-02 | 1.3 compressed voice; 7.2 data vs voice | Capture or upload reference clip, encode, fragment/protect/send, reassemble/decode/play; pair with known-data runs | Audio commands, codec/mode metadata, stage/message events, bounded artifact retention/retrieval | Encoded length/rate, compression ratio, RF fragments, delivered-message integrity, reference/recovered clips, paired data results |
| VOICE-03 | 7.1 sustained rate vs encoded rate | Select codec/radio/security/retry profiles; repeated voice messages or sustained encoded test payloads with declared duration | Node-driven pacing and buffer occupancy/underflow telemetry | Useful encoded goodput vs source bitrate, backlog/underflow, completion fraction; distinguish burst delivery from sustained feasibility |
| VOICE-04 | 7.1 voice end-to-end delay and intelligibility | Repeat fixed clips; inspect stage timings; listen to original and recovered audio with fixed rubric | Capture/encode/TX/reassembly/decode/playback timing and retrievable artifacts | Stage latencies, valid synchronized end-to-end latency where available, message RTT, separate host-observed duration, listening rating/notes |
| MODEL-01 | 7.1 raw size, chunk count, packet airtime, total delivery estimate | Preview prediction then compare to observed transmissions over selected profiles | Actual lengths/overhead, TX start/end timing, pacing, ACK/retry and processing times | Model inputs/version, predicted vs measured frame/message duration, residuals, actual fragment count |
| OPS-01 | 6 serial/power risks and controlled environment | Run interruption checks: disconnect, reset, failed config, telemetry gap; repeat stable bench baseline | Boot ID/reset cause, finite-run guard, telemetry-drop counters | Bounded stop, preserved partial records, interrupted/invalid status, environment/power notes |

## Physical node requirements (November 1, 2026)

IF-01, SEC-04 and VOICE-01 run on one node at a time; A or B may be connected
alone. MEM-01 and OPS-01 have one-node local cases and two-node RF cases. The
remaining procedures use the pair. Full repeat coverage on each device remains
required where specified, without requiring both devices simultaneously for local
checks. Future campaigns derive node requirements from their selected cases.
Capability/equipment/runner blockers remain independent of node count.

## Direct mapping of all section 7.2 experiment groups

| CDR experiment group | Catalog IDs |
| --- | --- |
| Spreading factor, bandwidth, coding rate, transmit power | RF-01 through RF-04 |
| Encryption enabled/disabled | SEC-01 and SEC-04 |
| Altered or repeated packets | SEC-02 and SEC-03; PKT-02 for application duplicate behavior |
| Message size and fragmentation settings | PKT-01, PKT-02 and MEM-01 |
| Acknowledgment/retry strategies | PKT-03 |
| Known data vs compressed voice | VOICE-02 through VOICE-04, paired with IF-02 and RF suites |

Additional section 7.1 measurements are explicitly covered by TIME-01/TIME-02,
SEC-04, MEM-01, and MODEL-01; integration stages are IF-01 through IF-03. Audio
isolation and reset/serial checks implement section 6 mitigations as validation
checks rather than inventing new RF experiments.

## Common experiment specification

Every run specification records:

- Catalog ID, schema version, campaign ID, run ID, repetition, selected order,
  and random seed when applicable.
- Roles/direction, physical nodes and firmware versions, radio frequency/BW/SF/
  coding rate/power, preamble/header/CRC/optimization, actual packet budget.
- Security profile/enable state and non-secret session identifier; no secret keys.
- Payload source/type/size/seed or audio artifact ID/hash and codec/mode.
- Fragmentation, acknowledgment policy, timeout, retry limit, packet/clip count,
  pacing, maximum duration, receiver drain, and termination conditions.
- Controlled fault pattern for injection/fragment tests, expected observations,
  metric definitions, acceptance criteria or explicitly exploratory status.
- Environment notes, required capabilities, clock calibration and uncertainty
  where applicable, and estimated run/campaign duration.

The host sends validated settings and stores node readback before arming the
receiver. Preserve both requested and applied values. Never compare runs as if
their settings were equal when a node applied different ones.

## Outcomes and evidence rules

Keep execution status (completed/cancelled/failed/interrupted/blocked) separate
from assessment (pass/fail/inconclusive/not assessed). A completed security test
can fail its assertions; a completed radio sweep may be exploratory.

- Correctness/security checks use explicit assertions, such as matching known
  reconstructed bytes, rejecting a frame known to have reached authentication,
  or preventing a replay from causing a second application delivery.
- Performance tests report observations and repetition variability. Do not invent
  a universal PDR, intelligibility, or latency threshold absent an agreed target.
- Each required case needs hardware evidence. Simulated results exercise host
  behavior and remain separately labeled, never closing hardware coverage.
- A frame not observed at the intended receiver stage is inconclusive for that
  rejection mechanism. An RF CRC drop is not proof of authentication rejection.
- Memory allocation failure is a measured result with size/configuration and
  recovery evidence, not a successful voice delivery.
- Missing telemetry and invalid synchronization make dependent metrics
  inconclusive. Do not substitute zero for an unavailable measurement.
- Every exported report includes the coverage ledger, configuration, raw-event
  references, metrics/units, artifact hashes, and validity/uncertainty notes.

## Security and reliability experiment details

For SEC-02, mutate protected data or the authentication tag after protection;
send with a correctly formed radio frame so the security layer is exercised.
Keep a legitimate positive control for each configuration. Explicitly report
whether the receiver observed the test frame, rejected it, or delivered it.

For SEC-03, reuse the captured protected frame without allocating a fresh nonce
or re-encrypting it. Define the session/window policy with firmware and record
it. Compare the first legitimate acceptance with the repeated frame's outcome.

For PKT-03, agree how reliable retransmissions interact with replay protection:
an already accepted fragment may require a repeated ACK while never being
delivered twice. Count that separately from acceptance of a fresh message. Do
not weaken replay checks merely to make retries appear successful.

Use controlled logical fragment loss for reproducible PKT-02/PKT-03 tests and
label its injection location. It supplements actual RF measurements; it is not
reported as naturally occurring RF loss.

## Timing and memory details

TIME-02 requires a shared timing reference or a validated synchronization
procedure with a documented uncertainty bound, resolution, offset and drift.
Select the method with firmware during interface design. A common wired timing
pulse with timer capture is one possible bench reference; pin availability and
wiring must be agreed. Repeated two-way clock exchanges are another candidate,
but asymmetric transport delay limits their accuracy. Verify the chosen method
using bench timing equipment before treating one-way values as valid.

Define TX/RX timestamp points consistently and record their phase (TX start/end,
RX completion, or application delivery). Account for airtime when comparing
different definitions. Invalidate clock calibration on either node reset or
when its documented validity/uncertainty limit is exceeded.

MEM-01 records actual allocations around capture, encoding, fragmentation,
security, reassembly, decoding and playback. Capture, codec workspace, protected
packets, and receive buffers may overlap in lifetime. Fragment count is not a
memory-footprint measurement by itself; test buffer limits and recovery rather
than assuming the chip's nominal total memory is available to audio.

## Voice and comparison details

The three-second raw baseline is `8000 * 2 * 3 = 48000` bytes. Encode before RF
fragmentation. Derive fragment count from actual encoded bytes, security/framing
overhead, and negotiated packet capacity. Compare the compressed-message digest
at sender/receiver before decoding; compare decoded audio perceptually using
the saved rubric, not a PCM equality assertion for a lossy codec.

VOICE-02 has two paired comparisons: equal useful-byte counts to expose transport
effects, and the actual three-second voice application versus a declared known
data workload. Label the comparison basis; codec processing time and variable
encoded size must not be mistaken for a radio-configuration effect.

Reference WAV upload occurs before the measurement window. Artifact retrieval
occurs afterward. Node microphone capture and receiver speaker playback remain
required paths; host upload/playback is an aid to repeatability and inspection.
Store exact source format, codec version/mode, sample/frame counts, original and
received artifact hashes, capture source, and any truncation/concealment policy.

The host shows continuous-source feasibility as goodput versus encoded source
rate, alongside measured buffer behavior. A successful delayed store-and-forward
clip is still a valid voice result even when continuous delivery is infeasible;
the feasibility conclusion and intelligibility evidence must state which mode
was actually tested.

MODEL-01 treats the CDR's numerical examples as estimates requiring validation.
Use the radio's actual configured modulation/timing and full transmitted length;
include processing, pacing, ACKs and retries in message predictions. Save model
error across configurations rather than asserting that one estimate is universal.

## Delivery tracking

Maintain one coverage ledger with catalog ID, firmware owner, host owner,
capability readiness, planned hardware integration date, latest evidence run,
execution/assessment status, and blocking reason. Initially all rows are planned.
Agree firmware dates with Homar; the schedule in the host design is a proposal,
not evidence that firmware commitments already exist.

By November 20, target at least one hardware execution for every row and identify
failed/blocked/inconclusive cases. Use November 21-27 for repeated measurements
and resolution, November 28-December 1 for rehearsal/fixes, and December 2-7 as
deadline buffer. A scope change must be explicit; readiness gating must not hide
missing required experiments.
