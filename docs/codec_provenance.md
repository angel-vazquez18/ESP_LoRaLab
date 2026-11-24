# Local codec workflow and three-file provenance (#45)

The shared `NodeAudio` owner can encode and decode one committed PCM source, then
retain independently retrieved source, encoded and decoded files. This is local
codec verification, separate from protected RF voice and acoustic qualification.
The API and CLI call this same service; there is no operator simulation path.

## Reading order

1. `testbed/src/lora_testbed/node_audio.py`: `start`, `roundtrip`, `download`,
   cleanup and `codec_content`/`link_playback`.
2. `app.py` and `cli.py`: the thin shared API/CLI entry points.
3. `codec_contract_v2.py`: the existing exact profile and typed stage results.
4. `testbed/tests/test_local_codec_host.py`: real portable C nodes behind isolated
   serial/DMA fixtures, including negative and recovery cases.

The existing audio owner keeps the bench for the whole job. It retrieves the
source first, requests `audio.encode` with a separate UUID, verifies/readbacks the
encoded result, requests `audio.decode` with a third UUID, then verifies/readbacks
PCM and writes its WAV wrapper. Each transfer uses the existing CRC/length/SHA
service. Encoding/decoding retain their own correlated node-local results/times.
No stage starts playback automatically. Capture/playback/RF/other host work cannot
compete with the job.

## Saved record and interpretation

- `source_artifact_id` and `source_manifest` retain the selected input. A matching
  earlier microphone capture is linked only when role, boot, artifact ID **and
  content hash** agree. Deleting/reusing a node artifact ID cannot attach a
  different recording's provenance.
- `codec_artifacts.source|encoded|decoded` retain the complete manifest, transfer
  ID and verification flag for each separate saved file. The linked transfer
  record retains host start/finish times, byte progress, hashes, errors and raw
  serial evidence. Node-local times are not subtracted across independent clocks.
- `codec_operations.encode|decode` retain operation IDs and observed terminal
  results, including stage timing and decoder heap snapshots. An accepted stage
  without an observed terminal result remains explicitly incomplete.
- `verified_roundtrip` becomes true only after both complete operations and all
  three independent file checks. It is false on failure, cancellation or restart.
  The assessment explicitly calls source-vs-decoded lossless equality inapplicable.
- On success, the top-level `artifact_id`, `transfer_id` and existing WAV/clip
  fields refer to decoded PCM. Codec child results stay in `codec_operations`;
  the existing audio-DMA `node_result` field is not overloaded.
- `hardware_qualified` remains false. Driver completion, exact encoded bytes and
  intelligible/heard speech are separate findings.

At 24,000 original samples, expect source 48,000 bytes, encoded 150 × 8 = 1200
bytes, and decoded 48,000 bytes. For a partial final frame, preserve the original
sample count and trim padding. Each file has its own ID/hash. The separate native
reference encoder verifies encoded bytes exactly; decoded PCM is lossy output.

Failures/cancel preserve verified earlier files and failed transfer/operation
references. Partial/unverified stages cannot be downloaded as verified content.
Stopping an active codec also waits for its correlated partial terminal result
within bounded cleanup. Disconnect/boot change never resumes work. Committed
node files remain available in that boot; unfinished codec buffers are discarded.
The store has four slots, so delete unused prior derived node files before another
round trip. Saved host files remain independent of node RAM retention.

All downloads recheck the saved file's length/hash, including after a previous
successful run. WAV wrapping applies only to PCM. CLI downloads use exclusive
creation and never overwrite an existing target.

## API and CLI

Start the matching backend at `http://127.0.0.1:8000` and connect either node role.
The node must advertise the exact current codec and artifact profiles, fresh
health and both finite codec commands. Old/unavailable images reject explicitly.
No wire schema or firmware image changes in this host-only issue; #41's matching
codec image remains required.

| Request | Behavior |
| --- | --- |
| `POST /api/nodes/A/audio/codec` with `{"artifact_id":"source UUID"}` | Start local round trip; returns job ID |
| `GET /api/audio/operations/{id}` | Status, three-file provenance, child results and errors |
| `GET /api/audio/operations/{id}/artifacts/{source\|encoded\|decoded}` | Verified raw bytes, including retained valid stages of an unsuccessful job |
| Same GET with `?as_wav=true` | Verified source/decoded PCM wrapped as WAV |
| `POST /api/audio/operations/{id}/stop` | Stop the shared job and clean up |
| `POST /api/audio/operations/{id}/playback` with playback `operation_id` and optional `stage` | Link a completed source/decoded playback observation |

Use the returned IDs in these root-relative examples. Wait for each job to finish
before starting its dependent operation:

```sh
uv run --project testbed lora-testbed audio-capture A
uv run --project testbed lora-testbed audio-status "$CAPTURE_JOB_ID"
uv run --project testbed lora-testbed audio-codec A "$SOURCE_ARTIFACT_ID"
uv run --project testbed lora-testbed audio-status "$CODEC_JOB_ID"
uv run --project testbed lora-testbed audio-codec-save "$CODEC_JOB_ID" source source.pcm
uv run --project testbed lora-testbed audio-codec-save "$CODEC_JOB_ID" encoded encoded.codec2
uv run --project testbed lora-testbed audio-codec-save "$CODEC_JOB_ID" decoded decoded.wav --wav
uv run --project testbed lora-testbed audio-play A "$DECODED_ARTIFACT_ID"
uv run --project testbed lora-testbed audio-status "$PLAY_JOB_ID"
uv run --project testbed lora-testbed audio-listening "$PLAY_JOB_ID" --heard heard --notes "Describe clarity, noise and distortion"
uv run --project testbed lora-testbed audio-link-playback "$CODEC_JOB_ID" "$PLAY_JOB_ID"
```

Use `--stage source` to link a source playback instead. Links require completed
playback for the same stage manifest, role, device and boot. Changed content under
a reused ID is rejected. New playback records retain their starting manifest;
older records without it cannot establish that exact link. Listening notes are
snapshotted when linked; explicitly relink to update a changed observation.
At most 32 linked playback observations are retained per codec job. No listening
note automatically qualifies hardware. Detailed codec UI remains issue #72.

## Verification

```sh
uv run --project testbed pytest testbed/tests/test_local_codec_host.py testbed/tests/test_node_audio_host.py -q
make check
```

Expected focused coverage: 13 new codec cases plus 25 existing audio cases. The
new cases exercise a full three-second reference comparison and all file hashes,
API downloads/WAV/notes/tamper checks, CLI routing/no-overwrite, encode/decode
cancellation and allocation failure, CRC/SHA transfer failure/recovery, UUID alias
rejection, capture/playback content provenance under ID reuse, and unavailable
codec rejection. The native serial fixture now forwards its actual codec-mode
selection rather than silently using the default.

Final `make check` passed 675 cases without skips, plus lint, frontend build,
generated contracts, repository invariants and retained dependency hashes. One
existing Starlette/httpx deprecation warning remains. Full release check and
physical status are recorded in [status](status.md).
This issue changes no firmware source, so it reuses #41's selected-board build;
it does not flash, alter NVS or claim a new target build.

## Physical acceptance still required

On an identified board running matching backed-up/reviewed firmware: capture a
fresh phrase; run the workflow; independently inspect the three file sizes/hashes;
listen to original and decoded WAV on the host; play source and decoded PCM on the
node separately and link the observations. Record actual node timings, heap/stack
margin and any underflows/distortion. Stop a codec job and confirm a following
job succeeds after clearing unused node artifacts. Secure two-node delivery and
complete voice acceptance remain #64/#68/#80. Latest deployment remains blocked
by unsuccessful backup attempts and unobserved PCB revisions; no flash occurred.

The audio owner also supports a separate finite receiver decode job for the
[#68 secure voice workflow](secure_voice_workflows.md). It retains planned output
IDs, encoded input and verified decoded PCM without claiming a local round trip.
Voice-owned temporary node copies can retire after host verification; saved
audio files and listening/provenance records remain available.
