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

The public packet planner supports those bounds. Operator execution still
advertises one message/one fragment until receiver reconstruction and transport
scheduling are integrated. No physical fragmentation result is claimed. Later
qualification must compare actual recovered bytes/hashes and retained metadata
across boundary lengths, both directions, loss, cancellation and recovery.
