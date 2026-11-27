# Reserved finite run lifecycle

Issue #69 makes known data and committed encoded voice use the same resource and
security owner. The shared backend sequences prepare, receiver arm, sender arm,
start, stop and close. GUI and CLI use that backend; there is no alternate runner.
Physical RF, audio quality and resource qualification remain separate.

## Read the change

- `run_protocol_v2.py` and `contracts/v2/execution.schema.json`: exact profile,
  arm policy and typed replies; `radio_examples.json` has independent examples.
- `radio/rf_execution.c`: checked transitions, transactional reservations,
  deadline handling and one cleanup path for both message contents.
- `radio/rf_reassembly.c`: reserve during prepare, schedule without allocation
  at arm, then authenticate/insert/verify through the existing receive path.
- `radio_runs.py`: receiver-first ordering, both arm replies, host clock bounds,
  evidence retention and cleanup whose errors do not replace the initiating error.
- `test_run_lifecycle_native.py` / `test_run_lifecycle_host.py`: public command and
  host workflows with actual portable C and isolated serial/SPI/allocator clocks.

## Transitions and resources

| Phase | Allowed next step | Resources and effects |
| --- | --- | --- |
| Open, idle | Configure, prepare, close | Session owns imported volatile source keys when protected |
| Preparing | Prepared, stop, close, timeout | Source/borrow, artifact reservation, sender or receiver/reassembly data, optional ACK owner reserved; no RF |
| Prepared | Arm, stop, close, timeout | Preparation result/evidence describes actual source bytes and artifact state |
| Sender armed | Start before deadline, stop, close, timeout | No RF command or new nonce use at arm |
| Receiver armed | Receive, stop, close, timeout | Existing storage scheduled, bounded RX enabled; no new work-buffer allocation |
| Running/draining | Completion, stop, close, timeout | Common retained-frame retry, authentication/replay and complete-message publication |
| Reporting failure | Finish report or bounded cleanup | Missing ranges retained only within the run deadline; incomplete evidence stays explicit |
| Terminal/idle | Read committed files, summary, close | Working buffers released; no automatic restart |

Prepare reserves the statically known working buffers before reporting success.
Any failed reservation unwinds all newly owned work/artifact reservations and
releases a borrowed source without deleting it. A generated-ID collision rejects
without deleting the preexisting file: rollback only deletes a reservation this
prepare actually created. Known-data source publication
occurs only after those reservations succeed. Preparation itself has the accepted
maximum-duration deadline, independent of owner keepalives. Existing session keys
precede preparation and remain session-owned after a rejected prepare; stop/close
or ownership loss retires them. Sequence reservations are never rolled back or
reused after failure. This does not promise that a crypto implementation or driver
can never fail an internal allocation; such failures remain explicit and bounded.

Stop, close, lease loss and USB loss retire active work and keys. Failed radio
arm/start also closes the failed session. A driver stop failure disables radio
availability through the existing driver; software idle is not physical RF
qualification. Close clears the run/session association. Committed evidence files
survive until explicit deletion/reset, while partial output cannot become playable.
A full telemetry queue cannot extend working-buffer or radio deadlines; forced
report termination marks missing-range evidence incomplete and preserves drops.

Local capture, encode/decode, playback and host-armed PTT retain their own finite
operation owner and existing cancellation cleanup. The voice coordinator composes
these with this RF lifecycle. PTT's 30-second wait/capture limit is unchanged.
Clock calibration is still unavailable and has no live calibration state to retain;
its later implementation must attach invalidation to session close/ownership loss.
No successful calibration or timing acceptance is implied here.

## Five-second start rules and clocks

`run.arm` returns `role`, `receiver_ready` and `arm_deadline_us`. Only a receiver
returns `receiver_ready:true`. Both roles require prepared state and the exact
applied revision. Only a sender accepts `run.start`, and only while locally armed
and strictly before its five-second deadline. A second arm cannot extend it.
Expiry releases working memory and keys; a new start/arm cannot resume the run.
The dispatch loop may process expiry before the command, yielding INVALID_STATE;
a direct expired-start check yields TIMEOUT. Neither admits a new transmission.

The host starts its conservative clock before requesting receiver arm, checks it
after receiver readiness and sender arm, and refuses to issue start at or beyond
five seconds. The start reply must also fit that host interval; a late reply fails
the run and triggers cleanup. The sender independently checks its local arm.
These are distinct checks: the sender cannot observe remote readiness or compare
its clock with the receiver. No cross-node synchronized-clock assertion is made.
Receiver RX/reassembly bounds include a five-second start allowance plus the
validated run/reassembly window, so a slow start cannot silently shorten it.
The host wait bound includes that allowance too.

## Errors and compatibility

`run.summary.stop_reason` preserves the initiating timeout/error/cancellation.
A later stop that truncates blocked failure reporting cannot relabel a timeout as
an operator cancellation. `cleanup_errors` independently lists RADIO_STOP_FAILED
and/or KEY_RETIRE_FAILED. Host run errors and per-node cleanup confirmation are
also retained separately; unconfirmed cleanup disconnects ownership and cannot
be reported as successful completion.

The lifecycle originally introduced `finite_message_execution_v2`. New work uses
`finite_message_execution_v3`, which adds the fixed VOICE-03 source and bounded
`run.source` evidence. Deploy matching host/firmware together and require the
exact generated profile/hash in identity and current health. Old peers remain
unavailable; historical records are preserved. Main-control, diagnostic,
artifact, audio, codec, PTT and OLED identities remain separate. See
[fixed source](fixed_rate_source.md) for the source variant and current digest.

## Reproduce software checks

From repository root:

```sh
uv run --project testbed pytest testbed/tests/test_run_lifecycle_native.py testbed/tests/test_run_lifecycle_host.py testbed/tests/test_rf_execution_native.py testbed/tests/test_protected_voice_native.py -q
make check
source /Users/anken18/.espressif/v6.0.2/esp-idf/export.sh
idf.py -C firmware/lora_node build size
```

Expected: no transmission before arm; success just before five seconds and rejection
at/after it; no new receiver work-buffer allocation at arm; each injected prepare
allocation failure restores its baseline; failed borrowed-voice preparation leaves
source bytes unchanged; stop/close/lease/disconnect free work and retire keys from
every owned phase; following sessions work. Driver faults and queue backpressure
retain truthful failure/cleanup evidence. These tests never open physical ports.

## Remaining physical acceptance

After PCB/pin/antenna identification and the deployment backup procedure, use two
matching nodes to run known data and a committed voice clip in each direction.
Observe prepare, both arms, start and bounded stop/close; retrieve and independently
verify actual files. Delay start beyond five seconds and require no new TX; cancel
at each phase and disconnect/reset each participant. Require fresh identity, idle,
retired security and a successful following run, with no automatic resume. Record
node/boot/build/profile identities and host/local clocks, partial evidence and
cleanup errors. Validate recovery memory separately under #73 and physical
qualification; software fixtures do not establish target heap/stack peaks, heard
speech, physical stop timing or radio propagation.
