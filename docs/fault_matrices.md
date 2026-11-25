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
- PKT-03 uses 321 useful bytes and 160-byte fragments. It compares
  no ACK and stop-and-wait with zero, one or two retries. It observes
  first-attempt loss and suppresses an ACK for policies that can retry.
  Exhausting every allowed attempt with one or more retries remains
  blocked pending a multi-target injection path.

Select a matrix in **Experiments**. For a quick SEC-02 run select C1
or C2 and one direction. Preview requires an owned compatible pair
with the declared lab build. A successful negative assertion retains
the matching arrival, rejection, fresh intact control comparisons and
cleanup. Inspect the saved case and follow its lab trial link to the
individual radio records. Standard builds still run intact packet
cases. A lab result only establishes the recorded fixture conditions.
