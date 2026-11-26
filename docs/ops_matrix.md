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
before reporting a consistency result. Board disconnect/reset, host
restart, and full physical campaign acceptance remain separate checks.

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
