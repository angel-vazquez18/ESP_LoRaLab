# Finite PCM encoding (#36)

The main node now accepts an owned `audio.encode` operation. It borrows a committed
8 kHz signed-16-bit little-endian mono PCM artifact, creates fresh Codec 2 mode 3200
state, and writes a separate encoded artifact. The source stays immutable. Each
step processes at most one 160-sample frame; a later step hashes and publishes the
complete output. Codec state and the source borrow are released before reporting
the terminal result. Capture, playback, RF and another operation remain mutually
exclusive with encoding.

A 24,000-sample clip produces 150 packed eight-byte frames: 1200 bytes, with no
extra file header. Odd/incomplete PCM samples, an uncommitted/failed source, wrong
format, reused output ID and source/output aliasing reject before acceptance.
References of 1–24,000 complete samples remain valid: only the final codec frame
is zero-padded, and its original sample count and padding count are retained.
This follows the selected voice contract; partial final frames are not silently
dropped. There is no host normalization, AGC or extra signal processing here.

## Firmware responsibilities

`audio/codec_clip` owns validation, the committed source borrow, private output
reservation, fresh library state, bounded steps, timing and cleanup. The public
dependency adapter exposes create/frame/destroy without leaking its private
library headers into portable control. The pinned upstream signal-processing
code and packed format are unchanged.

`artifacts/artifact_store` reserves the derived output under the same four-slot/
262,144-byte budget. It publishes only after final SHA-256 succeeds. The encoded
manifest carries `codec2_3200_v1`, original samples, frame count and source ID.
Ordinary `artifact.begin` uploads still accept known data or PCM; this change adds
node-produced encoded output, not an incomplete encoded-upload interface.

`control/node_control` composes the worker with the existing owner, duplicate
cache, operation ID, 30-second deadline, stop/lease/disconnect/reset and serialized
writer. A command acceptance that cannot be serialized/cached unwinds the private
reservation and context. An exact duplicate returns its original acceptance and
never starts a second encoder. Cancel/failure deletes uncommitted output, releases
the source and retains partial frame/byte counts. A later valid clip gets fresh
state. A failed final hash cannot publish a completed artifact.

Codec-enabled images require the dependency PR's 32 KiB main-task stack guard.
Same-toolchain reports include an 8272-byte analysis-window constructor frame and
several nested encoding/FFT frames; the old 8192-byte task is insufficient. The
32 KiB configuration is a resource budget, with physical high-water evidence still
pending. Native process stacks do not qualify the target's stack margin.

## Timing and result meaning

The result links source ID/SHA-256, output ID/manifest, input samples, total and
completed frames, produced bytes and declared final padding. A failed/cancelled
operation has no published artifact. The host validates those relationships.

- `setup_us`: temporary owner, source/output reservation and fresh codec creation;
- `conversion_us`: explicit little-endian sample conversion and final padding;
- `codec_us`: sum of frame calls through the bounded library adapter;
- `finalize_us`: output hashing and publication;
- `started_us`, `finished_us`, `duration_us`: same-boot node uptime endpoints and
  total operation duration, including cooperative scheduling/control gaps and cleanup.

These separate codec work from overall completion time. USB/RF latency is not
included in the codec-call sum, and no cross-node clock subtraction is performed.
The native fixture's controlled clock can report zero call durations; its tests
establish behavior and bytes, not physical encoding performance.

## Testbed responsibilities and profiles

`codec_contract_v2.py` defines the finite command, declaration, compact current
availability and strict terminal result. `NodeSession` checks matching identity/
current-profile fingerprints and fresh health before writing, tracks the accepted
operation and receives its typed terminal result through the existing observer.
A mismatched profile or stale health rejects before trace callbacks or serial I/O.
GUI/CLI operation controls and retained codec workflow records remain #68/#72;
this PR does not add an operator encode button or decoder.

When encoding is available, hello's `resource_limits.codec_io` combines dependency
version/revision/options, queried dimensions and the available command list.
Health repeats only its profile/hash/commands and current `codec2_3200` flag.
An unavailable dependency remains described by hello's `codec2_library` with no
working codec command. Immutable transport/workload bounds stay in same-boot
enrollment. Current profiles, flags, applied radio settings and measurements remain
fresh; bounded health tests include all peripherals, configured RF and an error.
The codec flag now means a usable selected mode; consult commands for supported
operations. `audio.decode` is still unavailable pending #41.

Two fingerprints identify this revision:

- Artifact manifest schema: `be841147b98f69e54ac99b758dfde0ccc7e1977716017895c0aee0546e22ec6d`
  → `2f630eb2bc3f5501f2b989958fcd342ef6c0af7bdba3cf58c4dc7b61570a5d9d`.
- New codec supplement `codec_io_v1`:
  `618c7597c32752c43c6391301d9ad489f02d1097c877776690dc77fa2c11c00d`.

Rebuild matching host/node sources for file/codec work; older artifact declarations
remain historical and are not relabeled current. Main-control, diagnostic, I2S
and RF execution schema identities are unchanged. The literal artifact capability
example follows the new manifest revision; saved hardware evidence is untouched.

## Read the code in order

1. `firmware/lora_node/main/audio/codec_clip.h` / `.c`: private lifetime and one-frame work.
2. `main/artifacts/artifact_store.c`: derived metadata and hash-before-publication.
3. `components/loralab_codec2/codec2_dependency.c`: bounded frame call and fresh state.
4. `main/control/node_control.c`: acceptance rollback, duplicate/ownership lifecycle,
   partial result and compact metadata. Firmware paths 2–4 start at `firmware/lora_node/`.
5. `testbed/src/lora_testbed/codec_contract_v2.py`, `artifact_contract_v2.py`,
   `control_v2.py`, `nodes.py`: matching public shapes and host operation tracking.
6. `testbed/tests/test_codec_encode_native.py` and `testbed/tests/native/codec2_probe.c`:
   production-node byte checks versus a separate public-library reference encoder.

The reference uses the same pinned library with its recorded constructor cleanup
patch; it is independent of the production clip worker, not an independently
implemented Codec 2 algorithm. Fixed full and partial clips match it byte-for-byte.
Repeated reference clips match with new state on this build. Cross-platform
floating-point byte identity and intelligibility are not assumed.

## Reproduce software verification

From repository root with pinned native/ESP-IDF prerequisites:

```sh
uv run --project testbed pytest testbed/tests/test_codec_encode_native.py testbed/tests/test_codec2_dependency.py testbed/tests/test_artifact_contract_v2.py testbed/tests/test_node_control_native.py -q
make check
idf.py -C firmware/lora_node build size
```

Expected focused count: 141 without skips. Coverage includes exact full-clip
counts/readback, fresh repeatability, five partial-frame boundaries, invalid
sources, cancel/lease/disconnect/deadline cleanup, worker/output allocation failure,
failed final hash, 100 acceptance-allocation positions, duplicate starts, one-frame
steps, typed host results, fresh/profile gates and bounded configured-peripheral
health. The dependency's eleven real constructor allocation failures also recover
before a fresh successful query.

Final `make check` passed 625 cases without skips, Ruff, frontend production build,
byte-exact generated contracts, repository checks and retained dependency hashes.
One existing Starlette/httpx deprecation warning remains. The selected V4.2/
32 KiB ESP-IDF build passed: 0x6d870-byte image, 57% app partition free, 3840 bytes
above the corrected #29 image. Whole-image static DIRAM is 73,841 bytes (13,530
data; 8256 BSS). Temporary codec heap, producer buffers and task stack are runtime
allocations, not included in that static total. No image was flashed for #36.

## Later physical checks

First obtain a complete verified backup, identify the intended node and release
its serial owner before installing matching source. The currently observed B
backup stream failed twice, so its original audio image remains installed. Use
an unselected-RF/audio-disabled build for a CPU-only codec check when board/pin
qualification is unavailable, and keep the required 32 KiB stack setting.

1. Enroll hello/current health and verify the two fingerprints above. Keep the
   same device/boot/build identifiers in the check record.
2. Upload and commit a fixed 48,000-byte PCM reference using the existing file
   workflow. Record source UUID, byte count and SHA-256; confirm its 24,000 samples.
3. Through an owned developer `NodeSession`/v2 command envelope, issue
   `audio.encode` with `source_artifact_id` and a distinct new `artifact_id`.
   Maintain the lease and correlate its accepted/terminal operation ID.
4. Require completed status, 150 frames/1200 bytes, zero padding, matching source
   identity/hash and a committed output manifest. Retrieve all output chunks and
   independently verify exact length/SHA-256. Repeat with a new output ID and
   compare the encoded bytes on the same build.
5. Cancel a longer clip after partial progress; require no output publication,
   released source, idle recovery and a successful fresh encode. Check target
   stack/heap headroom and actual stage durations. Preserve partial failures.

Actual microphone input, decoding, speaker quality and protected RF voice remain
separate work and physical qualification. A successful encode/readback does not
qualify those stages or close #80.
