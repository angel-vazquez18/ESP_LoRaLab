# Local audio through the host

The dashboard and CLI call one physical backend. A capture job records the finite
operation, retrieves its committed PCM with the existing verified file service,
then wraps the **unchanged** samples in a WAV. Playback runs on the node, while
WAV playback in a browser/computer is a separate inspection path. Neither proves
RF voice, speech response or acoustic output by itself.

## Operator workflow

Start `make serve`, connect the physical node in Bench overview (or use
`lora-testbed node A /dev/cu.usbmodem…`), then:

```sh
uv run --project testbed lora-testbed audio-capture A --samples 24000
uv run --project testbed lora-testbed audio-status AUDIO_JOB_ID
uv run --project testbed lora-testbed audio-save AUDIO_JOB_ID capture.wav
uv run --project testbed lora-testbed audio-play A ARTIFACT_ID
uv run --project testbed lora-testbed audio-stop AUDIO_JOB_ID
uv run --project testbed lora-testbed audio-retrieve A ARTIFACT_ID
uv run --project testbed lora-testbed audio-listening AUDIO_JOB_ID --heard not_checked --notes 'Awaiting operator'
```

The CLI addresses the default backend on port8000 and never opens a serial port.
Use IDs from command output. `audio-save` refuses to overwrite an existing file.
Capture supports 1–24000 samples; 24000 is exactly 48000 raw bytes / three seconds.
It includes the separately declared microphone startup interval before samples.
Use file upload with format `pcm_s16le_8000_mono` for an independent quiet output
reference; upload raw PCM rather than a WAV container. Only committed PCM plays.

| HTTP path | Behavior |
| --- | --- |
| POST `/api/nodes/A/audio/capture` | `{ "sample_count": 24000 }`; starts capture → retrieve → verify → WAV |
| POST `/api/nodes/A/audio/play` | `{ "artifact_id": "UUID" }`; finite playback of existing committed PCM |
| POST `/api/nodes/A/audio/retrieve` | Same ID body; independently verifies an existing PCM file and creates a WAV |
| GET `/api/audio/operations` or `/{id}` | Shared persisted progress/results/errors |
| POST `/api/audio/operations/{id}/stop` | Priority cancellation and cleanup |
| GET `/api/audio/operations/{id}/wav` | Verified saved WAV, rechecked against retained PCM and hashes |
| POST `/api/audio/operations/{id}/listening` | `{ "heard": "not_checked\|heard\|not_heard", "notes": "…" }`; separate operator observation |

Replace A with B as needed. Capture/play commands require the exact audio
supplement, configured direction, fresh health and an owned idle node. Other
bench operations reject while an audio job owns the bench, including its internal
file download. Stop remains available during that download. No automatic resume
after disconnect/reset/restart occurs. Restart marks running records interrupted.

Completed capture files remain in bounded node RAM for later playback; delete
unneeded ones through the file inspector. Captured host PCM/WAV and results remain
saved after node deletion/reset. Failed/cancelled jobs remove partial/new captures;
playback preserves its existing source. Cleanup uncertainty and errors stay in the
record; disconnect releases ownership when cleanup cannot be confirmed. Missing
completion events time out and fail, even if later health confirms the node idle.

## Reading the findings

The record retains device/boot/build identity, audio schema/configuration, source
fingerprint, timestamps, raw command/reply/operation-event evidence, linked file
transfer/hash evidence, node result, cleanup and separate listening observations.
`node_audio/` stores bounded job NDJSON/WAVs; `node_artifacts/` stores independently
verified PCM/download evidence. Running jobs are not usable audio files.

Inspection reports exact count, 8 kHz / signed16 LE / mono, PCM SHA-256, duration,
peak, RMS, sample extrema waveform and samples exactly at −32768/32767. Near silence
means RMS ≤32 PCM units; this declared threshold is diagnostic, not an acoustic
acceptance criterion. All-zero PCM receives a prominent signal warning. A byte-
valid silent WAV can complete retrieval while microphone response stays unverified.

Configuration and node results preserve 1/8 output amplitude, −18.0618 dB software
output gain, configured 6 dB amplifier gain and input conversion with unity added
capture gain. Clocks/rates are configured/calculated until instrument evidence
exists. Driver completion and operator `heard` notes never set hardware qualification.
Notes can be recorded after a job terminates, without rewriting its driver result.

## Code walkthrough and verification

- `node_audio.py`: one bounded job lifecycle and bench owner; actual node completion,
  exact count/DMA checks, verified transfer reuse, cancellation and durable evidence.
- `audio.py`: explicit PCM metrics and WAV wrapping with no sample conversion.
- `nodes.py`: exact direction-specific compatibility, live readiness and fresh-health
  operation reconciliation; no invented completion after a lost result.
- `host.py`, `app.py`, `cli.py`: shared service/ownership and public interfaces.
- `storage.py`: persistent audio records and interrupted restart handling.

All paths above are under `testbed/src/lora_testbed`. Run:

```sh
uv run --project testbed pytest testbed/tests/test_node_audio_host.py
make check
```

Expected: **24 focused cases / 360 total tests pass**, no skips. Focused cases use
production native C control with an isolated DMA seam: exact WAV samples/counts,
CRC/hash/terminal-count corruption, stop before start/during physical-write latency/
during capture/download, lost results, live capability loss, disconnect, shutdown/
restart, zero-signal warning, API integrity checks and CLI routing. Fixtures do not
qualify microphone/speaker hardware.

November16 actual-board host checks passed capture of 24000 samples, independent
48000-byte PCM hash/WAV wrapping, quiet-reference driver completion, cancellation
and a following valid capture, with zero observed gaps/framing errors. The capture
was **all zero**, and its explicit signal warning was verified. Evidence is retained
in ignored `local/m2-batch/host-audio-hardware-report.json` and `host-audio-data/`.
Physical microphone response, printed revision, listening, clocks/rail and #21
recovery qualification remain open; see [driver behavior](node_audio.md).
