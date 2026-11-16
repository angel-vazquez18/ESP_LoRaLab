# Node file-transfer contract

Issue [#2](https://github.com/angel-vazquez18/ESP_LoRaLab/issues/2), November 15, 2026.
This defines the file-transfer interface and host validation. Issue #11 adds real
RAM reservations, listing and deletion to the portable main firmware. Chunk
uploads (#14), final commit (#18), readback (#22), host workflows (#26) and audio
drivers remain follow-up work. Native checks exercise the production C store;
they do not establish physical board behavior.

An artifact is a named block of bytes in the node's RAM. It is not a filesystem
path and is not written to flash/NVS. File transfer requires an identified,
claimed, idle node; it does not require a second node, radio session, microphone,
amplifier or speaker. `run_id` can be null for local work. When associated with a
run, preserve its ID and obey the same owner/boot/session checks. Reject file
access during an active measurement or operation with `BUSY`.

## Messages and limits

Use the existing wire-v2 command/reply envelope, including the boot target and
monotonically increasing command sequence. Every argument below is required;
unknown fields are errors. All byte counts/offsets are strict JSON integers,
not strings, floats or booleans. The outer NDJSON record still fits 4096 bytes
including LF.

| Command | Arguments | Successful result |
| --- | --- | --- |
| `artifact.begin` | `artifact_id, kind, length_bytes, sha256, format` | `artifact_id, next_offset: 0` |
| `artifact.put` | `artifact_id, offset, data_b64, crc32` | `artifact_id, next_offset` |
| `artifact.commit` | `artifact_id` | One committed manifest |
| `artifact.list` | `{}` | `artifacts`: at most four manifests, including unfinished files; no contents |
| `artifact.get` | `artifact_id, offset, length_bytes` | `artifact_id, offset, length_bytes, data_b64, crc32, eof` |
| `artifact.delete` | `artifact_id` | `artifact_id, deleted: true` |

These commands return synchronous replies. An upload is a series of bounded
requests, not an asynchronous operation with an invented operation ID. Cancel a
host upload by stopping new chunks and deleting its unfinished artifact while
ownership is available. Existing operation cancellation remains responsible for
actual audio/diagnostic operations; these transfer definitions do not implement them.

| Resource | Profile ceiling |
| --- | --- |
| Reserved files | 4 per node |
| One file | 1–131072 bytes |
| Total reserved bytes | 262144, including unfinished and failed files |
| One chunk/read request | 1–1024 decoded/raw bytes |
| Base64 text for one chunk | At most 1368 characters |

Reserve the entire declared size at begin, check both slot and byte budgets before
allocation, and leave existing files untouched on failure. Report lower real
limits when needed; the host checks them before writing. A model-valid request
can still fail because the node's remaining free budget is insufficient.

`kind` is `source` or `recovered`, preserving the existing input/output distinction.
This first transfer profile supports two formats:

- `known_data`: opaque bytes; audio metadata is null. Stored file size is distinct
  from the separate 65536-byte RF message limit.
- `pcm_s16le_8000_mono`: signed 16-bit little-endian mono samples at 8000 Hz,
  1–24000 samples. Its byte length is even and at most 48000. Upload raw PCM,
  not a RIFF/WAV container; WAV wrapping/import belongs to the host workflow.

Codec 2 formats are not accepted by this initial profile. Add/version their
metadata and examples before advertising that later support; never mislabel
compressed bytes as PCM. Supporting PCM storage does not imply audio playback.

## Upload, retries and file lifetime

1. `begin` reserves an unused ID and starts an `uploading` file at offset zero.
   A new begin using an existing ID returns `INVALID_STATE`; do not overwrite it.
2. A new chunk must start at the current write offset, fit the declared file and
   pass standard canonical Base64 decoding and CRC-32/ISO-HDLC. The checksum is
   the `zlib.crc32` value as eight lowercase hex digits. Validate before writing.
3. An already-written range may be retried only when the bytes match exactly and
   the complete range is already present. Return the original chunk-end offset
   without rewriting data or moving the current cursor. Compare bytes, not only
   CRC values. A gap, conflicting repeat or partly overlapping append returns
   `OFFSET_MISMATCH` without changing contents/cursor.
4. `commit` requires the full declared length and matching lowercase SHA-256 over
   the exact bytes. An incomplete commit returns `INVALID_STATE` and stays
   `uploading`; a final hash failure returns `CHECKSUM_MISMATCH` and becomes
   `failed`. Neither can be consumed. Delete a failed file before starting again.
5. A successful commit becomes read-only. Repeating commit for that committed
   ID returns its unchanged manifest. `put` cannot modify a committed/failed file.
6. `get` exposes only committed bytes. It returns at most the requested length,
   clips the final chunk and includes its actual length/CRC. Offset equal to file
   length returns an empty EOF chunk (`data_b64: ""`, CRC `00000000`). An offset
   beyond the file returns `OFFSET_MISMATCH`.
7. Explicit delete frees a slot and its reservation. Reject a file in use with
   `BUSY`; never silently evict it. Unknown IDs return `ARTIFACT_NOT_FOUND`.

`artifact.list` and `artifact.get` are read commands; a timed-out read is retried
with a fresh command ID/sequence. Begin/put/commit/delete are mutating commands.
The normal 16-entry command-reply cache handles their exact wire retries. The chunk
rule above also applies to a fresh command ID/sequence repeating existing bytes;
these are separate tests. Reusing a command identity with changed arguments still
returns `COMMAND_CONFLICT`, before any file change.

Unfinished/failed files belong to their uploading claim and boot. Delete them at
session close, claim release, lease expiry or detected disconnect, including the
control-only path that has no RF session. They cannot resume under another claim.
Committed files remain through session/claim close until explicitly deleted or the
node reboots. Release all active consumers before deleting their files. Reboot
clears all RAM files; old IDs/boot-targeted requests cannot address new contents.

## Manifest and errors

A manifest contains the begin fields plus `state`, `next_offset`, `in_use`,
`codec`, `sample_rate_hz`, `sample_count`, `frame_count`, `source_artifact_id`.
States are `uploading`, `failed`, `committed`. Only a complete committed file may
be in use. `next_offset` never exceeds declared length and equals it at commit.
PCM has rate 8000 and sample count `length_bytes/2`; known data has null rate/count.
`codec` and `frame_count` are null in this profile. `source_artifact_id` is a UUID
or null, recording origin where applicable. Listing does not expose bytes.

Reuse the selected contract's errors: `INVALID_ARGUMENT` for malformed fields,
`RESOURCE_LIMIT` for advertised/reservation ceilings, `ALLOCATION_FAILED` for an
actual allocation failure, `CHECKSUM_MISMATCH` for CRC/final-hash mismatch,
`OFFSET_MISMATCH`, `ARTIFACT_NOT_FOUND`, `INVALID_STATE` and `BUSY` as above.
Ownership, boot and command-identity checks retain their existing errors. Only
explicitly transient busy/I/O/timeout errors may be marked retryable. Host-side
argument validation rejects malformed requests before sending; raw firmware
validation implements reservation/list/delete errors; chunk/hash/read errors
remain in their follow-up issues.

## Compatibility and implementation boundary

The six commands were already specified in contract 2.0.0. This work gives that
unimplemented subset its first exact `artifact_transfer_v1` schema; it changes
neither wire version nor any existing diagnostic/control/execution digest.

The [typed models](../testbed/src/lora_testbed/artifact_contract_v2.py) generate
[artifact.schema.json](../contracts/v2/artifact.schema.json). The
[examples](../contracts/v2/artifact_examples.json) include a valid/invalid argument
and result for each command and a complete command envelope. Cross-field rules,
CRC and reply correlation use the typed validators in addition to structural
JSON Schema. State-dependent admission, buffers and actual final-file SHA-256
require firmware checks; schema validation cannot establish them. The #11 store
implements reservation admission/buffers, not final-file SHA-256 or commit.

Implemented firmware must explicitly add `artifact_transfer` inside
`hello.capabilities.resource_limits` and
`health.capability_availability.resource_limits`, with these fields:

- `profile: artifact_transfer_v1` and the exact generated artifact `schema_sha256`;
- `commands`: the unique list of actually implemented file commands;
- `max_artifact_bytes`, `node_total_artifact_bytes`, `node_artifact_slots`,
  `artifact_chunk_bytes`, within the ceilings above and internally consistent.

The main firmware now advertises only `artifact.begin`, `artifact.list` and
`artifact.delete`, using generated `main/generated/artifact_profile.h` constants.
`artifact.put`, `artifact.commit` and `artifact.get` remain unavailable; diagnostic
firmware advertises none. A complete upload/download workflow requires all six.
Do not advertise commands merely because their schema exists.
The existing exact main-control handshake is still required. Diagnostic firmware,
missing descriptors or missing commands fail with `MISSING_CAPABILITY`; unknown
profiles/digests or malformed declarations fail with `UNSUPPORTED_VERSION`.

`NodeSession.request` requires the declaration from hello and checks current
health support/limits when available before a
serial write, then validates successful result shape, file ID, offset and chunk
integrity. It does not add a transfer loop, store files, enable UI controls or
make absent hardware usable. The earlier known-data execution format is a separate
profile; its old artifact types/digest are not silently reused or expanded.

## Verification and handoff

From the repository root:

```sh
uv run --project testbed pytest testbed/tests/test_artifact_contract_v2.py testbed/tests/test_nodes.py
make contracts-check
make check
```

The cases cover every command's positive/negative example, strict numeric fields,
1/1024/1025-byte boundaries, CRC/Base64 rejection, PCM metadata, four slots/full
byte budget, lower limits, reply identity/ranges, EOF and following valid requests.
Isolated serial peers also prove that missing/mismatched support sends no file
command. They are protocol fixtures, not a simulated file store or hardware proof.

## Reservation implementation and review (#11)

Read the [store interface](../firmware/lora_node/main/artifacts/artifact_store.h),
[store implementation](../firmware/lora_node/main/artifacts/artifact_store.c), then
[control integration](../firmware/lora_node/main/control/node_control.c). The store
owns four private slots, full-length RAM allocations, manifests, owner cleanup and
consumer guards. The control layer owns identity/lease/idle checks and JSON replies.
No raw data pointer is available to a consumer until a file is committed.

For `begin`, validate fields and budgets, allocate the full length, then construct
and cache the reply. If reply construction fails, undo the new reservation. For
`delete`, validate first, construct/cache/enqueue the reply, then free the slot.
Exact command retries reuse the reply without another allocation/free. Listing
is a read and can return all four manifests without the mutation cache's 1024-byte
limit. Health reports `memory.buffers.artifacts_reserved`, including unfinished
files, separately from free-heap observations. A declared SHA-256 is metadata at
this stage, not evidence that any bytes have been uploaded or verified.

Claim release, five-second lease expiry and detected disconnect free that owner's
unfinished/failed files. Destroying the control core frees all RAM files. RF
`session.close` is still unavailable; its cleanup hook must be integrated when
sessions are implemented. Committed files have explicit acquire/release protection
and survive ownership changes, but no wire command can create one until #18.

From the repository root, run:

```sh
uv run --project testbed pytest testbed/tests/test_node_artifacts_native.py testbed/tests/test_node_control_native.py -ra
```

Expected at this checkpoint: **112 passed, no skipped tests**. This compiles the
production C parser/control/store and locked cJSON. Cases cover four slots/fifth
rejection, the full 262144-byte budget, 131072-byte ceiling, PCM metadata, actual
buffer allocation failure, exact command retries, stale boot/non-owner/busy
requests, release/lease/disconnect/reboot cleanup, reply backpressure and every
injected JSON allocation failure across reservation/deletion reply construction.
A real `NodeSession` also exercises begin/list/delete against that C core and
blocks unsupported commit before serial writing.

The separate native lifecycle fixture explicitly seeds committed/failed state
inside the production store translation unit to check consumer guards, in-use
delete rejection and lifetime rules. It adds no production test hook, commit
handler, upload bytes or hash verification. These cases do not qualify #18 or
physical audio. All ordinary wire cases use the public control interface.

Also run `make check`, `make contracts-check`, frontend formatting, and the main
ESP-IDF build from [development commands](development.md). Build/check results do
not prove the connected board runs this source. Keep physical flash, heap behavior
and USB cleanup acceptance separate, with matching identity and released ownership
before authorized board work. No physical port is needed for this software issue.

Next implement actual chunk admission/retry (#14), final byte/hash commit (#18),
readback (#22) and the host transfer workflow (#26).
