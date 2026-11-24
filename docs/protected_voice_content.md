# Protected encoded message content (#64)

Committed Codec 2 artifacts can now use the existing protected message path.
An `encoded_source` run borrows the sender's immutable encoded file, fragments it
as ordinary DATA with content type 1, authenticates/reconstructs at the receiver,
and publishes a complete recovered encoded artifact. There is no second audio
radio format. Decode and playback remain explicit finite operations after RF
completion; each reports its own timing, samples, underflows and errors.

## Firmware reading order

1. `firmware/lora_node/main/radio/rf_execution.c`: source preflight, preparation,
   source borrowing, protected insertion, publication and common cleanup.
2. `main/artifacts/artifact_store.c`: private recovered encoded producer. Ordinary
   serial uploads still cannot create encoded artifacts or commit its partial bytes.
3. `main/audio/codec_clip.c` and `control/node_control.c`: existing separate
   decode/play operations, ownership, mutual exclusion and cleanup.
4. `testbed/src/lora_testbed/run_protocol_v2.py`: typed `EncodedSourceSpec` and the
   matching execution fingerprint.
5. `testbed/tests/test_protected_voice_native.py`: actual paired C control/radio/
   crypto/reassembly and explicit audio checks with isolated SPI/IRQ/DMA seams.

The source must be committed, unused, mode `codec2_3200_v1`, and agree exactly
with declared length, original samples, complete frame count and expected SHA.
Preparation validates metadata before borrowing. The sender uses that existing
file, so it needs no extra artifact slot or duplicated source allocation. The
source remains pinned through TX and is released on completion/cancel/failure.

The receiver reserves one private encoded output and reconstructs separately.
It does not generate or assume the expected voice bytes. Session/role/header,
GCM, replay and message checks precede insertion. Complete-message SHA must match
before taking/releasing reconstructed bytes; the final stored artifact is hashed
again before it becomes available. Its recovered manifest retains remote source
artifact ID, original samples, codec, frame count and hash. Rejected/incomplete
messages never publish a decodable artifact. File/audio operations remain blocked
while RF owns the node, and private producer buffers cannot be serial-committed.

A hash mismatch after authenticated reception is recorded as reassembly
`content_mismatch`, distinct from authentication rejection. An authenticated
fragment by itself is not a delivered clip. Stop/failure removes unfinished
receiver output and releases link/borrowed buffers. A following operation gets
fresh codec state. Existing key/nonce/retry/replay lifetimes remain unchanged.

## Execution contract and budget

The existing `run.prepare` spec now also accepts:

```json
{
  "catalog_id": "VOICE-02",
  "direction": "A_TO_B",
  "source": "encoded_source",
  "message_count": 1,
  "message_bytes": 1200,
  "source_seed": null,
  "source_artifact_id": "sender encoded artifact UUID",
  "sample_count": 24000,
  "security": "aes128_gcm",
  "max_duration_ms": 30000,
  "source_duration_ms": null,
  "instrumentation": {
    "packet_events": true,
    "crypto_samples": false,
    "memory_10hz": false,
    "clock_samples": false
  },
  "expected_sha256": "sender encoded artifact SHA-256",
  "playback": false
}
```

Replace the descriptive ID/hash values with actual manifest values. Both peers
receive the same source metadata in the owned control plane. Length is required;
it must equal `ceil(sample_count / 160) * 8`, with 1–24,000 original samples.
The source is already encoded, so `source_seed` and paced duration are inapplicable.
Only AES-GCM is admitted for this source; a downgrade and implicit playback reject.
Message count defaults to one and remains bounded to one.

Use the common radio/link settings and airtime/retry budget. The selected contract's
conservative voice processing allowance adds 5,000,000 microseconds to processing
and reassembly bounds; it is not a measured codec duration. Capture/playback
budgets inside this RF operation are zero because those stages are separate.
Actual codec and audio results retain their own node-local timestamps. RF airtime,
node stage time, host transfer time and perceived acoustic delay stay distinct.

At 1200 bytes and default 160 useful bytes per fragment, expect **eight original
DATA packets**: seven 160-byte bodies and one 80-byte body. Each protected packet
adds the existing 40-byte header and 16-byte tag: 1648 DATA bytes before preamble/
PHY overhead, ACKs or retries. Stop-and-wait uses the same exact-ciphertext retry
and referenced fresh ACK behavior as known data; it never delivers a clip twice.

`execution_limits.encoded_source:true` advertises this implemented transport.
The historical profile name `known_data_execution_v1` is retained, but the exact
execution SHA changes from `3e307399…` to
`b029707a7d0c0056e808f07034e70e0a0575654772d0856695be8acc55024602`.
The schema scope now says `finite_message_execution`. Matching host/firmware must
upgrade together and re-enroll current capabilities. Prior records keep their
original profiles; no historical evidence is upgraded into a current pass.
Artifact, codec, control, audio and diagnostic schemas are unchanged here.

## Verification and limits

```sh
uv run --project testbed pytest testbed/tests/test_protected_voice_native.py -q
uv run --project testbed pytest testbed/tests/test_node_control_native.py -q
make check
# Pinned ESP-IDF v6.0.2 environment:
idf.py -C firmware/lora_node build size
```

Expected dedicated coverage: 19 cases. They verify a real committed 1200-byte
encoder output, eight protected fragments, independent GCM opening/readback,
recovered metadata, explicit decode/play counts, lost-ACK exact retry in both
directions and once-only delivery. Missing fragments, tag changes and final hash
mismatch suppress publication/playback. Transfer/decode/play cancellation releases
resources and permits a following clip. Source metadata/protection/length rejection
includes an omitted length that would otherwise match the old known-data default.
The typed host/native prepare models agree on admitted inputs.

These are actual implementation checks behind isolated interfaces, not physical
RF, microphone, speaker, clock or performance evidence. Final full `make check`
passed 694 cases without skips plus lint/frontend/contracts/repository/dependency
checks. The selected V4.2/32 KiB IDF build is 0x6e520 bytes, 57% application space
free (+1584 bytes over #41), with unchanged static DIRAM/data/bss accounting.
One existing Starlette/httpx warning remains. Full release results and the target
build are recorded in [status](status.md). The main task retains the
32 KiB requirement. No flash was performed; local audio qualification and original
checkout fixes remain separate. Host voice orchestration/comparisons follow #68;
dedicated voice controls follow #72. There is no new operator simulator.

## Remaining physical acceptance

After board identity/revision, applicable backup and matching firmware/host are
ready:

1. Capture or upload a finite source and encode it; retain complete source and
   encoded manifests. Configure both nodes identically with fresh protected keys.
2. Prepare receiver first with the same source ID/hash/sample metadata, then arm
   it, arm the sender and start within the five-second arm bounds. Expect eight originals for the 1200-byte baseline.
3. Wait for bounded RF summaries/idle, then retrieve complete encoded bytes from
   both nodes outside the RF timing interval. Independently compare exact bytes,
   hashes, lengths and frame counts.
4. Decode the receiver's committed encoded artifact into a distinct PCM ID, verify
   its expected trimmed length/hash, then request playback separately. Record
   intelligibility/distortion as observations alongside actual node stage results.
5. Repeat in reverse direction and with ACK/retry. Record real frame/attempt/
   signal evidence. Exercise stop/loss at transfer, decode and play boundaries;
   no partial clip should become playable, resources must recover.
6. Record actual rail/clock and memory/stack evidence where required; complete
   physical voice qualification remains #80. Instrument-free listening does not
   establish calibrated timing or power.

Latest physical deployment remains blocked by unsuccessful full-backup attempts
and unobserved printed PCB revisions; Node A was absent in the last USB inventory.

The common host orchestration and labelled comparison workflows are now implemented
in [#68](secure_voice_workflows.md). Receiver decode/play remain separate node
operations under that shared host owner; physical qualification stays open.
