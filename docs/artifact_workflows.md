# Local node file workflows

Issue #26 adds one backend-owned workflow shared by API and CLI. It uses the
physical `NodeSession`; no simulator mode or second port owner is introduced.
Main firmware must advertise the exact artifact profile and needed commands.
One connected A or B node is sufficient. Audio operation is a separate capability.

## What a successful transfer means

An upload reserves a fresh node ID, sends contiguous bounded CRC chunks, commits,
then reads the committed bytes back and independently checks exact length, bytes
and SHA-256. A download lists a committed file, reads its chunks and checks the
same length/hash before saving. Only verified bytes become a downloadable host
file. An incomplete transfer or failed final check never becomes a successful
saved-file record. Raw PCM is accepted explicitly; WAV headers are rejected for
raw PCM and must be imported as samples by the audio workflow.

`artifact_transfers.py` owns progress, cancellation, integrity and evidence;
`Host.artifact_action` serializes bench admission; `NodeSession` retains protocol
ownership/retries and finishes a bounded serial write before cancellation can
release its command lock. `Store` persists records and marks active transfers
interrupted on restart, without automatically resuming them.

Transfer states are running, completed, failed, cancelled and interrupted. Progress
separates upload bytes from readback-verification bytes. A transfer has a 180-second
deadline, at most 4096 planned requests and 8 MiB of raw evidence. A node advertising
smaller chunks may require a smaller file to fit the host request budget. Input
JSON is bounded to 196608 bytes and the decoded file to 131072 bytes.

Cancellation preserves observations, deletes an unfinished upload where possible
and frees the transfer's bench ownership. The normal connected-node claim remains
when cleanup succeeds. If cleanup cannot be confirmed, the host disconnects to
release ownership and records that uncertainty; it does not invent success.

## API

| Action | Endpoint |
| --- | --- |
| List manifests | `GET /api/nodes/A/artifacts` |
| Upload | `POST /api/nodes/A/artifacts` with `data_b64,format,kind,name` |
| Download node file | `POST /api/nodes/A/artifacts/ARTIFACT_ID/download` |
| Delete unused node file | `DELETE /api/nodes/A/artifacts/ARTIFACT_ID` |
| Transfer history/current ID | `GET /api/artifact-transfers` |
| Progress, errors and provenance | `GET /api/artifact-transfers/TRANSFER_ID` |
| Cancel | `POST /api/artifact-transfers/TRANSFER_ID/cancel` |
| Verified host bytes | `GET /api/artifact-transfers/TRANSFER_ID/content` |

Upload/download return 202 and a transfer ID. Poll until finalized before using
the content endpoint. Invalid/unsupported work returns an explicit error; another
bench operation returns 409. Use B in place of A for an independently connected
node. Node artifact IDs and host transfer IDs are distinct UUIDs.

## CLI review

Start the backend with `make serve`; use `lora-testbed ports` and connect one role
with `lora-testbed node A PORT`. From the repository root, prefix CLI commands with
`uv run --project testbed` if the environment is not activated.

```sh
lora-testbed artifact-upload A /tmp/reference.bin
lora-testbed artifact-transfer TRANSFER_ID
lora-testbed artifact-list A
lora-testbed artifact-download A ARTIFACT_ID
lora-testbed artifact-transfer DOWNLOAD_TRANSFER_ID
lora-testbed artifact-save DOWNLOAD_TRANSFER_ID /tmp/recovered.bin
shasum -a 256 /tmp/reference.bin /tmp/recovered.bin
lora-testbed artifact-delete A ARTIFACT_ID
```

Expect completed status, identical lengths/hashes and identical source/recovered
bytes. `artifact-save` never overwrites an existing destination. For raw PCM,
pass `--format pcm_s16le_8000_mono`; this does not imply playback support.

## Evidence and verification

The backend data directory contains `node_artifacts/TRANSFER_ID.bin` only after
verification, and `TRANSFER_ID.ndjson` for bounded command/reply evidence, including
failed/cancelled attempts. Records retain UTC observation times, node/boot/build
identity, contract and host source fingerprints, progress/errors, expected/actual
hashes and the final evidence-file hash. Content serving checks the saved bytes
again, detecting later corruption. Runtime files remain ignored by Git.

```sh
uv run --project testbed pytest testbed/tests/test_artifact_transfers.py -ra
make check
```

Expected at the #26 checkpoint: 23 focused cases, 290 total tests, no skips. Native
serial cases exercise actual C firmware for roundtrip boundaries, corrupted CRC
and final hashes, cancellation before start/after reserve/during a serial write,
restart, disconnect/reconnect, capability loss, evidence quotas and recovery.
API/CLI cases use the same service; malformed and oversized inputs create no
accepted file. No physical ports are opened by the normal suite.

November 16 physical checks on esp-f85b1ba27744 also passed upload plus separate
download at 1/1024/1025/48000 bytes, independent hashes, cancellation/cleanup and a
following valid transfer. Raw evidence and the isolated store remain in ignored
local/m2-batch. This is local file evidence; listening, microphone response and
full M1/audio qualification remain separate physical checks.

## Node inspector (#33)

Open Bench overview → Inspect node → Node files. Upload a raw binary/PCM file,
watch transfer and verification progress, inspect committed size/hash, retrieve
it, and save verified host bytes. Files in use cannot be deleted; unfinished or
failed files cannot be retrieved. Exact compatibility/current support comes from
the backend snapshot, not a browser copy of protocol hashes.

Recent completed/failed/cancelled findings remain visible after disconnect or
refresh. Disconnected/unsupported node actions are disabled, while verified host
copies remain available. Reconnect resets current RAM-file observations and keeps
transfer identity/boot provenance. File list refresh uses its own bounded request
state, ignores stale responses and refreshes after fast transfers complete.

Review: upload a known file, retrieve/save it, compare SHA-256, cancel a larger
transfer, inspect its retained progress/error/cleanup, then disconnect/reconnect.
Confirm unsupported/in-use actions stay disabled. `make check` and frontend build/
formatting passed at this checkpoint: 293 total tests (three new exact-readiness
cases). The focused host file suite now has 26 cases.

November 16 browser verification used the actual connected node in an isolated
data store: 1025-byte upload/retrieve/save matched exact bytes and SHA-256; an
invalid-ID request stayed visibly failed/unusable; cancelling a disposable
131072-byte upload retained 4096-byte progress and removed its node reservation.
Deletion, disabled disconnected controls, retained findings and fresh-boot
reconnect all passed. A screenshot is retained in the Codex visualization folder.
No speaker/microphone operation is established by these checks.
