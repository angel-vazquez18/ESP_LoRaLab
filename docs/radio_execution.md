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
   The first implementation uses single-fragment known data with ACKs disabled;
   fragmentation, retries and security require their own implemented capabilities.
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
