# Campaigns and comparisons

> Historical document. The November 1 physical-only decision supersedes the
> simulator workflows and commands below; those implementations were removed.
> See [current status](status.md) and [host usage](../testbed/README.md).

Implemented October 18, 2026. These workflows currently execute **legacy v1
simulation only**. Hardware mode remains diagnostic; campaigns cannot issue RF
commands to the attached board. The full CDR experiment list remains required.

## Operator workflow

1. Select Simulation in the header and connect the simulated pair on the bench.
2. Open Campaigns. Expand “Plan a new campaign”, select a preset and settings,
   then preview the complete case list. Any edit invalidates the preview.
3. Inspect case order, repetitions, directions, payload seeds and estimated
   duration before starting. The estimate uses artificial packet pacing and
   excludes setup/pauses; it is not LoRa airtime.
4. Pause after the current case, resume, or stop. A paused campaign retains bench
   ownership. Stop preserves completed/partial runs and marks unstarted cases
   skipped. Changing mode, connections or starting other work is blocked while
   the campaign owns the bench. Page changes and browser refresh do not stop it.
5. Open each case's run or inspect its individual result bar. Completed-case
   summaries group identical sweep settings and direction, with sample count,
   per-run mean and sample SD. SD requires two samples. These are unweighted
   run statistics, not pooled packet statistics or significance estimates.
6. Select cases in a finished campaign to rerun them as a new linked campaign.
   It preserves their settings/seeds and source order. The original is retained.

The initial presets support baseline repetitions or a single varied setting:
payload size, SF, bandwidth, coding rate denominator or TX power. Radio settings
are read back and recorded by the simulator but **do not model radio behavior**.
All constituent cases remain IF-02 simulated runs; IF-03 identifies the host
campaign workflow rather than a hardware validation result.

Limits: 64 cases, up to 8 unique sweep values, 10 repetitions and 30 minutes of
total artificial pacing; each run retains its existing 120-second bound. Within
one repetition, cases share a payload seed across directions/settings. The seed
increments for the next repetition; seeded random ordering is saved exactly.
Failure halts the campaign. Original and cleanup failures are recorded separately.
Host shutdown or an unclean restart interrupts work; it never resumes automatically.

## Comparison and export

Results can be filtered by name/run/campaign ID and execution status. Choose up
to four runs to review configuration/provenance differences before PDR or useful
throughput bars. Zero and absent values remain distinct. Partial runs and
simulation are explicitly identified. Export the comparison as JSON.

Campaign CSV includes every case, including skipped cases without measurements.
JSON contains the campaign, constituent runs and repetition statistics. ZIP
contains the same records, raw event JSONL per run, a printable HTML report, the
23-entry CDR readiness catalog and a SHA-256 manifest for all included files.
Export requires the campaign to finish or stop. It does not assign correctness
or security assessments; measurements remain exploratory/not assessed.

The HTML report currently provides the case matrix and reproducible settings;
interactive result bars are in the dashboard. Static result figure exports,
capability-driven physical campaigns, delta/paginated live history and a
case-level hardware coverage ledger remain subsequent work.

## CLI and HTTP

```sh
uv run --project testbed lora-testbed connect
uv run --project testbed lora-testbed campaign testbed/presets/simulation/known_data_campaign.json --preview
uv run --project testbed lora-testbed campaign testbed/presets/simulation/known_data_campaign.json
uv run --project testbed lora-testbed pause CAMPAIGN_ID
uv run --project testbed lora-testbed pause CAMPAIGN_ID --resume
uv run --project testbed lora-testbed stop
uv run --project testbed lora-testbed compare RUN_ID_1 RUN_ID_2
```

HTTP: `POST /api/campaigns/preview`, `POST /api/campaigns`,
`GET /api/campaigns/{id}`, `POST /api/campaigns/{id}/pause` with `{"paused":true}`,
`POST /api/campaigns/{id}/rerun` with `{"case_indices":[0,2]}` (zero-based),
`GET /api/campaigns/{id}/export/{csv|json|zip}` and
`POST /api/analysis/compare` with `{"run_ids":["…","…"]}`.

The existing `POST /api/runs/stop` stops the bench owner, whether a single run
or a campaign. Campaign metadata is added to the existing SQLite database;
earlier runs and node observations are retained.
