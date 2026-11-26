# Remaining milestone implementation batch

## User direction

Continue software development through the remaining milestones. Group work by
reviewable outcome, with small descriptive Conventional Commits and linked issues
for coverage. Stack dependent PRs and continue without waiting for individual
reviews. The user will review and merge. Hardware qualification is deferred.
A separately connected audio node was exercised at the user’s request using its
existing image; its RF profile is still unconfirmed and it was not flashed. Preserve the original checkout's
19 existing changes and their ignored snapshot under `local/milestone-batch`.

## Checkouts and dependencies

Implementation checkout: `~/Documents/ESP_LoRaLab-milestones`, an independent
clone. Its initial base is `feat/local-audio-inspector` (PR #160), not the pending
physical-audio qualification PR #161. Stack each implementation PR on its actual
software prerequisite and record the base explicitly. Do not close hardware
qualification issues from software fixtures. The current board revision is
unconfirmed; V4.3 R2 GPIO5 conflicts with the previous audio plan.

## Remaining software batches

1. **Lab controls and evidence.** Finish #76, then group fragment/ACK fault cases
   with host reconciliation and operator views. Make missing observations
   explicit and require an intact control for recovery assertions.
2. **Shared procedure runner.** Use the existing physical services and campaign
   ownership for typed case plans, capability preflight, child links, assertions,
   cancellation/restart, immutable evidence and exports. Prove the shared path
   with IF-01, IF-02 and IF-03. Gate operations by the actual device capabilities.
3. **Experiment suites.** Add RF sweeps, packet/security, timing, memory/voice,
   model and recovery matrices by family. Reuse cases and analysis where the
   procedures call for the same run. Keep all 23 procedure IDs accounted for.
   One-way time processing uses saved pulse evidence and remains unavailable
   without valid calibration; board pin selection and loaded timing stay deferred.
4. **Release verification.** Build the standard and lab images, verify the full
   host suite, exercise the dashboard and CLI against isolated fixtures, check
   all 23 coverage/evidence paths and document repeatable setup and review.
   Software completion advances those issue cards to Testing; hardware signoff
   remains in the separate validation ledger.

## Prior capability sequence

- M3: #3 contract, #12 driver initialization, #15 modem settings, #19 finite TX,
  #20 finite RX, #25 frame acceptance, #27 host runs, #34 dashboard, #39 physical
  enrollment/qualification.
- M4: #28 fragmentation, #35 reconstruction, #40 acknowledgments, #43 retries,
  #47 host multi-fragment runs, #51 physical qualification.
- M5: #44 key/session contract, #48 GCM, #52 key/nonce lifecycle, #53 local crypto
  measurement, #60 replay, #63 host keys, #67 physical qualification.
- M6: #29 Codec 2 dependency, #36 encode, #41 decode, #45 provenance, #64 protected
  voice, #68 host workflow, #72 dashboard, #80 physical qualification.
- M7/M8: follow live GitHub dependency links for controls, buffers, campaigns,
  timing and all 23 CDR procedure matrices. Keep implemented software and physical
  qualification distinct; no operator simulator or passing placeholder evidence.

## Progress

- #3: execution capability gate, shared lifecycle examples and generated firmware
  fingerprint complete; 366 tests and full `make check` passed. Hardware execution is not advertised yet.

- #3: PR #162 (`docs/radio-execution-contract` → `feat/local-audio-inspector`).
- #12: portable/ESP-IDF initialization, explicit revision references, native
  failure/recovery coverage, default and selected-board builds. Physical #1 remains
  a qualification prerequisite; no board revision has been inferred.

- #12: PR #163 (`feat/sx1262-init` → `docs/radio-execution-contract`).
- #15: strict real `config.set`, status/readback record, atomic rejection, no
  hardware effect before reply reservation and host fresh-health gating. Full
  checks and IDF build passed; physical parameter verification is pending.

- #15: PR #164 (`feat/radio-modem-settings` → `feat/sx1262-init`).
- #19: finite transmit driver and native fault/recovery cases complete; operator
  run commands remain unadvertised until RX/message integration.

- #19: PR #165 (`feat/finite-radio-tx` → `feat/radio-modem-settings`).
- #20: finite RX, signal/CRC attribution, queue-pressure/timeout/cancel and
  reinitialization-after-SPI-fault checks. Next #25 header/content acceptance.

- #20: PR #166 (`feat/finite-radio-rx` → `feat/finite-radio-tx`).
- #25: explicit frame vectors, deterministic source, once-only verification and
  finite one-message node execution implemented. Radio limits deliberately remain
  one message/fragment, <=215 bytes, <=30 s until later transport work. Next #27
  serial-backed receiver-first host workflow, then #34 dashboard.

- #25: PR #167 (`feat/single-fragment-data` → `feat/finite-radio-rx`), 408 checks
  and IDF build passed. One-message node lifecycle now implemented; source/recovered
  artifacts are verified. Original 19 file hashes still match.
- #27: receiver-first host/API/CLI, independent exact readback, bounded snapshots/
  traces/hashed export and cancel/restart/disconnect recovery complete. 424 checks
  passed. A deterministic test fixed stop cancelling a worker already in cleanup;
  caller cancellation is shielded. Next #34 dashboard, then M4 #28/#35/#40/#43/#47.

- #27: PR #168 (`feat/physical-radio-runs` → `feat/single-fragment-data`).
- #34: shared radio dashboard, server readiness and actual evidence inspection;
  browser verification covered both directions, incomplete telemetry with verified
  bytes, stop, shared ownership, missing peer and light/mobile layout. No boards
  were connected. Next #28 fragmentation; physical #39 stays pending.

- #34: PR #169 (`feat/radio-link-dashboard` → `feat/physical-radio-runs`),
  424 checks and browser acceptance passed; original checkout untouched.
- #28: allocation-free 65,536-byte/4,096-fragment planning and exact unprotected
  encoding, sequence-range preflight and protected tag reservation implemented.
  Execution remains single-fragment until receiver/scheduler integration.

- #28: PR #170 (`feat/bounded-message-fragments` → `feat/radio-link-dashboard`),
  435 checks and selected-board ESP-IDF build passed.
- #35: bounded reconstruction, missing indexes, once-only hash verification and
  cleanup/recovery implemented; 12 new public-API cases pass. Canonical parser is
  used by current single-frame execution. Reliability scheduling follows.

- #35: PR #171 (`feat/bounded-message-reassembly` →
  `feat/bounded-message-fragments`), 447 checks and selected-board build passed.
- #40: exact referenced ACKs, bounded receiver turnaround/cache and explicit
  retry-versus-replay classification implemented. Combined reconstruction checks
  require fresh re-ACKs with one application delivery. #43 adds sender policy.

- #40: PR #172 (`feat/referenced-radio-acks` →
  `feat/bounded-message-reassembly`), 452 checks and selected-board build passed.
- #43: real-radio-backed immutable frame sender, airtime-aware zero/one/two
  retries, exact ACK completion, high-water/cancel/observation cleanup implemented;
  19 focused cases pass. Next #47 integrates these packet modules into node
  execution and host multi-fragment runs; physical #51 remains pending.

- #43: PR #173 (`feat/bounded-stop-and-wait` → `feat/referenced-radio-acks`).
- #47: multi-fragment node/host/UI integration and independent accounting are
  implemented. Full checks passed 501 cases, selected-board IDF build and desktop/mobile
  browser acceptance. Documentation is ready for the issue’s PR. Physical #51 remains
  pending. Next is M5 #44. Audio follow-up found acceptable tone output but faint/
  distorted processed speech and an internal contiguous-allocation limit; raw
  recordings remain private, and full audio qualification is not closed.

- #47: PR #174 (`feat/multi-fragment-radio-runs` →
  `feat/bounded-stop-and-wait`) is ready for review with five implementation/docs
  commits, 501 checks and selected-board build/browser evidence. No merge.
- Next: #44 specifies session-key provisioning/redaction and protected retry/
  replay boundaries; current operator runs remain unprotected until implementation
  and compatibility work is complete.

- #44: documented key provisioning/redaction/nonce and retry/replay boundaries,
  added public protected vectors with independent checks, and fixed input-bearing
  session rejection errors (red/green native-session regression). Full checks
  passed 511 cases. Protected operator sessions remain gated. Next #48 uses
  the public PSA API in the pinned IDF Mbed TLS/TF-PSA-Crypto sources.

- #44: PR #175 (`docs/session-key-contract` →
  `feat/multi-fragment-radio-runs`) is ready for review, 511 checks, no merge.
  Starting #48 against the public PSA interface in the pinned IDF crypto tree.

- #48: bounded PSA frame-cipher API and target build implemented; actual pinned
  native crypto passed 10 focused conformance/failure/cleanup cases. Full suite
  passed 521 cases; final lint/frontend/contracts/repository stages and IDF build
  passed. No hardware access. Protected session support remains gated; next #52
  owns fresh keys, nonce sequences and close/lease/reset invalidation.

- #48: PR #176 (`feat/authenticated-radio-frames` →
  `docs/session-key-contract`) is ready for review. No merge. Next #52 binds
  private keys and nonce counters to session/ownership lifetime.

- #52: private source key/nonce owner, owned firmware setup, retirement/readiness,
  secret setup-cache invalidation and secure JSON/raw-input cleanup implemented.
  Final checks passed 539 cases and selected-board IDF build; no flash. Protected
  RF/host provisioning stay blocked pending #60/#63. Next #53 is a local public-
  vector crypto measurement; full physical acceptance remains #67.

- #52: PR #178 (`feat/ephemeral-session-keys` →
  `feat/authenticated-radio-frames`) is ready for review, 539 passing checks
  and the selected-board build. No merge or flash. Starting #53 for checked,
  bounded node-local crypto measurements independent of serial/RF time.

- #53: checked public-vector local benchmark and shared API/CLI evidence retrieval
  implemented; four sizes and separate first/warm-up/timed counts pass through the
  real PSA/C serial seam. Cancellation/missing evidence never produces a valid
  distribution. Selected-board IDF build passed (0x641a0 bytes, 61% app free);
  final full checks passed 556 cases without skips, lint/frontend/contracts/repository checks. Physical batches and
  acceleration/target resource qualification remain pending. Next #60 is replay
  acceptance and authenticated duplicate re-ACK.

- #53: PR #179 (`feat/local-crypto-benchmark` →
  `feat/ephemeral-session-keys`) is ready for review, 556 checks and IDF build
  passed. No merge or physical timing claim. Starting #60 replay integration.

- #60: authenticated 128-frame receive window, commit-after-insertion, bounded
  exact-DATA retry cache, protected reassembly and fresh referenced ACKs integrated
  into actual node transport. Six focused public-oracle/C-node cases include a
  two-node lost-ACK recovery with one delivery and exact readback. Final full
  checks passed 562 cases without skips and selected-board IDF build (0x65390,
  60% app free). Host protection remains gated until #63; physical #67 pending.

- #60: PR #180 (`feat/authenticated-replay-window` →
  `feat/local-crypto-benchmark`) is ready for review, 562 checks and final IDF
  build passed. No merge or physical RF claim. Starting #63's private host key
  owner, allowlisted setup traces and persistence guards.

- #63 in progress: fresh private host source pairs, allowlisted setup callbacks,
  independent metadata/trace/export/API guards, protected GUI/CLI runs and
  observed-stage assessment implemented. Source/role/run freshness and actual
  disk/export scans pass; host mismatch, wrong-key RF arrival, uncertain setup,
  cancel/disconnect/fresh reconnect are covered. A real completed-drain clock
  race was reproduced (one of nine crossings), fixed without wider deadlines,
  and locked down alongside an unfinished-ACK failure case. Explicit accepted
  ACK events change execution SHA to 3e3073993d76a7133d3ef594d2147967936c1bdb6c4a770aebe9d5444f48e6a1.
  Thirty-one focused cases and the IDF build (0x65480, 60% app free) passed.
  Final `make check` passed 587 cases without skips plus lint/frontend/contracts/
  repository checks. Isolated browser acceptance verified both protected directions,
  exact bytes, authenticated fragments/ACKs, idle cleanup and mobile width 390.
  Repeated immutable schema generation was profiled and fixed without caching
  live state. No physical port or flash; physical #67 remains pending.

- #63: PR #181 (`feat/private-host-sessions` →
  `feat/authenticated-replay-window`) is ready for review with scoped Conventional
  Commits, 587 checks, IDF build and isolated desktop/mobile browser evidence.
  Issue status is Testing; no merge. Original checkout's 19 saved files still
  match their hashes. User reports both nodes wired/connected; USB inventory
  currently exposes only `esp-f85b1ba27744`. Physical backend is stopped; neither
  port has been opened or flashed. Printed PCB revisions remain unobserved.
  Next: M6 #29, pinned Codec 2 mode 3200 dependency/provenance.

- #29 implemented: pinned official Codec 2 1.2.0 subset, reproducible retained
  codebook/resources/notices, actual frame queries and metadata with codec commands
  still unavailable. Allocator probing reproduced an upstream 4480-byte partial-
  construction leak; the recorded local cleanup patch passes all eleven actual
  failure positions and a following fresh query. Final `make check`: 603 cases,
  no skips, lint/frontend/contracts/repository/resource hashes pass. Focused codec/
  control: 93. IDF: 0x6c950, 58% app free, +29,904 bytes over #63; no flash.
  Physical backend restored at8000 and B identified on14601 (boot101, original
  local-audio build a5ecf08a…); A not enumerated, PCB revision still unknown.
  Preparing this issue's scoped commits/PR before M6 #36.

- #29: PR #182 (`chore/codec2-mode3200` → `feat/private-host-sessions`)
  is ready for review with four scoped commits, 603 passing checks and the selected-
  board build. Issue status is Testing; no merge. Starting #36 for finite committed-
  PCM encoding, fresh state and a separate immutable encoded artifact.

- #29 follow-up while starting #36: exact target stack reports exposed an 8272-byte
  constructor frame, larger than the old 8192-byte task. Added 32 KiB defaults and
  a codec-enabled build guard. Actual old-profile build fails; explicit 32 KiB V4.2
  rebuild passes (same 0x6c950 image). Native 16 cases/contracts pass. Required
  full-flash backup failed twice after 12,288 streamed bytes; no flash. B is back
  on 8000 at boot104 with unchanged original audio image. Earlier temporary binary
  is marked superseded. #36 WIP is saved in a named stash while this parent fix
  is published, then will be reapplied on the corrected base.

- #29 bounded-report follow-up: reproduced a configured audio+RF missing health
  reply directly in C. Constant enrollment metadata now stays in hello; current
  profiles/flags/settings/errors/measurements remain in health. Focused 94 and full
  604 cases pass, plus selected 32 KiB IDF build (0x6c970, 58% app free). Existing
  schema identities/4096-byte limit remain unchanged. Publishing the parent fix
  before reapplying the saved #36 implementation. No flash.

- #36 implemented on corrected #29 base 406122e: bounded fresh-state encoding,
  private derived output/hash publication, original/padded frame counts and stage
  timing. Exact full/partial output matches a separate public-library reference;
  cancel/lease/disconnect/deadline, allocation, final-hash and 100 acceptance-failure
  positions recover cleanly. Compact current codec profile preserves bounded
  configured health. Full 625 checks and focused 141 pass without skips; selected
  V4.2/32 KiB build 0x6d870, 57% app free. Artifact SHA 2f630… and codec SHA 618c75…;
  other wire fingerprints unchanged. All #36 work restored from named stashes;
  conflict resolved preserving parent bounds and child encoding. Preparing scoped
  commits/PR; next #41. Physical B remains original a5ecf08a… at boot 104 on 8000;
  full backup failed twice at 12288 bytes, no flash; A/PCB revisions still pending.

- #36: PR #183 (`feat/finite-pcm-encoding` → `chore/codec2-mode3200`)
  is ready for review with five scoped implementation/docs commits, 625 full checks,
  141 focused cases and the 32 KiB selected-board build. Status Testing; no merge
  or flash. Original 19 saved files still match. The two temporary WIP stashes
  are retired after all source is committed/pushed. Next M6 #41: complete-artifact
  decoding with fresh state, bounded PCM output, errors/resources and cleanup.

- #41 implemented: complete encoded artifacts decode into separate trimmed PCM,
  one frame per step, with retained errors/counts/timing and before/ready/after
  platform heap snapshots. A minimized public-library repro exposed the upstream
  static phase PRNG; a recorded reproducible patch makes it context-owned.
  Repeated/interleaved fresh decoders agree; all eleven constructor failures,
  worker/output/hash failures and interruption paths recover. Focused 152/full
  662 cases and selected 32 KiB IDF build 0x6def0 (57% app free) are the release
  checks. No flash; B remains original audio, A not enumerated, backup/PCB
  observation pending. Preparing PR on #183 before #45's API/CLI provenance.

- #41: PR #186 (`feat/finite-codec-decoding` → `feat/finite-pcm-encoding`)
  is ready for review with scoped Conventional Commits, 152 focused/662 full
  checks and the selected-board build. Status Testing; no merge or flash. Original
  19 files remain unchanged. Next #45 preserves three-file local codec provenance
  through the existing shared audio service, API and CLI.

- #45 implemented: shared local audio owner/API/CLI now preserve three distinct
  independently retrieved files, node stage results/timings, partial failures and
  verified playback/source references. Same-boot artifact-ID reuse cannot link
  changed capture/playback contents. Codec child results preserve existing audio
  client compatibility. Thirteen new plus 25 existing audio cases are included in
  the passing 675-case full check; lint/frontend/contracts/repository/dependency
  checks pass, no skips. Host-only change; no firmware build/flash. Original 19
  saved files still match. Preparing PR on #186; next #64 protected encoded bytes
  through the common message path, then #68 host voice and #72 UI.

- #45: PR #187 (`feat/local-codec-provenance` → `feat/finite-codec-decoding`)
  is ready for review with five scoped commits and 675 full passing checks, no
  skips. Issue Testing, no merge or flash. Starting #64 on the dependent branch
  for committed encoded bytes through authenticated reconstruction and guarded
  decode/playback. Local job API/CLI reading/test instructions are in
  `docs/codec_provenance.md`.

- #64 implemented: committed encoded bytes use the common protected message path,
  source borrowing and private recovered codec publication. Eight default DATA
  fragments preserve the exact 1200-byte source; lost-ACK retry works in both
  directions with one delivery. Missing/tag/hash failures suppress publication;
  transfer/decode/play stops release resources and following work succeeds. New
  typed source geometry/required length matches C admission. Nineteen dedicated
  and 694 full cases pass, no skips, plus all shared checks; selected 32 KiB IDF
  build 0x6e520, 57% app free. Execution SHA b029707…; other wire schemas unchanged.
  No flash/physical claim; original 19 files unchanged. Preparing PR on #187,
  then #68 common host secure voice and matched byte/workload comparisons.

- #64: PR #188 (`feat/protected-voice-content` → `feat/local-codec-provenance`)
  is ready for review with five scoped commits, 19 dedicated/694 full passing
  cases and selected-board IDF build 0x6e520, no skips. Issue Testing; no merge or
  flash. Starting #68 on its own dependent branch: common host voice orchestration,
  fresh protected sessions and labelled equal-encoded-size versus standard64 data
  comparisons, with retrieval outside the RF window.

- #68 implemented: reference/microphone workflows compose shared codec, protected
  radio, explicit receiver decode/play and two labelled known-data comparisons.
  Readbacks follow the observed RF window; child owners release before advancing;
  terminal outcomes follow cleanup. Only newly job-owned node files retire after
  host retention. Cancelled stop callers preserve bench ownership. Twelve dedicated
  cases cover both directions/sources, failures/cancellation, API/CLI files,
  listening and active shutdown without resume. Full 706 cases and shared checks
  pass without skips. Host-only, no wire/build/flash change; #64 target prerequisite
  remains 0x6e520. Original 19 files match saved hashes. Preparing PR on #188; next
  #72 voice-stage UI. Physical voice qualification remains #80.

- #68: PR #189 (`feat/secure-voice-workflows` → `feat/protected-voice-content`)
  is ready for review with seven scoped implementation/test/docs commits and 706
  full passing cases, no skips. Status Testing, no merge/flash. Starting #72 on
  its own dependent branch for shared controls, clip inspection, clock labels,
  integrity, listening and accurate incomplete states.

- #72 implemented: shared reference/microphone controls, linked verified four-file
  inspection/waveforms, local clocks, explicit unavailable one-way latency and
  persistent clip/listening identity. Three public API cases cover successful,
  corrupted, cancelled and incomplete files. Full 709 checks passed; final
  file-identity/duration presentation passes the focused cases and UI build. Browser native fixtures passed
  reference A→B/comparisons, microphone B→A, loss/stop, navigation/refresh/notes,
  both themes and 390 px width with no overflow or console warnings/errors.
  Screenshot saved in the session visualization directory. No physical ports,
  firmware build, flash or qualification. Next #30 PTT remains hardware gated by
  unobserved PCB/wiring; implement/test the explicit opt-in portable input path.

- #72: PR #192 (`feat/voice-stage-dashboard` → `feat/secure-voice-workflows`)
  is ready for review with four scoped implementation/test/docs commits and 709
  full passing cases, no skips, plus final focused/build/format checks. Status
  Testing; no merge/flash. Browser proof is
  `secure-voice-dashboard-software-fixture.jpg` in the session visualization root.
  Starting #30 on its own dependent branch; input remains opt-in and unqualified
  until PCB/GPIO47 wiring acceptance.

- #30 implemented: optional portable 50 ms release/press gate and opt-in GPIO47
  input, one host-selected finite capture using existing operation/artifact/audio
  cleanup. No implicit RF or resume; disabled/held/busy/unowned input cannot start
  work. Twenty new native/API/CLI cases pass, including 80 admission-failure
  positions with following-work recovery and exact current/identity profiles.
  Native serial fixture preserves compact bounded JSON. Full 729 cases pass with
  no skips, plus all shared checks and frontend formatting.
  V4.2/32 KiB IDF builds: disabled 0x6e880 and isolated microphone/PTT enabled
  0x6e930, 57% app free, static DIRAM 73,841. PTT supplement 547a3d…; other wire
  hashes unchanged. No flash or physical GPIO/PCB acceptance; original user
  checkout remains separate. Next #37 optional OLED views of actual node state.

- #30: PR #193 (`feat/host-armed-ptt` → `feat/voice-stage-dashboard`) is ready
  for review with six scoped commits and 729 full passing cases, no skips; both
  IDF configurations pass, normal PTT stays off. Issue Testing, no merge/flash.
  PCB/GPIO47 physical prerequisite #1 remains open; PR does not auto-close it.
  Starting #37 on its own dependent branch for optional bounded OLED status
  derived from real state, with absence/failure isolated from serial control.

- #37 implemented on #193: fixed nonsecret actual-state view, original bounded
  text/bitmap, ten-write/5 ms panel transport and opt-in one-slot OLED worker.
  Failure leaves USB/control running; passive exact-profile observations do not
  claim observed pixels. Eighteen dedicated tests and the 771-case current-main
  integration check pass with no skips, plus all shared checks and UI formatting.
  Final IDF builds pass: disabled 0x6ed10/57%/73,841 static DIRAM; isolated full
  audio/PTT/OLED enabled 0x73530/55%/75,661. Normal configuration remains off.
  Board reference v3/1da5acc… adds GPIO36 LOW Vext control, matched table/Mermaid/
  PNG; official V4.2/V4.3 pages and native bitmap visually inspected. Passive
  OLED supplement e57d4c…; other wire hashes unchanged. No flash or PCB/screen
  qualification. User merged #192/#193 while work continued; rebased OLED onto
  main. A reproduced native fixture write-after-close crash now raises OSError
  under the port lock; production USB behavior is unchanged. PR #194 is ready
  against main, issue Testing, no agent merge. Next #69 resource/arm transitions
  before #73.

- #69 implemented on #194: transactional run reservations, allocation-free
  receiver arm, both-role five-second start checks and finite preparation/run/
  reporting cleanup independent of telemetry space. Stop/close/lease/disconnect
  retire buffers/keys; committed files and borrowed voice sources survive.
  Initiating timeout remains distinct from cleanup errors. Forced ID collision
  reproduced deletion of an unowned preexisting file; rollback now tracks actual
  successful reservation ownership. Final full check: 808 cases, no skips, all
  shared checks and formatting; 37 dedicated lifecycle cases. V4.2/32 KiB IDF
  build 0x6f000/57% app free/73,841 static DIRAM. Execution profile becomes
  finite_message_execution_v2/04f50ab…; unrelated profiles and original 19 user
  files unchanged. No flash; calibration and physical acceptance remain open.
  PR #195 is ready (`feat/reserved-run-lifecycle` → `feat/actual-oled-status`),
  issue Testing, no agent merge. Next #73 named stage memory observations.

- #73 implemented on #195: finite 10 Hz plus stage memory observations with
  separate boot/measurement/workload minima, nonoverlapping requested ranges,
  observed lifetimes, real internal/PSRAM classification and explicit unknown/
  untracked scope. Drops/missed intervals and host retention loss stay distinct;
  ownership loss/reconnect never resumes work. Primary audio/RF cleanup survives
  observer failure. Static radio metadata remains in identity so full configured
  health and live errors remain under 4 KiB. New independent memory profile
  stage_memory_observation_v1/4004d780…; existing hashes unchanged. Full check 828
  cases, no skips, all shared checks/formatting; 20 dedicated cases. V4.2/32 KiB
  IDF 0x711a0/56% app free/73,841 static DIRAM. Original 19 files unchanged;
  no flash or target memory qualification. PR #196 is ready
  (`feat/stage-memory-observations` → `feat/reserved-run-lifecycle`), issue Testing,
  no agent merge. Next #74 fixed-rate encoded producer, bounded whole-message
  queue and actual consumer accounting.

- #74 implemented on #196: independent reserved producer task, 4,800-byte total
  encoded payload queue, actual frame/5 Hz evidence, whole-message outcome masks,
  bounded drain and quiescent payload retirement. Twenty-message protected RF
  reuses fresh sequences, exact retries and one reserved reassembly buffer;
  incomplete/hash-invalid messages leave explicit receiver archive holes.
  Failed worker joins retain dependencies and block new operations. Exact
  finite_message_execution_v3/08e34008… adds bounded run.source readback; general
  one-message limits remain explicit. Seventeen dedicated cases and 845 full
  cases pass without skips, all shared checks and UI formatting. Final 32-case
  source/memory checks pass. V4.2/32 KiB IDF 0x73c50/55% app free/74,097 static
  DIRAM. Original 19 files unchanged; no flash/physical qualification. Source
  procedure/assessment is #105 and physical acceptance #136; #75 is the common
  host lifecycle and must not be mistaken for the source procedure.

- #74: PR #197 (`feat/fixed-rate-encoded-source` →
  `feat/stage-memory-observations`) is ready with scoped Conventional Commits,
  walkthrough, expected checks and physical limits. GitHub issue/card Testing;
  no agent merge. Full 845 cases and shared checks pass; final controller 77 and
  source/memory 32 cases pass, target build remains 0x73c50. Next #75 integrates
  common physical host lifecycle/error/recovery rules across existing data,
  audio and diagnostic workflows; it is not the VOICE-03 procedure (#105).

- #75 implemented on #197: one physical adapter shared by radio/audio/files/local
  diagnostics, with device/boot/connection binding and safe per-step cleanup.
  Same-boot reconnect cannot resume old work or close the new connection.
  Durable diagnostic jobs/summary/evidence cover acceptance, missing results,
  immediate stop and shutdown. Committed captures survive failed readback for
  explicit recovery; original and cleanup failures remain separate. A red
  acceptance/shutdown test reproduced a write after database close; shutdown now
  joins the acceptance owner before closing resources. Twenty-one dedicated
  cases, full 866 cases without skips, all shared checks/UI formatting and final
  63-case recovery/provenance checks pass. Host-only; no wire/build/flash change.
  Procedure provenance includes actual shared modules. Next #81 persists physical
  campaign plans/order/case links; execution remains the separate #87 scope.

- #75: PR #199 (`feat/common-physical-lifecycle` →
  `feat/fixed-rate-encoded-source`) is ready with scoped commits, code reading
  order, checks and remaining physical validation. Issue/card Testing; no merge.
  Final full 866 cases and all shared checks pass; final 63 focused cases and
  UI formatting pass. Original 19 files unchanged. Beginning #81 on a separate
  branch: persist physical plans, seeded order, requirements and linked bounded
  batches. Do not restore historical simulator execution; #87 owns execution.

- #81 implemented on #199: typed physical workload/procedure references,
  deterministic matched-seed expansion/order, immutable hashed intent and linked
  64-case/30-minute batches with no dropped cases. Local node B works alone; RF
  checks distinct identities. All 23 full procedure references remain explicitly
  blocked until implemented. Existing compatible request models and historical
  expansion/storage patterns were inspected; no simulator execution is restored.
  API/CLI preview/save/list/reload and verified nine-case offline example work.
  Full 889 cases without skips and all shared checks pass; final 24 planner and
  86 integration cases pass, plus final lint/contracts/repository/UI formatting.
  Host-only, no wire/build/flash change. Execution is #87, campaign UI #115. Next #82 is
  host memory-observation procedure/evidence integration; inspect its live scope.

- #81: PR #200 (`feat/physical-campaign-plans` →
  `feat/common-physical-lifecycle`) is ready with scoped commits, planner/API/CLI
  walkthrough, verified example, checks and explicit execution/qualification
  limits. Issue/card Testing; no merge. Full 889 cases and all shared checks
  pass; final 24 planner cases (added example) and 86 integration cases pass.
  Original 19 files unchanged. Starting #82: actual stage/queue evidence,
  independently reconciled totals, distinct startup/3–60s/drain assessments,
  inconclusive gaps and unavailable unsampled memory peaks. #105 remains the
  full sustained-source procedure; #82 is assessment, not its qualification.


- #82 implemented on #200: immutable source/queue and stage-memory evidence,
  independently reconciled byte/message identities, startup/[3,60)/drain cohorts,
  optional exact receiver archive verification and honest clock/peak limits.
  Completed overload is a valid negative finding; partial drops are not complete
  messages. Actual bound readback, API/CLI, concurrent memory observation and
  partial timeout/reconnect/shutdown evidence work through shared sessions.
  Twenty-five dedicated cases and full 915 cases pass without skips, all shared
  checks and UI formatting pass. Original 19 files unchanged. Host-only: no
  wire/firmware/build/flash change or physical qualification. #105 remains the
  full source procedure, #88 plots/UI. Next #87 executes saved physical campaign
  cases with pause/cancel and exclusive ownership, reusing existing runners.

- #82: PR #201 (`feat/memory-source-assessment` →
  `feat/physical-campaign-plans`) is ready with five implementation/test/doc
  commits, walkthrough, expected checks and physical instructions. Issue/card
  Testing; no agent merge. Full 915 cases, 25 dedicated cases and all shared
  checks pass. Starting #87 on a fresh branch based on this reviewed stack.


- #87 implemented on #201: atomic separate execution/case ledger, saved seeded
  order/batch links, shared local/data/voice child runners, exclusive ownership
  through pause/resume, partial cancellation, fail-stop and independent peer
  cleanup. Missing acceptance retains a durable child reference; late stop cannot
  leave completed work cancelling. Active/paused restart never opens ports or
  resumes RF. Final 13 campaign cases pass; full 928 cases without skips and all
  shared checks/UI formatting pass. Final stronger tests verify actual shuffled
  payload requests 2048/512/1024 and nondefault radio source settings. Original
  19 files unchanged; no firmware/build/flash/physical validation.

- Live issue verification corrected an earlier handoff: #88 is memory/source
  history plots, #107 is restart/selected-case reruns/exports, and #115 is campaign
  UI. Follow #88 next, then #107/#115 and physical #132; retain all 23 procedures.

- #87: PR #202 (`feat/physical-campaign-execution` →
  `feat/memory-source-assessment`) is ready with scoped commits, code walkthrough,
  expected checks and hardware instructions. Issue/card Testing; no merge. Full
  928 cases and final 13 strengthened campaign cases pass; all shared checks and
  UI formatting pass. Starting #88 memory/source-history plots on a fresh branch.


- #88 implemented on #202: bounded actual-row memory/source plots, explicit clock/
  gap/null scope, distinct boot/sample/workload minima and startup/[3,60)/drain,
  valid negative overload findings, paged stages/buffers and independent complete
  hash-checked JSON exports. Compatible finite observer controls reuse current
  connection binding. Nine dedicated cases and full 937 cases pass without skips,
  all shared checks/UI formatting. Isolated native/browser fixtures verify long
  traces/one-sample peak, active/terminal collection, disconnect, full download,
  dark/light and 390-pixel layout; no hardware qualification. Original 19 files
  unchanged; no firmware/wire/build/flash/physical access. Next #107 linked reruns
  and verified campaign exports, then #115 campaign UI and physical #132.

- #88: PR #203 (`feat/workload-observation-plots` →
  `feat/physical-campaign-execution`) is ready with five scoped implementation/
  test/doc commits and browser evidence. Issue/card Testing; no merge. Full 937
  cases and all shared checks pass; nine dedicated cases/UI formatting pass.
  Next #107 on a separate branch: linked subset reruns and verified campaign
  bundles; never restore or automatically resume an interrupted RF execution.


- #107 implemented on #203: linked selected-case reruns preserve original history,
  exact saved settings/order/seeds/batches and fresh bound preflight/ownership.
  Header/case hashes and bounded complete child/file graph exports, persisted
  radio file fingerprints and offline ZIP/count/link verification reject corrupt
  evidence. One tracked worker keeps export I/O off the control loop and joins
  through cancellation/shutdown before DB close. Legacy/interrupted files retain missing prior-hash scope. A wider
  regression reproduced an unreadable-fingerprint finalizer leaving radio running;
  it now preserves terminal failure and cleanup. Twenty-seven dedicated cases and
  full 964 cases pass without skips, all shared checks/format/CLI help. Combined
  55 lifecycle/radio cases pass; final dedicated run adds serial/limit cases.
  Actual native two-node DATA/voice graph and cold active/paused process exits are
  software fixtures, not physical qualification. Original 19 files unchanged;
  no firmware/wire/build/flash/physical access. Next #115 campaign controls/UI,
  physical #132 remains blocked on real setup and predecessor acceptance.

- #107: PR #205 (`feat/campaign-reruns-evidence` →
  `feat/workload-observation-plots`) is ready with scoped commits, walkthrough,
  expected checks and physical follow-up. Issue/card Testing; no merge. Final
  full 964 cases and all shared checks pass, plus 27 dedicated cases, formatting
  and CLI help. The export worker red test reproduced control-loop blocking;
  the joined bounded worker fixes it. Original 19 files preserved. Starting #115
  saved-plan/ledger controls, refresh attachment, selected reruns and exports.


- #115 implemented on #205: bounded read-only case views/current page readiness,
  compact live headers and a shared-owner dashboard for plan imports, explicit
  start/pause/resume/stop, partial/blocked history, linked selected reruns and
  verified downloads. Session preferences contain IDs only; no browser read or
  reconnect starts work. Three dedicated cases and full 967 cases pass without
  skips/all shared checks; final UI build/format pass with identical JS after a
  type-only correction. Isolated browser checks cover pause/navigation/reload,
  three saved children, cancel+skip, one-case rerun and unchanged original,
  nine-case import with no start, exact downloaded 1-case/1-child/2-file/7-member
  hash verification, cold active restart and still-six unique diagnostic starts,
  unconfirmed cleanup, light/dark and 390-pixel no-overflow layout. Console clear.
  Test-only fixture port 8874 stopped; original 8000 untouched. Download/chooser
  tools were unexpectedly slow, not product timing evidence. Original 19 files
  preserved; no firmware/wire/build/flash/physical access. Physical #132 remains
  open. Live #46 explicitly requires both exact boards/schematics/instruments
  before pulses; leave pins unassigned/disabled. Next independent M8 slice #65
  verified-byte echoes and requester-local RTT, then dependent host/timing work.

- #115: PR #206 (`feat/physical-campaign-dashboard` →
  `feat/campaign-reruns-evidence`) is ready with scoped Conventional Commits,
  walkthrough, expected software/browser/physical checks. Issue/card Testing;
  no agent merge. Full 967 cases/all shared checks, final identical-asset UI
  build/format and three dedicated cases pass. Original 19 files preserved.
  Next #65 echo/RTT firmware on its own branch; #46/#49 pulse wiring/capture and
  #132 physical acceptance remain gated by their actual hardware prerequisites.


- November 25: #65 implemented on #206 with one pending verified echo, fresh
  responder sequence, requester-local TX-command/acceptance RTT, null timeouts,
  bounded late/duplicate exclusions and cleanup in the actual C radio/security
  path. Execution v4 coordinates typed intents/results and generated metadata;
  unrelated profiles remain stable. Thirty-seven echo cases and combined 73
  full-capability cases pass; full 1,004 cases/all shared checks pass without
  skips. ESP-IDF v6.0.2 build/size succeeds (479,571-byte image); no physical port,
  reset or flash. Host collection/accounting #83 is next, then full procedures;
  #46/#49 pulse review/capture and actual hardware qualification remain gated.

- #65: PR #208 (`feat/verified-echo-rtt` →
  `feat/physical-campaign-dashboard`) is ready with five scoped Conventional
  Commits, walkthrough, expected checks and physical follow-up. Issue/card
  Testing; no merge. Original 19 files verified unchanged. Continue #83 on a
  separate branch for physical echo orchestration and independently reconciled
  requester-local distributions; preserve raw exclusions and host timing.


- November 25: #83 adds shared physical echo runs, actual bounded returned bytes,
  independent request/reply/content/local-time correlation and device/boot/
  settings cohorts with n/median/nearest-rank p95. Host transaction timing stays
  separate; timeout/invalid/partial evidence remains excluded with reasons.
  An actual end-to-end case caught serialization-time drift in `rx.accepted`;
  it now shares the captured acceptance instant with the echo result. Bounded
  integrity-checked aggregation uses the shared tracked evidence worker, joined
  before store close. A repeated-run check caught retained temporary artifacts;
  verified fresh echo files now retire after readback, preserving pre-existing
  files and failed readbacks. Six consecutive runs and explicit retirement
  failure/session-close checks pass. Twenty-eight new cases, full 1,030 cases
  without skips, final 75 recovery cases and all shared checks pass; IDF build/size passes (480,067-byte image), no physical access.
  Original 19 files preserved. After review PR, continue #76/#77 lab fault hooks,
  then #85 accounting/#89 views and all full procedure matrices. #84 one-way
  calibration still depends on actual pulse setup/capture prerequisites.

- #83: PR #209 (`feat/physical-echo-rtt` → `feat/verified-echo-rtt`) is ready
  with eight scoped Conventional Commits, shared CLI/API commands, code
  walkthrough and expected physical checks. Issue/card Testing; no merge.
  Twenty-eight dedicated cases, full 1,030 cases, final 75 recovery cases and all
  final shared checks pass; original 19 files unchanged. No physical access.
  Echo-only artifact retirement now prevents repeated-run exhaustion while
  preserving user files. Check whether the existing known-data path needs the
  same verified run-artifact policy before large campaigns; do not delete
  uploaded encoded source references or failed-readback evidence. Continue the
  independent #76/#77 fault hooks and the remaining full procedure matrices.


- #210 was filed after the actual native known-data probe failed on message 5
  with RESOURCE_LIMIT. On `fix/repeated-data-artifacts` over #209, generated DATA
  now uses initial artifact IDs and retires only fresh independently read-back
  objects. Pre-existing files, failed readbacks and downstream encoded voice
  objects keep their lifecycle. Six dedicated and combined 20 DATA/echo cases
  pass, including six consecutive runs in all direction/security combinations,
  verified host exports and continued close attempts after retirement failure.
  Full 1,038 cases and all shared checks pass without skips; formatting passes.
  Original 19 files unchanged. Host-only, no wire/firmware/build/physical access.
  Finish checks and this bug PR before #76/#77; all full procedures remain open.

- #210: PR #211 (`fix/repeated-data-artifacts` → `feat/physical-echo-rtt`)
  is ready in three scoped commits with retention walkthrough and expected
  checks. Issue/card Testing, P1/default host owner Angel; depends on #83.
  Full 1,038 cases/all shared checks, six dedicated/20 combined cases and
  formatting pass. Original 19 files unchanged. No firmware/physical access.
  Continue #76 on its own branch: explicit default-off laboratory post-protect
  mutation/retained replay, then #77 fragment/ACK faults. No pulse pins guessed.

- #76 software verification: 59 focused and 1,077 full cases pass without
  skips. Standard and isolated lab ESP-IDF builds pass, and execution v5
  metadata matches. See [laboratory checks](../lab_frame_faults.md).

- PR #213 is ready for #76 on top of #211. The issue and Project card are in
  Testing. The full check and both ESP-IDF build profiles passed.
- The grouped lab controls branch implements #77 with receiver-local arrival
  ordinals, repeatable exact-byte duplicates, and prepared reversal up to 32
  frames. The 77 focused checks passed. Host reconciliation should require
  applied target, matching TX/RX wire digests or exact RX arrival, the observed
  receiver stage and fresh before/after controls. Bind the evidence to both
  device boots and preserve negative results independently of execution status.

- #77 branch `feat/lab-fragment-controls` is pushed over #213, with 77 focused,
  1,095 full checks, and standard/lab builds. GitHub PR creation returned
  server errors. Check for an existing review before trying to create one.
- #85 uses three bound radio child runs, independent target/digest/stage
  correlation, and a shared dashboard/API/CLI entry. Lab controls are
  available on PKT-02/03 and SEC-02/03. The native browser fixture retained
  a passing retry result with the same evidence links after reload.

- #85 host checks: full 1,105 tests, 10 focused trial cases, lint, frontend
  build/format and generated contract/repository/vendor checks passed.
  The isolated browser checked a passing three-child trial, refresh and
  an eight-member evidence hash manifest. No bench hardware was exercised.
  Continue with the shared IF-01/02/03 procedure matrix and evidence runner.

- The lab host branch `feat/lab-trial-evidence` is pushed after final software
  checks; GitHub returned errors opening the firmware and host PRs. Review
  branch diffs over their actual dependencies. Keep full hardware qualification
  issues open.
- Grouped integration work on `feat/shared-integration-matrices` adds CDR
  case plans and a shared executor for serial basic/error replies, the IF-02
  baseline/sizes/peer-mismatch groups and six IF-03 groups. Preview reports
  blocked serial and campaign variants explicitly. Host fixture verified
  directions, cancellation and the nested export graph. See
  [integration matrices](../integration_matrices.md). Next experiment family is
  RF-01 to RF-04 with controlled one-factor settings and per-child observations.

- GitHub accepted the shared integration PR #214 over the lab testbed branch,
  the lab firmware PR #215 over #213, and the lab testbed PR #216 over #215.
  The shared integration full check passed 1,110 tests and all repository
  checks. No reviews were merged.
- The next grouped branch `feat/rf-experiment-sweeps` implements RF-01 to
  RF-04 case generation and execution through the shared ledger, with separate
  applied settings, modeled airtime and sender/receiver observations. All 13
  focused checks passed, including actual native readback at each setting.

- RF sweep PR #217 is open over #214. Full `make check` passed 1,118 tests.
  Issues #55/#56/#57/#58 link to the execution PR. Full comparison plots and
  assessment remain open.
- On `feat/packet-and-protection-series`, PKT-01 and SEC-01 reuse the shared
  executor. The native checks pass bounds, complete readback, per-fragment
  GCM tag length, independent wrong-key and peer-profile assertions and
  intact follow-up with no keys in evidence. Full `make check` passed 1,122 tests.
  Next grouped software slice can reuse verified echo and local crypto
  benchmarks for TIME-01 and SEC-04.

- Packet/protection PR #218 is open over #217. Issues #70/#71 link to it
  and retain their remaining software coverage.
- The timing batch adds execution for the positive TIME-01 echo cohorts
  and SEC-04 known-answer batches, with per-run raw evidence and no
  fabricated timing for an unavailable case. The suite passed 1,125
  tests. The shared dashboard matrix controls are the next review slice.

- Timing PR #219 is open over #218. Issues #62 and #102 link to it.
- The matrix dashboard adds reviewed-plan start, run-specific stop,
  per-case readiness and archive inspection across supported suites.
  The isolated browser completed IF-01 C1, preserved the saved run after
  page navigation and disabled start for C3. All four member hashes in
  the archived evidence matched.

- Dashboard PR #220 is open over #219. Full regression passed 1,126
  tests, with the remaining build, lint and contract checks verified.
- MEM-01 C1/C2 now run one-node idle and paired observed-data cases.
  Verified matching stage/workload IDs, separate idle windows, observer
  cancellation and retained hashes through the native fixtures. Full
  make check passed 1,130 tests.

- Memory PR #221 is open over #220. Issue #90 links to the partial runner.
- MODEL-01 groups the 90 independent reference vectors, isolated TX
  observations and no-ACK, ACK and confirmed one-retry message cases.
  Full make check passed 1,134 tests. Instrumented physical tolerance
  is still separate from node-local TX timing.

- Airtime model PR #222 is open over #221 and linked to #91.
- The grouped packet/security matrix executes matched lab trials
  with retained child IDs and scope. Missing long-window replay and
  multiple controlled drops stay blocked. The 1,137-test regression
  and targeted third-workload packet check both passed.

- Grouped packet/security PR #223 is open over #222.
- VOICE-02 C1 now runs selected three-second references with matched
  data controls and linked stage evidence. All 19 focused checks pass.
  The microphone sequence and physical listening remain outstanding.

- Reference voice PR #224 is open over #223 with #79 linked.
- OPS-01 C7 now verifies a 100-case linked plan and runs through the
  shared campaign executor. The ten-case fixture and linked export
  passed along with the 43 focused campaign/API checks. Disconnect,
  restart, loss injection and loaded stability remain separate.

- Recovery campaign PR #225 is open over #224.
- VOICE-01 C3 now supports one-node reference upload, verified codec
  stages, playback command and owned cleanup. The native fixture
  retained an unrelated preexisting artifact. All 41 focused checks
  passed. Physical listening remains separate.

- Local audio PR #226 is open over #225.
- Offline TIME-02 assessment checks retained pulse and frame identity,
  exact fit, per-phase intervals, expiration and uncertainty. All 37
  focused clock/echo checks pass. Live calibration remains open.

- Offline clock PR #227 is open over #226.
- VOICE-04 saved review checks encoded transport and both PCM artifacts
  before presenting clips, and validates each score against its original
  hash while preserving node-local phases and missing calibration.

## Grouped review checkpoint

| Procedure family | Software entry point | Coverage still open |
| --- | --- | --- |
| IF-01–03 | Experiments matrix and `integration-matrix` | Supervised active/paused restart and campaign navigation cases |
| RF-01–04 | Seeded sweeps, applied settings, delivery evidence and matched requester RTT | Full repetitions and bench review of baseline changes |
| SEC-01–04 | Matched GCM, mutation, replay and local benchmark matrices | Old-window replay, rate and overhead comparisons and full repeated batches |
| PKT-01–03 | Boundary/workload matrices, firmware limit refusal and exact packet fault trials | Same-session packet cohorts and invalid ACK |
| TIME-01–02 | Matched echo, controlled timeout and offline `clock-evaluate` | Live pulse calibration, loaded measurements and calibrated delay |
| MEM-01 | Idle, known data, audio stages, firmware limit refusal and controlled memory recovery | Full repetitions and physical acceptance |
| VOICE-01–04 | Local and paired references, fixed-rate source matrix and `voice-review` | Attended microphone/error cases, calibrated delivery window, listening study and plots |
| MODEL-01 | Independent vectors, frame/message matrices and measured residual plots | Instrumented airtime/tolerance and full bench study |
| OPS-01 | Linked recovery campaign matrix with all 100 fixture cases verified | Physical campaign acceptance, deliberate USB and reset interruptions, restart, telemetry/timeouts and loaded stability |

Keep fixture results and physical qualification records separate. Grouped
support remains partial where a documented case is unavailable.

The final dashboard fixture exercised one-node VOICE-01 C3 and paired
VOICE-02 C1 through the saved reference controls. The paired result
persisted across navigation. Every member of both archives matched its
manifest. The voice review accepted two fixture ratings tied to their
clip SHA-256 values and left one-way timing unavailable.

The full OPS-01 fixture completed all 100 cases in four linked batches
and verified 260 child and transfer records. A separate browser run
showed the planned count, retained the active matrix across navigation,
then verified targeted stop, skipped cases, confirmed cleanup and a
hash-verified partial archive. The offline model run saved 90 passing
reference cases and verified their archive with no device bindings.

The dashboard and CLI share the matrix service for 20 of 23 catalog
entries. TIME-02, VOICE-03 and VOICE-04 have separate evidence workflows.
Both standard and lab ESP-IDF v6.0.2 images rebuilt successfully with
distinct hashes and only the lab's generated configuration enabling
the fault controls. Physical qualification remains deferred.

The final full `make check` passed 1,155 tests with no skips. Ruff,
the dashboard build, generated contracts, repository resources and the
pinned Codec 2 files passed. Prettier passed for the changed UI. All
19 originally changed workspace files still match their saved hashes.

IF-01 C3 runs all 27 default USB cases per selected role and compares
device framing counters with the expected rejections. The isolated native
fixture covers the full one-role schedule and interrupted multi-write cleanup.
The separate UART and physical qualification remain open.

Campaign restart now retains the original active/paused checkpoint and
hashes each retained interrupted radio trace. The test restarts an
isolated host during active transmit and after a settled pause and
confirms unchanged history, verified archives and fresh follow-up runs.
Supervised procedure iteration and physical checks are pending.

IF-01 C2 now records before/after applied radio settings, link settings and
configuration revision for the firmware rejection. The 12 selected-role
cases passed against the native fixture. Only the configuration case
requires radio support.

IF-01 C6 now covers competing claims and lease expiry with an actual
unowned idle health reading and fresh claim. Six default cases passed on
one role, and cancellation after expiry restored control. The deliberate
silence fixture remains open.

IF-01 C5 covers dropped, delayed and identically retried responses and
changed bytes under a reused command identity. The fixture correlates a
fixed diagnostic with its independent result and compares retry hashes.
The controlled stale-boot case remains open.

IF-01 C4 checks all three compatibility mismatches through the normal
connection handshake. The one-role fixture verifies nine independent
rejections, closed ports and absence of claims or downgrade.

IF-01 C6 now includes all three health-silence repetitions. The native
fixture verifies that real health is retained in evidence while the
watchdog observes silence and reconnects with a fresh binding.

The supported IF-01 USB matrix now includes stale-boot rejection after
the testbed observes the same device on two boots. Native regression
exercised all 15 C5 cases. UART and physical transport qualification
remain open.

PKT-03 C4 targets all allowed attempts, records ACK receive timeouts and
checks bounded failure, exact missing ranges and fresh controls. Native
tests include all reply policies and an incomplete-observation check.

The complete native IF-01 USB schedule passed all 146 cases on both
roles, retaining 1,202 evidence rows and a hash-verified archive.
The preceding full repository check passed all 1,166 tests.

The optional UART profile and default USB profile both built under
ESP-IDF v6.0.2. A mixed-transport native fixture passed 73 matching cases
for each role, retained 146 unmatched case rows and verified all archive
hashes. The preceding repository check passed 1,167 tests.

RF-01 through RF-04 now distinguish verified delivery, bounded
non-delivery and unresolved outcomes. A complete case retains the
delivery ratio, counted signal and useful data per active TX second.
The native fixture verified a mixed RF-02 cohort with an omitted frame.

RF comparisons now retain individual repetitions, their unweighted
ranges, and paired baseline changes for each direction. The native tests
verify incomplete cohorts and archive hashes. The browser check verified
all seven power settings, a second metric and the opened baseline table.

The full repository check through RF sweep comparisons passed 1,171 tests.
MEM-01 C3 now links capture, codec, reassembly and playback to firmware
workload IDs and measures sampled memory change against the preceding
baseline. Twenty-one focused tests passed, including reassembly without
receiver playback, integrated voice and local capture cancellation.

MEM-01 C4 sends max plus one over the typed control connection and requires
a resource refusal, unchanged idle health and artifacts, and a successful
64-byte recovery run. The native pair passed both directions with observed
65,537-byte refusals and no arm/start commands for the oversized requests.

MEM-01 C5 records controlled cancellation of prepared work and a confirmed
protected delivery failure. Both measurements compare post-cleanup samples
against declared bounds, verify named buffer release and link a fresh
64-byte recovery transfer. The cancellation case verifies and retires only
the source artifact that it prepared.

PKT-01 C3 now uses the firmware size-refusal check in both security
profiles. The native cases observed unchanged device state, no arming,
and exact recovery data. The protected fixture verified fresh key-set
identities and redacted wire evidence.

TIME-01 C2 uses two intact controls and one owned echo session with the
responder stopped before arming. Native evidence verifies a confirmed
request, bounded requester-local timeout, null RTT and a subsequent reply.
An absent transmit observation makes the same evidence inconclusive.

Companion echo runs preserve the same complete applied radio and link
settings and boot identities as their DATA cases. The native power sweep
checks per-role power readback, seven distinct settings and recorded RTT
values. The dashboard and CSV retain companion counts and null timeouts.

VOICE-03 now runs the ordered sustained profile matrix through normal
dashboard and CLI entry points, with the producer trace and receiver
archive collected before session close. The native reference case verified
3,000 producer frames, a 24,000-byte archive, exact delivery IDs, and
cleanup. The uncalibrated in-window delivery rate remains unavailable.

The full repository check through matched RF timing passed 1,180 tests.

MODEL-01 review now plots matched observed values and signed residuals
by configuration. Isolated command-to-done observations and message
completion retain separate capture bases. The per-observation CSV is
fingerprinted in the procedure archive.
