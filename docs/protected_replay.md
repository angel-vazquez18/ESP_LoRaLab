# Protected DATA, replay and retry acceptance (#60)

The main node now composes the source-key owner, real PSA frame cipher and finite
radio/reassembly path. With an available selected radio it advertises
`security_gcm`; `security_ready` still means a usable **owned** key pair has been
loaded. #63 now adds fresh shared-host provisioning, safe setup records and
independent persistence guards; see [protected host sessions](protected_host_sessions.md). Software fixtures can exercise
this node slice without enabling an operator simulator or opening a physical port.

## Receive decisions

`rf_secure_receive` is the application receive boundary. The lower-level
`rf_secure_open` remains an authentication-only primitive and cannot establish
replay freshness. The receive boundary binds the source/session, verifies the
complete authenticated header and tag into private scratch, then consults a
session-scoped 128-frame window shared by all accepted protected frame types.

- A new sequence above the high-water mark shifts the bounded bitmap **only after
  the insertion callback succeeds**. A large jump clears obsolete bits.
- An unseen sequence 0–127 below the highest accepted sequence remains usable.
  A sequence 128 or more behind it is too old. No uint32 wrap is permitted.
- Invalid tags, wrong sessions/roles, failed metadata checks or refused insertion
  do not consume a position or shift the window. Scratch plaintext is wiped.
- An already accepted sequence is replay unless the exact authenticated DATA
  frame qualifies for the retry exception below. ACK replay never completes a
  sender operation or extends its deadline.

The insertion callback checks the current message, geometry, protection/ACK
policy and actual expected source bytes before reassembly. It keeps the protected
header intact. `rf_data_inspect` exposes structural metadata only and returns no
plaintext pointer for protected input. `rf_reassembly_accept_authenticated` is a
trusted post-authentication seam; ordinary unprotected acceptance still rejects
protected bytes. Clearing the protected flag cannot switch an owned protected
session to plaintext.

The current finite execution limit remains one known-data message, at most
65,536 bytes / 4096 fragments / one hour. Protected fragment capacity is 199
bytes. Prepared budgets include the 16-byte tag in DATA airtime, ACK airtime,
wait windows and RX limits; a protected ACK is 56 bytes. A mismatched security
specification or oversized protected fragment fails before arming/RF.

## Legitimate retry exception

The owner keeps at most 16 accepted DATA frame hashes, each with its original
acceptance time and a fixed retry expiry. The whole header/ciphertext/tag is
hashed. A duplicate can produce `RF_SECURE_RETRY_DUPLICATE` only if it has passed
authentication again, is still inside the 128-frame window, ACK mode is enabled,
its accepted hash matches and its original retry horizon has not expired.

This decision never invokes the insertion callback, inserts another fragment,
extends the cache horizon or delivers another message. The receiver may then
emit a newly referenced ACK using its next local source sequence and key. An
identical retry after eviction/expiry, a changed authenticated frame at the same
sequence, or a repeated DATA with ACKs disabled is replay. An injected identical
frame inside this exception is indistinguishable from a legitimate lost-ACK
retry; therefore SEC-03's strict replay check uses ACKs disabled.

DATA is sealed once when staging an original and copied into the existing
sender's immutable outstanding-frame buffer. Retry attempts transmit those exact
retained bytes; they do not reseal or reserve another DATA sequence. Sender ACK
acceptance runs the same authentication/replay boundary and then validates the
exact outstanding reference before committing replay state. A bad-tag ACK does
not consume a later valid ACK's sequence. Fatal crypto-provider failure stops
the sender instead of continuing work with an unusable session.

The current one-way message source reserves its complete DATA sequence range
before starting. The opposite node reserves fresh ACK sequences when needed.
They use independent source owners. Future bidirectional ECHO/other producers
must share those owners and preserve reservation/sealing order; no parallel
independent counter is introduced here.

## Lifetime and evidence

Replay bits and the accepted-hash cache live in the same private RAM owner as
keys/counters. Close, stop, lease loss, disconnect and reset retire them together;
a previous owner cannot resume. Normal completed work may drain before explicit
close. No key bytes appear in replies/events or these new rejection records.

The existing typed `rx.frame` remains a raw observation, not authenticated-delivery
proof. `rx.rejected` distinguishes framing, session, authentication and replay
failures. `rx.accepted`, once-only `message.result`, summaries and actual committed
readback remain separate observations. No new schema shape is needed: current
execution/profile fields already define protection and these stages. Existing
main-control, diagnostic, artifact, audio and execution hashes were unchanged
by #60. #63 subsequently adds explicit accepted-ACK events and updates the execution
fingerprint; follow its migration when rebuilding the protected operator stack.

Read these files for review:

1. `security/session_crypto.c`: authenticate → replay decision → metadata/insertion
   callback → commit, bounded retry hashes and cleanup.
2. `radio/rf_execution.c`: protected staging, authenticated insertion, fresh ACKs,
   rejection evidence and byte/hash-verified artifacts.
3. `radio/rf_sender.c`: retained attempts and authenticated referenced ACK acceptance.
4. `radio/rf_reassembly.c` / `rf_fragments.c`: structural versus trusted plaintext seams.
5. `testbed/tests/test_secure_replay_native.py` and
   `testbed/tests/test_protected_rf_execution_native.py`: independent public-key
   oracles and the production C/provider/radio boundary.

## Reproduce software checks

From repository root with pinned ESP-IDF/cJSON/crypto sources and the native
compiler/CMake available:

```sh
uv run --project testbed pytest testbed/tests/test_secure_replay_native.py testbed/tests/test_protected_rf_execution_native.py -q
make check
idf.py -C firmware/lora_node build
```

Expected focused results: six passing cases, no skips. The window cases cover
immediate replay, 129-sequence advancement, exact 127/128 distance boundaries,
unseen reordering, uint32 maximum, bad tags, refused insertion, session mismatch,
fixed-horizon expiry and 16-entry eviction. Node cases exercise protected DATA,
profile downgrade rejection, wrong session, failed DATA/ACK tags, exact ciphertext
retries and fresh-nonce re-ACKs with one delivery.

The paired-node case runs two actual C/PSA node cores over an isolated SPI/IRQ
fixture. It suppresses the first protected ACK, requires three DATA attempts for
two original fragments, ACK source sequences 1/2/3, one message delivery and
independently identical recovered bytes/hash. Fixture scheduling allowances are
not RF propagation/airtime measurements. No physical device was used or flashed.

## Later physical validation

After #63's host support and normal two-device identity/revision/wiring/backup
checks, run protected known-data traffic in both directions. Retain builds,
applied settings, receiver-stage failures, exact readback and original/attempt/
ACK/delivery counts. Repeat bad-tag and old-session rejection, ACK-disabled replay,
ACK-loss recovery and cancellation/lease/disconnect/reset cleanup with subsequent
fresh sessions. Perform the paired-node and loaded heap/stack acceptance under
#67. ECHO/fault-injection operators and all physical security results remain
separate pending work; this implementation does not qualify them.
