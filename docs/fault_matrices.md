# Grouped packet and security lab cases

These matrices use the existing lab trial service and preserve the
before, fault and after runs for each targeted case. The parent list
keeps direction, repetition, expected target and the original child
evidence. A missing fault observation yields an inconclusive result.

- SEC-02 selects a protected 64-byte message and flips one bit either
  in ciphertext at offset 40 or in the tag at offset 104. Each case
  independently requires matching CRC-valid arrival, receiver
  authentication rejection and zero altered application delivery.
- SEC-03 C1 replays the exact protected frame from a confirmed initial
  delivery while the receiver is still armed. C2 requires advancing
  the same retained session beyond the 128-frame replay window.
  That case remains blocked.
- PKT-02 uses 1200 useful bytes and 16/64/160/199-byte fragment settings.
  Each series places the loss, duplicate or reversed block in the
  third workload at the default ten-message count. Each workload
  uses a separate finite session. The deliberately incomplete case
  retains exact missing-index evidence and intact controls.
  The intact case reopens both retained byte artifacts and independently checks
  expected source contents, receive indexes, and final-fragment lengths. The
  ledger records each message's seed, digest and session identity.
  An ACK-disabled drop must also have an explicit receive timeout, exact archived
  source digest, matching confirmed arrivals, and observed insertion for every
  index other than the selected missing fragment.
  The duplicate case ties one accepted insertion to the original arrival and
  one explicit replay or duplicate rejection to the second matching arrival.
  The reorder case matches the complete planned index order against sender TX,
  CRC-valid arrival and receiver insertion. Matching frame digests tie each
  receive observation to the transmitted bytes.
- PKT-03 uses 321 useful bytes and 160-byte fragments. It compares
  no ACK and stop-and-wait with zero, one or two retries. It observes
  first-attempt loss and suppresses an ACK for policies that can retry.
  C4 schedules one drop for every allowed attempt in the same bounded
  trial. The sender reports each ACK receive timeout. The testbed
  verifies the exact reused frame digest, distinct CRC-valid receiver
  arrivals, no partial delivery, the missing fragment suffix when the
  sender stops, and a fresh intact recovery control.
  Native firmware checks inject isolated bad-tag and authenticated wrong-reference
  ACK fixtures. The sender emits a reason tied to the receive timestamp, retains
  its outstanding DATA, retries within the budget, and accepts the matching ACK.
  The physical matrix still offers ACK suppression and needs a separately
  verified on-bench wrong-reference fixture.

Select a matrix in **Experiments**. For a quick SEC-02 run select C1
or C2 and one direction. Preview requires an owned compatible pair
with the declared lab build. A successful negative assertion retains
the matching arrival, rejection, fresh intact control comparisons and
cleanup. Inspect the saved case and follow its lab trial link to the
individual radio records. Standard builds still run intact packet
cases. A lab result only establishes the recorded fixture conditions.

On a bench, select PKT-03 C4 with matching lab images. Use default
repetitions for both directions. Inspect the selected third workload
under each link policy. Stop-and-wait should retain one, two or three
confirmed attempts and matching ACK timeout events. The no-ACK run
continues after the targeted drop and reports the one missing index.
The attempt time is evaluated on the sender's local clock from its
first TX command through the final observed ACK timeout.
