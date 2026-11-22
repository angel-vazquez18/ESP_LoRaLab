# Radio acknowledgment and retry behavior

## Referenced acknowledgments

`radio/rf_ack` implements the selected 40-byte unprotected ACK: type 2, empty
body, ACK-request clear, reversed source/destination and the DATA session,
message/fragment/content/complete-length fields. Its reference is the original
DATA sequence; its own sequence is fresh in the receiving node's source space.
There is no ACK-of-ACK. Sequence exhaustion stops new ACK generation without
wrapping. Protected ACKs remain unavailable until GCM is integrated.

`rf_ack_matches` checks an ACK against the exact outstanding DATA. Wrong session,
source/destination, message, fragment, complete length or reference cannot match;
malformed/extra-body/reserved-field input rejects. A nonzero ACK sequence alone
does not establish replay freshness; later security validation must precede this
reference matcher.

The bounded receiver scheduler is called **after** content validation and the
receive/replay decision. It never inserts or delivers application bytes. The
classification seam distinguishes new accepted DATA, eligible retry duplicates,
replay and rejected frames. Only ACK-request DATA in the bound direction/session
can schedule an ACK. Retry duplicates must additionally match the SHA-256 of the
exact retained full frame, remain within the supplied retry horizon, and be among
the last 16 accepted originals. An unknown/changed/expired frame or replay
classification cannot obtain an ACK through that seam. Identical retry packets
remain indistinguishable from a malicious byte-for-byte retransmission within
that horizon; neither creates new application delivery.

One ACK can be pending. The caller takes it only after the configured turnaround;
repeated offers for that same queued reference coalesce. Each actual take consumes
a fresh local sequence. Cancellation clears pending/cache state without resetting
the sequence. The caller must derive a horizon covering the complete retry budget
and must share the local sequence space with every other sourced frame type.
This module does not qualify PHY timing or independently authenticate a peer.

## Review checks

Run `uv run --project testbed pytest testbed/tests/test_rf_ack_native.py -q`.
Expected: five cases pass without skips. Literal ACK bytes must match, early takes
produce nothing, only the exact outstanding DATA matches, byte-identical eligible
retries receive fresh ACK sequences, wrong/expired/replay frames reject, sequence
exhaustion/cancel/cache bounds hold, and combined reconstruction plus re-ACK
produces exactly one application delivery. Run `make check` and compile the main
ESP-IDF image. These modules are not yet advertised as operator ACK/retry support;
the reliability scheduler and host multi-fragment integration follow.

Physical acceptance later needs lost-DATA/lost-ACK cases, exact DATA retry byte
hashes, one application delivery, observed ACK turnaround/deadlines, distinct
DATA/ACK accounting and timeout/stop/lease-loss recovery on identified boards.
No ESP was connected during implementation.
