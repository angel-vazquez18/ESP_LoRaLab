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
restart, timeout and telemetry perturbation, and full physical campaign
acceptance remain separate checks.

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
