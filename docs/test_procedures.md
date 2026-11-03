# LoRa Testbed Test Procedures

Revision 2.0 | October 26 2026 | EN.525.743 Fall 2026

This manual specifies repeatable laboratory procedures for evaluating a two-node encrypted LoRa communications testbed. It covers serial control, automated experiments, radio performance, security, packet handling, timing, memory, voice and fault recovery. Each procedure defines its prerequisites, configuration, repetitions, numbered actions, measurements, expected results, acceptance criteria and required records.

## System under test

The system comprises a macOS host and two ESP32-S3 based embedded nodes, designated A and B, connected independently to the host by USB serial. Each node includes a compatible 915 MHz LoRa radio and antenna. Voice procedures additionally require an I2S microphone, audio amplifier and speaker on each node. Firmware uses ESP-IDF and exposes the versioned command and telemetry interface defined by contract 2.0.0 [2]. Node roles indicate test direction and do not replace persistent device identities.

## Required equipment and software

| Item | Requirement |
| --- | --- |
| Host | Installed host application, serial drivers as needed, persistent run storage and export/analysis tools; record software revisions |
| Embedded nodes | Two identified boards and radios with compatible firmware, documented resource limits, stable bench power and separate USB paths |
| RF connections | Correct antennas or characterized attenuated RF fixture; record separation, orientation, gain, cabling and attenuation |
| Audio equipment | Microphones, amplifiers and speakers; verified I2S pins, supply levels, sample conversion and gain; three fixed speech references |
| Timing equipment | Shared 3.3 V pulse with common ground, capture pins on both nodes, timing markers and logic analyzer or oscilloscope |
| Test fixtures | Controlled serial proxy, version/schema fixtures, public crypto vectors and firmware fault hooks with observable application events |
| Records | Board/pin manifests, build hashes, configuration profiles, case ledger, raw telemetry, artifact hashes and instrument identifiers |

## Applicability and test sequence

Perform serial and local subsystem checks independently on each node. Two-node RF procedures require both nodes; calibrated one-way timing requires the timing fixture. Verify capabilities and equipment before each case. Record an unmet prerequisite as blocked rather than reducing the required case set.

Execute IF-01 before IF-02, followed by IF-03 and radio sweeps. Complete SEC-01 before protected packet tests, and VOICE-01 before voice transmission. Qualify the airtime model before using it for duration limits. Repeat affected procedures after a firmware, hardware, configuration or analysis change. Record whether evidence comes from physical hardware or a labeled fixture/simulation; fixture results do not establish physical link or audio performance.

## Using the procedures

The procedure index identifies all 23 tests and their required setup. Common setup, baseline settings and measurement definitions apply unless a test specifies an override. Record each configuration, direction, fault variant and repetition as a separate case. A completed experiment can produce an unfavorable performance result; execution status and acceptance assessment are separate records.

<!-- page -->
# Bench Preparation

**Prerequisites:** Installed host software; one identified node for serial/local checks or two nodes for RF checks; board and pin documentation; compatible firmware; appropriate power, USB and peripheral connections. Preserve the original firmware image and its hash before replacing an installed build.

**Configuration and repetitions:** Prepare A and B separately. Observe each node at idle for at least 30 seconds at approximately 1 Hz before workload testing. Repeat preparation after a board, wiring or firmware change.

## Numbered procedure

1. Record board and radio models/revisions, chip and memory configuration, firmware build, USB path and connected peripherals. Verify supply levels, ground connections, antenna or RF fixture and peripheral pin assignments against the board documentation.
2. Start one host backend. Enumerate serial ports and assign distinct devices to A and B. Use only one process per serial port; disconnect the host before a separate monitor, flasher or diagnostic tool opens that port.
3. Connect each node and obtain its persistent device ID, boot ID, firmware/build/ESP-IDF identifiers, supported interface versions, schema digest, capabilities and resource limits. Stop if identity or compatibility differs from the recorded configuration.
4. Claim control of each node. Verify idle state, approximately 1 Hz health, advancing uptime, internal heap and PSRAM reporting where present. Save the full 30 second observation interval, event continuity and error/drop counters.
5. Confirm that the capability report matches connected hardware. A radio, audio or timing procedure may start only when its required capabilities and readbacks are available. Record missing capability as a blocked prerequisite.
6. For audio work, verify microphone and amplifier power, I2S routing, sample format, gain and speaker output. Keep these settings fixed within a comparison. For timing work, verify source voltage, common ground, capture routing and instrument resolution.
7. Establish fixed RF placement and a stable unsaturated receiving condition. Record separation, antenna orientation, nearby obstructions and interference observations. Use a characterized attenuated fixture if close placement prevents a stable measurement.
8. Allocate the case ledger and evidence directory. Record procedure revision, instrument IDs, software/build hashes and intended settings. Run IF-01 on each node before any link workload. Release control and verify idle if preparation stops before execution.

**Measurements:** Device and boot identities, interface compatibility, reported capabilities, resource limits, health sample count/age, event gaps, errors, drops, idle internal/PSRAM observations and recorded physical conditions.

**Expected results:** Each connected node is uniquely identified, compatible, responsive and idle. Reported peripherals and limits agree with the physical setup and firmware build.

**Acceptance criteria:** Every prerequisite for the selected test is verified. Identity/schema mismatch, unexplained reset, incomplete health evidence or missing required hardware prevents entry into that case.

**Evidence collection:** Save equipment and pin manifests, wiring photographs, identity/capability responses, health observations, build hashes and preparation findings.

**Cleanup and recovery:** Release claims and close ports when finished. Resolve wiring, power, compatibility or health faults before repeating preparation. After a reset, record the new boot identity and invalidate old sessions and clock mappings.

<!-- page -->
# Common RF Run Procedure

**Prerequisites:** Bench preparation completed; IF-01 passed on both nodes; required radio, security, packet and optional audio/timing capabilities verified. Each run has a finite workload, resource budget and stop bound.

## Numbered procedure

1. Record date, operator, case ID, direction, repetition, host revision, contract/schema/profile hashes, firmware builds, board manifests and instrument IDs. Confirm the recorded RF placement and supply condition.
2. Connect and claim A and B. Verify distinct device/boot identities, idle state, live health and required capabilities. Save baseline memory and error/drop counters.
3. Allocate a new run and session. For protected traffic, provision fresh per-source, per-run keys through the owned USB connections. Retain only non-secret session/key-set identifiers; exclude keys and secret-bearing commands from logs and exports.
4. Apply radio/link settings to both nodes and save requested values, applied readbacks and configuration revisions. Reject unsupported values, silent clamping and incompatible peer settings. Enable only the declared fault hook on its designated node and stage.
5. Calculate the complete duration/resource budget from actual frame lengths, attempts, ACKs, processing, guard, fault, drain and audio stages. Save the calculation version and inputs. Extend or explicitly split the workload if the default duration is insufficient.
6. Prepare both nodes and verify their prepared responses, lengths and budgets. Arm the receiver before starting the sender, within the five-second arm interval. A disagreement blocks start.
7. Save raw validated events before display aggregation. Check event sequence continuity, boot/session/run identities, drop counters, original/attempt identities and message results throughout execution.
8. Stop source generation at the declared boundary and allow the declared bounded drain. Collect node summaries, applied settings and artifacts before closing the session. Retrieve artifacts outside the RF measurement window unless the test explicitly measures retrieval.
9. Reconcile raw records and summaries. Compute measurements with the definitions in this manual. Save execution status, acceptance assessment, exclusions and exploratory performance findings separately. Export records with integrity hashes.
10. Remove injections, stop radio/audio/clock operations, close sessions and verify idle state and buffer cleanup. Preserve partial evidence and original errors after failure or cancellation. Use a fresh session for the next run.

## Stop and recovery

An operator stop prevents new frames and retries. Firmware may finish its current noninterruptible radio frame or I2S DMA block. The allowed stop bound is max(current frame airtime, audio DMA block duration) plus 2 seconds. Record the bound before starting and compare it with observed cessation. Command acknowledgement alone does not establish physical stop.

A reset, peer loss or control-lease loss invalidates the run/session and affected clock calibration. Stop the peer, retain partial evidence and reconnect through fresh preflight. Do not resume automatically. Record the initiating fault and cleanup faults separately. Incomplete serial telemetry cannot establish that a missing RF event was radio loss.

<!-- page -->
# Baseline Configuration and Repetition Policy

Apply these settings unless a procedure specifies an override. Resolve every request against reported hardware limits and save applied readbacks. Unsupported required conditions remain blocked; do not silently substitute another value.

| Setting | Baseline |
| --- | --- |
| Software and interface | macOS host; ESP-IDF 6.0.2; wire version 2; contract 2.0.0 and matching schema digest |
| Serial framing | UTF-8 newline-delimited JSON records; 4096 bytes including LF; native USB or separately qualified UART 115200 8N1 |
| Command control | 2 second reply timeout; two retries with identical command identity/bytes; 1 second keepalive; 5 second control lease |
| Radio | 915000000 Hz; spreading factor SF7; bandwidth 125000 Hz; coding rate 4/5; requested TX power 14 dBm |
| Radio framing | Eight preamble symbols; explicit header; radio CRC enabled; normal IQ; private sync word 0x1424; applied LDRO recorded |
| Packetization | 40-byte protocol header; 160 useful bytes per fragment; protected useful maximum 199 bytes; unprotected maximum 215 bytes |
| Link reliability | ACK disabled initially; guard 50000 us; reliable override uses stop-and-wait, at most two retries and ACK timeout 100000 us plus ACK airtime |
| Security | AES-128-GCM; 16-byte authentication tag; fresh source-specific RAM-only keys; 128-frame replay window |
| Known data | 100 messages of 64 useful bytes; base seed 743; three repetitions per condition and direction |
| Voice | Codec 2 1.2.0 mode 3200; 8000 Hz signed 16-bit little-endian mono; 24000 samples per three-second reference |

## Deterministic payload generation

For each message, concatenate SHA-256 blocks over ASCII lora-testbed-v2 followed by BE32(seed), BE32(message_id) and BE32(block_index); retain the first requested number of bytes. BE32 means a four-byte unsigned big-endian integer. Message IDs begin at 1 and block indexes at 0. Generate expected contents independently at the host and compare actual reconstructed bytes or SHA-256 digests. Packet counts alone do not verify contents.

## Repetitions and matched conditions

Run A-to-B and B-to-A separately. Save randomized order and seed before execution. Use the same workload seed across matched settings/directions within a repetition and increment it for the next repetition. Hold placement, payload, fragment size, security, ACK policy and pacing fixed when studying one factor.

Unless overridden, performance conditions use 100 messages x three repetitions x both directions; fault conditions use 10 messages x three repetitions x both directions; voice uses three clips x three repetitions x both directions. Repeat single-node tests on A and B. A reduced workload is a separately labeled smoke test and does not complete the specified coverage.

## Duration and resource limits

Compute the worst-case budget and select max_duration_ms at least max(120000, ceil(budget_us/1000) + 1000), within the negotiated ceiling of at most 3600000 ms. Split into linked cases when needed, preserving original totals. Per-message size is at most 65536 bytes and per-artifact size at most 131072 bytes, subject to lower reported limits. Run baseline controls before and after each sweep block.

<!-- page -->
# Measurements and Acceptance Rules

Retain units, measurement interval, node/direction, sample count, timestamp phases and analysis version with every result. Preserve raw events and summaries. Report an unavailable or invalid value as null with a reason; zero means an actual zero observation.

## Payload and traffic measurements

Packet delivery ratio (PDR) is the count of unique accepted original DATA or ECHO_REQUEST identities matched to confirmed original TX-done identities divided by confirmed original packets. Retries add attempts, not originals. ACKs, echo replies and injected replays are separate traffic classes. Reconcile unmatched identities and counter disagreements.

accepted_fragment_bps is eight times the useful bytes in unique accepted fragments divided by the measurement duration in seconds. goodput_bps uses only useful bytes in complete verified delivered messages. Finite-transfer rates use the sender interval from first TX command to final DATA TX-done, with drain policy recorded. Report intended/started/finished counts, complete-message ratio and host whole-transaction duration separately. A zero denominator makes the rate unavailable.

## Timing memory and signal measurements

Round-trip time (RTT) is the sender-local echo reply acceptance timestamp minus request TX-command timestamp. Report valid echoes, timeouts, median and nearest-rank p95 with n; p95 is sorted sample ceil(0.95 x n). One-way times require TIME-02 calibration and uncertainty. USB event-arrival timestamps do not replace node timestamps.

Memory measurements separate non-overlapping internal heap and external PSRAM scopes, free/minimum/largest blocks, named live buffers and failures. Distinguish boot minimum from observed run minimum and report sampling limits. Received signal strength (RSSI, dBm) and signal-to-noise ratio (SNR, dB) belong to actual received frames; missing frames have no observed signal sample.

Airtime includes full protocol header/body/tag lengths and applied modem settings. Low-data-rate optimization (LDRO) must use the applied value. Record radio-command/ramp and interrupt-capture contributions when comparing software timestamps to predicted on-air duration.

## Expected outcomes and acceptance

| Result dimension | Interpretation |
| --- | --- |
| Execution | completed, cancelled, failed, interrupted or blocked; describe whether the planned actions finished |
| Assessment | pass, fail, inconclusive or not_assessed; assess each stated assertion with linked evidence |
| Performance | Report measured behavior; apply a numerical threshold only if specified before execution |
| Incomplete evidence | Telemetry gaps, unobserved fault arrival or invalid clocks make dependent claims inconclusive |
| Negative case | Require the intended rejection, proof that the stimulus reached its target stage and successful legitimate controls |

Every case records its expected observation, actual observation, criterion and evidence. Radio CRC rejection is not authentication evidence. Exact-frame replay repeats the protected bytes within the same session. Correctness requires valid applied settings, verified contents and bounded behavior. No universal delivery, throughput or listening-score threshold is assumed by this manual.

<!-- page -->
# Test Procedure Index

The IDs map to the Critical Design Review (CDR) experiment and integration requirements [1,4]. Verify the required setup before starting each test. Record each configuration, direction, fault variant and repetition in the case ledger.

| ID | Procedure | Required setup |
| --- | --- | --- |
| IF-01 | Serial interface validation | One node at a time and serial fixtures |
| IF-02 | Verified known-data exchange | Two RF nodes and content verification |
| IF-03 | Automated campaign and persistence | Host fixtures and two RF nodes |
| RF-01 | Spreading factor sweep | Two RF nodes with SF readback |
| RF-02 | Bandwidth sweep | Two RF nodes with BW readback |
| RF-03 | Coding rate sweep | Two RF nodes with CR readback |
| RF-04 | Transmit power sweep | Two RF nodes and verified power mapping |
| SEC-01 | Protected and unprotected comparison | Two RF nodes with AES-GCM |
| SEC-02 | Altered protected packet rejection | Post-protection mutation and stage events |
| SEC-03 | Replay rejection | Retained-frame replay and stage events |
| SEC-04 | Cryptographic processing overhead | Each node with timed crypto diagnostics |
| PKT-01 | Message size and reconstruction | Two RF nodes and bounded reassembly |
| PKT-02 | Fragment loss duplication and ordering | Controlled fragment fault hooks |
| PKT-03 | ACK and retry behavior | Stop-and-wait and ACK fault hooks |
| TIME-01 | Round-trip delay | Two RF nodes with verified echo |
| TIME-02 | Calibrated one-way delay | Shared pulse and timing instrument |
| MEM-01 | Stage and buffer memory behavior | Each node with memory instrumentation |
| VOICE-01 | Local capture codec and playback | Audio peripherals on each node |
| VOICE-02 | Voice RF transfer and data comparison | Two qualified RF/audio nodes |
| VOICE-03 | Sustained encoded-source feasibility | Fixed-rate source and bounded queue |
| VOICE-04 | Voice delay and intelligibility | Recovered audio and stage timestamps |
| MODEL-01 | Airtime and delivery model validation | Timing reference and radio markers |
| OPS-01 | Disconnect reset and recovery | Host fault fixtures and two RF nodes |

Complete the required ledger entries rather than closing an entire test from one successful sample. Preserve failed, blocked and inconclusive cases and identify the reruns needed after a correction.

<!-- page -->
# IF 01 Serial Interface Validation

**Purpose and traceability:** IF-01; CDR 5.4 Stage 1. Verify framing, command ownership, reply correlation, errors and bounded recovery without using RF.

**Prerequisites:** One identified node at a time, compatible serial command processor, host command logger and controlled proxy/version/schema fixtures. Repeat on A and B. Qualify native USB and UART as separate transports when both are required.

**Configuration and repetitions:** C1 valid identity/claim/status/keepalive/release, ten cycles per node/transport; C2 invalid argument and unknown/unavailable command; C3 oversized, split, concatenated, duplicate-key, invalid UTF-8 and malformed JSON; C4 incompatible version/schema; C5 reply loss/delay, retry, conflicting identity reuse and stale boot; C6 competing claim and lease expiry. Repeat each C2-C6 variant three times. Split one valid fixture record at every byte boundary and exercise representative board splits.

## Numbered procedure

1. Save firmware/host/schema hashes, USB identity and boot ID. Run C1 ten times and capture correlated command/reply timestamps and 1 Hz health. Do not claim RF or audio capabilities on a diagnostic target.
2. Send C2 inputs once per connection and require the applicable structured error. Verify invalid configuration cannot change prior applied settings. Unknown commands and known-but-unavailable commands must remain distinguishable.
3. For C3, split a valid record at every byte boundary in the host fixture, then exercise representative splits on the board. Send a record above 4096 bytes followed by a valid status request. Verify discard-through-LF and resynchronization; repeat each malformed type three times.
4. For C4 connect a fixture advertising an unsupported wire/contract version or incompatible schema digest. Require explicit incompatibility, port cleanup and no automatic downgrade or experiment start.
5. For C5 use a controlled proxy/fixture to delay or suppress one reply. Retry a mutating request with identical identity and bytes; require one side effect. Change reused contents and require conflict. Simulate reboot and verify old targeted commands cannot act on the new boot.
6. Verify another client cannot steal an unexpired claim. Stop keepalive, confirm expiry and bounded idle behavior, then reconnect with a fresh claim. Test host stale at 3 seconds and unresponsive at 5 seconds without fabricating health.

**Measurements:** Command/reply identity and latency, side-effect count, errors, framing resynchronization, event continuity, lease expiry, stale/unresponsive detection and recovery times. Record startup text separately from measurement framing errors.

**Expected results:** Valid commands receive correlated replies; invalid records produce structured errors and resynchronize. Retries cause one side effect, conflicting reuse is rejected, stale-boot commands cannot act, and expired claims return the node to bounded idle behavior.

**Acceptance criteria:** Pass each observed diagnostic/error assertion independently. Missing replies must terminate within the configured retry/deadline policy. A proxy-only result is host evidence; repeat applicable cases against actual firmware. An unimplemented handler is blocked, not passed.

**Evidence collection:** Save redacted wire fixtures, commands/replies/errors, timestamps, before/after settings, boot/device IDs, sequence/drop counters, side-effect counts and recovery observations.

**Cleanup and recovery:** Release claims and close the port. After a timeout/reset, establish a fresh connection and claim, verify idle and repeat a valid status command. Stop any active operation using the common recovery rules.

<!-- page -->
# IF 02 Verified Known Data Exchange

**Purpose and traceability:** IF-02; CDR 1.3 and 5.4 Stage 2. Establish actual known-data delivery in both directions before security and audio integration.

**Prerequisites:** IF-01 passed on both nodes; two radio-enabled nodes with configure/prepare/arm/start/stop/summary support, applied-setting readback and independent payload verification. Fixed RF setup and validated duration/resource calculations.

**Configuration and repetitions:** C1 unprotected 64-byte baseline; C2 diagnostic payload lengths 1, 159 and 160 bytes; C3 invalid peer radio configuration as a preflight rejection. Run both directions and three repetitions; use 100 messages per positive condition.

## Numbered procedure

1. Complete common setup and IF-01. Save antennas/placement, hardware limits, exact radio readbacks and stable positive-link condition. Select security none, 160-byte fragments and no ACK for bring-up.
2. Generate the deterministic source independently on host and node from the saved seed and message IDs. Compare source hashes before transmission. Preview count, airtime, resource and drain budgets.
3. Prepare both nodes, arm the receiver and start the sender. Record every confirmed original TX, RF observation, accepted fragment and message result. Allow drain and retrieve summaries.
4. For each delivered message compare the reconstructed bytes or SHA-256 with the independently generated source. Check message/fragment IDs, unique delivery, ordering rules and complete-message totals. Reconcile counters with raw events.
5. Repeat C1/C2 in reverse direction with matched conditions. For C3 request incompatible peer settings and verify the host refuses to arm/start; correct the configuration and rerun a legitimate control.

**Measurements:** Confirmed originals/attempts, unique accepted fragments, complete verified messages, PDR, accepted-fragment rate, application goodput, sender window, signal samples and errors. Associate RSSI/SNR with actual RX packets, not heartbeat freshness.

**Expected results:** Delivered messages exactly match their independently generated source and appear once at the application. Incompatible peer settings prevent start. Delivery counts and summaries reconcile with packet records in both directions.

**Acceptance criteria:** Content correctness requires every delivered message to match and no duplicate application delivery. Report loss and completion rate; performance has no universal PDR target. At least one verified delivery in each direction establishes basic exchange, but full coverage requires every planned repetition/case and a reviewed loss outcome. No delivery is inconclusive for payload correctness and cannot establish link success.

**Evidence collection:** Save source/recovered hashes, raw packet/message events, summary reconciliation, requested/applied settings, signal observations, duration budgets and physical setup records.

**Cleanup and recovery:** Drain, close sessions and verify idle/buffer release. After an error restore matched settings and demonstrate a new valid baseline; retain the original failed run.

<!-- page -->
# IF 03 Automated Campaign and Persistence

**Purpose and traceability:** IF-03; CDR 5.4 Stage 3. Validate a repeatable configure-to-export workflow with independent run records and one bench owner.

**Prerequisites:** IF-02 passed; host campaign storage, pause/cancel/restart controls and exports; finite firmware operations, summaries and exclusive bench control. Run labeled host-fixture cases before the physical two-node series.

**Configuration and repetitions:** C1 baseline: 100 messages of 64 useful bytes, three repetitions in each direction, producing six campaign cases. C2 pause/resume; C3 cancel with queued cases; C4 failed configuration; C5 refresh/navigation; C6 host restart while active and paused; C7 selected-case rerun; C8 hash verification and concurrent-start rejection. Repeat each C2-C8 variant three times using the six-case plan.

## Numbered procedure

1. Save the complete six-case plan, seed/order, source/settings hashes, notes and expected workload before starting. Preview all cases and confirm requested/applied compatibility and duration limits.
2. Start C1. Verify each case gets a new run/session, config readback, receiver-first ordering, collection/drain and terminal record. Reject a second run/campaign or connection/mode change while the owner is active.
3. In C2 request pause during a case. The current case must finish; the next must wait while ownership is retained. Resume and verify the saved order. Navigate/refresh in C5 and verify the backend continues unchanged.
4. For C3 stop an active case. Preserve its partial metrics and mark unstarted cases skipped with a reason. For C4 request a controlled invalid setting; require campaign halt and preserve the original error separately from cleanup errors.
5. For C6 restart the host during a bounded case and again while paused. Require interrupted evidence and no automatic RF resumption. Reconnect through fresh ownership/session preflight.
6. For C7 select cases from a finished campaign. Start a new linked campaign with their original settings/seeds/order. For C8 reopen records and export CSV/JSON/raw events and the evidence bundle; independently recompute every manifest hash.

**Measurements:** Planned/started/terminal/skipped case counts; run/session links; order/seeds; state-transition and pause/stop/restart times; ownership conflicts; export record counts and independently verified hashes.

**Expected results:** Each case has a distinct linked run/session and retained settings. Pause preserves order, cancellation preserves partial records, restart marks interruption, concurrent starts are rejected and exported hashes match the saved records.

**Acceptance criteria:** Pass workflow assertions only when linked records, case counts, provenance and terminal states agree. Simulation validates the host workflow; repeat physical lifecycle and finite-stop assertions on hardware before accepting the physical IF-03 series. Missing export data or silently resumed activity fails its assertion.

**Evidence collection:** Save campaign plan, seeds/order, case/run links, transitions, raw events, pause/cancel/restart logs, exports, manifest hashes and concurrent-start rejection records.

**Cleanup and recovery:** Finalize every case as completed, failed, interrupted or skipped with a reason. Release bench ownership, verify both nodes idle and use fresh preflight after restart.

<!-- page -->
# RF 01 Spreading Factor Sweep

**Purpose and traceability:** RF-01; CDR 7.2. Measure delivery and useful throughput as spreading factor changes, using an actual RF link.

**Prerequisites:** IF-02 passed; two compatible radios with spreading-factor and LDRO readback, per-packet signal/timing telemetry and content verification; validated airtime inputs and fixed RF placement.

**Configuration and repetitions:** Sweep supported SF 7, 8, 9, 10, 11 and 12. Hold BW125 kHz, coding rate 4/5, requested power 14 dBm, 64-byte messages, 160-byte fragments, no ACK and security profile fixed. Use AES-GCM after SEC-01 qualification; retain an explicitly separate unprotected bring-up series otherwise. Use 100 messages, three repetitions and both directions per setting.

## Numbered procedure

1. Complete common preflight and save one stable baseline before the sweep. Freeze placement, power, antennas, security and source seeds. Record the advertised SF subset; unsupported required values remain blocked.
2. Create a seeded randomized plan with settings matched within each repetition. Verify both nodes' applied SF/BW/CR/power/security settings and LDRO. Recompute the full budget for each SF; retain the declared count even when the default duration is too short.
3. Execute each case with receiver-first ordering. Save all attempts, confirmed originals, accepted fragments, verified message results and packet-associated signal/timing samples. Drain and reconcile summaries.
4. Repeat in reverse direction. Run the baseline again after the sweep block. If its behavior changed materially, document the environmental change and rerun a separate controlled block; retain all original results.
5. Plot individual repetitions versus applied SF, separated by direction/security, then show unweighted run variability. Pair matching TIME-01 cases when RTT is required; do not derive delay from USB arrival times.

**Measurements:** PDR and complete-message ratio, application goodput and accepted-fragment rate, actual frame lengths, predicted/observed transmission durations, RSSI/SNR distributions with sample counts, retries if unexpectedly observed and fault/drop counters.

**Expected results:** Both nodes apply the requested supported SF. Delivered contents remain correct and every setting has retained measurements. Airtime and rates can change with SF; no monotonic delivery trend is required.

**Acceptance criteria:** Correct settings, complete evidence and valid payload reconstruction are required; no monotonic PDR/throughput trend is presumed. A supported setting that fails is a retained result, not an omitted row. Telemetry corruption makes dependent metrics inconclusive.

**Evidence collection:** Export settings-difference tables, individual repetitions and variability plots, raw records, model inputs, applied readbacks and baseline drift observations.

**Cleanup and recovery:** Close sessions and restore the recorded baseline with readback. Investigate drift, then repeat a separately identified block without overwriting the original results.

<!-- page -->
# RF 02 Bandwidth Sweep

**Purpose and traceability:** RF-02; CDR 7.2. Compare supported LoRa bandwidths while holding useful workload and other settings fixed.

**Prerequisites:** IF-02 passed; two radios with bandwidth and LDRO readback, valid duration calculations, per-packet signal/timing telemetry and content verification. Use the supported bandwidth intersection.

**Configuration and repetitions:** Sweep 125000, 250000 and 500000 Hz where supported. Baseline SF7, coding rate 4/5, requested power 14 dBm, 64-byte messages, 160-byte fragments, ACK disabled and one fixed qualified security profile. Use 100 messages x three repetitions x both directions. If a second SF block is studied, make it a separately labeled factor block.

## Numbered procedure

1. Fix the bench environment and save a baseline with full requested/applied settings. Confirm the supported bandwidth intersection and exact radio units. Keep preamble, header, CRC, IQ and sync word fixed.
2. Generate a seeded randomized case order and paired source seeds. Apply each bandwidth on both nodes, validate readbacks and applied LDRO, and prepare the corresponding resource/time budget.
3. Execute each run using common prepare/arm/start/drain/finalize steps. Record actual lengths and verified reconstructed content, not just requested counts. Save signal values only for observed packets.
4. Execute the reverse direction with the same design. Repeat baseline cases after the block and preserve any environment/configuration deviation as a separate condition.
5. Compare per-run PDR, application goodput and accepted-fragment rate versus bandwidth. Show missing data and repetitions. Add matched TIME-01 results as a separate latency panel, retaining timestamp definitions.

**Measurements:** Unique originals/accepted packets, complete-message counts, useful bytes/rates, frame durations/model residuals, RSSI/SNR distribution, all radio/serial errors and measurement validity. Separate source pacing from RF airtime.

**Expected results:** Both nodes apply the supported requested bandwidth with other comparison factors fixed. Contents remain correct and measurements are retained at every condition. A larger bandwidth need not improve delivery.

**Acceptance criteria:** Require correct applied settings and content validity. Report observed performance without assuming wider bandwidth improves delivery. A frame-length or security difference invalidates a claimed single-factor comparison until it is explicitly reconciled. An unavailable requested bandwidth is blocked, not silently replaced.

**Evidence collection:** Save each condition/repetition/direction, requested/applied settings, profile hashes, baseline records, raw events, configuration differences and comparison plots.

**Cleanup and recovery:** Close sessions, verify idle and restore baseline bandwidth/readback. If an uncontrolled factor changed, reestablish the baseline and repeat the affected matched block.

<!-- page -->
# RF 03 Coding Rate Sweep

**Purpose and traceability:** RF-03; CDR 7.2. Measure delivery, useful throughput and airtime changes across coding rates.

**Prerequisites:** IF-02 passed; two radios with documented coding-rate mapping/readback, packet telemetry and independent content verification. Fixed RF setup and validated duration calculations.

**Configuration and repetitions:** Sweep coding-rate denominators 5, 6, 7 and 8, representing 4/5 through 4/8. Hold frequency 915 MHz, SF7, BW125 kHz, requested power 14 dBm, 64-byte messages, 160-byte fragments, security and no-ACK policy constant. Run 100 messages, three repetitions and both directions per supported value.

## Numbered procedure

1. Record board-supported coding rates and a stable baseline. Verify the interface uses the denominator field; do not confuse denominator 5 with a radio driver's encoded index 1.
2. Prepare the complete case list and saved order/seeds. Apply each requested denominator to both nodes and require matching readback before preparing or arming. Recalculate airtime and expanded run budgets.
3. Run the finite known-data workload with common event capture and drain. Compare reconstructed contents with the deterministic source and reconcile original/attempt/message counts.
4. Repeat the matched design in the reverse direction and repeat baseline after the block. Preserve low-delivery or failed cases with their actual conditions; investigate signal saturation or changed placement before attributing a difference to coding rate.
5. Plot PDR, complete-message delivery, useful goodput and observed frame-duration distributions against applied coding rate. Show each repetition and its direction/security. Include companion RTT only from matching TIME-01 runs.

**Measurements:** PDR, accepted useful fragment bytes, complete-message bytes, both defined transfer rates, radio signal samples, modeled/observed durations, settings, error/drop counters and sample counts.

**Expected results:** Both nodes apply the requested coding denominator with matching readback and correct contents. Duration and useful throughput may change; additional redundancy does not guarantee higher delivery.

**Acceptance criteria:** Correctness requires applied-rate agreement, valid content and complete evidence. Performance is exploratory; additional coding redundancy is not an automatic delivery guarantee. If firmware readback uses an undocumented convention, block rather than relabel results after execution.

**Evidence collection:** Save coding-rate mapping, requested/applied values, raw packet/message events, per-run plots, modeled/observed durations and baseline controls.

**Cleanup and recovery:** Close sessions, restore coding rate 4/5 and verify idle/memory recovery. Correct an undocumented mapping before repeating affected conditions.

<!-- page -->
# RF 04 Transmit Power Sweep

**Purpose and traceability:** RF-04; CDR 7.2. Compare requested transmitter power settings under a controlled, documented bench condition.

**Prerequisites:** IF-02 passed; two radios with verified board front-end, RF-switch and power-setting mapping; signal telemetry and a stable unsaturated receiving condition. Requested power is not a calibrated radiated-power measurement.

**Configuration and repetitions:** Sweep 2, 5, 8, 11, 14, 17 and 20 dBm where the board supports them. Keep SF7, BW125 kHz, coding 4/5, 64-byte messages, 160-byte fragments, security and ACK-disabled mode fixed. Use 100 messages, three repetitions and both directions. Receiver settings remain unchanged within each block.

## Numbered procedure

1. Document antenna/fixture, placement, external PA or RF-switch controls, supply settings and expected receiver operating range. Start with a low supported power and establish a stable unsaturated receiving condition.
2. Save supported versus requested power values and the complete seeded case order. Request the selected transmitter setting and validate its readback/front-end mapping; do not silently clamp or equate driver setting with radiated power.
3. Run the common finite known-data workload at every supported value. Record actual RX RSSI/SNR samples and clipping/saturation indications where available, plus verified payloads and all errors.
4. Repeat with the opposite node transmitting. Save direction-specific hardware differences. Run the baseline before/after each block, and retain fixture/placement changes as a new condition.
5. Compare individual repetitions of PDR, goodput, signal distributions and matched RTT. Annotate missing RX samples, low counts and any saturated regime. Do not infer a calibrated RF power curve from requested settings alone.

**Measurements:** Requested/applied power, original and complete-message delivery, useful goodput, actual RX RSSI/SNR distributions, saturation indicators, sample counts, errors and matched RTT where measured.

**Expected results:** Applied transmitter settings agree with the verified board mapping. Per-packet signal and delivery observations are retained without receiver saturation or hidden changes in placement.

**Acceptance criteria:** Pass configuration/control assertions when readback and board mapping agree. Report delivery and signal measurements as exploratory. Unsupported settings are blocked; unexplained clamping or a changed receiver condition prevents a matched power-effect claim.

**Evidence collection:** Save board/front-end mapping, requested/applied power, fixture description, per-packet signal records, content checks, timing inputs and comparison plots.

**Cleanup and recovery:** Restore baseline power with readback and close sessions. Correct saturation or fixture changes, save the new condition and repeat its baseline before further comparisons.

<!-- page -->
# SEC 01 Protected and Unprotected Comparison

**Purpose and traceability:** SEC-01; CDR 7.1 and 7.2. Verify legitimate authenticated encrypted delivery and measure its overhead against matched unprotected runs.

**Prerequisites:** IF-02 passed; AES-128-GCM on both nodes, public known-answer vectors, fresh-key session lifecycle, authenticated reassembly, message hashes and observable authentication rejection.

**Configuration and repetitions:** C1 none versus aes128_gcm with useful message sizes 16, 64 and 160 bytes; C2 a 321-byte fragmented message; C3 wrong-key/profile negative controls. Positive conditions use 100 messages x three repetitions x both directions; each negative control targets one declared frame with a legitimate before/after control. Repeat each negative variant three times in both directions.

## Numbered procedure

1. Verify public known-answer vectors independently before live RF use. Save vector IDs, implementation/build and outcomes; ordinary run keys are fresh and never exported.
2. Prepare paired conditions using the same radio, useful bytes, 160-byte fragment setting, ACK policy, source seeds and placement. Open a fresh session for each run. Provision independent A-source/B-source keys only in RAM for protected operation.
3. Transmit the legitimate known workload in each mode. Require GCM verification before plaintext insertion/delivery and compare reconstructed bytes/hashes. Save non-secret readiness/session state and actual frame lengths.
4. For C3 provision a deliberately mismatched receiver key in a declared lab case. Require observed authentication rejection and zero application delivery. Separately request incompatible peer security profiles and require host preflight rejection without arming. Close sessions, restore matching configuration/fresh keys and demonstrate legitimate delivery again.
5. Compare useful delivery/rates and duration using matched windows. Show the 16-byte per-frame tag and framing overhead in actual lengths. Keep crypto processing samples distinct from whole RF duration.

**Measurements:** Verified delivered messages, PDR, useful goodput, complete frame lengths/tag overhead, transfer durations, authentication rejection counts and public-vector outcomes. Record non-secret session/key-set identifiers only.

**Expected results:** Valid protected frames authenticate before application delivery and recover the original contents. Wrong-key frames reach authentication and are rejected. Incompatible peer profiles are rejected separately during host preflight.

**Acceptance criteria:** Protected positive delivery must be authenticated and content-correct. Wrong-key authentication and host profile-mismatch rejection are separate assertions. Missing RF arrival makes the wrong-key assertion inconclusive; successful preflight rejection does not prove receiver authentication. Performance differences remain observations without an invented rate threshold.

**Evidence collection:** Save non-secret session/key-set IDs, settings, lengths, public-vector results, message digests, receiver-stage rejection evidence and matched comparisons. Verify that exports contain no keys.

**Cleanup and recovery:** Close sessions, invalidate keys/readiness and verify idle. After a negative case, restore matching configuration with fresh keys and demonstrate legitimate delivery.

<!-- page -->
# SEC 02 Altered Protected Packet Rejection

**Purpose and traceability:** SEC-02; CDR 7.1 and 7.2. Demonstrate rejection at authentication when protected bytes are deliberately changed after encryption.

**Prerequisites:** SEC-01 passed; two nodes with a post-protection byte-mutation hook, fault.applied and receiver-stage events. The radio recalculates a valid physical CRC over the mutated protected frame.

**Configuration and repetitions:** C1 flip one ciphertext bit; C2 flip one tag bit. Select a valid offset in each actual frame, use xor_mask 1, ACK disabled and a 64-byte known message. Run each case three times in both directions with legitimate controls immediately before and after.

## Numbered procedure

1. Save the exact build, declared fault hook, injection UUID, node, target message/fragment/attempt, frame length and byte offset. Use a new run/session and reserve fault/drain airtime.
2. Establish a positive control under the same radio/security settings and verify its complete application payload.
3. Arm tx_after_protect plus xor_byte on the sender for the chosen frame. Protect normally, mutate only the declared ciphertext or tag byte, and transmit without re-encrypting. The radio must calculate its CRC over the mutated bytes.
4. Capture fault.applied, confirmed target TX and receiver rx.frame with a valid RF CRC. Require rx.rejected at the authentication stage for the target, and no new accepted fragment or application message from it.
5. Clear the injection and complete the legitimate after-control. Repeat independently for the tag/ciphertext variants and reverse direction; keep each observation linked to its injection identity.

**Measurements:** Planned, applied, TX-confirmed and receiver-observed stimuli; authentication rejections; unexpected accepted/delivered counts; legitimate-control outcomes and telemetry completeness. RF or serial loss is a separate outcome.

**Expected results:** Each mutation is observed at its intended authentication stage and rejected, with zero altered application deliveries. Legitimate before/after controls deliver correct contents.

**Acceptance criteria:** Pass requires both valid controls, confirmed intended receiver-stage arrival, authentication rejection and zero altered application delivery. An RF CRC rejection does not satisfy this test. An unobserved target or missing rejection event is inconclusive. Any altered application delivery is a correctness failure.

**Evidence collection:** Save injection ID, target metadata, mutation offset/mask, non-secret protected-frame digest, raw stage events, application-counter changes and control outcomes. Exclude session keys.

**Cleanup and recovery:** Remove all hooks, close sessions and verify no active injection. Open a fresh session and demonstrate ordinary authenticated delivery before subsequent tests.

<!-- page -->
# SEC 03 Replay Rejection

**Purpose and traceability:** SEC-03; CDR 7.1 and 7.2. Show that replaying an already accepted protected RF frame cannot cause a second application delivery.

**Prerequisites:** SEC-01 passed; exact protected-frame retention/replay hook, fault trigger, receiver replay decisions and application counters. Disable ACKs to isolate deliberate replay from legitimate ACK-loss recovery.

**Configuration and repetitions:** C1 immediate same-session replay of a delivered single-fragment message; C2 replay after the receiver advances more than the 128-frame window. Three repetitions per case and direction. C2 declares at least 132 original messages and preserves the selected original frame until replay.

## Numbered procedure

1. Open a fresh protected session and arm tx_retained plus replay for the selected target with a unique injection ID. Include retention, host barrier and replay airtime in the finite fault/drain budget.
2. Transmit the legitimate frame, observe first authenticated fragment acceptance and complete-message digest, and record the application-delivery counter. Do not fire replay based only on sender TX.
3. For C1 send fault.fire while the receiver remains armed. Reuse the retained header, ciphertext and tag byte-for-byte with the same frame sequence/session. No new encryption or nonce allocation is performed for this retransmission.
4. For C2 allow at least 129 later new peer frame sequences before the same retained replay. Verify the window advancement from raw records, then fire within the declared active-run budget.
5. Require receiver observation and replay/too-old rejection for the target. Compare delivered message IDs/counters before and after. Continue with a new legitimate frame and require normal delivery. Repeat in reverse direction with new sessions.

**Measurements:** Initial acceptance, injection application, repeated-frame digest identity, receiver observation/reason, replay-window position and application counter delta. Count injected attempts separately from original packets.

**Expected results:** The first frame is accepted once. The byte-identical immediate or out-of-window replay is observed and rejected without a second delivery. A new legitimate frame still succeeds.

**Acceptance criteria:** Pass requires correct first delivery, observed duplicate rejection, zero second delivery and a successful later control. Missing target arrival is inconclusive. A newly encrypted message with repeated application text is not an exact protected-frame replay test.

**Evidence collection:** Save retained-frame digests, target/session/sequence IDs, replay trigger/barrier, stage events, window advancement, before/after counters and positive-control results.

**Cleanup and recovery:** Delete retained frames, remove replay hooks and close sessions. Use fresh session keys and verify a legitimate baseline. Qualify retry/ACK duplicates separately in PKT-03.

<!-- page -->
# SEC 04 Cryptographic Processing Overhead

**Purpose and traceability:** SEC-04; CDR 7.1. Measure node-local encryption/decryption cost independently from USB and RF scheduling.

**Prerequisites:** Each node provides timed encryption/decryption diagnostics, public known-answer vectors, crypto-operation samples and documented timestamp resolution. Record crypto library/build and CPU/acceleration settings.

**Configuration and repetitions:** Payload sizes 16, 64, 160 and 199 bytes. Execute 1000 operations per size/operation/node, repeated three times. Use a separate first-call sample plus 50 warm-up iterations before each timed batch. Public diagnostic material never becomes an ordinary session key. Keep CPU/crypto acceleration settings fixed.

## Numbered procedure

1. Record implementation/library/ESP-IDF/build, CPU settings, acceleration availability, timestamp resolution and instrumentation configuration. Verify encrypt/decrypt known-answer outcomes first.
2. Run public-vector encryption and valid-tag decryption with timestamps immediately around the crypto operation, excluding serial printing, source generation, allocation and radio work. Retain both original timestamps and reported duration where available.
3. Collect the first-call sample separately, run 50 warm-ups, then 1000 timed iterations per size. Check every operation's status/output. Repeat batches on both nodes without merging device identities.
4. Measure a comparable no-security copy/timing-wrapper baseline with the same payload and buffer policy. Label it as a baseline operation, not encryption. Collect invalid-tag checks separately; never mix failure-path timings into successful decryption statistics.
5. Reconcile sample counts/drop indicators, check duration units and summarize each size, operation, node and repetition. If operation duration approaches timer resolution, report that limitation rather than spurious precision.

**Measurements:** n, failure count, first-call latency, median, nearest-rank p95, mean, spread and per-byte cost; baseline cost; memory before/after; timestamp resolution and acceleration settings. Keep RF overhead comparisons in SEC-01.

**Expected results:** Known-answer outputs match, invalid tags are rejected and each successful timing batch contains the specified sample count. First-call, warm-up, successful operations, invalid-tag checks and copy baseline remain distinct.

**Acceptance criteria:** Correctness requires valid vectors and rejection of invalid tags. Processing measurements are exploratory. Missing/drop-corrupted samples make affected distributions inconclusive; a completed benchmark is not automatically an overhead-performance pass.

**Evidence collection:** Save public vector IDs/results, timing samples, first-call/warm-up labels, build/CPU/acceleration details, timer resolution, memory samples, statistics and charts.

**Cleanup and recovery:** Stop diagnostics, verify memory recovery and clear any ordinary session state. Resolve vector or sample-integrity failures before repeating a timed batch.

<!-- page -->
# PKT 01 Message Size and Reconstruction

**Purpose and traceability:** PKT-01; CDR 7.1 and 7.2. Verify complete known-message reconstruction across fragment boundaries and negotiated buffer limits.

**Prerequisites:** IF-02 passed; bounded fragmentation/reassembly, message-result/digest events and negotiated buffer limits. Complete SEC-01 before the protected series.

**Configuration and repetitions:** With 160-byte fragments test message lengths 1, 159, 160, 161, 319, 320, 321, 1200 and 48000 bytes, plus negotiated maximum minus one and maximum. Deduplicate coincident sizes. Default is 100 messages x three repetitions x both directions; budget each size explicitly. A max-plus-one request is a separate rejection case. Repeat maximum-plus-one rejection three times per node.

## Numbered procedure

1. Confirm resource limits and required buffers before opening a session. Use fixed radio/security/ACK settings and deterministic source generation. Save expected message hash and ceil(length/160) fragment count for each message.
2. Preview each size's complete worst-case time/memory budget. Declare linked subruns if needed to preserve the designed total; do not shorten workloads silently.
3. Execute common finite runs. Collect per-fragment identity/length/acceptance and message.result, including missing-range parts and summary totals. Require exact final-fragment remainder and consistent metadata.
4. Compare reconstructed bytes/SHA-256 and exact message length against the source. Verify one application delivery per complete message and no delivery of a partial message. Record reassembly latency with its local phase definition.
5. Request the negotiated maximum plus one without arming. Require a deterministic resource/argument rejection and unchanged idle/buffer state. Return to a valid baseline and demonstrate recovery.

**Measurements:** Expected/observed fragment count, original PDR, complete-message ratio, content match, reassembly duration, useful message goodput, buffer occupancy and allocation failures. A 48000-byte known-data test is not an encoded voice measurement.

**Expected results:** Supported complete messages reconstruct to exact length/hash once; partial messages are never delivered. Maximum-plus-one input is rejected before arming and a subsequent small valid workload succeeds.

**Acceptance criteria:** Every delivered message must have exact length/content and no duplicate delivery. An unsupported required size stays blocked. A supported allocation failure is a retained measured failure with cleanup evidence; it is not successful reconstruction. Unexpected metadata/length acceptance fails correctness.

**Evidence collection:** Save size cases, source/reconstructed hashes, fragment and missing-index maps, resource/time preflight, raw events, rejection records and memory recovery.

**Cleanup and recovery:** Release reassembly/source buffers and close sessions. Run a small valid baseline after rejection/failure to verify recovery before proceeding.

<!-- page -->
# PKT 02 Fragment Loss Duplication and Ordering

**Purpose and traceability:** PKT-02; CDR 7.2 and reassembly obligations in 7.1. Exercise controlled complete, missing, duplicate and reordered fragments.

**Prerequisites:** PKT-01 passed; controlled receiver pre-reassembly drop and transmitter duplicate/reorder hooks, observable fault application, missing-index/rejection events and finite reassembly deadlines.

**Configuration and repetitions:** A 1200-byte deterministic message; useful fragment sizes 16, 64, 160 and protected maximum 199 where supported. ACK disabled, fixed qualified security/radio. C1 intact; C2 drop one middle fragment; C3 duplicate one fragment; C4 reverse a four-fragment block within one message. Use 10 messages x three repetitions x both directions for each combination.

## Numbered procedure

1. Compute fragment counts and exact index/last-fragment lengths. Select a middle target in message 3 and a four-fragment reorder block. Retain the expected byte/hash result and reassembly deadline.
2. Run intact controls. For C2 install receiver rx_before_reassembly plus drop on the named target. Confirm the fragment passed validation before the controlled drop and was not marked accepted/replay-consumed for insertion.
3. After the declared deadline, require a failed/incomplete message and exact missing-index evidence. Confirm no partial application delivery; a later independent message must still reconstruct normally.
4. For C3 use tx_schedule duplicate to transmit exact retained bytes. Require one unique insertion and at most one application delivery, with a separate duplicate/replay event. For C4 reverse a block of at most 32 fragments, staying inside one message and the replay window.
5. Require unseen authenticated reordered fragments to be accepted and complete the correct message. Repeat at each fragment size and direction with new sessions. Clear injections and finish a final intact control.

**Measurements:** Expected/accepted/missing indexes, injected versus natural loss, arrival order, duplicates/rejections, content hash, completion/timeout, duration and memory recovery. Do not combine deliberate drops with natural RF-loss estimates.

**Expected results:** Intact, duplicated and reordered series reconstruct exactly once. A controlled missing fragment yields an explicit bounded incomplete result with correct missing indexes and no partial application delivery.

**Acceptance criteria:** Intact/duplicate/reordered cases require exact reconstruction and no extra delivery. The missing-fragment case passes its negative assertion through bounded failure and zero partial delivery. Missing fault arrival or incomplete missing-range telemetry is inconclusive. Reassembly timeout must not become an unbounded wait.

**Evidence collection:** Save fault node/stage/ID, target/index maps, attempts, arrival order, hashes, missing/timeout events, buffer records and before/after controls.

**Cleanup and recovery:** Remove drop/duplicate/reorder hooks, stop operations, close sessions and verify resources return to idle. Demonstrate an intact control before the next fault family.

<!-- page -->
# PKT 03 ACK and Retry Behavior

**Purpose and traceability:** PKT-03; CDR 7.1 and 7.2. Measure eventual delivery, retransmission cost and duplicate-safe recovery under matched controlled loss.

**Prerequisites:** PKT-01 and PKT-02 passed; stop-and-wait with bounded retry cache, retained exact-byte retransmissions, ACK/result events, receiver drops and ACK suppression.

**Configuration and repetitions:** 321-byte messages, 160-byte fragments and fixed protected radio settings. Policies: no ACK/no retries, stop-and-wait with zero, one and two retries. Faults: none; first-attempt receiver pre-reassembly drop; one suppressed ACK; all allowed attempts dropped for a target. Use 10 messages x three repetitions x both directions, with positive controls.

## Numbered procedure

1. Save each policy's timeout: ACK turnaround 20000 us plus ACK airtime plus margin 80000 us. Preview the total budget and retain source/fragment hashes. Apply receiver-side drops or ACK suppression on the correct node.
2. Run matched no-fault baselines. Drop message 3's fragment 1 before reassembly on its first attempt. Verify no-ACK behavior, then repeat under each reliable policy without changing useful bytes or placement.
3. On retries require byte-identical DATA frame digest, unchanged original sequence/nonce and increasing attempt index. Count a retry as an attempt, not another original packet. Require eventual delivery only when an allowed attempt actually reaches acceptance.
4. Suppress one receiver ACK after successful DATA insertion. Require a repeated DATA classification of retry_duplicate, a new valid ACK and no second application delivery. Invalid/wrong-reference ACK fixtures must not acknowledge the DATA.
5. Drop every permitted attempt for one target. Require timeout/retry exhaustion within its budget, explicit message failure and bounded continuation/stop according to the declared case. Clear hooks and show successful recovery.

**Measurements:** Original/attempt/retry counts, ACK successes/timeouts, complete-message ratio, useful goodput, duplicate deliveries, duration and retransmission cost. Reconcile both nodes' summaries with actual attempt identities.

**Expected results:** Allowed retries preserve protected bytes and recover when an attempt is accepted. ACK loss causes re-ACK without duplicate delivery. Attempts remain within policy and exhausting all attempts produces a bounded explicit failure.

**Acceptance criteria:** Pass policy assertions when attempts never exceed 1 + max_retries, correct retries recover when observed, exhaustion is bounded and application delivery stays unique. Unobserved or unexplained stimuli are inconclusive. Compare performance without inventing a required improvement.

**Evidence collection:** Save timeout/model inputs, injection targets, exact-byte digests, ACK references, attempt timelines, exhaustion/missing-message results and recovery controls.

**Cleanup and recovery:** Remove drop/ACK hooks, close the session to clear retained retry/cache state and verify idle. Run a new no-fault baseline to establish recovery.

<!-- page -->
# TIME 01 Round Trip Delay

**Purpose and traceability:** TIME-01; CDR 7.1. Measure request-to-echo acceptance on one node clock without assuming synchronized peers.

**Prerequisites:** Two qualified RF nodes with ECHO_REQUEST/REPLY, exact echoed bytes, request references, sender-local timestamp phases and finite echo deadlines. Use SEC-01 qualified profiles for protected cases.

**Configuration and repetitions:** Single-fragment payload lengths 16, 64 and 160 bytes, ACK disabled, matched none/protected profiles after the relevant profile is qualified. Use 100 echo requests x three repetitions x both directions. Begin at baseline radio, then use explicitly matched RF configurations for companion delay results.

## Numbered procedure

1. Verify both nodes' clock resolution and timestamp definitions. The requester records tx_command_us immediately before the radio command; the same node records echo_reply_accepted after validation. This interval includes radio/peer turnaround and both airtimes.
2. Prepare the exact request count, interval/timeout and source hashes. Arm the responder before starting the requester. Require each reply to echo the original bytes, reference the request frame and use the responder's own fresh frame sequence.
3. Match successful replies by session/source/reference and verify contents. Compute RTT only from the requester's local timestamps. Exclude unrelated, duplicate, invalid or late replies from success samples while retaining their outcomes.
4. Record timed-out requests separately. Run a controlled missing-reply case to verify bounded timeout and no fabricated zero-delay sample. Do not calculate delay from USB receive-time differences.
5. Repeat directions and matched profiles/settings. Plot individual observations and an ECDF/histogram with n, median and nearest-rank p95. Keep failed requests visible and annotate low sample counts.

**Measurements:** Intended/confirmed requests, valid replies, timeouts, late/invalid responses, RTT distribution, peer turnaround if available, airtimes, payload/security and timestamp resolution. Report host transaction duration separately.

**Expected results:** Each accepted echo matches one request and produces a sender-local RTT sample. Missing replies become explicit timeouts; unrelated, duplicate, invalid and late replies do not produce false successful samples.

**Acceptance criteria:** Correct matching, verified echo contents, valid local timing and bounded timeout are correctness assertions. Delay is exploratory unless a target was agreed. A no-reply condition is not a zero RTT; its latency is unavailable. One-way claims require TIME-02.

**Evidence collection:** Save request/reply IDs and contents/digests, raw local timestamps, reason-coded exclusions, timeout records, settings, sample counts and distribution data.

**Cleanup and recovery:** Drain outstanding responses, stop echo operations and close sessions. Exclude stale replies from later runs and reestablish fresh identifiers after reset.

<!-- page -->
# TIME 02 Calibrated One Way Delay

**Purpose and traceability:** TIME-02; CDR 7.1. Establish valid one-way timing with explicit phases and measured uncertainty.

**Prerequisites:** Two nodes with hardware capture/marker pins, shared 3.3 V pulse and common ground, continuous clock capture, RF timestamps and logic analyzer or oscilloscope. Verify pin mapping and capture-latency bounds.

**Configuration and repetitions:** C1 calibration and RF under normal load; C2 representative audio/processing load when included in the declared case; C3 missing/extra pulse; C4 expired calibration; C5 either node reset. Three repetitions per supported condition and both directions for delay samples.

## Numbered procedure

1. Verify the board manifest: one 3.3 V source from A drives capture inputs on both A and B, with common ground and no pin conflicts. Capture A's physical edge too. Record instrument resolution, wiring and marker behavior.
2. Arm both continuous captures, then start 10 Hz pulses. Collect 32 paired rising edges and check pulse indexes/counts/intervals. Fit time_A = scale * time_B + offset_us. A missing/extra edge invalidates the batch; never shift indexes to hide it.
3. Validate capture latency/skew using instrument traces and capture markers under normal and representative load. Combine that bound, fit residual, quantization and drift extrapolation. Fit residual alone is insufficient.
4. Install mapping metadata and keep 10 Hz pulses running. Refit the latest 32 paired edges. Require total uncertainty <=1000 us and an update no older than 2 seconds, with unchanged boot/capture identities.
5. Run 100 matched RF observations x three repetitions x both directions. Report command-to-RX-done and command-to-application-acceptance separately, mapping both to the common domain and retaining uncertainty.
6. Exercise C3/C4/C5. Require dependent samples to become invalid/null with a reason; recalibrate before further valid one-way results. RTT may remain separately available.

**Measurements:** Paired pulse count/indexes, fitted scale/offset, residuals, capture skew, quantization/drift bounds, mapping age, total uncertainty, valid/invalid sample counts and each named one-way interval.

**Expected results:** Valid mappings use matched pulse edges, documented capture bounds and uncertainty <=1000 us. Expired, reset or malformed calibration invalidates dependent one-way samples; fresh calibration restores eligibility.

**Acceptance criteria:** Calibration/invalidity assertions pass only with saved instrument evidence and correct rejection of invalid mappings. One-way performance remains exploratory. Do not label software-command time as exact on-air start or use USB arrival-time subtraction.

**Evidence collection:** Save raw paired pulses, fit/mapping revisions, uncertainty components, instrument traces, raw timing samples, invalidation records and recalibration results.

**Cleanup and recovery:** Stop pulse source/captures, expire mappings and close sessions. After any invalidation, reacquire and qualify calibration before accepting new one-way samples.

<!-- page -->
# MEM 01 Stage and Buffer Memory Behavior

**Purpose and traceability:** MEM-01; CDR 6 and 7.1. Measure buffer footprints, allocation limits and recovery under data and voice workloads.

**Prerequisites:** Each node reports non-overlapping internal/PSRAM memory statistics, named allocations, buffer lifetimes and stage samples. RF and audio subcases require their qualified hardware and capabilities.

**Configuration and repetitions:** C1 idle baseline; C2 data lengths 64, 160, 321, 1200, 48000 and negotiated maximum; C3 24000-sample PCM capture, codec, reassembly and playback stages; C4 oversized request; C5 cancellation and failure recovery. Three repetitions per supported case on each node; RF workloads run both directions.

## Numbered procedure

1. Record 30 seconds idle at 1 Hz. Save free/minimum/largest internal heap and PSRAM separately, plus current live buffers, counters and reset cause. Do not add overlapping heap-capability totals.
2. For each C2 case enable 10 Hz memory instrumentation and stage entry/exit samples. Record source, radio, reassembly, artifact and queue allocations with their lifetimes. Include a 30 second post-run idle observation.
3. For C3 isolate capture, encode, transfer/reassemble, decode and playback, then execute the integrated path. Record overlapping buffers; compute measured internal/PSRAM changes from the appropriate stage baseline.
4. Distinguish boot minimum from observed run minimum. Compare largest free block and explicit live allocations, since polling alone may miss short peaks. Preserve reported allocation failures with the exact requested size, stage and recovery outcome.
5. Request max-plus-one work before arming. Require resource rejection without a reset or partial activation. Cancel a valid workload and verify buffer release, idle state and successful subsequent small workload. Save the declared baseline recovery band before the case.

**Measurements:** Stage/run free-memory minima, largest blocks, named live allocation bytes, memory sampling coverage, allocation failures, reset cause, post-run recovery and message/fragment/codec counts. Fragment count is not itself a memory-footprint measurement.

**Expected results:** Stage allocations and memory changes are attributable to named buffers. Oversized work is rejected without partial activation; cancellation/failure releases resources and a subsequent small workload succeeds.

**Acceptance criteria:** Resource-bound and cleanup assertions require predictable rejection, zero unexplained corruption/reset and recovery within the declared band. Feasibility at a size is a measured result. An audio subcase without its prerequisites is blocked; report sampling limits for unobserved transient peaks.

**Evidence collection:** Export annotated heap/buffer timelines, memory scope definitions, stage/allocated-byte records, failed-size requests, sampling intervals and pre/post-run recovery observations.

**Cleanup and recovery:** Stop diagnostics/workloads, retrieve evidence, delete unused artifacts and close sessions. Verify idle health and memory within the predeclared recovery band; investigate unexplained residual allocation.

<!-- page -->
# VOICE 01 Local Capture Codec and Playback

**Purpose and traceability:** VOICE-01; CDR 1.3 and audio-isolation mitigation in section 6. Qualify the complete local audio path on each node before RF integration.

**Prerequisites:** Physical microphone, amplifier and speaker on each node; verified I2S mapping; bounded capture/playback, Codec 2 mode 3200 and artifact retrieval. Browser reference playback does not establish node audio output.

**Configuration and repetitions:** C1 microphone capture and raw local playback; C2 encode/decode/local playback; C3 a reproducible uploaded PCM reference; C4 invalid format/length, cancellation and corrupt/incomplete artifact. Use three utterances/references x three repetitions on each node.

## Numbered procedure

1. Record microphone/speaker models, I2S pins/conversion/gain, supply settings, codec release/commit/build and sample-rate validation. Keep gain and noise processing fixed. Confirm resource preflight for PCM, codec working memory and artifacts.
2. Capture exactly 24000 samples at 8000 Hz, signed 16-bit mono. Retrieve the 48000 raw PCM bytes, verify length/hash and wrap them in WAV for inspection. Check actual duration/sample rate and note clipping, silence or dropped samples.
3. Play the captured PCM locally and document audible output. Encode with fresh Codec 2 mode-3200 state, require the library's 160 samples/64 bits per frame and record 150 frames/1200 bytes for the baseline. Decode with fresh state and play locally.
4. Upload one fixed reference before timing using contiguous <=1024-byte chunks, CRC-32 and final length/SHA-256 commit. Repeat codec/playback and retrieve original/encoded/decoded artifacts. PCM equality is not required after lossy coding.
5. Exercise C4: incompatible format, excessive sample count, wrong chunk checksum/offset, wrong final hash and cancellation. Require explicit errors, no use of uncommitted content, bounded stop and recovery. Capture/playback never overlap in v2.

**Measurements:** Sample count/rate, raw/encoded/decoded lengths and hashes, codec frames, clipping/silence/drop observations, stage durations, memory, artifact errors and physical playback observations.

**Expected results:** The raw capture contains 24000 samples/48000 bytes. Mode-3200 encoding produces 150 frames/1200 bytes for that input, decodes successfully and is physically audible. Invalid/uncommitted artifacts are never used.

**Acceptance criteria:** Require exact capture counts, committed artifact integrity, valid codec frame structure, physically observed playback and documented error recovery. Listening findings remain qualitative. No RF or continuous-voice claim follows from a local success.

**Evidence collection:** Save original/decoded WAVs, encoded bytes, manifests/hashes, sample-rate trace, codec build/frame counts, stage timings, listening observations, errors and memory traces.

**Cleanup and recovery:** Stop capture/playback, retrieve evidence before artifact deletion and verify idle/resource release. Correct format/wiring or codec errors before repeating local qualification.

<!-- page -->
# VOICE 02 Voice RF Transfer and Data Comparison

**Purpose and traceability:** VOICE-02; CDR 1.3 and 7.2. Demonstrate complete compressed voice delivery and compare transport with declared known-data workloads.

**Prerequisites:** VOICE-01 passed on both nodes; qualified RF/security/reassembly and bounded artifact transfer. Microphone-source and receiver-speaker paths must be physically connected and observed.

**Configuration and repetitions:** Three fixed three-second references x three repetitions x both directions, plus node-microphone captures. Pair each encoded workload with equal useful-byte known data and with the declared standard 64-byte data workload. Hold radio/security/ACK/fragment settings fixed within each comparison.

## Numbered procedure

1. Upload/commit references outside the measurement window and save hashes/codec provenance. Preflight buffers and all stage/transfer budgets. For microphone cases capture begins at run start; reference preparation remains outside timing.
2. Encode the source and save actual encoded length, frame/sample counts and digest. For the baseline expect 1200 bytes and eight 160-byte DATA fragments; verify the library/output rather than assuming size from raw PCM.
3. Transmit, authenticate and reassemble. Compare complete encoded-message SHA-256 at both ends before decoding or playback. No partial/unverified message reaches audio output.
4. Decode, play on the receiver speaker and retrieve the encoded/recovered artifacts after the timed RF window. Listen and record output/errors. Repeat with both nodes serving as microphone source and speaker destination.
5. Run the equal-useful-byte known-data comparison with the actual encoded size and matched message count. Separately compare the three-second application with the declared standard data workload. Label the comparison basis; do not hide codec work or change useful-byte counts implicitly.
6. Collect stage timestamps and memory throughout. Use calibrated one-way time only when TIME-02 is valid; retain host transaction time separately. Analyze feasibility/intelligibility further in VOICE-03/04.

**Measurements:** Encoded frame/byte/fragment counts, verified message delivery, useful goodput, stage/transaction duration, calibrated one-way intervals when valid, signal/memory samples and matched known-data results.

**Expected results:** Complete encoded bytes match across the RF link before decoding, and the receiver produces physical playback. Voice and known-data comparisons retain their explicitly matched byte/workload basis.

**Acceptance criteria:** Require encoded content equality after transport, valid codec metadata, complete-message delivery and observed physical playback for the claimed delivered cases. Delayed store-and-forward success is valid but does not establish sustained voice. Missing source/speaker hardware blocks those cases.

**Evidence collection:** Save source/encoded/recovered artifacts and hashes, matched data-run links, stage timestamps, calibration references, RF/signal/memory events and playback observations.

**Cleanup and recovery:** Retrieve artifacts before session close, stop audio and release buffers. After an incomplete transfer, suppress playback, preserve the failure and rerun from a new session.

<!-- page -->
# VOICE 03 Sustained Encoded Source Feasibility

**Purpose and traceability:** VOICE-03; CDR 7.1. Determine whether the selected link can sustain the encoded source rate without hiding backlog or source loss.

**Prerequisites:** Qualified RF message delivery, fixed-rate encoded producer, bounded source queue and observable occupancy, producer/consumer totals, overflow/drop and underflow events. Validate the producer independently.

**Configuration and repetitions:** Generate 8 encoded bytes every 20 ms for 60 seconds, forming 1200-byte messages every three seconds. Queue ceiling is 4800 bytes including the active/partial message. Keep the first 3 seconds as an explicit startup interval; assess the 3-to-60 second interval and save all startup/drain observations. Three repetitions and both directions per declared radio/security/ACK profile.

## Numbered procedure

1. Independently validate source frame rate and total produced bytes/counts. Compute RF/processing/drain budgets without slowing the producer to fit the link. Save exact queue accounting and overflow policy.
2. Start the finite encoded source and RF consumption together. Sample queue occupancy at 5 Hz and emit source/consumer totals and whole-message overflow drops. Retain actual producer timestamps and message IDs.
3. Stop source generation at 60 seconds. Preserve generated, admitted, dropped, transmitted and delivered counts. Allow the declared bounded drain, recording all completion times and residual backlog.
4. Compute production rate and complete verified useful delivery rate during the declared assessment interval. Separately report eventual delivery after drain. Inspect queue trend, overflows, source-byte drops and consumer underflows.
5. Repeat profiles/directions without moving the bench. A matched reliable/unreliable series keeps source production fixed and counts retries/ACK costs separately. Do not present eventual queued delivery as in-window sustained throughput.

**Measurements:** Produced/admitted/dropped/transmitted/delivered bytes and messages; actual source rate; queue occupancy/trend; overflow and underflow; verified in-window delivery rate; final backlog and drain duration.

**Expected results:** The source continues at 3200 bit/s independently of RF capacity. A sustainable profile keeps up without growing backlog or source loss; an unsustainable profile exposes queue growth, drops or delayed delivery.

**Acceptance criteria:** A feasible observation requires delivery keeping pace with the 3200 bit/s source, no growing backlog hidden by drops, and no overflow/source-loss condition during the assessed interval. Report the actual finite observation length. An infeasible finding can be a valid completed experiment; incomplete rate/queue telemetry makes the conclusion inconclusive.

**Evidence collection:** Save the producer schedule, queue traces, exact observation windows, all byte/message totals and hashes, drop/underflow events, completion times and drain records.

**Cleanup and recovery:** Stop the producer, complete or discard pending messages under the declared stop policy and save final queue state. Release queue/session resources and verify idle.

<!-- page -->
# VOICE 04 Voice Delay and Intelligibility

**Purpose and traceability:** VOICE-04; CDR 7.1. Measure named voice stages and document the intelligibility of physically recovered speech.

**Prerequisites:** VOICE-01 and VOICE-02 passed; source/recovered artifacts, physical playback, stage timestamps and listening records. Valid TIME-02 calibration is required for cross-node one-way timing.

**Configuration and repetitions:** Use the same three fixed reference clips across configurations, three repetitions and both directions. Include microphone-source cases with matching utterance instructions. Fix gain, codec, listening level and reproduction equipment; save their settings and listener identifiers.

## Numbered procedure

1. Save source hashes/transcripts or intended phrases, codec/build, clip order and environment. Use randomized coded playback order where practical and retain the ordering key. Obtain independent source/reference and recovered listening observations.
2. Execute the complete capture/encode/queue/transmit/reassemble/decode/play path. Verify encoded transport integrity before evaluating intelligibility; record truncation, concealment, clipping and audio errors.
3. Measure each stage on its local clock. With valid mapping, compute capture-start to receiver playback-completion and report uncertainty and timestamp phase. This is the declared software/I2S transaction interval; an acoustic mouth-to-ear claim requires separate acoustic instrumentation.
4. Without valid synchronization leave cross-node one-way latency unavailable and retain local stage durations, matched message RTT where supported, and host whole-transaction duration under their own labels.
5. Listen to corresponding source/recovered clips with the fixed five-point rubric: 1 unintelligible, 2 occasional words, 3 meaning with effort, 4 mostly clear, 5 clear. Save ratings, listener IDs, clip order and free-text observations per clip/configuration.
6. Plot stage-duration distributions and display source/recovered waveforms. Report individual ratings and sample counts before aggregates. Separate microphone, codec and RF impairments using the qualified local controls.

**Measurements:** Local stage durations, valid cross-node capture-start to playback-completion with uncertainty, matched RTT, transcript/listening ratings, listener/clip counts, truncation/clipping and artifact integrity.

**Expected results:** Recovered speech artifacts and physical playback are available for each claimed result. Stage timings retain clock validity and listening scores remain linked to clips, listeners and configurations.

**Acceptance criteria:** Correctness requires artifact identity/transport validity, observed physical playback and honest timing validity. No universal listening pass score is assumed. Poor intelligibility or high delay can be a valid measured finding; missing recovered audio makes that claim incomplete.

**Evidence collection:** Save source/recovered WAVs and encoded bytes, transcripts, rubric forms, listener IDs/order, stage timestamps, calibration links, waveforms and duration plots.

**Cleanup and recovery:** Stop capture/playback, retrieve all evidence and close sessions. Repeat affected observations after correcting missing audio or invalid timing; preserve excluded results.

<!-- page -->
# MODEL 01 Airtime and Delivery Model Validation

**Purpose and traceability:** MODEL-01; CDR 7.1. Verify frame/fragment accounting and compare predictions with independently observed radio and whole-message durations.

**Prerequisites:** Identified radio matching the model domain; applied modem settings and actual frame lengths; RF timing markers and logic analyzer/oscilloscope, or a documented software timing uncertainty. Independent numerical vectors.

**Configuration and repetitions:** Numerical vectors cover SF7/9/12, BW125/250/500 kHz, coding 4/5 and 4/8, supported LDRO and protected/unprotected frame lengths. Measure ten isolated frames per supported vector condition. Message cases use ten messages of 64, 160 and 1200 useful bytes, ACK disabled/enabled and one controlled retry. Run three repetitions in both directions.

## Numbered procedure

1. Freeze model_version sx126x_lora_v1, units, valid profile domain and independent calculation source [6]. Verify exact quarter-symbol arithmetic and final microsecond ceiling against the worksheet. The attached board must match the model's radio domain.
2. Derive actual body/40-byte-header/16-byte-tag lengths and final-fragment remainder. Count DATA, ACK, retry and injected frames separately. Do not use raw PCM size as encoded voice size.
3. Compute finite message predictions including all airtimes, ACK turnaround/waits, guard/pacing, processing, faults and drain. Save nominal prediction and expanded worst-case budget separately.
4. Compare isolated frame predictions with measured on-air markers where available. Compare tx_command-to-tx_done only with its additional command/ramp/ISR contributions recorded; it is not automatically exact airtime.
5. Execute message cases and compare predicted versus observed transfer and whole-transaction durations with identical timestamp definitions. For retries compare actual observed attempts and separately assess worst-case budget containment.
6. Plot predicted versus observed values and residuals by configuration/frame type. Declare numerical rounding tolerance and the instrument/software capture uncertainty before assessment; investigate systematic offsets rather than silently tuning constants.

**Measurements:** Actual header/body/tag/frame lengths, fragment/attempt counts, applied modem settings, predicted and observed airtimes/durations, timing uncertainty, residuals and worst-case budget containment.

**Expected results:** Independent numerical vectors agree and actual frame lengths match accounting. Observed durations agree within the declared measurement tolerance or produce a retained, explained model discrepancy.

**Acceptance criteria:** Golden-vector agreement is a correctness assertion. Hardware agreement uses predeclared timing uncertainty/tolerance. Whole-message predictions are exploratory where processing bounds are provisional. A disagreement blocks model-qualified previews until reconciled; retain the failed vector or case.

**Evidence collection:** Save equations/model revision, independent vector inputs/results, applied LDRO/settings, actual frame lengths, marker traces, attempts, residuals and budget comparisons.

**Cleanup and recovery:** Close sessions and preserve the model revision with exported figures. Resolve discrepancies and rerun failed vectors/cases before using model-qualified previews.

<!-- page -->
# OPS 01 Disconnect Reset and Recovery

**Purpose and traceability:** OPS-01; CDR section 6 risks and repeatable operation. Verify bounded behavior and preserved evidence during expected bench failures.

**Prerequisites:** Two qualified RF nodes with finite runs, lease expiry, bounded stop, boot IDs and health/error counters; host persistent storage/restart handling and labeled timeout/telemetry-gap fixtures.

**Configuration and repetitions:** C1 unplug either USB node mid-run; C2 reset either node; C3 host stop/restart while active and paused; C4 invalid configuration or controlled command timeout; C5 known telemetry gap/drop; C6 stable 60-minute physical observation; C7 100-case synthetic campaign. Repeat C1-C5 variants three times with active roles reversed. Run one 60-minute observation per direction and one 100-case fixture campaign in linked batches of at most 64 cases/30 minutes.

## Numbered procedure

1. Save baseline health, versions, placement, active run/session and its computed stop/deadline bounds. Start a finite known-data case long enough to inject the selected fault at a recorded point.
2. For C1 unplug only the selected USB path; for C2 use its documented reset control. Record host detection, boot/lease behavior and peer-stop request. Verify no new work after the applicable finite bound and no reuse of old session keys/calibration.
3. For C3 stop the host process during a run and while a campaign is paused. On restart require interrupted records and explicit new preflight; no automatic resumption or false completed/pass status.
4. For C4 require failed configuration to preserve prior settings and prevent arming. For C5 inject a known telemetry omission using a labeled host fixture, then require gap/drop indicators and dependent inconclusive metrics rather than artificial RF loss.
5. Reconnect using fresh claims/session and demonstrate a legitimate baseline. Verify source/queue/buffers return to the declared idle condition and original versus cleanup errors remain separate.
6. Execute C6 with actual 1 Hz physical health; add a declared representative traffic load for the declared loaded subcase. For C7 run physical campaign batches totaling 100 cases while exercising UI navigation, stop and export. Use the node requirements of each case; retain missing firmware/runner capabilities as blockers. Limit each batch to 64 cases and 30 minutes; preserve the 100-case total through linked batches.

**Measurements:** Fault/detection/stop/reconnect times, boot/session changes, initiating and cleanup errors, retained record counts, health gaps/drops, host/UI resource growth, recovery workload outcome and stability duration.

**Expected results:** Faults produce explicit bounded interruption, preserve partial records and invalidate old sessions/calibrations. Fresh preflight recovers operation; missing telemetry is visible and never silently converted into RF loss.

**Acceptance criteria:** Require bounded cessation, correct attribution/state, preserved partial data, visible evidence loss and successful fresh-session recovery. Stable operation must show bounded host/UI buffers and no unreported drops. Synthetic endurance cannot qualify physical RF/audio reliability.

**Evidence collection:** Save fault/operator timestamps, boot/run links, detection/stop/reconnect latencies, storage/restart logs, process/resource traces, counters and recovery controls.

**Cleanup and recovery:** Finalize every queued/active case, remove fault hooks and verify idle ownership. Reconnect through new claims/sessions and complete a valid baseline before resuming experiments.

<!-- page -->
# Timing Resource and Numerical Worksheet

Use these numerical checks during duration preflight and MODEL-01. They define reference arithmetic for the baseline profile; physical timing still requires instrumented measurements.

## Packet and audio accounting

| Quantity | Calculation | Result |
| --- | --- | --- |
| Three-second raw PCM | 8000 samples/s x 2 bytes/sample x 3 s | 48000 bytes |
| Protected useful maximum | 255 minus 40 header minus 16 tag | 199 bytes |
| Unprotected useful maximum | 255 minus 40 header | 215 bytes |
| Baseline raw fragments | ceil(48000/160) | 300 DATA fragments |
| Baseline encoded frames | 24000 samples / 160 samples per codec frame | 150 codec frames |
| Baseline encoded bytes | 150 frames x 8 bytes | 1200 bytes |
| Baseline encoded RF fragments | ceil(1200/160) | 8 DATA fragments |
| CDR illustrative 246-byte slice | 48000/246 = 195.121951; take ceiling | 196 fragments |

Use the full 40-byte protocol header and actual security overhead when calculating fragment capacity. For any slice size, divide the useful message length by useful slice capacity and take the ceiling. Fragment count alone does not determine allocation footprint.

## Airtime equation

For SF7 through SF12, explicit header, applied LDRO DE, radio CRC flag CRC and coding denominator CRden:

Tsym = 2^SF / BW seconds

Npayload = 8 + max(ceil((8*PL - 4*SF + 28 + 16*CRC) / (4*(SF - 2*DE))) * CRden, 0)

Tair_us = ceil((preamble + 4.25 + Npayload) * Tsym * 1000000)

PL includes all protocol header/body/tag bytes. CRden is 5 through 8, not the radio driver's index 1 through 4. Record applied DE; do not extrapolate to SF5/6 or a different modem. Formula cross-check: Semtech's SX126x reference calculation [6]. Codec frame dimensions: pinned source [7].

Golden inputs use BW125000, CRden5, preamble8, CRC1 and explicit header: PL120/SF7/DE0 = 199936 us; PL216/SF7/DE0 = 343296 us; PL216/SF12/DE1 = 7872512 us. Validate independently before model use.

At SF12, 100 protected 64-byte single-fragment messages already need more than the 120 second default. Record the expanded budget and selected duration. A finite message budget sums actual frame attempts, ACK activity/waits, processing and applicable guards; drain is at least max(2000000 us, ack_timeout_us + guard_us). Sustained-source observations keep their production window separate from drain.

<!-- page -->
# Run Record and Acceptance Worksheet

Copy one worksheet per required case, direction, configuration and repetition. Attach raw evidence by stable file/run identifiers; do not replace the record with screenshots alone.

## Identification and prerequisites

Case ID and revision ____________________  Parent campaign ____________________

Run ID ____________________  Session ID ____________________  Repetition ______

Operator and reviewer ____________________  Date and time ____________________

Direction ______  Provenance hardware or simulated ______  CDR requirement ______

Build purpose engineering or qualification __________________________________

Host build and analysis version ______________________________________________

Node A device and boot ____________________  Node B device and boot ___________

Firmware builds and manifests _______________________________________________

Schema profile artifact and model hashes ____________________________________

Placement antennas supply and instrument records ____________________________

Required capabilities observed ____________________  Missing prerequisites ______

## Planned condition and actual observations

Requested and applied settings references ___________________________________

Message count size source seed and expected hash _____________________________

Fragment security ACK retry fault and pacing settings ________________________

Predicted duration expanded budget and stop bound ___________________________

Timestamp windows calibration and uncertainty _______________________________

Expected observation and predeclared acceptance _____________________________

Actual observation metrics and sample counts ________________________________

Telemetry gaps drops or exclusions __________________________________________

## Assessment evidence and closure

Execution status ______  Assessment ______  Exploratory performance conclusion ______

Assertion result and evidence paths _________________________________________

Original failure ____________________  Cleanup failure ____________________

Artifact manifests export hashes and reviewer notes _________________________

Idle state buffer recovery and fresh control run ____________________________

Required follow-up and coverage ledger disposition __________________________

<!-- page -->
# Evidence Package and Recovery Checklist

## Required case record

Retain test ID, case/variant ID, procedure revision, prerequisite checks, operator, physical or fixture/simulated provenance, build purpose, host/firmware/analysis versions, board and boot IDs, schema/profile/model hashes, requested/applied settings, direction, repetition, source seed and artifact hashes. Link the run/session/campaign, timestamp phases, measurement interval, expected/actual observations, exclusions, execution status and assertion assessment.

Record every specified configuration and fault variant, including unsupported, failed and inconclusive conditions. Preserve the original result when a correction requires a linked rerun. A firmware or analysis change must identify which cases require requalification; previous passes do not transfer automatically.

## Evidence collection procedure

1. Save raw validated event records and node summaries before calculating final metrics. Retain event sequence numbers, drop counters, errors and boot/session/run identities. Record any missing intervals.
2. Retrieve source/recovered artifacts before session close or deletion. Verify lengths, chunk checksums where used and complete SHA-256 values. Save source, encoded and decoded artifacts under distinct identifiers.
3. Save requested and applied settings, hardware/firmware manifests, physical setup photographs, instrument traces, calibration data and fault application records. Keep non-secret identifiers; exclude keys and secret-bearing serial command bodies.
4. Recompute reported counts and metrics from raw records. Reconcile unique originals versus attempts, accepted fragments versus complete messages, and source versus delivered byte totals. Record analysis version and reason-coded exclusions.
5. Export case/campaign data, tables, figures and artifact manifests. Independently verify exported record counts and file hashes. Include every attempted condition and preserve links to interrupted or blocked cases.
6. Package the procedure revision, setup/wiring instructions, software/build identifiers, measured results, raw evidence references, known limitations and library/license citations required to reproduce the series.

## Cleanup and recovery procedure

1. Stop the source and prevent new work. Observe physical cessation within the saved stop bound; a serial acknowledgement alone is insufficient.
2. Remove all fault hooks, stop audio/pulse/capture operations and apply the declared drain or discard policy. Save partial artifacts, final queue state and both initiating and cleanup errors.
3. Close the session, invalidate keys and clock mappings as applicable, release buffers and verify idle memory/health against the predeclared recovery condition.
4. Release control and close ports when the bench is no longer in use. Reconnect with fresh boot/claim/session checks after a reset, disconnect or host restart.
5. Execute a small legitimate baseline before resuming a series. Retain failed evidence and label the recovery/rerun separately. Escalate an unresolved resource, identity or timing discrepancy by keeping the dependent case blocked or inconclusive.

## Acceptance of the evidence package

The package is complete when every specified ledger entry has an execution status, an evidence-supported assessment or blocking reason, valid integrity hashes and a recorded cleanup outcome. Unsupported measurements remain null with reasons. Performance findings retain their declared conditions, sample counts and uncertainty, including unfavorable results.

<!-- page -->
# References and Document Control

## Normative project references

[1] Rodriguez HA and Vazquez AK. LoRa Based Encryption and Communications Testbed Critical Design Review. October 12 2026. EN.525.743 Fall 2026. Requirements: sections 1.3 and 1.4; integration: 5.4; risk controls: 6; measurements and experiment matrix: 7.1 and 7.2. Source file: docs/secure_lora_comms_testbed_cdr.pdf.

[2] Host and node interface contract 2.0.0. Defines wire version 2, command/event semantics, binary framing, session keys, replay/retry behavior, audio, timing and metric definitions. Source file: docs/testbed_contract_v2.md.

[3] Baseline profile and public conformance examples. Sources: contracts/v2/default_profile.json and contracts/v2/conformance_vectors.json. Record exact file hashes with the test release. Public vector keys are diagnostic material and must not become operational session keys.

[4] CDR experiment catalog. Maps the 23 procedure IDs to the review requirements. Source file: docs/test_experiment_catalog.md. The procedure text provides operating conditions and acceptance requirements; the catalog provides traceability.

## Primary technical references

[5] LoRa Testbed campaign workflow. Source file: docs/campaigns.md. Defines campaign controls, run links, exports and bounded batch behavior.

[6] Semtech LoRaMac-node SX126x radio reference implementation. RadioGetLoRaTimeOnAirNumerator and RadioTimeOnAir. https://github.com/Lora-net/LoRaMac-node/blob/master/src/radio/sx126x/radio.c . Reference checked October 25 2026. Record the resolved source revision when qualifying the airtime model.

[7] David Rowe and contributors. Codec 2 release 1.2.0, src/codec2.c. codec2_bits_per_frame and codec2_samples_per_frame define the mode-3200 frame dimensions. https://github.com/drowe67/codec2/blob/1.2.0/src/codec2.c . Record the source commit, build options and applicable license when integrating.

## Revision and change control

Revision 2.0, October 26 2026. Standalone laboratory procedure edition covering all 23 tests under interface contract 2.0.0. Numbered operating steps, prerequisites, configurations/repetitions, measurements, expected outcomes, acceptance, evidence and recovery are specified for each test. This document defines procedures and does not certify any execution result.

Record changes by date, affected test/case IDs, rationale, settings, workload or measurement definition, source hashes and required requalification. Keep historical evidence under its original procedure and analysis revision. Changes to interface/schema, fault definition, timing window or metric require explicit versioned review and affected-case reruns.

Distribute the manual with the referenced contract/profile/vector files and a source-hash manifest. Detailed command encoding is governed by the matching interface contract.

Revision 2.1, November 1 2026: physical-only host decision; OPS-01 C7 now requires
physical campaign execution rather than simulation. The 100-case total is retained.
One-node local checks remain independent; two-node RF prerequisites are unchanged.
Old records retain their original revision and never establish current qualification.
