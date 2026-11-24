# Observed memory and fixed-source assessments

Issue #82 adds persisted evidence and analysis, not the complete MEM-01 or VOICE-03
procedure matrices. Software consistency, execution outcome and physical
qualification remain separate. No import or readback in this slice sets
`hardware_qualified` to true. Campaign execution (#87), dashboard plots (#88), the
full sustained-source procedure (#105) and physical acceptance (#136) follow.

## Source accounting

`workload_assessment.py` consumes the typed `run.source` status, actual frame trace
and queue snapshots from the selected fixed-source profile. It checks both byte
balances independently of delivery:

```text
produced = admitted + whole-message overflow bytes
admitted = sent + failed + consumer-discarded + queue-discarded
           + partial-discarded + remaining occupancy
```

Whole-message counters, outcome masks, borrowed/partial/ready occupancy and frame
bytes must also agree. A source worker that completed can produce a valid
`unsustainable` finding. Losing 16 whole messages while producing all 24,000 bytes
is a useful negative result; it does not become an execution failure or a
sustainable-link claim. Source completion alone never establishes the parent RF
run's execution outcome.

The startup cohort is nominal **[0, 3) seconds**, message 1. The assessment cohort
is **[3, 60) seconds**, messages 2–20: 2,850 frames, 22,800 bytes and 3,200 bit/s.
A frame at exactly 3 seconds belongs to the assessment interval. Actual frame
production times and actual-time interval counts remain available separately.
Subtracting inclusive samples at 3 and 60 seconds would misclassify the frame at
3 seconds, so cohort totals come from the frame trace and message identities.
Drain starts at 60 seconds, lasts at most the configured 30 seconds, and cannot
add produced bytes. Drain completion/discards remain recorded separately.

Overflow or sampled growth beyond one whole-message of additional backlog
prevents a `no_overload_observed` finding. The one-message allowance excludes
normal final-message assembly/active transmission. This is a finite-window
criterion, not a prediction of indefinite operation. Partial assemblies are
removed before comparing whole backlog at the 3/60-second sampled boundaries.
The 5 Hz trajectory cannot resolve every transient; the separately reported queue
peak is a producer counter, not an inferred memory peak. Missing frame/pages,
inconsistent snapshots, missing audits, missed producer periods and recorded
telemetry loss make the relevant capacity conclusion inconclusive. Telemetry
backpressure can affect the consumer, so the result does not isolate RF airtime
as a cause.

Sender `sent_bytes` are never delivered bytes. Optional receiver evidence keeps
reported IDs distinct from independently verified bytes. Verification requires
the 1,200-byte reference and full 24,000-byte archive with its SHA-256: delivered
slots must equal the reference, and every unreported slot must be zero. A
matching digest alone cannot hide wrong contents. Lost final ACKs can allow a
receiver delivery when the sender records a failed message. Receiver clocks are
independent: **receiver delivery rate inside the sender's 3–60 second window is
unavailable without calibration**. Eventual delivery for the source cohort is a
separate measure.

## Memory scope

Typed `memory.sample` records retain their device, boot, role, observation ID,
actual capture bounds, stage and workload ID. Samples are grouped into contiguous
stage/workload segments, including separate idle periods before and after work.
Observation indices and final `samples_taken` detect missing or duplicated rows;
gaps in the global event sequence alone are not interpreted as lost memory rows,
since other event types interleave.

Reported boot minima, firmware observation/workload minima and reconstructed
sample minima have separate fields. Free internal/PSRAM bytes, largest free
blocks and known requested buffers are separate quantities. Known buffer bytes
are a subset of allocations and must never be added to heap consumption.
Absent PSRAM remains unavailable. Names plus generation identify observed buffer
lifetimes; first/last retained observations and first later absence do not invent
an exact allocation/free timestamp. Inventory truncation/overlap remains visible.

The true memory peak is always unavailable with a reason: 100 ms non-atomic
samples miss between-sample peaks, and provider, library, DMA and task internals
are not fully tracked. First/last sampled free-byte differences are descriptive;
no undocumented threshold turns them into a leak or recovery qualification.

## Collect and save

Use the existing backend; these commands do not open a competing serial port.
One compatible node, A or B, is enough for a local observer:

```sh
uv run --project testbed lora-testbed memory-observe A --duration-ms 30000
# Run the selected local workload through the ordinary testbed controls.
uv run --project testbed lora-testbed memory-collect A OBSERVATION_UUID --stop
uv run --project testbed lora-testbed workload-assessments
uv run --project testbed lora-testbed workload-result ASSESSMENT_UUID
```

The observer can surround an existing local or RF workload without taking its
bench ownership. `--stop` only stops the exact current observation ID. Without
it, an active observation can be saved, with an inconclusive assessment. The
finite firmware observer stops on deadline/owner loss; reconnect never resumes it.

`source-collect A RUN_UUID` reads an already owned **terminal sender** before the
parent runner calls `session.close`. It never starts or stops RF, reconnects a
node, closes its session, or treats a source worker's terminal state as parent
run success. It paginates frames (16 per page) and snapshots (one per page), checks
stable terminal status, and uses a 45-second collection bound. On a timeout,
connection change or cancellation after the initial status, partial pages and an
inconclusive assessment are saved. Shutdown joins collectors before closing the
store. The parent sustained-source runner still belongs to #105; this command
alone cannot start a sustained run. Receiver archive collection belongs to that
parent and is not fabricated by this sender-only readback.

Physical readback preserves its connection/device/boot binding, current exact
profile hashes and normalized result bodies. Queue gap accounting conservatively
includes observed connection gaps and the latest boot-wide reported telemetry
drops; it does not invent a per-run drop baseline. Already persisted memory
events are collected from SQLite rather than the small live history deque.

For a trace collected elsewhere, save a JSON object matching `AssessmentRequest`
(`source`, `memory`, or both, and optional `parent_run_id`) and run:

```sh
uv run --project testbed lora-testbed workload-assess path/to/trace.json
```

Imports are labelled `imported_unverified`, even if internally consistent. They
are analysis inputs, not an operator simulator or authenticated hardware proof.
The saved `evidence` object can be used as another assessment request. Records
include schema/source fingerprints, normalized raw evidence, its SHA-256 and a
whole-document hash. Historical records are verified on read and never silently
reassessed under new source. Raw input is bounded at 12 MiB and final records at
16 MiB. Runtime data remains under the selected ignored backend data directory.

The API uses the same service:

- POST/GET `/api/workload-assessments`; GET `/api/workload-assessments/{id}`.
- POST `/api/nodes/{role}/memory-observation` with `duration_ms`.
- POST `/api/nodes/{role}/memory-observation/{id}/collect?stop=true`.
- POST `/api/nodes/{role}/source-observation/{run_id}/collect`.

## Review and checks

Read `workload_assessment.py` for balances/windows/unknowns,
`workload_observations.py` for persistence and bound readback, then the public
ASGI/native cases in `test_workload_assessments.py`. API/CLI callers live in
`app.py`/`cli.py`; `storage.py` retrieves the durable observer records.

From repository root:

```sh
uv run --project testbed pytest testbed/tests/test_workload_assessments.py -q
make check
npm --prefix testbed/frontend run format:check
```

The native no-consumer fixture must reconcile 24,000 produced, 4,800 admitted,
19,200 overflow-dropped and 4,800 drain-discarded bytes, with no delivery claim.
The fast consumer fixture must retain all source bytes and verify only the
independently present archive slots. Fault fixtures remove frames/audits, change
counters/boots/minima and interrupt readback; affected conclusions must be
inconclusive or inconsistent, with retained evidence. The native memory fixture
must retain preparation/capture/idle stages, 399,680 sampled minimum internal
free bytes, distinct 130,000 boot minimum and unknown true peak. The real
NodeSession/native-serial fixture checks concurrent observation and a local job;
all of these are explicitly software fixtures.

Physical validation remains open. With the correct board profile and a released,
identified node, collect an idle/workload/recovery observer trace and confirm the
saved events and actual device/boot match. When the parent sustained-source
runner is implemented, collect a complete source run before close, independently
read the receiver archive, compare every byte/message category, and repeat under
a slower radio setting. Record measurements and gaps; do not infer a physical
pass from these software checks.
