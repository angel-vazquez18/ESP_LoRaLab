# Remaining milestone implementation batch

## User direction

Continue software development through the remaining milestones without waiting
for individual PR merges. One issue/branch/PR per scope, small descriptive
Conventional Commits, no merges. The user will review and test later. No ESP is
connected; do not flash or open physical ports. Preserve the original checkout's
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
