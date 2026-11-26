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
