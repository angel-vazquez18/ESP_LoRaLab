# Testbed implementation checklist

Updated November 1, 2026. The user replaced simulation-first development with a
physical-only host. All 23 procedures in `test_procedures.md` remain required.
Old simulated procedure completion is historical and does not count as current
implementation or physical qualification. Simulator engines/runners were removed.

## Relationship to node development

The November 4 [node development plan](node_development_plan.md) orders firmware
work by reusable capabilities and end-to-end workflows. Use the experiments below
to check coverage and complete qualification; do not create one firmware engine
per experiment. All 23 procedures and their evidence requirements remain intact.

## Current shared support

- [x] macOS dashboard, CLI, persistent appearance and one local backend.
- [x] Independent physical A/B connections, diagnostic identity/schema checks,
  ownership, health, memory and reset detection.
- [x] One-node defaults for local checks, pair requirements for RF tests, explicit
  local/RF requirements for MEM-01 and OPS-01, duplicate-device rejection.
- [x] Bounded physical diagnostic check with command/reply evidence, cancellation,
  source/profile hashes, durable results and hashed exports. This is partial IF-01.
- [x] Reference WAV ingestion, inspection and browser playback.
- [x] Numerical airtime/fragment/retry budgets, payload/hash utilities and public vectors.
- [x] All 23 catalog entries and historical evidence readers/exports.
- [ ] Full physical execution adapter/lifecycle: configure/readback, prepare, arm
  receiver first, start, collect/drain, summary/artifacts, stop and cleanup.
- [ ] Physical campaigns, repetition, pause/resume and rerun workflows. Derive
  required nodes/capabilities from selected cases; local-only campaigns need one.
- [ ] Full physical procedure ledgers with independent assertions and repeated
  evidence. Unit-test serial peers and partial checks never close qualification.

## Individual experiment implementation

Implement each procedure against actual physical capabilities. One-node procedures
can be executed on A or B separately; later repetition on the other device is a
coverage obligation, not a simultaneous two-node prerequisite. Keep unavailable
firmware, equipment and runner features explicitly blocked.

### 1 IF-01 Serial interface validation

The shared [integration runner](integration_matrices.md) implements the
main-control USB checks. One selected role can run the matrix. The
stale-boot case uses a recorded boot transition on the same device.

- [x] Implement the USB framing, invalid-argument, compatibility, reply fault,
  exact retry, conflict, stale-boot, ownership and lease cases in the shared runner.
- [x] Add expected-error, side-effect, resynchronization and health recovery assertions.
- [x] Build the selectable UART endpoint and bind serial cases to the announced transport.
- [ ] Collect complete physical C1–C6 evidence per required node and transport,
  including the reset and reconnect sequences.

### 2 IF-02 Verified known-data exchange

The shared radio runner and IF-02 matrix support finite known-data exchange
with independent source and recovered readback and controlled peer mismatch.

- [x] Implement radio settings verification, bounded receive/transmit, timestamped
  evidence, reconciliation and independent content verification.
- [ ] Execute the complete 1/64/159/160-byte matrix, negative controls and physical
  repetitions on two nodes with verified cleanup.

### 3 IF-03 Automated campaign and persistence

The shared campaign runner preserves plan identities, child evidence and restart checkpoints.

- [ ] Implement immutable case plans, applied-setting checks, finite budgets,
  receiver-first ordering, fresh sessions and per-case node/capability preflight.
- [ ] Add pause/resume, cancel, failed configuration, refresh, host restart,
  selected rerun, ownership and export-integrity checks through the physical adapter.
- [ ] Execute every procedure configuration/repetition, including active/paused
  interruption; preserve blocked, failed, interrupted and skipped evidence.

### 4 RF-01 Spreading factor sweep

- [ ] Expose supported SF values and applied SF/LDRO on both radios.
- [ ] Add seeded SF7–12 case generation, matched controls, repetition/direction
  handling and plots of delivery, goodput, airtime and received signal.
- [ ] Execute every supported condition with baseline controls and correct
  content; retain unsupported settings as blocked and poor outcomes as results.

### 5 RF-02 Bandwidth sweep

- [ ] Expose applied bandwidth and LDRO with exact units and supported limits.
- [ ] Implement matched 125/250/500 kHz sweeps, duration budgets and comparison
  plots while holding the other factors fixed.
- [ ] Execute both directions and repetitions, including baseline drift checks.

### 6 RF-03 Coding rate sweep

- [ ] Implement and verify denominator-based coding-rate configuration/readback.
- [ ] Add 4/5, 4/6, 4/7 and 4/8 sweeps, content assertions and delivery/goodput/
  duration comparisons with unchanged workload and security.
- [ ] Execute supported conditions in both directions with the required repeats.

### 7 RF-04 Transmit power sweep

- [ ] Implement verified board/front-end power controls and applied readback.
- [ ] Add supported 2/5/8/11/14/17/20 dBm cases, fixed receiver conditions,
  saturation annotations and signal/delivery/goodput plots.
- [ ] Execute both transmitting roles and repetitions without treating a driver
  setting as calibrated radiated power.

### 8 SEC-01 Protected and unprotected comparison

- [ ] Implement on-node AES-128-GCM, nonce/session lifecycle, fresh RAM-only keys,
  authenticated receive processing and secret-free host provisioning/logging.
- [ ] Add matched none/GCM runners, independent public-vector/content checks,
  actual overhead measurements, wrong-key rejection and profile-mismatch controls.
- [ ] Execute single-fragment cases, then the 321-byte case after reassembly is
  available; include both directions, repeats and legitimate recovery controls.

### 9 SEC-02 Altered protected packet rejection

- [ ] Implement observable post-protection ciphertext/tag mutation with the radio
  computing a valid physical CRC over the altered bytes.
- [ ] Add targeted injection, before/after controls and receiver-stage assertions:
  observed authentication rejection and zero altered application delivery.
- [ ] Execute both mutation variants/directions/repetitions. Mark an unobserved
  stimulus inconclusive; do not substitute RF CRC rejection as proof.

### 10 SEC-03 Replay rejection

- [ ] Implement exact protected-frame retention/replay, replay-window rejection,
  application counters and observable fault triggering after first delivery.
- [ ] Add immediate same-session and out-of-window replay cases, exact-frame
  digest checks, unchanged-delivery assertions and a later legitimate control.
- [ ] Execute both directions and repetitions with ACK disabled and fresh sessions.

### 11 SEC-04 Cryptographic processing overhead

- [ ] Add node-local timed encryption/decryption diagnostics with public vectors,
  documented timer resolution and CPU/acceleration/build settings.
- [ ] Implement first-call, 50 warm-up and 1000 timed-operation batches at
  16/64/160/199 bytes; separate copy baseline and invalid-tag timings.
- [ ] Execute three repetitions on each node and export raw timings, sample
  validity and distributions. This test can use one node at a time.

### 12 PKT-01 Message size and reconstruction

- [ ] Implement bounded fragmentation/reassembly, exact final-fragment sizing,
  independent complete-message hashes, missing results and buffer cleanup.
- [ ] Add boundary/large/negotiated-limit cases, oversized-request rejection,
  complete-message and no-partial/no-duplicate-delivery assertions.
- [ ] Execute unprotected cases and protected cases after SEC-01 qualification,
  with both directions/repetitions and recovery controls.

### 13 PKT-02 Fragment loss duplication and ordering

- [ ] Add observable pre-reassembly drop, exact duplicate and reorder hooks,
  bounded deadlines and complete missing-index reports.
- [ ] Implement 16/64/160/199-byte fragment cases with intact, missing, duplicate
  and reversed-block stimuli; verify exact reconstruction or bounded failure.
- [ ] Execute all direction/repetition variants and verify buffer recovery.

### 14 PKT-03 Acknowledgment and retry behavior

- [ ] Implement stop-and-wait, validated ACK references, bounded exact-byte
  retries, duplicate re-ACK/cache behavior and observable ACK suppression.
- [ ] Add no-ACK and zero/one/two-retry policies under matched DATA/ACK loss;
  reconcile originals versus attempts and enforce 1 + max_retries.
- [ ] Execute delivery, ACK-loss, exhaustion and recovery cases in both directions.

### 15 TIME-01 Round-trip delay

- [ ] Implement verified echo requests/replies with sender-local timestamp phases,
  request references, fresh reply sequences and finite timeouts.
- [ ] Add content/identity matching, missing/late/invalid-reply handling and RTT
  distributions for 16/64/160-byte workloads and matched profiles.
- [ ] Execute both directions/repetitions. Keep timeouts distinct from zero RTT;
  no cross-node clock synchronization is required for this test.

### 16 TIME-02 Calibrated one-way delay

- [ ] Assemble verified 3.3 V shared-pulse/common-ground wiring and instrument
  markers; implement pulse generation and physical capture on both nodes.
- [ ] Implement 32-edge fits at 10 Hz, measured capture/skew bounds, live updates,
  uncertainty <=1000 us and two-second expiry/reset/missed-edge invalidation.
- [ ] Add RF timing cases and invalid-calibration assertions; execute both
  directions/repetitions with saved instrument traces and uncertainty.

### 17 MEM-01 Stage and buffer memory behavior

Existing support: finite typed 10 Hz/stage memory observations, named requested
buffers and observed lifetimes (#73), plus durable collection and independent
sample/stage assessment (#82). Imported and physical-readback evidence remain
distinct; missing observations are inconclusive and true peaks unavailable.
Full procedure cases, recovery criteria, plots and physical acceptance below
remain open; see [assessment scope](workload_assessments.md).

- [ ] Add named buffer allocations/lifetimes, stage entry/exit observations and
  10 Hz internal/PSRAM samples during RF, codec, artifacts and audio workloads.
- [ ] Implement size/oversize/cancel/failure cases, predeclared recovery bands,
  allocation-failure assertions and memory/buffer timeline plots.
- [ ] Execute supported subcases on each node; keep audio cases open until their
  hardware exists and distinguish observed run minima from boot minima.

### 18 VOICE-01 Local capture codec and playback

Existing support: host WAV references/browser playback, bounded artifact transfer
with independent CRC/SHA verification, finite local node PCM capture/playback,
verified unchanged-sample WAV retrieval, waveform/silence/clipping inspection and
shared API/CLI/UI controls. Native/software and actual DMA/count/hash checks pass;
physical microphone response remains unverified because both raw slots return
zero. Heard output, printed revision, instruments and full #21 recovery remain
open. Codec 2 and the complete VOICE-01 procedure runner are not implemented.
See [single-node qualification](milestone_2_audio_review.md). The combined
procedure items below stay unchecked until all their requirements are fulfilled.

- [ ] Verify I2S wiring and implement bounded capture/playback, Codec 2 mode 3200
  and chunked artifact transfer/storage with CRC-32 and complete SHA-256 checks.
- [ ] Add 24000-sample capture, raw playback, encode/decode/playback, fixed
  references and invalid/incomplete/corrupt-artifact/cancel controls.
- [ ] Execute three utterances/references with three repetitions on each node;
  retain physical speaker observations and source/encoded/decoded artifacts.

### 19 VOICE-02 Voice RF transfer and data comparison

- [ ] Connect qualified node audio/codec/artifact operations to authenticated RF
  transport and complete-message reassembly before receiver playback.
- [ ] Add three-second reference and microphone cases, end-to-end encoded hashes
  and matched equal-useful-byte/standard-data comparisons with stage measurements.
- [ ] Execute both directions/repetitions with physical playback and recovered
  artifacts. Delayed clip delivery does not establish sustained voice.

### 20 VOICE-03 Sustained encoded-source feasibility

Existing support: reserved fixed-rate source, bounded whole-message queue,
protected multi-message execution and paged actual-time/audit evidence (#74).
Host assessment/readback (#82) reconciles startup/[3,60)/drain cohorts and optional
independent receiver archive bytes, with explicit gaps and clock limits. The full
parent procedure runner (#105), plots and declared physical repetitions below
remain separate. See [source assessments](workload_assessments.md).

- [ ] Implement a fixed 8-byte/20 ms producer, 1200-byte messages and bounded
  4800-byte source queue with occupancy/drop/underflow telemetry.
- [ ] Add 60-second runs, separate startup/assessment/drain windows, 5 Hz queue
  observations and verified production-versus-delivery/backlog analysis.
- [ ] Execute declared profiles/directions/repetitions without slowing the source
  to hide an inadequate link. Preserve valid infeasibility findings.

### 21 VOICE-04 Voice delay and intelligibility

- [ ] Add complete capture/codec/queue/RF/reassembly/playback stage timestamps,
  recovered audio and calibration links for cross-node timing.
- [ ] Implement paired waveforms, stage-duration plots, randomized listening
  records and the five-point intelligibility rubric with listener/clip IDs.
- [ ] Execute three clips/repetitions/both directions. Report local durations
  separately; calibrated one-way claims require valid TIME-02 evidence.

### 22 MODEL-01 Airtime and delivery model validation

Existing support: exact numerical airtime/fragment/retry calculations and
independent software vectors.

- [ ] Add actual applied modem/length records and radio markers or a documented
  software timing bound; link independent instrument observations to runs.
- [ ] Implement frame/message prediction comparisons, residual plots, predeclared
  tolerances, observed retry accounting and worst-case budget assertions.
- [ ] Execute baseline unprotected measurements first, then protected/retry
  variants as their features become available. Numerical agreement alone does
  not complete hardware qualification.

### 23 OPS-01 Disconnect reset and recovery

Existing support: diagnostic reset detection and bounded diagnostic cancellation.

- [ ] Implement RF/audio stop, lease/watchdog cleanup, fresh-session reconnect,
  durable host restart handling and explicit evidence-gap reporting.
- [ ] Add USB unplug, either-node reset, host restart, configuration failure,
  timeout and telemetry-gap cases; collect fault/detection/stop/recovery times.
- [ ] Execute fault repetitions, 60-minute physical stability observations and
  the linked 100-case fixture campaign, preserving their different provenance.

## Completion work for every experiment

- [ ] Implement validated settings, complete case generation and procedure repetitions.
- [ ] Add UI/CLI controls and per-case equipment, node-count and capability blockers.
- [ ] Add required observations/charts and independent expected-result assertions.
- [ ] Preserve raw evidence, settings, build/procedure/analysis versions, errors,
  exclusions, separate execution/assessment, source bytes and hashed exports.
- [ ] Verify bounded stop, cleanup and recovery after negative cases.
- [ ] Execute the full required physical ledger on designated firmware; retain old
  simulated, development/reference and physical qualification provenance separately.

Next: implement main-node board identity/health and bounded diagnostic control,
then the physical RF execution adapter and IF-02 lifecycle. Dedicated test matrices
remain open until their full physical evidence supports completion.
