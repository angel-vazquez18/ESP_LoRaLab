# Memory and source histories

Issue #88 adds bounded views of the immutable observations saved by #82. Open
**Results & exports → Memory and source histories**. Select a saved record, then
Memory stages or Source and backlog. No fixture or simulated device is available
as an operator mode. Imported evidence remains `imported_unverified`; readback
consistency does not establish physical qualification.

## Reading the views

Memory shows free bytes, largest block, reported observation minimum and known
requested buffer bytes. Boot minimum, retained-sample minimum, reported workload
minimum and unknown true peak have separate labels. Known requested bytes are a
subset of allocations, not heap consumption. Missing PSRAM stays unavailable.
Stage/workload intervals and named buffer generations have independent 32-row
pages. First/last sightings and later absence do not establish exact allocation
or free times. The raw node microsecond timestamps remain visible in these tables.

Source charts use actual sender elapsed timestamps, with separate nominal startup
[0,3), assessment [3,60) and bounded drain [60,deadline) shading. Cohort bytes are
computed by the existing assessor from frame/message identities, not subtraction
of inclusive counter samples. A completed overloaded run shows **Overload
observed**, with its exact window and negative feasibility explanation. Produced,
admitted, overflow and sender-completed counters stay separate from eventual
verified receiver bytes. A receiver delivery rate in the sender window remains
unavailable without clock calibration. The complete source procedure is still
#105; these views do not start it or qualify VOICE-03.

Missing indices, delays, missed periods, telemetry drops and inconsistent snapshots
remain visible. Lines break at retained segment boundaries or nulls. Mixed memory
boots/observations and conflicting source origins disable timeline geometry with
a reason. No wall-clock timer extends a saved history after disconnect. Missing
memory tails stop at the last observed sample, while counted-but-unretained rows
remain a gap. Full reasons and raw rows remain in the export.

## Bounded display and independent export

`GET /api/workload-assessments/{id}/plots` selects at most 480 actual rows per
series by default. `max_points` accepts 32–960. Selection retains endpoints and
per-bucket minima/maxima across the plotted metrics; it never manufactures an
averaged observation. Short omitted segments are counted explicitly. The display
is a bounded overview, not a guarantee that every local extremum is visible.
Stage/buffer offsets select independent 32-row pages. A new record resets offsets.
Live node updates do not reload or grow the historical SVG buffers.

`GET /api/workload-assessments/{id}/export` downloads the entire saved JSON record,
independent of display selection/paging. Its `X-Content-SHA256` hashes the exact
UTF-8 download bytes, including the final newline. The embedded
`document_sha256` hashes canonical compact sorted JSON with that field removed;
`evidence_sha256` separately hashes canonical evidence. These are different hash
scopes. Both endpoints first verify the saved document and evidence; corrupted
records are rejected. Unsupported historical plot schemas still allow intact full
record export instead of silently reinterpreting old evidence.

The response projection has profile `observed_workload_plot_v1`. It is a host view,
not a new node wire contract. Read `workload_plots.py` for clock/gap/selection
rules, `app.py` for export/query bounds, and `WorkloadObservations.tsx` plus
`workload-observations.css` for rendering and operator controls.

## Collect a finite memory observation

With a compatible connected node, choose A or B and 1,000–300,000 ms, then select
**Start observation**. Run an ordinary local workload in the same backend.
**Save current samples** preserves an active partial window as inconclusive;
**Stop and save** stops only the exact current observation and saves its durable
history. The backend owns observation, compatibility and assessment rules.
Accepted IDs are bound to the current host connection; reconnect cannot reuse
an old accepted ID. A node with missing support keeps controls unavailable.

These controls reuse the API/CLI service documented in
[observed workload assessments](workload_assessments.md). They never open a
competing serial port or change ownership of an existing workload.

## Software verification observed November 24, 2026

Run from repository root:

```sh
uv run --project testbed pytest testbed/tests/test_workload_plots.py -q
make check
npm --prefix testbed/frontend run format:check
```

The focused native/ASGI cases compare selected rows against actual portable C
queue/observer outputs, preserve a one-sample 1,024-byte requested-buffer peak in
a five-minute, 3,001-sample injected-clock observation, exercise stage/buffer
paging, missing prefixes/tails, null PSRAM, mixed clocks and corrupted storage.
The full JSON must retain all 3,000 source frames and 451 audits regardless of
plot limit. Native clocks and heap fixtures do not measure ESP32 timing or memory.

Browser verification used an isolated backend on port 8873 with an explicit
SOFTWARE FIXTURE banner, actual native C observations and temporary storage. The
normal backend on port 8000 and physical serial ports were untouched:

| Action | Observed result |
| --- | --- |
| Open long memory record | 23 selected actual rows from 3,001; one-sample peak at 150 s retained; separate boot/sample minima |
| Navigate stages/buffers | Stages 33–64 of 81 and buffers 33–42 of 42; correct previous/next bounds |
| Open overloaded source | 24,000 produced, 4,800 admitted, 19,200 overflow, zero sender-completed; distinct phases and valid negative finding |
| Omit rows / select absent PSRAM | Gap reasons stay visible; no PSRAM free/block curve or invented zero |
| Export full source record | 709,155-byte download independently verified; 3,000 frames, 451 audits and valid canonical document hash |
| Save observer while active | 232 retained rows, inconclusive active window |
| Collect terminal observer | All 301 rows of the finite 30-second window, consistent assessment |
| Disconnect fixture node, reload partial record | Same 232 retained rows; no future samples; observer controls unavailable |
| Light/dark and 390-pixel layout | No page overflow; charts scroll internally; mobile heading and refresh remain readable |
| Console after final navigation | No captured warnings/errors |

Hardware checks remain separate: collect a real finite node observation around a
known local workload, compare raw timestamps/values with the view, disconnect and
confirm the saved endpoint stays fixed, and export/count/hash all rows. Verify
physical PSRAM scope, allocation behavior and source overload only with applicable
firmware, wiring and full procedure evidence. No ESP32 was flashed, reset or
opened for this issue.
