# Physical campaign execution (#87)

A campaign executes the cases in an immutable saved plan through the existing
memory/crypto diagnostic, partial serial, audio, known-data and secure-voice
runners. It keeps their actual preparation, byte verification, cleanup and
provenance; it does not reimplement firmware work or add an operator simulator.
Full CDR procedure references remain blocked until their individual matrices are
implemented. All 23 remain selectable in plans and visible in the execution ledger.

## Start and inspect

With the existing backend running, from repository root:

```sh
uv run --project testbed lora-testbed campaign-plan testbed/examples/local_and_radio_plan.json
uv run --project testbed lora-testbed campaign-execute PLAN_UUID
uv run --project testbed lora-testbed campaign-executions
uv run --project testbed lora-testbed campaign-result EXECUTION_UUID
uv run --project testbed lora-testbed campaign-pause EXECUTION_UUID
uv run --project testbed lora-testbed campaign-resume EXECUTION_UUID
uv run --project testbed lora-testbed campaign-cancel EXECUTION_UUID --reason 'Retain partial results'
```

Saving a plan still starts no work. New plans record current execution-service
availability; it is separate from per-case capability readiness. Older saved
plans retain their original availability snapshot and hash. The current execution
service, not historical readiness flags, checks each case before doing work.

The shared HTTP interface is POST `/api/physical-campaigns/executions` with
`plan_id`, GET `/api/physical-campaigns/executions` or `/{execution_id}`, and POST
`/{execution_id}/pause`, `/resume` or `/cancel`. Cancel accepts a bounded `reason`.
The normal global stop also cancels an active campaign. The [dashboard controls](campaign_dashboard.md)
added in #115 use this same service as the CLI.

## Ownership and order

One campaign reserves the bench, including while paused. Other runs, campaigns,
file/audio operations and connection changes reject while it owns the bench.
Internal child dispatch uses an opaque owner token; operator requests cannot
supply it. Each child still passes the ordinary compatibility, freshness,
capability, resource and idle checks. The independent finite memory observer may
surround work; it is instrumentation, not a competing bench workload.

Local cases may use either node alone, including B. RF/voice require distinct
A/B devices. Connected roles needed by the plan are enrolled by exact device,
boot and host USB connection ID at campaign start. A reset or same-boot reconnect
cannot resume queued work, and cleanup for the old connection cannot close its
replacement. An absent role cannot be connected midway through an owned campaign.

Execution follows the saved case order, source seeds, directions and batch links;
it never expands or randomizes the plan again. Each execution has a separate
header and ordered case ledger. The original plan and its empty future `run_id`
fields remain immutable. The ledger links actual child service/record IDs and
planned case/batch IDs. Case reservation is committed before hardware effects;
a diagnostic child is linked before sending its acceptance command, so a lost
reply does not hide the failed child job. Repeated lost acceptance can outlast
the control lease and force disconnect: the parent then records interruption
and unconfirmed cleanup, requiring a fresh connection. It does not invent an
accepted operation ID or idle confirmation.

Linked planning batches keep their existing case/time bounds. Execution traverses
them in order, retaining every case. Per-case bounds come from the saved planning
reserve, while the existing child services retain their more specific deadlines
and bounded cleanup. These are scheduling limits, not measured RF durations.

## Pause, cancel and failure

Pause waits for the active case to finish, including its cleanup, then holds the
remaining queue and bench ownership. Resume uses the same enrolled connections
and exact remaining order. A pause requested during the final case does not park
an empty queue; the campaign finishes. Resume never reconnects or restarts a node.

Cancel stops the active child through its own service, waits for cleanup and
retains its partial record. Unstarted cases become skipped with an explicit
reason such as `operator_cancel` or `host_shutdown`. An immediate global stop
before the worker starts sends no diagnostic/RF command. Completed earlier cases
remain completed. Cancellation during the parent's final cleanup waits for that
cleanup and returns the existing outcome; it cannot overwrite completion with a
permanent `cancelling` state. Parent completion is published only after cleanup,
with a separate `stage=cleanup` while it is still active.

A runtime child failure stops the campaign and reason-codes queued cases with
`child_failed`, `child_start_failed`, `case_timeout` or `node_changed`, as
appropriate. The original child error and its cleanup remain linked. Cleanup
checks each enrolled node independently; unconfirmed cleanup never becomes an
idle or qualification claim. Already unavailable cases are recorded as blocked
and execution can visit later cases. A campaign that visits all cases but has
blocked entries ends blocked, rather than reporting all work completed.

Graceful host shutdown joins the campaign and its child cleanup before closing
the serial sessions/database. Cold restart marks unfinished campaigns interrupted,
active cases interrupted and unstarted cases skipped with `host_restart`.
Previous cleanup stays unconfirmed; no port is opened and no RF/audio operation
is automatically resumed. To run again, explicitly create a new execution from
the saved plan. Linked selected-case reruns and verified exports are implemented in #107; see
[rerun, recovery and evidence policy](campaign_reruns_evidence.md).

## Records and scope

The new `physical_campaign_executions_v1` and `physical_campaign_cases_v1` SQLite
tables preserve execution state separately from immutable plans and historical
legacy campaigns. Child records remain in their existing diagnostic, procedure,
audio, radio and voice stores with their raw events, bytes and hashes. Header
snapshots are compact; detailed case rows are retrieved explicitly. Records retain
plan/source fingerprints, bindings, timestamps, status, reason codes and cleanup.

Execution outcome, each child's assessment and full physical procedure
qualification are separate. The campaign never converts software fixtures,
partial IF-01 checks, local DMA completion or a finite voice delivery into full
hardware qualification. Missing acceptance/results are not invented. A valid
negative experimental finding may still come from a successfully completed child.

## Review and verification

Read `physical_campaigns.py` for reservation, dispatch, pause/cancel/finalization
and restart behavior. `host.py` retains the common ownership gates;
`diagnostic_jobs.py` reserves durable child links before acceptance and preserves
actual partial terminal results after stop. `app.py` and `cli.py` expose the same
controller. `campaign_plans.py` only records intent and its availability snapshot.

From repository root:

```sh
uv run --project testbed pytest testbed/tests/test_physical_campaign_execution.py -q
make check
npm --prefix testbed/frontend run format:check
```

Software cases use the actual portable C control/PSA/Codec 2 code behind isolated
serial/audio/radio fixtures. They check a single B node, mixed local jobs, saved
seeded order, active/paused ownership, partial cancellation, both-peer cleanup on
RF failure, exact data/voice readback, all 23 unavailable procedure references,
immediate stop, same-boot replacement safety, late-cancel cleanup and cold
restart. These fixtures never qualify physical hardware.

Physical acceptance remains open. With identified compatible nodes and released
ports, create a short plan containing a local check and bidirectional known data.
Confirm child links, exact source/readback bytes and idle/key cleanup. Request
pause during a case: it must finish while queued order remains unchanged and new
work/connection changes reject. Resume, then repeat with cancel, unplug/reset
and host restart; retain partial/skipped records and confirm no automatic RF
resume. Repeat a local-only plan with B alone. Use the correct board profile;
software verification does not authorize a speculative flash or substitute for
these physical observations.
