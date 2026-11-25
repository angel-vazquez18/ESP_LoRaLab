# Laboratory protected-frame checks

Issues #76 and #77 add fault controls for finite, generated known-data runs.
Protected-frame mutation and replay require AES-GCM. Fragment and ACK controls
work with the corresponding protected or unprotected run. The controls are available only when `CONFIG_LORALAB_LAB_FAULTS=y` and
radio execution is available. The option defaults off. Use the matching
`finite_message_execution_v6` schema for both nodes and the host. The diagnostic
and main-control schema fingerprints remain independent.

`hello` lists the supported commands. Laboratory `health` records use the
schema-defined `lab` command set to keep active health within the 4 KiB serial
record bound. The host expands that set using the matching schema.

## Scope and evidence

- The source configures an exact session, message, fragment, attempt and
  injection ID before arming. The firmware checks offsets against actual frame
  geometry and rejects invalid inputs before applying hooks. The limits are
  eight entries per request, 32 per session and 16 retained frames.
- The byte-change hook operates on a scratch copy after protection and before
  radio submission. Original sender retry bytes remain immutable.
- The retained-frame hook uses bytes already submitted by that run. It needs a
  prepared drain budget and can fire once. It does not reserve another frame
  sequence or call encryption again.
- A receiver drop matches an eligible arrival after frame, content and any
  authentication checks, before insertion. The protected insertion callback
  returns before the replay window advances. No ACK is generated for a dropped
  DATA fragment. A later exact retry can still be accepted.
- ACK suppression acts after DATA acceptance and preserves exact retry
  eligibility, including the unprotected ACK cache. A bounded duplicate retry
  can get an ACK without another insertion.
- Receiver `attempt_index` counts observed eligible arrivals or ACK
  opportunities for that target. The unchanged retry frame does not encode
  the source's attempt number. Join sender and receiver evidence explicitly.
- Duplication and reversal require ACK disabled. A duplicate uses the exact
  retained original after its completed transmission and has a separate
  `fault.tx` outcome. It needs a fault airtime and guard budget. A reorder block
  allocates space during prepare for up to 32 frames. The sender builds the
  originals in sequence order and submits the saved frames in reverse, with
  the original sequence and bytes preserved. A reorder block cannot overlap
  another source fault on the same range.
- `fault.status` reads up to four entries per page. Fault evidence carries
  target identity, frame size, before/after SHA-256 and node-local application
  time. Receiver faults carry the matched radio arrival time. Lab DATA
  `tx.attempt`, CRC-valid `rx.frame` and extra `fault.tx` records carry wire
  digests so the host can join actual observations. A rejection can carry
  parsed identity and RX time. These are observed header fields.
  Compare these records with receiver evidence before assessing a case.
- Cancel, ownership loss and session close disable hooks and clear retained
  bytes. A prepared hook that expires without application is marked missed.
  Control cases, echo and encoded content can still run on the lab build.

The firmware scheduler composes the control in
[`rf_execution.c`](../firmware/lora_node/main/radio/rf_execution.c).
[`rf_faults.c`](../firmware/lora_node/main/radio/rf_faults.c) owns selectors,
scratch/retained storage and cleanup. Host types and pagination checks live in
[`fault_protocol_v2.py`](../testbed/src/lora_testbed/fault_protocol_v2.py).
The hooks are low-level controls. Use the [controlled lab trial](lab_trials.md)
to exercise one selected fault between verified controls and inspect the retained
sender, receiver and application evidence.

## Software review

From the repository root, activate ESP-IDF v6.0.2, then run:

```sh
uv run --project testbed pytest testbed/tests/test_lab_fragment_controls_native.py testbed/tests/test_lab_fault_commands_native.py testbed/tests/test_rf_faults_native.py testbed/tests/test_radio_execution_contract.py testbed/tests/test_memory_observation_native.py -q
make check
idf.py -C firmware/lora_node build size
```

For the second build, use a separate SDKCONFIG and build directory. Enable
`CONFIG_LORALAB_LAB_FAULTS` in that copy through `menuconfig`. Keep the same
selected board settings as the standard build.

Expect 77 focused cases to pass without skips. The native pair verifies exact
retry and duplicate bytes, single delivery, protected reversal at the 32-frame
bound, exact missing-index reporting and invalid or overlapping target
rejection. Tests also check protected mutation/replay and cleanup. The radio
and CRC observations in these tests come from isolated fixtures. Actual PHY
CRC and over-the-air outcomes require separate bench evidence.
