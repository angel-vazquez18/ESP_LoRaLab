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
