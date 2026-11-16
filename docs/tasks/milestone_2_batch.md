# Milestone 2 implementation batch — November 16, 2026

Status: implementation PRs ready for review; physical qualification incomplete.

The user authorized completing the remaining M2 implementation as one branch/PR
per issue, small Conventional Commits and necessary builds/flashes/board checks.
Prepare the entire stack for later review; do not merge. This supersedes the earlier
stop-after-each-PR instruction. #2/#11 are merged; no PR in this batch was merged.

## Review order

Each PR targets the preceding branch; #152 targets main. Review/merge in this order
and inspect the next PR's base/diff before merging it. The PR descriptions include
walkthroughs, important files, commands/expected results and physical limitations.

| Issue | PR | Scope | Checkpoint |
| --- | --- | --- | --- |
| #14 | [#152](https://github.com/angel-vazquez18/ESP_LoRaLab/pull/152) | Chunk offsets and CRC | Ready for review |
| #18 | [#153](https://github.com/angel-vazquez18/ESP_LoRaLab/pull/153) | Verified artifact commit | Ready for review |
| #22 | [#154](https://github.com/angel-vazquez18/ESP_LoRaLab/pull/154) | Bounded file readback | Ready for review |
| #26 | [#155](https://github.com/angel-vazquez18/ESP_LoRaLab/pull/155) | Shared host transfers | Ready for review |
| #33 | [#156](https://github.com/angel-vazquez18/ESP_LoRaLab/pull/156) | Node file inspector | Ready for review |
| #23 | [#157](https://github.com/angel-vazquez18/ESP_LoRaLab/pull/157) | Finite PCM playback | Ready for review |
| #24 | [#158](https://github.com/angel-vazquez18/ESP_LoRaLab/pull/158) | Finite microphone capture | Ready for review |
| #32 | [#159](https://github.com/angel-vazquez18/ESP_LoRaLab/pull/159) | Host audio / verified WAV | Ready for review |
| #38 | [#160](https://github.com/angel-vazquez18/ESP_LoRaLab/pull/160) | Audio inspector / stop | Ready for review |
| #42 | [#161](https://github.com/angel-vazquez18/ESP_LoRaLab/pull/161) | Physical qualification packet | Draft; physical work pending |

All implementation issues are open in Testing while awaiting review/merge. #42 is
also open/blocked, with a draft PR: only actual count/hash and error/recovery
criteria are checked. It must not auto-close; it additionally depends on physical
USB recovery #21. There are no GitHub CI checks reported on these PRs; verification
below was run locally and recorded in their descriptions.

## Verification and hardware handoff

- Final `make check`: **383 passed**, no skips; lint, frontend production build,
  generated schemas and repository/GPIO checks passed. Final frontend formatting
  passed. Existing Starlette/httpx deprecation warning remains.
- Audio-enabled and default-disabled ESP-IDF v6.0.2 builds passed. Current enabled
  image is 0x44080 / 73% app-partition free, ELF
  `f8865602905622507888f8937be66a90dc2e00cb4cb3c64fa9ac6bf903200d65`.
- Identified `esp-f85b1ba27744`, USB `/dev/cu.usbmodem2101`. Original and fresh full
  flash backups retained/verified before authorized flashes; NVS/eFuses preserved.
  The final audio-enabled image is installed; boot69 was the last direct check.
  No active operation, port released and isolated QA server stopped.
- Real artifact roundtrips 1/1024/1025/48000/131072 bytes, CRC/offset/retry/hash/
  capacity cases passed. Real audio source/DMA counts, independent PCM hashes/WAV,
  sequential play/capture, cancellation/cleanup/recovery and current-image invalid
  CRC/SHA/odd PCM/unfinished playback rejections passed. These do not prove sound.
- Actual browser checks covered file workflows and local capture/waveform/warnings,
  play/stop, error/recovery, listening notes, disabled-image gates and retained
  history after restoration/reconnect. The WAV endpoint was byte/hash verified;
  in-app browser download location and light/mobile visual QA remain unconfirmed.
- **All microphone PCM and both raw slots are zero.** The minimal signal probe
  fails `SIGNAL_UNVERIFIED`. The cause is not established. No speech response,
  heard output, printed board revision, measured clock/rail or instrument absence
  is claimed. The user is away; prepare attended checks for later.

See [driver](../node_audio.md), [host workflow](../node_audio_workflows.md),
[UI procedure](../local_audio_ui.md) and [physical review](../milestone_2_audio_review.md).
The actual operator packet is `local/m2-batch/qualification-packet`; it includes
quiet reference PCM/WAV and actual automated recovery evidence, while human/
instrument/USB fields stay pending. `audio_qualification.py assess` returns
expected exit2/pending. Never treat its packet consistency as automatic hardware
qualification. Compact source evidence is in
[the manifest](../evidence/local_audio_2026-11-16.json).

## Preserved work and runtime evidence

Seven pre-existing edits remain unstaged and byte-for-byte equivalent in their
added/removed lines: the two issue forms, GitHub workflow/node plan/project brief/
status docs and hardware README. They are excluded from all batch commits. Their
initial patch/digests and the exact branch/PR head map remain in ignored
`local/m2-batch`. Reuse this checkout; never reset/stash those edits blindly.

Raw reports, serial records, captured WAVs, QA stores and full flash backups stay
ignored on this laptop. SHA/location/identity checkpoints are in the tracked
manifest. Screenshots `m2-file-inspector.png`, `m2-audio-inspector.png` and
`m2-audio-disabled.png` are in this chat's visualization folder. Software/native
fixtures never qualify physical RF/audio. No RF/codec/duplex capability was added.
