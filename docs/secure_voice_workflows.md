# Secure finite voice workflows (#68)

The shared host now coordinates a complete protected clip workflow from an uploaded
reference or microphone capture. It reuses the existing artifact, local-audio and
radio owners. API and CLI call that same workflow; the dedicated dashboard follows
in #72. No operator simulator is added.

## Reading order

1. `testbed/src/lora_testbed/voice_runs.py`: request/preflight, stage composition,
   linked records, job-owned artifact retirement, stop/shutdown and downloads.
2. `radio_runs.py`: `EncodedRadioRunRequest` and the common protected radio
   lifecycle. Source metadata/readback adapt to encoded artifacts; configuration,
   fresh keys, receiver-first arming, observations and cleanup remain shared.
3. `node_audio.py`: the separate receiver decode job and reusable finite transform.
   Planned output IDs are retained so cancellation can account for its files.
4. `experiments_v2.py`: common airtime/retry calculations and the selected
   provisional voice processing allowance.
5. `host.py`, `app.py`, `cli.py`: one bench owner and thin shared entry points.
6. `testbed/tests/test_voice_workflows.py`: public services/API/CLI with actual
   portable C nodes behind isolated serial/SPI/IRQ/DMA interfaces.

## Stage flow

1. Validate both distinct connected identities/current profiles, codec operations,
   sender microphone when requested, receiver playback and the finite RF budget.
   A missing capability blocks before source work begins.
2. Upload validated reference PCM or perform a finite microphone capture. Reference
   WAV bytes/hash and raw PCM bytes/hash are separate. Reference count comes from
   the file; `sample_count` configures microphone capture.
3. Use the local codec workflow to verify source, encoded and locally decoded
   copies. This includes an extra sender-side decode validation step. Its copy is
   retired before RF; its time is not part of the RF interval.
4. Borrow the committed encoded source in the common protected radio runner.
   Configure both nodes, provision fresh independent source keys, arm receiver
   first, then start sender. Wait for summaries and verified exact readback before
   any receiver decode/play request.
5. Run a separately owned receiver decode, retrieve/verify PCM, then explicitly
   request playback. Driver result/counts, listening observations and qualification
   remain separate.
6. By default, run two additional protected known-data cases with the same
   direction, modem/link settings and maximum duration, recording distinct bases:

   - `equal_encoded_bytes`: known data equal to the actual encoded clip length;
   - `standard_64_bytes`: the standard 64-byte known-data workload.

   Each case uses its own common radio run and fresh key set. Set
   `include_comparisons:false` to perform only the clip workflow.
7. Confirm idle/retired session keys and retire only the job's new node artifacts.
   Verified host files and linked records remain available.

At the full three-second baseline, expect 24,000 original samples, 48,000 PCM
bytes, 150 codec frames, 1200 encoded bytes and eight default radio fragments.
Decoded PCM is lossy and has its own hash; it is not compared byte-for-byte with
its original recording. Listening/physical quality is never inferred from hashes.

## Timing and comparison meaning

The common radio runner records `rf_window_closed_at` when both terminal
summaries have been observed. Source/recovered RF readbacks start after that
marker. Source preparation and receiver decode/play occur outside the RF window.
The marker is host UTC observation time, not a calibrated RF or one-way timestamp.
Node clocks, host receipt times and acoustic delay remain distinct.

The encoded-source budget includes the selected conservative 5,000,000 us codec
allowance; matched known data does not include codec work. This is a declared
bound, not measured processing time. Child plans retain the exact applied budget,
settings and node timestamps. The equal-byte case isolates the comparison basis
from the separate 64-byte workload; it does not assert identical application CPU
work or predict signal/propagation. One-message comparisons are exploratory,
not full statistical experiment matrices.

The parent creation-to-finish interval includes preparation, local validation,
RF, retrieval, playback, optional comparisons and cleanup. Do not label it RF
latency or acoustic mouth-to-ear time. Detailed experiments/calibration remain
later work.

## Records and files

The `voice_runs_v1` record links:

- selected reference metadata or `jobs.source_audio` capture, plus any source upload;
- `jobs.codec`, `radio_run_id`, `jobs.decode` and `jobs.playback`;
- each comparison's basis, message bytes and radio run ID;
- complete initial device/boot/build/profile identities and source fingerprints;
- independent `delivery_verified`, `playback_completed`, listening and overall
  execution/cleanup outcomes.

A completed audio driver still has no automatic heard verification. Parent
`hardware_qualified` stays false. A later comparison failure does not erase real
completed clip stages, but the overall job reports its failure stage/error.
Microphone silence/clipping warnings remain in the linked audio records.

Source/encoded/recovered/decoded downloads reuse the existing independently
verified stored files and recheck length/hash. WAV wrapping is available for source
or decoded PCM only. A failed job can retain earlier verified files; unverified
or absent receiver output cannot be downloaded as valid content. CLI downloads
never overwrite an existing file.

Node artifacts are temporary job resources. The initial inventory protects
preexisting node files. The ledger tracks only new IDs, including planned codec
outputs; matching content metadata and idle ownership are checked before deletion.
The spare sender validation copy and comparison artifacts are retired when no
longer needed, keeping the four-slot store usable. Completion/failure retires the
remaining owned files after host evidence is saved. Child audio records say when
node copies are retired; their host WAV/files remain intact. This is not a general
node-store erase.

The parent waits until each child releases its owner, rather than advancing on
an early completed result during cleanup. It publishes its own terminal outcome
after cleanup. Cancellation of a caller waiting for stop cannot free bench
ownership while cleanup continues. Shutdown marks interrupted work and startup
never reconnects/resumes a voice job automatically. Unconfirmed cleanup is retained
as an error with disconnected ownership; it is not turned into a successful run.

## API and CLI

Run the matching backend at `http://127.0.0.1:8000`. Both nodes need #64's current
execution/codec/artifact profiles. This host-only change does not alter the wire
schemas or require a different firmware build than #64.

| Request | Purpose |
| --- | --- |
| `POST /api/voice/preflight` | Readiness and explicit capability/budget blockers |
| `POST /api/voice/runs` | Start a reference/microphone workflow |
| `GET /api/voice/runs` or `/{id}` | Compact history or complete linked record |
| `POST /api/voice/runs/{id}/stop` | Stop the whole pipeline with bounded cleanup |
| `GET /api/voice/runs/{id}/artifacts/{source\|encoded\|recovered\|decoded}` | Verified raw stage bytes |
| Same GET with `?as_wav=true` | Source/decoded PCM as WAV |
| `POST /api/voice/runs/{id}/listening` | Receiver playback observation, separate from driver completion |

Example start body:

```json
{
  "source": "microphone",
  "direction": "A_TO_B",
  "sample_count": 24000,
  "security": "aes128_gcm",
  "timeout_ms": 30000,
  "include_comparisons": true
}
```

For a reference, use `source:"reference"` and its uploaded `reference_id` instead;
the file supplies the sample count. Upload/inspect references through the existing
reference controls/API first. Default radio is 915 MHz, SF7/BW125k/CR4/5, requested
2 dBm; radio/link settings may be supplied explicitly within validated limits.

Root-relative CLI examples, using the actual returned identifiers:

```sh
uv run --project testbed lora-testbed voice-start --check
uv run --project testbed lora-testbed voice-start --source microphone --direction A_TO_B
uv run --project testbed lora-testbed voice-start --source reference --reference-id "$REFERENCE_ID" --direction B_TO_A
uv run --project testbed lora-testbed voice-status "$VOICE_ID"
uv run --project testbed lora-testbed voice-save "$VOICE_ID" source original.wav --wav
uv run --project testbed lora-testbed voice-save "$VOICE_ID" encoded sent.codec2
uv run --project testbed lora-testbed voice-save "$VOICE_ID" recovered received.codec2
uv run --project testbed lora-testbed voice-save "$VOICE_ID" decoded recovered.wav --wav
uv run --project testbed lora-testbed voice-listening "$VOICE_ID" --heard heard --notes "Describe intelligibility, noise and distortion"
uv run --project testbed lora-testbed voice-stop "$VOICE_ID"
```

`--no-comparisons` omits the additional data cases. `--ack stop_wait --retries 2`
selects the common reliability policy. `--sf`, `--bandwidth`, `--coding-rate`,
`--power`, `--guard-us` and `--timeout-ms` keep requested conditions explicit.
Listening can be annotated after completed receiver playback; it updates the
linked audio observation without claiming full physical qualification.

## Verification and remaining physical checks

```sh
uv run --project testbed pytest testbed/tests/test_voice_workflows.py testbed/tests/test_local_codec_host.py testbed/tests/test_node_audio_host.py testbed/tests/test_multi_fragment_radio.py -q
make check
```

Dedicated coverage has 12 new cases: common encoded transport/post-RF readback,
separate receiver decode, full reference/comparisons, reverse microphone delivery,
missing speaker rejection, failed capture recovery, cancelled/incomplete RF without
partial playback, cancelled stop caller, API downloads/listening/saved-file tamper,
CLI/no-overwrite and active shutdown/restart. Existing audio/data tests remain
applicable. Release results are in [status](status.md). No firmware source changed;
#64's selected V4.2/32 KiB build remains the prerequisite, not hardware acceptance.

On identified/backed-up matching physical boards: run a known reference and fresh
spoken phrase in both directions, independently compare encoded readbacks and
sample/frame/hash metadata, listen on the receiver and record observations. Check
both comparison bases and real radio/audio stage evidence. Exercise stop, missing
peer and failure recovery and confirm only job-owned RAM files were retired.
Record rail/clock/memory/stack evidence as required. Physical audio, RF and complete
voice qualification remain open (#42/#39/#51/#67/#80); no flash or physical
performance/quality claim was made here.
