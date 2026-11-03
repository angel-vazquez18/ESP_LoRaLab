# V2 simulation execution

> Historical document. The November 1 physical-only decision supersedes the
> simulator workflows and commands below; those implementations were removed.
> See [current status](status.md) and [host usage](../testbed/README.md).

October 26, 2026. The common execution path now runs IF-02 known-data workloads
and IF-03-style campaigns through two virtual nodes. It processes actual bytes;
signal, device clocks, memory and radio timing are synthetic. No physical RF or
audio procedure is qualified by these results. The complete 23-experiment case
matrix is tracked in `experiment_implementation_checklist.md`.

## Dashboard

1. Start the backend and select **Simulation** in the header.
2. Open **Experiments**, select IF-02, and use **Plan and run a simulation**.
   Choose message size/count, direction and radio settings, then calculate.
3. Check the duration budget. Increase the maximum duration if necessary;
   workloads are never silently shortened. GCM and ACK/retry remain preview-only.
4. Optionally enable seeded DATA loss, duplicate observations, reversed fragment
   delivery or message-1 corruption. These are explicit fixtures, not RF forecasts.
5. Start the simulation. The runner discovers/connects/claims both virtual
   nodes, checks capabilities and applied settings, prepares both, arms the
   receiver, starts the sender, collects results and releases resources.
6. Inspect confirmed frames, independently verified messages, PDR, virtual
   goodput, progress, assertions, raw events and sampled binary artifacts.
   A content mismatch can complete execution while failing its assessment.
   Missing evidence makes rates unavailable and the assessment inconclusive.
7. Use **Stop and save partial evidence** to cancel. Refresh/navigation do not
   stop execution. Bench and Results expose the same saved v2 records.
8. Export JSON, CSV, all raw events as JSONL, or a ZIP containing records, events,
   artifacts, provenance and a SHA-256 manifest. Exports require finalized cleanup.

**Campaigns** uses the same planner and runner. Select baseline repetitions or
one sweep axis, directions and seeded/sequential order. Preview every case
before starting. Oversized case groups are divided automatically into linked
batches without changing case order, configurations or message counts.
Pause takes effect between cases; resume preserves the order.
Cancellation retains skipped cases. Select completed campaign cases for a linked
rerun. Compare up to four runs, review setting differences, and inspect passing
case repetition means and sample standard deviations. Non-passing cases remain
in the campaign record and are excluded from those aggregate statistics.

Light/dark appearance uses the existing persistent header toggle. Legacy v1
metadata controls and results remain accessible through explicitly labeled
buttons; they use separate records and do not verify payload bytes.

## CLI

With the backend running at `http://127.0.0.1:8000`:

```sh
uv run --project testbed lora-testbed mode simulated
uv run --project testbed lora-testbed preview-v2
uv run --project testbed lora-testbed run-v2
uv run --project testbed lora-testbed run-v2 --reverse
uv run --project testbed lora-testbed campaign-v2 --spec contracts/v2/simulation_campaign_example.json --preview
uv run --project testbed lora-testbed campaign-v2 --spec contracts/v2/simulation_campaign_example.json
uv run --project testbed lora-testbed status
uv run --project testbed lora-testbed stop
```

`run-v2 --plan FILE` accepts a `KnownDataPlan`. `--simulation FILE` accepts
simulation options. `campaign-v2 --spec FILE` accepts a campaign request, whose
`base` contains both `plan` and `simulation`. Commands return the accepted record;
poll status or open the dashboard to observe completion. The `connect`, `run`
and `campaign` commands remain legacy v1; v2 connects virtual nodes automatically.

## Execution seam and protocol

- `adapters.py`: `NodeAdapter` defines discovery, connect, command/reply, event
  delivery, snapshot and close. `NodeClient` enforces correlation, boot identity,
  per-role sequencing, serialized requests and bounded retry behavior.
- `virtual_nodes.py`: two distinct identities, control leases, bounded command
  cache, asynchronous preparation/start results, applied configuration, health,
  payload generation, framing, reassembly and chunked artifact retrieval.
- `frames_v2.py`: actual unprotected 40-byte DATA headers matching the public
  conformance vector. Payload fragments are reassembled and independently hashed.
- `run_protocol_v2.py`: typed command arguments/results and RF events. NDJSON
  records cross the 4096-byte decoder boundary, including split command input.
  Mutating lost-reply retries retain the exact command identity and apply once.
- `execution_v2.py`: shared finite orchestration and campaign lifecycle. Runners
  use only the adapter interface. Hardware mode cannot start this simulator path.
- `analysis_v2.py`: independent expected bytes, confirmed original/accepted
  identity matching, duplicate accounting, telemetry continuity and final-summary
  reconciliation. Useful goodput counts only verified complete-message bytes.
- `run_records_v2.py` / `reports_v2.py`: separate v2 SQLite tables and artifacts,
  stable device enrollment plus per-run boot/session identities, raw events with
  host UTC/monotonic receipt times, paginated history and hashed exports.

`GET /api/protocol/v2/execution` publishes the execution schema/digest.
`contracts/v2/execution.schema.json` is generated by
`uv run --project testbed python scripts/generate_contract.py`. The installed diagnostic profile
and `/api/protocol/v2` retain their original schema hash; this richer simulation
profile does not advertise compatibility with diagnostic firmware.

## Faults, bounds and recovery

Simulation options include seeded loss/duplication, within-message reversed
fragment order, content corruption, A/B reset/disconnect/lease loss, preparation
refusal/missing completion, command delays/lost replies and dropped/duplicated
events. Unknown command/event fault targets are rejected.

Virtual device time advances in bounded steps with health/lease renewal. The
wall pacing setting only controls simulation speed. Independent A/B clock
offsets prevent treating raw cross-node timestamps as calibrated delay.

A run is bounded to 1000 messages, 10000 original DATA packets and a 65536-byte
message. Resource profiles can lower the message limit. Reassembly retires an
incomplete previous message before accepting the next; final missing ranges are
bounded/split. The first source and first recovered message are retained as
binary samples, while every delivered message retains its complete hash.

Each linked batch is limited to 64 cases, 20000 original DATA packets and 30
minutes of expanded virtual budget. The entire campaign group is bounded to
256 cases, 100000 original DATA packets and three hours of virtual budget.
The current repetitions/directions/eight-value interface can generate at most
160 cases. Batch packing preserves all requested cases and their saved order;
one finalized campaign/export contains every batch. Selected reruns accept up
to 64 cases at a time and preserve source order. A single case exceeding its
run/batch budget still requires explicit workload splitting; it is never shortened.
Security, replay, ACK/retry, echo,
clock-pulse calibration and audio command families remain individual experiment
work and are capability-blocked today.

One host owns active legacy/v2 work. Stop/shutdown performs bounded cleanup and
records idle/buffer-release checks or explicit errors. A host restart marks
unfinished work interrupted, replays v2 raw evidence for analysis, and does not
resume transmitting. Physical disconnects can leave cleanup unverified; creating
a fresh virtual run demonstrates software recovery, not hardware recovery.

## HTTP entry points

| Operation | Endpoint |
| --- | --- |
| State | `GET /api/v2/execution` |
| Start / detail | `POST /api/v2/runs`, `GET /api/v2/runs/{id}` |
| Stop active v2 work | `POST /api/v2/stop` |
| Paginated events | `GET /api/v2/runs/{id}/events?after=0&limit=100` |
| Evidence | `GET /api/v2/runs/{id}/export/{json,csv,jsonl,zip}` |
| Binary sample | `GET /api/v2/runs/{id}/artifacts/{sha256}` |
| Compare | `POST /api/v2/comparisons` with `run_ids` |
| Campaign preview/start | `POST /api/v2/campaigns/preview`, `POST /api/v2/campaigns` |
| Campaign detail | `GET /api/v2/campaigns/{id}` |
| Pause/resume | `POST /api/v2/campaigns/{id}/pause` with `paused` |
| Linked rerun | `POST /api/v2/campaigns/{id}/rerun` with `case_indices` |
| Campaign evidence | `GET /api/v2/campaigns/{id}/export/zip` |

The intended physical transition replaces the adapter and requires matching
firmware, schema/capability checks and measured procedure validation. The current
execution service deliberately admits simulated provenance only. Physical
support must explicitly enable its provenance and measurements; selecting a port
alone cannot turn simulated evidence into hardware evidence.
