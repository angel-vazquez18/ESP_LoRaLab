# Physical radio execution interface

The main-control envelope remains NDJSON v2. RF work reuses the selected execution
vocabulary in `run_protocol_v2.py`; there is no second `radio.*` command family.
A control-schema match alone does not enable RF. The host requires both identity
and current health to advertise `resource_limits.execution`, profile
`known_data_execution_v1`, the exact generated execution digest and the requested
command. New work also requires `capabilities.radio = true`. Cleanup commands
(`run.stop`, `session.close`, `run.summary`) remain callable after radio failure.
Only implemented handlers belong in the declaration; the generated C header
identifies the vocabulary, not an implementation promise.

## Finite lifecycle

1. Claim both distinct node identities and open a run-scoped session. Record each
   device/boot ID, host run UUID and nonzero 64-bit session ID. Initial bring-up
   uses `security = none`; key fields are null.
2. Send `config.set` while idle. Preserve the requested radio/link objects and the
   returned applied objects and configuration revision separately. Unsupported
   frequency, power, spreading factor, bandwidth or coding-rate values must fail
   without clamping or partially changing a previous configuration. Coding-rate
   denominator 5 means 4/5; it is not the driver's numeric enum. Applied power is
   a configured setting, not a calibrated antenna-power measurement.
3. `run.prepare` supplies the bounded source specification and calculated budget.
   Acceptance is not completion: wait for the correlated preparation result and
   `run.prepared` evidence before arming.
4. Arm the receiver with the applied revision and wait for `receiver_ready = true`
   before starting the sender with its applied revision. A stale revision fails.
   Known data supports bounded fragmentation and optional stop-and-wait with up
   to two retries. Require the relevant capabilities and numeric limits on both
   peers. Security and encoded content remain unavailable.
5. Collect frame/message events and a final `run.summary` from each node. Stop on
   cancellation, deadline, peer loss or ownership loss, then close the session.
   Reset/reconnect never resumes a previous run. An uncertain stop invalidates the
   run and requires fresh identity/idle reconciliation.

## Evidence and clocks

`tx.attempt` identifies session, source role (event envelope), frame sequence,
message, fragment and attempt. `tx_command_us` is taken immediately before the
finite radio transmit request; `tx_done_us` is the node's observation of TX-done.
`rx.frame.rx_done_us` is the receiving node's observation of RX-done. Timestamp
resolution and polling/IRQ observation latency must be reported by the driver.
These clocks are local to each boot: subtracting A's TX time from B's RX time does
not establish one-way delay. CRC failure is an observed radio frame, never an
accepted application fragment. Accepted bytes and reconstructed message hashes
must be independently checked by the host.

`contracts/v2/radio_examples.json` contains public literal examples for settings,
session, prepare, receiver-ready, start, stop, summary and TX phase timestamps,
plus rejected configurations. They are interface fixtures, not measurements.
`make contracts-check` checks generated schema/header drift. The legacy execution
schema's `virtual_known_data_execution` scope string is retained as an opaque
historical identifier; it does not authorize simulated operator runs. The added
capability declaration changes only the execution digest, not diagnostic/control,
artifact or audio compatibility. No installed firmware previously advertised it.

## Checks and remaining hardware work

Run `uv run --project testbed pytest testbed/tests/test_radio_execution_contract.py -q`
and `make check`. Expected: missing/unknown commands and mismatched digests fail;
loss of radio readiness blocks starts but preserves declared cleanup; literal
examples validate and invalid configurations are rejected.

The printed PCB revision is still unconfirmed. The official standard V4.3 R2
schematic assigns GPIO5 to the RF front end; the old audio-plan microphone WS on
GPIO5 must not be enabled with that RF profile. Firmware must select a documented
revision and reject conflicting pins before enabling RF. Do not assume the R8
variant has the same layout. Physical checks still require identified compatible
boards, matched antennas, verified RF control wiring and directional frame/hash,
IRQ, timeout, stop, reconnect and applied-setting evidence. No ESP was connected
for this change.

## Implemented single-message execution (#25, #47)

The main image implements the eight selected execution commands through the real
SX1262 driver. Explicit board selection and successful initialization are required.
`resource_limits.execution_limits` bounds one known-data message per session,
65,536 useful bytes, 4,096 fragments, 3,600,000 ms and two retries. Fragment body
capacity is 16–215 bytes (default 160). Both identity and current health must
advertise the capabilities needed by the actual request. The host also checks
smaller limits from an older peer before opening/arming a session.

Multiple/protected/encoded messages reject rather than being truncated or silently
substituted. Configuration and preparation validate applied airtime, ACK timeout,
receiver drain, processing and reassembly deadlines before allocation or RF.
No full IF-02 qualification or operator simulation is introduced.

`session.open` binds a host run UUID, a nonzero session ID, owner, A/B role and a
distinct peer device/boot identity. Configure while idle, then prepare a typed
one-message known-data spec/budget, including its full fragment count. Preparation generates the documented SHA-256
block source and reserves a RAM artifact: committed source on TX, an expected-hash
reservation on RX. The preparation result labels that artifact state explicitly.
`run.prepared` and its correlated operation result precede arming/starting.
Stale revisions reject. The receiver arms before the sender starts; only the
sender starts an asynchronous TX operation. The node never invents peer readiness.

The portable fragment module encodes each field at explicit big-endian offsets;
there are no packed-struct wire assumptions. Receive order is PHY CRC/header,
bounded DATA framing, session/roles/message metadata, exact deterministic body,
then bounded reconstruction and hash-gated once-only delivery. The complete actual received bytes and their hash are committed
as a recovered artifact. Duplicate/stale message tracking prevents second
application delivery. Wrong/truncated/changed frames produce rejection evidence
and rearm within the remaining finite window. There is no authentication claim
for this unprotected bring-up mode.

The execution module emits typed frame/message observations and summaries, holds
radio terminal results until the telemetry queue has room, and releases incomplete
reservations on stop, close, lease loss, disconnect or shutdown. Ownership loss
invalidates the session; reconnect never resumes it. Committed artifacts remain
until explicit deletion/reset, following the existing artifact contract. Requests
that would steal resources while prepared/armed/running reject as busy. Both reply
outcomes are reserved before mutating operations; cached retries apply once.

`physical_wire_v2.py` decodes control plus RF events. NodeSession separately
requires the exact advertised execution profile and a known run before accepting
RF observations. A small closed-run history admits legitimate delayed events;
foreign boots/runs still fail. Shutdown attempts finite stop/close before release.
The original main-control/diagnostic schema digests remain unchanged.

Read `radio/rf_frames.c` for exact bytes/source/delivery, `radio/rf_execution.c`
for the bounded lifecycle and artifact/evidence rules, then the small routing in
`control/node_control.c`. Run:

```sh
uv run --project testbed pytest testbed/tests/test_rf_frames_native.py testbed/tests/test_rf_execution_native.py -q
make check
idf.py -C firmware/lora_node build
```

Expected: public header/source vectors match; 1/159/160-byte valid receives yield
one committed, exact readback with the independent source hash; corrupt/session/
length/CRC failures never publish a delivery and a following valid frame works;
sender bytes/attempts, stale revisions, duplicate commands and stop/lease/disconnect
cleanup remain attributable. Allocation-failure cases do not reserve hidden work.
The serial/SPI peers in these checks exist only in tests. No ESP is connected;
physical RF, board revision, antenna-power and precise IRQ timing validation stay
pending. The receiver-first host workflow/dashboard follow in #27/#34.

The execution owner composes `rf_fragments`, `rf_reassembly`, `rf_ack` and
`rf_sender`. Source/recovered artifacts are published in 1,024-byte store chunks;
large messages do not bypass the artifact chunk ceiling. A completed TX-done
confirms an original once, while each DATA/ACK attempt retains distinct evidence.
Failed reconstruction emits all available missing-index parts before its result
and summary. Explicit stop remains bounded even if that report is backpressured,
and marks interrupted reporting incomplete. See [accounting, review commands and
physical checks](physical_radio_runs.md#multi-fragment-accounting-and-review-47).

## Owned protected setup (#52)

Firmware `session.open` now accepts the selected protected key variant and
imports a private role/session-bound owner. Close/stop/ownership loss retires it,
and readiness reports actual loaded keys. This expands the generated execution
digest; rebuild matching RF stacks. Protected `run.prepare`, `security_gcm`
advertisement and ordinary host provisioning remain blocked until their replay/
transport and safe provisioning implementation. See
[session key lifetime](session_key_lifecycle.md) for exact limits, erasure checks
and compatibility migration.

## Protected known-data node slice (#60)

The main image now accepts matching protected known-data specifications after
owned private setup. GCM authentication/replay checks precede insertion, DATA
retries reuse exact bytes, and eligible duplicate DATA produces a fresh referenced
protected ACK without second delivery. Timing budgets include tag bytes and
56-byte ACKs. Node GCM capability reflects selected radio availability; ordinary
host provisioning remains gated pending #63. See [review, checks and physical
limits](protected_replay.md). No physical RF/security qualification is established.
