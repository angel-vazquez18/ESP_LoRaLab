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
ESP-IDF image. Operator execution now composes these modules and advertises ACK/retry support
only with current radio availability. The host checks both peers’ capabilities
and numeric limits before starting; see [shared runs](physical_radio_runs.md).

Physical acceptance later needs lost-DATA/lost-ACK cases, exact DATA retry byte
hashes, one application delivery, observed ACK turnaround/deadlines, distinct
DATA/ACK accounting and timeout/stop/lease-loss recovery on identified boards.
No ESP was connected during implementation.

## Bounded sender policy

`radio/rf_sender` drives the real finite `node_radio` API with one retained DATA
frame. Begin validates applied-modem airtime, retry/guard settings and remaining
run budget, then copies the complete original before RF. Caller mutation cannot
change retries. The context binds source/session/direction and a sequence high
water; a completed or cancelled original cannot be restarted. A fresh higher
sequence can use the same radio after a terminal result. New sessions need a
new sender context. Encryption is not performed by this module.

The selected explicit-header/CRC quarter-symbol airtime calculation includes
LDRO at symbol durations >=16 ms. ACK timeout from observed DATA TX-done is
turnaround + actual configured ACK airtime + margin. The absolute run deadline
bounds every phase; per-attempt TX/RX remains within the driver's 30-second cap.
A new attempt waits the configured guard. Zero/one/two retries permit exactly
one/two/three total DATA attempts, while the original denominator remains one.
ACK disabled permits no retries and completes after observed TX-done.

Only a CRC-valid exact ACK reference finishes the outstanding original. Rejected
ACKs do not extend its deadline. ACK loss can produce the identical DATA retry,
a fresh receiver ACK and one application delivery. Exhaustion is explicit and
leaves the radio reusable. Cancellation must be invoked on stop, ownership loss
or shutdown by the execution owner; the execution owner now wires those lifecycle hooks into bounded multi-fragment
runs. Delivered receive state remains available through drain so a lost final ACK
can be answered without another application delivery.

Radio observations are retained through the public poll interface. A blocked
consumer prevents further attempts, while finite driver/run deadlines still
advance. Both an undrained TX observation and a later RX timeout remain readable
after deadline cleanup. Destruction stops/drains owned work and releases the
retained frame context; it is not a substitute for collecting evidence first.

Run `uv run --project testbed pytest testbed/tests/test_rf_sender_native.py -q`.
Expected: 19 cases pass without skips using the real portable radio and pinned
vendor driver behind injected SPI/GPIO/time. They cover exact retries and attempt
indexes, zero/one/two exhaustion and fresh-original recovery, wrong ACK without
deadline extension, real caller-buffer mutation, ACK-loss once-only recovery,
five literal airtime vectors, ACK-disabled operation, cancellation at ready/TX/
ACK/guard, preflight before RF, old-sequence rejection and retained observations
through the run deadline. Compile the main ESP-IDF image and run `make check`.
Software checks also cover full host runs and stop/lease/disconnect integration.
Physical IRQ/ACK timing, actual loss recovery and hardware resource behavior
remain later acceptance; no RF image was installed during this work.
