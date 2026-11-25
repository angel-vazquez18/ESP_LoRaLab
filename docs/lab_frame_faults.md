# Laboratory protected-frame checks

Issue #76 adds two fault controls for finite, protected, generated known-data
runs. The controls are available only when `CONFIG_LORALAB_LAB_FAULTS=y` and
radio execution is available. The option defaults off. Use the matching
`finite_message_execution_v5` schema for both nodes and the host. The diagnostic
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
- `fault.status` reads up to four entries per page. Fault evidence carries
  target identity, frame size, before/after SHA-256 and node-local application
  time. `fault.tx` records a separate radio outcome for the extra submission.
  Compare these records with receiver evidence before assessing a case.
- Cancel, ownership loss and session close disable hooks and clear retained
  bytes. A prepared hook that expires without application is marked missed.
  Control cases, echo and encoded content can still run on the lab build.

The firmware scheduler composes the control in
[`rf_execution.c`](../firmware/lora_node/main/radio/rf_execution.c).
[`rf_faults.c`](../firmware/lora_node/main/radio/rf_faults.c) owns selectors,
scratch/retained storage and cleanup. Host types and pagination checks live in
[`fault_protocol_v2.py`](../testbed/src/lora_testbed/fault_protocol_v2.py).
The hooks are low-level controls. Procedure orchestration, evidence correlation
and fragment/ACK fault cases follow separately.

## Software review

From the repository root, activate ESP-IDF v6.0.2, then run:

```sh
uv run --project testbed pytest testbed/tests/test_rf_faults_native.py testbed/tests/test_lab_fault_commands_native.py testbed/tests/test_memory_observation_native.py testbed/tests/test_radio_execution_contract.py -q
make check
idf.py -C firmware/lora_node build size
```

For the second build, use a separate SDKCONFIG and build directory. Enable
`CONFIG_LORALAB_LAB_FAULTS` in that copy through `menuconfig`. Keep the same
selected board settings as the standard build.

Expect 59 focused cases to pass without skips. The native tests check wrong
targets, ciphertext and tag rejection, identical replay bytes, one delivery,
a later valid control, and cleanup. They use isolated radio/CRC fixtures.
Actual PHY CRC and over-the-air rejection require separate bench evidence.
