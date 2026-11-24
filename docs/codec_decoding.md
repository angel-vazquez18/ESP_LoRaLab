# Finite Codec 2 decoding (#41)

An owned `audio.decode` operation converts a committed `codec2_3200_v1` artifact
into a separate `recovered` PCM artifact. It never starts the speaker. The encoded
source remains immutable and borrowed until completion or cleanup. A 1200-byte
clip contains 150 frames and produces 24,000 signed-16-bit little-endian samples
(48,000 bytes). Decoding is lossy: the decoded bytes are hashed as their own file,
not compared with the original recording.

## Firmware path

Read `audio/codec_clip.c`, then the codec dependency adapter and
`artifacts/artifact_store.c`. The worker checks the committed format, mode-specific
frame geometry and declared sample count before allocation. It creates a fresh
actual library context, reserves PCM under the existing four-slot/262,144-byte
budget, and decodes at most one eight-byte frame per step. Only declared samples
are copied from the final 160-sample frame; padding is trimmed explicitly.
A later step hashes and publishes the finished output. Failed/cancelled work
releases the source/context and removes its private output.

`control/node_control.c` owns command acceptance, operation identity, duplicate
reply caching, stop/lease/disconnect/deadline cleanup and the serialized result.
The same finite worker/lifecycle serves encoding and decoding. An exact duplicate
acceptance keeps one worker; active artifacts cannot be deleted. Audio capture,
playback and RF remain mutually exclusive with this operation. Playback is a
separate, explicitly requested `audio.play` command.

The only encoded inputs currently admitted to this node store come from the
completed encoder. Ordinary uploads still admit known data or PCM, so truncated
or untyped arbitrary bytes cannot be presented as a ready encoded artifact.
The worker also checks exact length = frame count × 8 and
frame count = ceil(original samples / 160). Typed manifest validation rejects
incomplete/unsupported declarations. No encoded import protocol is added here;
remote encoded-artifact admission belongs to the protected voice workflow.
Whole aligned raw codec frames have no intrinsic checksum or authenticity;
validating their format does not establish that their contents are trustworthy.

## Decoder state correction

The upstream `codec2_rand` phase generator used a process-wide static value.
Two fresh public-library contexts decoding one identical frame reproduced
different samples without involving node buffers. Recorded patch
`0002-keep-decoder-phase-random-state-per-context.patch` moves that value into the
codec context and passes it through phase synthesis/postfilter calls. Each context
starts with the original seed 1 and uses the original arithmetic; packed encoded
bytes, codebooks and mode are unchanged. It is a phase generator, not security
randomness. Repeated and interleaved contexts now agree and cannot advance one
another's phase stream. The dependency importer applies both recorded patches
and verifies the retained resource hashes.

The actual fault allocator checks all eleven constructor positions and a normal
extra position, followed by a fresh successful decode in the same process. Its
observed requested heap peak is 31,324 bytes on this native build, excluding
allocator overhead; this is not an ESP32 measurement.

## Testbed responsibilities and result

Read `codec_contract_v2.py`, the codec gate in `nodes.py`, and the decoder checks
in `test_codec_decode_native.py`. The shared session gates matching hello/current
codec declarations and fresh health before serial writes, tracks the accepted
operation and validates the terminal result. The compact current declaration lists
both `audio.encode` and `audio.decode`. API/CLI workflow and saved provenance are
#45; RF voice orchestration/UI remain #64/#68/#72.

The decoder result records source ID/hash, output ID/manifest, declared/completed
samples and frames, produced PCM bytes, trimmed padding and node-local setup,
conversion, codec-call, finalize and total timing. A failed operation retains its
partial counters and error; no partial file is reported as committed.

Three `memory` snapshots use the existing platform memory callback:

- `before`: before source/output/context setup;
- `ready`: after setup, before acceptance/result JSON construction;
- `after`: after context/source cleanup, before result JSON construction.

Each retains internal/PSRAM free/minimum/largest bytes and allocation-failure
count. Successful `after` still includes the published PCM output. These are
snapshots, not a continuous operation peak. Heap minima are boot-wide. The native
fixture reports its injected memory model and excludes the library's real malloc
heap; actual library allocations are checked separately by the allocator probe.
Physical memory/stack qualification remains open. Codec-enabled images retain the
32 KiB main-task requirement; native tests do not qualify target stack margin.

## Verification and review

```sh
uv run --project testbed pytest testbed/tests/test_codec_decode_native.py testbed/tests/test_codec_encode_native.py testbed/tests/test_codec2_dependency.py testbed/tests/test_node_control_native.py -q
make check
# In the pinned ESP-IDF environment:
idf.py -C firmware/lora_node build size
```

Expected focused result: 152 passing cases, no skips. The decoder file contributes
37 cases: complete reference output, boundary padding/fresh state, interruption,
worker/output/hash failures, untyped/truncated input, malformed manifests, shared
host tracking, actual constructor failure positions, duplicate ownership and
interleaved phase independence. The separate native reference executable calls the
public library directly and compares decoded output; it does not compare lossy
PCM with its original recording.

Full checks: 662 cases, no skips, plus lint/frontend/contracts/repository/resource
checks. Selected V4.2/32 KiB ESP-IDF build: 0x6def0 bytes, 57% application partition
free, +1664 bytes over #36. Static DIRAM remains 73,841 bytes; data 13,530 and bss
8256. Runtime codec/output allocations are additional to that static accounting.

The codec supplement changes to
`d5786bfccce2339b4af139d196d54d6646c8a35b6d9b77e04888166d3e614efe`.
Upgrade matching host and firmware together; old evidence keeps its original
fingerprint. Artifact, main-control, diagnostic, audio and execution digests stay
unchanged from #36. Re-enroll identity/current health before codec work.

## Remaining physical checks

No image was flashed for this issue. Node B still runs its existing audio image;
required full-flash backup attempts failed. Node A is not currently enumerated,
and printed PCB revisions are unobserved. Those are deployment prerequisites,
not software failures or completed hardware acceptance.

After matching identity, applicable backup and verified board configuration:

1. Capture or upload/commit a three-second PCM source; retain its ID and hash.
2. Use the shared owned session to encode into a fresh UUID, then decode the
   committed encoded ID into another fresh UUID. Expect 150/150 frames and
   24,000 samples, no unsolicited playback, and a new committed 48,000-byte PCM.
3. Read back the encoded and decoded artifacts in full. Independently verify each
   file hash/length and link the decoded source ID to the encoded artifact.
4. Inspect the decoded PCM as 8 kHz mono WAV, then request node playback
   separately. Record intelligibility, noise and distortion as listening
   observations. Do not claim lossless source equality.
5. Record same-boot timings and the three actual heap snapshots. Measure main-task
   stack high-water margin across repeated encode/decode cycles separately.
6. Stop a decoder in progress, check idle/source release/no partial PCM, then run
   a fresh clip. Exercise reset/disconnect recovery with retained host evidence.

Full physical voice acceptance remains issue #80.
