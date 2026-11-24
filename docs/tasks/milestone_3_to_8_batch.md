# Remaining milestone implementation batch

## User direction

Continue software development through the remaining milestones without waiting
for individual PR merges. One issue/branch/PR per scope, small descriptive
Conventional Commits, no merges. The user will review and test later. Software work does not use physical ports.
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

## Work order

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
