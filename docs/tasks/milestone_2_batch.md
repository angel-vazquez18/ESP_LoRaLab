# Milestone 2 implementation batch — November 16, 2026

Status: in progress.

The user authorized all remaining M2 issues as one branch/PR per issue, small
Conventional Commits, full testing and relevant builds/flashes/board checks.
Prepare all PRs for later review; do not merge them. This supersedes the earlier
stop-after-each-PR instruction. Dependent PRs form a stack, each based on its
predecessor; merge/review order is explicit in each PR.

Order: #14 → #18 → #22 → #26 → #33 → #23 → #24 → #32 → #38 → #42.
#2 and #11 are merged. #42 also depends on physical recovery issue #21.

The attached device is esp-f85b1ba27744, currently /dev/cu.usbmodem2101. The user
confirmed all documented audio wiring on November 16. Printed board revision
remains unobserved. The user is away: prepare listening/spoken-phrase checks for
later. Do not claim heard output, speech response, measured clocks or rail voltage
without observations. Full physical qualification may remain incomplete.

Use existing main firmware and physical-only host. Preserve seven earlier local
edits, excluded from these PRs. Their backup/hashes and active execution state are
in ignored local/m2-batch. Build/flash only an identified, released port after
verifying the retained flash backup. No eFuse changes or NVS erase.

## Progress

- #14: implemented and verified: 20 new native cases; full checks 240 passed;
  ESP-IDF main build passed (0x3c0c0 bytes, 77% partition free). PR #152 open.
  Existing board still ran the old log-only image; verified original backup and
  started a fresh 16 MiB snapshot before the first batch flash.
- #18: implemented real SHA-256 commit, immutable/failed transitions and real
  consumer lifecycle tests. 10 new cases; full checks 250 passed. ESP-IDF build
  passed (0x3c2c0 bytes, 76% partition free). PR #153 open, based on #152.
- #22: committed readback/CRC/EOF implemented. 17 new cases; full checks 267
  passed. ESP-IDF build passed (0x3c890 bytes, 76% partition free). Fresh full
  flash backup verified and cumulative artifact image flashed, NVS retained.
  Device/schema/ELF matched; initial real 1/1024/1025/48000/131072-byte round trips
  passed. Negative/capacity hardware evidence is being finalized.
- #26: shared host service/API/CLI implemented; 23 focused cases, full checks
  290 passed. Real host upload/download at 1/1024/1025/48000 bytes and cancellation,
  cleanup and valid recovery passed. Evidence: local/m2-batch/host-transfer-hardware-report.json.
  PR publishing next, based on #154.
- Later issues: pending.

Each PR includes its code walkthrough, verification commands/expected outcomes,
dependency and remaining physical evidence. Current status/evidence goes in
this document, docs/status.md and the linked issue; software fixtures never
qualify physical audio.
