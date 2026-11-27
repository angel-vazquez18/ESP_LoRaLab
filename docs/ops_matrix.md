# Bench stability and recovery

## Linked recovery campaign

OPS-01 C7 uses the shared campaign planner and executor. The procedure
defaults plan 100 cases in a saved seeded order, with 20 single-node
memory checks and 80 paired known-data exchanges. Each linked batch has
at most 64 cases and a declared bound of at most 30 minutes. The matrix
checks that the batches contain exactly the ordered campaign list with
unique IDs, correct previous/next links and intact per-case evidence.

In **Experiments**, select **OPS-01**, **C7** and **Quick check** with
both roles connected and idle. Preview reports any missing capability.
The quick run has ten cases. Use **Inspect cases** and follow the
campaign export to verify its archive. A complete quick fixture
retains ten case results and 26 child records including file transfers.
Choose **Procedure defaults** to request the full 100-case campaign.

The matrix saves the underlying campaign reference before it starts
checking results. Stopping a run cancels the current child and retains
the partial campaign. The completed export is independently verified
before reporting a consistency result. Physical qualification uses the
full campaign and its saved evidence.

## Idle and loaded stability

OPS-01 C6 retains the nodes' periodic 1 Hz health events and checks each
against its original device, boot and role. It brackets the observation
with owned status readbacks. A missing sequence, a health gap of at least
two seconds, new telemetry or framing errors, or an allocation failure
keeps the case inconclusive. The idle variant requires both nodes to
remain idle. The loaded variant schedules one independently verified
64-byte known-data transfer at the start and every 60 seconds thereafter.
Stopping the procedure cancels any transfer it owns and retains partial
evidence and the final idle checks.

Select **OPS-01**, **C6** and **Quick check** for a ten-second observation
per selected idle or loaded case and direction. Both nodes must be
connected and owned. Expect periodic samples from both nodes and one
verified transfer in the loaded case. **Procedure defaults** uses
3,600 seconds for each idle and loaded case in each direction.

The equivalent short CLI request can be saved as `stability.json`.

```json
{"catalog_id":"OPS-01","groups":["C6"],"directions":["A_TO_B"],"ops_observation_s":10}
```

```sh
uv run --project testbed lora-testbed integration-matrix stability.json --preview
uv run --project testbed lora-testbed integration-matrix stability.json
```

The evidence ZIP retains raw health events, the scheduled and actual
transfer starts, child run IDs, counter changes, and host resource
samples. Host peak RSS is the process high-water mark. The bounded
health-buffer counts describe the live data supplied to the dashboard.
Browser heap use and the hour-long physical trials still require bench
measurement.


## Control rejection and timeout recovery

OPS-01 C4 brackets each controlled case with verified 64-byte transfers
of the same source bytes in fresh sessions. The transmitter in the
selected direction is the control target. The invalid configuration
variant sends the fixed rejected frequency and requires its prior radio
settings, link settings, and configuration revision to survive unchanged.
The timeout variant withholds one real reply to a bounded memory
diagnostic in the host fixture. It records the host timeout and verifies
that the node completed exactly one diagnostic and returned idle.

In **Experiments**, select **OPS-01**, **C4** and **Quick check**. The
quick plan covers both controls in both directions. Expect two verified
transfers per case and an explicit rejection or timeout between them.
The evidence ZIP retains the original replies, the scope of the
controlled omission, the matched controls, and cleanup.

## Missing receive observation

OPS-01 C5 deliberately withholds one CRC-valid DATA receive observation
at the host boundary, after the line passes wire and identity checks.
The original is retained as controlled-fault evidence. The next firmware
event exposes one sequence gap. The host still reads back and checks the
actual bytes. The faulted child has incomplete measurement evidence, so
its record excludes RF loss and transfer rates.

In **Experiments**, select **OPS-01**, **C5** and **Quick check**. Expect
three children per direction. The first and third transfers complete in
fresh sessions and independently verify the same 64 bytes. The middle
child records `telemetry_gap`, preserves verified bytes, and confirms
cleanup. The overall procedure case passes only when it proves both the
gap and verified recovery. Physical execution remains a bench check.

## Active and paused host restart

OPS-01 C3 reviews pairs of saved campaign executions. Both the interrupted
campaign and the explicit selected-case rerun are needed. The review can
run after disconnecting the nodes.

1. Create an ordered campaign of at least two bounded known-data cases
   in one direction. For the active variant, stop the host while a
   known-data child is transmitting. Select a long enough transfer to
   catch that stage. For the paused variant, request pause during the
   first transfer and wait for **Paused** between cases before stopping
   the host.
2. Start the backend with the same data directory. Open the saved
   execution and check that it is interrupted. Reconnect the same two
   nodes to their original roles. In the interrupted execution, select
   exactly the interrupted child for an active restart, or the first
   completed child for a paused restart, and choose **Rerun selected
   cases**. Retain the IDs of both executions.
3. In **Experiments**, select **OPS-01**, **C3**, and the required
   workload. Paste the array below into **Saved restart evidence
   (JSON)**, substituting the execution IDs. Preview and start the
   assessment. Use a separate pair of IDs for each case. A quick plan
   has four cases. The default plan has 12, with three repetitions of
   each variant in both directions.

```json
[
  {
    "variant": "restart_active",
    "direction": "A_TO_B",
    "repetition": 1,
    "interrupted": "422ed491-22a7-4319-9949-aee83ab1739f",
    "recovery": "09fae31a-4d41-4b87-a544-52cd0c5c8910"
  }
]
```

The CLI uses the same input array in `ops_restart_evidence` alongside
`"catalog_id":"OPS-01"`, `"groups":["C3"]` and the chosen repetition count.
Save that JSON object as `restart.json`, then run
`uv run --project testbed lora-testbed integration-matrix restart.json`.

Expect a pass for each pair with a saved shutdown/restart checkpoint,
new host and connection identities, a fresh preflight, a fresh radio
session, complete recovery telemetry and matching archived bytes.
Unattached cases are blocked. Missing or damaged records leave that
case inconclusive. The original cleanup result and fault reason are
preserved. Keep both campaign ZIPs with the matrix evidence. An abrupt
restart can preserve incomplete original cleanup, so record physical
cessation and lease timing during bench qualification.

## USB loss and reconnect

OPS-01 C1 reviews an interrupted transfer and a fresh known-data transfer
with the same request. The host records which owned serial connection
failed and how long it took to finish cleanup. The case requires an
acknowledged stop, closed session and confirmed idle state on the peer
that stayed connected. It keeps the original error and the unplugged
node's unconfirmed cleanup in the record.

1. Connect both bench nodes. Start a bounded known-data transfer with
   a long enough transmit window to unplug the selected node while it
   is active. Save the radio run ID and the physical unplug time.
2. Let the host finish stopping the peer. Reconnect the unplugged node
   to the same role and leave the other node on its original connection.
   Use the same saved request for a fresh transfer. Save its run ID.
3. In **Experiments**, select **OPS-01**, **C1**, and the required
   workload. Paste the array below into **Saved USB recovery evidence
   (JSON)** after substituting the radio run IDs. Preview and start.

```json
[
  {
    "target_role": "A",
    "direction": "A_TO_B",
    "repetition": 1,
    "interrupted": "422ed491-22a7-4319-9949-aee83ab1739f",
    "recovery": "09fae31a-4d41-4b87-a544-52cd0c5c8910"
  }
]
```

For the CLI, put the array in `ops_usb_evidence` in a matrix request
with `"catalog_id":"OPS-01"`, `"groups":["C1"]` and the chosen
repetition count. Use `lora-testbed integration-matrix` against the
running backend. A quick plan has four cases. The full C1 plan covers
both fault roles, both directions and three repetitions for 12 cases.

Expect a valid case to link both radio archives, report peer cleanup
within five seconds of host serial failure detection, and verify the
same source bytes after a fresh session. A missing pair blocks its
case. The wrong role, an unconfirmed peer stop or mismatched recovery
evidence leaves it inconclusive. Host detection timing starts when
serial read fails. Use the operator's recorded unplug time and physical
observations to complete the bench timing and lease checks.

## Board reset and stale boot

OPS-01 C2 uses two protected known-data transfers and the existing
IF-01 stale-boot case. Keep the peer connected to its original role
throughout. The reset node must report the same device on a new boot.

1. Start a bounded AES-128-GCM known-data transfer. Use the board's
   reset control while the selected node is active. Record the physical
   reset time and the interrupted radio run ID.
2. Wait for confirmed peer cleanup. Reconnect only the reset node,
   then run **IF-01**, **C5**, **Quick check** for that role. Save the
   procedure ID. The stale-boot case must pass before the next transfer.
3. Repeat the original protected known-data request in a fresh session.
   Save the recovery radio run ID.
4. In **Experiments**, select **OPS-01**, **C2**, and the required
   workload. Paste the three IDs into **Saved reset recovery evidence
   (JSON)**, using the format below. The CLI uses the same rows in
   `ops_reset_evidence` with `"catalog_id":"OPS-01"` and
   `"groups":["C2"]`.

```json
[
  {
    "target_role": "B",
    "direction": "A_TO_B",
    "repetition": 1,
    "interrupted": "422ed491-22a7-4319-9949-aee83ab1739f",
    "stale_boot_procedure": "20db796e-a60a-48fe-9fe9-34022180ee95",
    "recovery": "09fae31a-4d41-4b87-a544-52cd0c5c8910"
  }
]
```

Expect the selected case to show a different boot, a raw `STALE_BOOT`
reply, an idle status with no run or keys, and independent provisioning
and exact readback of the recovery run. A reset may first appear as a
lost serial connection or as a message carrying the new boot identity.
Record three repetitions for each node and direction. Bench validation
still requires the physical stop and lease observations. Cross-node
clock calibration requires its separate timing procedure.
