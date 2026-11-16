# Local audio in the node inspector

Start `make serve`, connect the board in **Bench overview**, then choose
**Inspect node → Local audio**. The configured capture/playback paths come from
the shared backend's exact live readiness. A firmware flag is not proof of a
working microphone/speaker. The microphone currently returns all-zero raw slots;
its signal response remains unverified.

## Check the workflow

1. Choose **Capture 3 seconds**. Other capture/play/file actions must disable while
   the shared job runs. **Stop audio** remains available during recording and
   retrieval. The backend independently enforces the same sequencing.
2. Wait for retrieval/verification. Expect 24000 samples, 48000 bytes, three seconds,
   a PCM SHA-256, min/max waveform, peak/RMS and clipped-sample count. All-zero data
   must show a signal warning; it never establishes microphone response.
3. Choose **Play clip on node** for a current-boot captured file, or **Play file on
   node** on a committed PCM file in **Node files**. Expect a separate node-driver
   operation/result. Capture remains disabled during playback. The file's format,
   current boot and availability are checked again by the backend.
4. Expand **Operator listening** and record an actual speaker observation/notes
   after the job finishes. Leave **Not checked** until someone listens. These notes
   never rewrite the driver result or establish automatic hardware qualification.
5. **Save verified WAV** requests the integrity-checked WAV. **Listen on this
   computer** uses the laptop, not the node speaker. Inspect PCM bytes/format/hash
   independently using the [host workflow](node_audio_workflows.md).
6. Stop a capture during recording or retrieval, then start a following operation.
   Expect cancelled status, retained error/cleanup evidence and restored controls.
   Delete only disposable test files to check missing-file errors; saved WAV and
   waveform findings must remain. A following valid request must clear the error.
7. Disconnect/reconnect or change to an audio-disabled image. Expect unavailable
   controls and explanations, with saved findings still visible. Previous-boot
   files cannot play on the new boot; no audio restarts automatically.

The configured output is 12.5% sample amplitude with a reported 6 dB amplifier
strap. Sample rates/gain are configuration metadata, not electrical measurements.
RF voice/codec paths remain unavailable; the Voice workspace points to these
local controls without implying that its entire RF pipeline is implemented.

## Code walkthrough

- `NodeAudio.tsx`: shared job progress, priority stop, waveform/signal findings,
  current-boot playback gating and separate listening form/computer preview.
- `NodeArtifacts.tsx`: existing PCM files call the same play/retrieve backend.
- `HardwareBench.tsx`: integrates audio with the inspector, capability wording and
  bench ownership; non-memory results do not display invented verified-byte counts.
- `main.tsx`: shared audio state and operation gating; no browser-owned audio runner.
- `nodes.py`: starts each reconnect with a fresh health age; its new test holds
  the handshake and verifies that stale previous health cannot label it unresponsive.

Frontend paths are under `testbed/frontend/src`; the session is in
`testbed/src/lora_testbed`. No browser serial access, resampling or independent
acceptance criteria are added.

## November16 verification

- `make check`: **361 passed**, no skips; lint, production frontend, generated
  contracts and repository checks passed. The new reconnect case is in
  `test_node_audio_host.py` (25 host audio cases total).
- `npm --prefix testbed/frontend run build` and `format:check`: passed on final UI.
- Real-board browser: capture → retrieval → exact counts/hash/flat waveform and
  explicit all-zero warning; node playback completion; capture disabled during
  playback; stop during retrieval/playback; cleanup and following valid request;
  missing-file error; pending-listening note persisted separately.
- The WAV link was clicked and its served WAV bytes/format/hash independently
  verified. The in-app browser's downloaded-file location was not confirmed;
  no claim is made about a file saved in Downloads. Verified WAV remains in the
  host store and ignored `local/m2-batch/audio-ui-verified.wav`.
- Actual default audio-disabled image was built/flashed to the identified board
  after backup/port checks. Browser capture/play controls disabled with clear
  explanations and retained findings on boot66. Audio-enabled image was restored,
  matched by ELF, and fresh controls/history observed on boot68. NVS/eFuses retained.
- Final board port released and isolated QA server stopped. No sound was claimed
  heard, speech response observed, or clocks/rail measured. Light/mobile visual
  QA was not performed; existing theme variables/responsive conventions are used.

Ignored QA states/evidence: `local/m2-batch/audio-ui-*-state.json` and `browser-qa/`.
Screenshots: `m2-audio-inspector.png`, `m2-audio-disabled.png` in this task's
visualization folder. Full hardware qualification (#42/#21) remains incomplete.
