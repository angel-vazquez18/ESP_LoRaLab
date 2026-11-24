# Bounded message fragments

`radio/rf_fragments.h` plans a message without allocating memory or touching the
radio. The caller supplies immutable source bytes for the message lifetime.
Identity (session, source/destination, content and message ID) stays fixed; each
original fragment uses `first_sequence + index`. Initialization reserves the full
sequence range and rejects exhaustion instead of wrapping. Retry attempt indexes
will not change wire bytes.

The selected limits are 65,536 useful message bytes and 4,096 fragments. Fragment
size is 16–215 bytes unprotected or 16–199 with the 16-byte GCM tag reserved;
default is 160. Every DATA frame has the selected 40-byte big-endian header. The
last body contains exactly the remaining bytes, including a full-size final body
when the length is a multiple of the fragment size. No message hash is invented
in the header: source/reassembled hashes belong to run/artifact evidence.

`rf_message_plan_init` validates before work and leaves its output unchanged on
rejection. `rf_message_header` produces header bytes for a valid indexed slice;
protected headers are additional authenticated data for later encryption.
`rf_message_fragment` emits complete **unprotected** DATA from caller bytes and
rejects protected plans. It never labels plaintext as ciphertext. Existing
single-frame execution uses this encoder through `rf_single_encode`.

## Check it

Run `uv run --project testbed pytest testbed/tests/test_rf_fragments_native.py
 testbed/tests/test_rf_frames_native.py -q` (join the command onto one line).
Expected: 16 cases pass without skips, with independent host frame parsing and
literal boundary expectations for 1/159/160/161/319/320/321 bytes. Maximum-size
messages at fragment sizes 16/160/215 reconstruct the exact caller bytes.
Maximum-plus-one, zero length, invalid capacity, sequence exhaustion and invalid
index/source length reject without changing the output. Protected header vectors
reserve the full tag, reject 200-byte protected slices and never emit an
unencrypted protected frame. Run `make check` and build the main ESP-IDF image.

The public packet planner and operator execution support those bounds for one
unprotected known-data message. Reconstruction and bounded stop-and-wait
scheduling are integrated; see [shared runs](physical_radio_runs.md). No physical fragmentation result is claimed. Later
qualification must compare actual recovered bytes/hashes and retained metadata
across boundary lengths, both directions, loss, cancellation and recovery.

## Receiver reconstruction

`rf_reassembly` owns one message buffer per peer/session. Its opaque interface
uses the platform's allocation/release and SHA-256 callbacks. Creation binds the
session, roles and fragment capacity. Begin fixes a nonzero increasing message
ID, content, complete length, expected SHA-256 and absolute node-local deadline;
all limits reject before message allocation. The initial implementation accepts
unprotected DATA only. Protected frames reject before plaintext insertion.

Accept validates framing, session, direction and consistent metadata. A bitmap
tracks exact missing indexes while duplicate slices do not add bytes. Reordering
within the message is supported. Completion hashes the actual reconstructed
buffer and compares the expected hash before `take` exposes a borrowed pointer.
Take succeeds once; the pointer lasts until begin/cancel/destroy. A late
conflicting duplicate cannot revoke or free a buffer already delivered.

Timeout, conflicting metadata/content, hash failure and cancellation scrub/release
the incomplete buffer. Missing indexes remain queryable in ascending pages after
failure; a failed/delivered message ID cannot restart in the same context. A new
higher ID can use the released resources. An active message must be explicitly
cancelled/expired before beginning its replacement. Caller-supplied expected
hashes are trusted local run context, not authentication of an RF peer.

`rf_data_decode` is the canonical unprotected multi-fragment parser. Existing
single-fragment execution now uses it through its narrow compatibility adapter.
The execution owner now composes reconstruction with the reliability scheduler
and advertises fragmentation only when the real radio is available. Missing
indexes emit in bounded 64-range pages before the terminal message result. Stop
can interrupt reporting and explicitly marks that evidence incomplete.

Run `uv run --project testbed pytest testbed/tests/test_rf_reassembly_native.py -q`.
Expected: 12 cases pass without skips. They cover reordered/duplicate exact
once-only delivery, missing middle fragment/deadline, conflicting metadata and
content, wrong final hash, cancellation and fresh-message recovery, late conflict
without freeing a borrowed result, 65,536 bytes at 16/160/215-byte capacities,
paged missing indexes, maximum-plus-one/preflight before allocation, allocation
failure and malformed/session/role/protected frame rejection. Tracked heap
boundaries must be empty after destruction. Physical loss/reorder, board memory,
RF delivery and full transport integration remain separate checks.
