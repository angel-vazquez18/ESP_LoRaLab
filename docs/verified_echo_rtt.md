# Verified echoes and requester-local RTT

Issue #65 adds a finite firmware capability. The shared host workflow is now
described in [physical echo timing](physical_echo_timing.md) (#83). The full
TIME-01 matrix (#102) and physical qualification remain separate.
The checks below use the actual portable C control/radio/security code with an
isolated radio bus; they are not measured LoRa performance.

## Behavior and bounds

One owned run contains one immutable known-data request and at most one reply.
Either A or B can request. The responder is armed first; requester arm does not
transmit. Start sends ECHO_REQUEST (type 3). A verified request schedules one
ECHO_REPLY (type 4) after the selected 20,000-us turnaround. The reply has the
exact request body, swapped roles, the request frame reference and a freshly
reserved responder sequence. Source sequence namespaces are independent: A:1
and B:1 are different identities, even though their numeric counters coincide.

Echo uses one fragment, no ACK and no retries. Payloads are 1–215 bytes plain or
1–199 bytes protected and must fit the selected fragment capacity (16–215 bytes,
limited to 199 for protected profiles). Known bytes use the existing seeded
SHA-256-block recipe. The pending owner borrows that immutable body and stores
one 255-byte wire buffer plus an accepted-frame digest; there is no request queue.
Requested memory inventory includes `rf_echo_pending`; it is not total heap use.

The requester takes `tx_command_us` from the real radio terminal observation of a
confirmed successful transmission. It records `reply_accepted_us` after framing,
session, role, protection, replay, request reference, exact content and deadline
checks. `rtt_us` is their difference on that requester's boot clock. The peer's
clock, USB arrival time and TX-done time are not substituted. Both radio airtimes,
peer turnaround and processing remain included. This is not one-way delay.

Protected frames use the existing per-source volatile PSA key and shared sequence
allocator. Authentication and outstanding request/content checks precede replay
commit. A bad tag, wrong reference or changed content therefore cannot consume
the later legitimate reply's replay entry. Public fixed keys appear only in the
native conformance checks; normal sessions retain fresh RAM-only keys.

## Results and failure handling

The requester emits one `echo.result`, with a matching nested terminal
`run.summary.echo`. A valid result contains session, request/reply sequences,
expected payload length/hash, both local timestamps, their exact difference,
`valid: true` and `reason: matched`. The later #83 wire revision also retains
actual accepted `reply_hex` bytes and shares one captured acceptance instant with
`rx.accepted`; the exact generated execution digest gates that addition. Typed host validation rejects inconsistent
intervals. Requester results identify source and boot through the event envelope.
Responder summaries keep RTT unavailable; accepting a request is not measuring RTT.

| Observation | Result |
| --- | --- |
| Exact, timely verified reply | One valid local RTT sample |
| Wrong session/source/message/reference/content/protection | `rx.rejected` reason; pending request remains; no sample |
| Failed authentication | Authentication rejection; no replay commitment or sample |
| Duplicate request | Excluded, no second reply or sequence reservation |
| Duplicate reply | Excluded, no second sample |
| Missing reply | `timeout`, null accepted time and null RTT |
| Reply after the reply deadline | `late` during drain; timeout remains null |
| Unconfirmed/failed request transmission | `tx_failed`, null timing; no success |
| Stop, lease loss or disconnect | Pending buffers retire; work cannot resume |

The reply deadline precedes the overall selected duration by the prepared drain
interval (at least two seconds). The responder has the existing five-second arm
allowance because it cannot observe remote start acceptance. After one response,
both ends listen through bounded drain to classify duplicates/late frames. The
hard overall deadline releases resources even when telemetry is backpressured.
Missing or dropped telemetry prevents a complete host measurement; a summary is
not a replacement for independent transmit/reply correlation.

Explicit stop retains a terminal summary while the session is owned. Ownership
loss closes the session and destroys keys/pending state; disconnect can discard
outgoing telemetry. The host must preserve what it observed and mark missing
evidence unavailable. Committed source artifacts retain their existing lifecycle;
closing the echo owner does not erase all ready artifacts. Fresh work requires a
new session/run and identifiers; nothing resumes automatically.

## Wire migration

The selected execution profile is now `finite_message_execution_v4`, with the
exact digest generated from the typed models. It adds `EchoSpec`, the echo result
and optional summary field. Host and firmware must use the matching generated
execution schema; old v3 identities are not silently accepted or relabelled.
Diagnostic, main-control, artifact, audio and memory profiles remain independent.

`EchoPlan`/`EchoSpec` build a one-request intent. The common preview calculates
both airtimes, 30,000 us processing allowance, 20,000 us turnaround and bounded
drain. These are declared budgets, not measured CPU/airtime evidence. The operator uses the shared physical echo runner described in
[host timing](physical_echo_timing.md); readiness checks actual compatible nodes
before starting work.

## Code walkthrough

1. `testbed/src/lora_testbed/run_protocol_v2.py` defines echo intent and execution
   compatibility. `rf_events_v2.py` defines valid versus unavailable timing.
2. `firmware/lora_node/main/radio/rf_echo.c` owns the one-pending-request state
   machine, exact validation, fresh reply sequence, local timestamps and drain.
3. `radio/rf_execution.c` composes that owner into existing prepare/arm/start,
   artifacts, radio observations, summaries, memory inventory and cleanup.
4. `control/node_control.c` advertises echo only when the radio is available.
5. `testbed/tests/test_echo_rtt_native.py` drives actual C nodes in both
   directions with deliberately unrelated clocks and independently decrypts the
   protected reply using public fixture keys.

## Review checks

From the repository root:

```sh
uv run --project testbed pytest testbed/tests/test_echo_rtt_native.py -q
make check
source /Users/anken18/.espressif/v6.0.2/esp-idf/export.sh
idf.py -C firmware/lora_node build size
```

Expect 37 dedicated echo cases without skips, one valid sample per successful
request, null latency for missing/unconfirmed replies, explicit exclusions and a
fresh successful request after timeout. The full checks include existing
full-capability 4-KiB serial record guards and DATA/security/voice regressions.
The target must build without flashing. Native fixtures require the pinned C,
PSA and Codec 2 sources as described in `development.md`.

Physical review remains open: identify both actual board revisions/profiles,
release serial ownership and follow the applicable backup/build/flash procedure.
With two qualified compatible radio nodes and antennas, use the #83 host runner
once available to repeat requests in both directions, inspect raw TX/reply
identities and exact payload hashes, suppress a reply, then recover a fresh run.
Record real timestamp phases/resolution and observed results. Do not claim TIME-01
qualification from these software cases, and do not enable pulse pins or infer
one-way timing; #46/#49 and calibrated TIME-02 remain gated separately.
