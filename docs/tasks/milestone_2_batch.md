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

- #14: PR #152, branch feat/artifact-chunks, base main. 20 new native cases.
- #18: PR #153, branch feat/artifact-commit, base feat/artifact-chunks. 10 new
  cases; replaced seeded consumer tests with real upload/commit.
- #22: PR #154, branch feat/artifact-readback, base feat/artifact-commit. 17 new
  cases. Firmware build 0x3c890, 76% partition free. Fresh full flash snapshot
  verified and image flashed, NVS retained.
- Physical artifact check passed at 1/1024/1025/48000/131072 bytes, raw CRC/offset/
  retry/hash/capacity/recovery, zero gaps/framing errors. Evidence:
  local/m2-batch/artifact-hardware-report.json; boot 55, matched schema/ELF.
- #26: PR #155, branch feat/host-artifact-transfers, base feat/artifact-readback.
  23 new host cases; 290 total tests. Real host roundtrips, cancellation, cleanup
  and recovery passed. Evidence: local/m2-batch/host-transfer-hardware-report.json.
- #33: implemented node inspector files/progress/history and exact server readiness.
  Full checks 293 passed; frontend build/format passed. Real browser upload,
  retrieve/save byte/hash verification, visible invalid request, cancel/delete,
  disconnected gating and reconnect passed. Screenshot in visualization folder:
  m2-file-inspector.png. QA server stopped; node port released. PR #156, feat/node-artifact-inspector.
- #23: finite playback implemented, native fault/boundary checks and audio-enabled
  IDF build pass; fixed 1/8 amplitude and DMA source/frame counts remain distinct
  from heard output. See docs/node_audio.md.
- #23: PR #157, feat/finite-pcm-playback, base feat/node-artifact-inspector.
- #24: finite capture and private hash publication implemented; 43 audio / 336 total
  tests pass, IDF build 0x43e90 / 73% free. Cumulative real-board DMA/count/hash,
  sequential/cancel/recovery checks passed on boot 60. No heard/speech/instrument
  qualification. Evidence local/m2-batch/audio-hardware-report.json.
- Next: #32 host audio → #38 UI audio → #42 physical
  qualification. Printed revision, operator listening/speech and instruments are
  still unobserved; user is away and asked to prepare those checks for later.

Each PR includes its code walkthrough, verification commands/expected outcomes,
dependency and remaining physical evidence. The ignored state map contains exact
PR/branch heads. Preserve seven prior local edits. Software fixtures never qualify
physical audio. All source changes/commits/pushes/PRs and required board builds,
flashes and tests are authorized; do not merge any PR.
