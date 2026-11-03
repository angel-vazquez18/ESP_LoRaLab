# Simulated integration procedures

> Historical document. The November 1 physical-only decision supersedes the
> simulator workflows and commands below; those implementations were removed.
> See [current status](status.md) and [host usage](../testbed/README.md).

IF-01, IF-02 and IF-03 now have executable procedure matrices, separate from
individual runs and custom campaigns. The normative settings and acceptance
rules remain in `test_procedures.md` revision 2.0. Physical USB/RF validation is
still pending. No board, radio firmware, microphone or speaker is required here.

## Operator workflow

1. Build the frontend and start the backend using the README instructions.
2. Select **Simulation → Experiments → IF-01**. Preview and execute the full
   serial procedure. It must pass for both roles under the current source profile.
3. Select **IF-02**, preview its 30-case full plan, then start validation.
4. Review group progress, the case ledger, expected/observed assertions, cleanup
   and linked child runs. Inspect the direction/payload-size goodput chart.
5. After IF-02 passes, select **IF-03** and execute its 25-fixture full plan.
6. Open **Results & exports** and use the IF-01/IF-02/IF-03 tabs to revisit
   saved procedures. Download JSON, CSV, raw JSONL or a hashed ZIP bundle.

Full passing prerequisite runs are linked in the procedure record. A quick
check, selected groups, one direction or reduced message/repetition counts
cannot close full readiness. Readiness uses the latest finalized full run
matching the current implementation profile. A later failed/interrupted full
run revokes that indication; partial checks do not replace full evidence.

The **Individual runs and custom campaigns** disclosure retains ad hoc settings,
fault injection, comparisons and the existing common execution workflow.

## IF-02 matrix

| Group | Conditions | Executions |
| --- | --- | --- |
| C1 | 64 useful bytes, 100 messages, both directions, three repetitions | 6 |
| C2 | 1, 159 and 160 useful bytes, 100 messages, both directions, three repetitions | 18 |
| C3 | Applied peer frequency mismatch rejected before arm/start, followed by a corrected 100-message control; both directions, three repetitions | 6 |

The 30 procedure cases retain 36 child runs: 24 positive runs, six rejected
controls and six successful recovery controls, totaling 3,000 verified messages
in the no-loss fixture. Each positive run verifies source/readback, receiver-first
ordering, packet/summary reconciliation, independent content hashes and cleanup.
Mismatch controls require zero confirmed transmissions and no arm/start commands.

Full delivery is an expected property of this explicit no-loss software control.
It is not a universal PDR acceptance target for physical RF measurements.

## IF-03 matrix

Every fixture starts from a saved seeded six-case plan: 100 useful 64-byte
messages, three repetitions in both directions. C1 runs once; each other
variant runs three times, producing 25 procedure fixtures.

| Group | Variant and assertions |
| --- | --- |
| C1 | Six linked runs, distinct sessions, saved order/settings and content correctness |
| C2 | Current case completes; five cases wait while paused; resume preserves order |
| C3 | Stop after an observed TX; retain partial metrics, one cancelled run and five skipped cases with reasons |
| C4 | Applied configuration mismatch halts the campaign; preserve original error separately from cleanup; successful fresh recovery |
| C5 | Retrieve the dashboard and repeated state/campaign reads during execution; preserve cases, owner and links |
| C6 | Restart active and paused application lifespans against the same SQLite store; interrupted terminal evidence, no automatic resumption, fresh ownership/session preflight |
| C7 | New linked campaign containing exactly selected source cases and original settings/seeds/order |
| C8 | Reject concurrent starts and mode/connection changes; reject incomplete export; verify CSV/JSON/JSONL and every ZIP manifest hash |

C5 exercises backend/page retrieval. Interactive browser reload/navigation is a
separate UI verification step; it could not be repeated on October 31 because
the browser automation connection was unavailable and the native fallback timed
out. C6 uses real orderly application shutdown/reopen, not an OS process kill
or physical power-loss test. A separate regression checks interrupted persisted
campaign recovery without automatic resumption. Active cancellation/restart
fixtures use 2 ms wall pacing to observe a confirmed transmission cut-point;
device airtime still comes from the virtual clock.

## Execution and evidence

Each integration case creates an isolated production FastAPI/Host instance in
`data/procedure-fixtures/<procedure>/<case>`. It uses the actual ASGI routes,
bench ownership checks and common adapter/execution engine. There is no listener
or serial-port access. Restarting a fixture never restarts the operator's backend.

Child run/campaign records, exact raw node events, original host receipt times
and sampled binary artifacts are imported into the normal result tables. Stable
parent device enrollments are retained, with original fixture enrollments saved
for traceability. Procedure evidence includes HTTP actions and response hashes,
plans, state transitions, assertions, errors, cleanup and child records/events.

The procedure ZIP contains its JSON record, a CSV case ledger including metrics
and child links, raw JSONL, provenance, and the independently verified child ZIPs.
An outer SHA-256 manifest covers every file. Saved child bundle hashes are checked
again during export; changed evidence prevents a successful export.

All runs retain simulated provenance. Signal, virtual timing and synthetic memory
are not measurements of an ESP32 or a physical radio link. Source/profile hashes
identify the procedure, contract, schema, execution, analysis and API implementation.

Stop finalizes the current fixture, preserves partial records, skips unstarted
cases with reasons, verifies idle/buffer cleanup and releases bench ownership.
Outer host shutdown marks the procedure interrupted. Reopening storage does not
resume a procedure or transmission. Historical evidence remains exportable.

## CLI and HTTP

```sh
uv run --project testbed lora-testbed serial-check
uv run --project testbed lora-testbed integration-check --experiment IF-02 --preview
uv run --project testbed lora-testbed integration-check --experiment IF-02
uv run --project testbed lora-testbed integration-check --experiment IF-03
uv run --project testbed lora-testbed integration-check --experiment IF-03 --quick
uv run --project testbed lora-testbed procedure-status RUN_ID
uv run --project testbed lora-testbed stop
```

Use `POST /api/procedures/integration/preview` or
`POST /api/procedures/integration` with `catalog_id`, optional `groups`,
`directions`, `repetitions`, `message_count` and `seed`. Full counts are the
defaults. IF-03 requires both directions and at least five messages so a partial
transmission can be observed. `GET /api/procedures` lists history and active virtual
node/workflow data. Saved detail, paginated per-case evidence and finalized
exports use the existing `/api/procedures/runs/{id}` routes.
