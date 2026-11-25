# Physical echo orchestration and RTT evidence

Issue #83 adds the shared physical host path for the finite echo capability.
It does not qualify TIME-01 (#102), enable pulse instrumentation or establish
one-way timing. The operator uses actual serial nodes; native bus/serial peers
exist only in isolated checks.

## Run and inspect

Start the normal shared backend from the repository root with `make serve`.
Both enrolled nodes need fresh idle health, distinct identities, the exact current
execution schema, radio/echo support and compatible artifact readback. The same
bench owner excludes competing data, voice, audio, diagnostic and campaign work.

```sh
uv run --project testbed lora-testbed echo-start --preview
uv run --project testbed lora-testbed echo-start --direction A_TO_B --message-bytes 64
uv run --project testbed lora-testbed radio-status RUN_ID
uv run --project testbed lora-testbed echo-start --direction B_TO_A --security aes128_gcm
uv run --project testbed lora-testbed echo-distribution RUN_ID_1 RUN_ID_2
uv run --project testbed lora-testbed radio-export RUN_ID /tmp/echo-evidence.zip
```

Use `--config PATH` for the existing explicit radio/link/security/timeout settings.
One run sends one fixed-length request. Repetition/full TIME-01 matrices remain a
separate procedure; do not assume this command automatically starts 100 requests.
Use `radio-stop RUN_ID` to cancel. Status, raw wire/content and hashed export use
the existing radio routes; no second lifecycle or browser owner is introduced.
The dedicated timing/fault dashboard is #89, not part of this host slice.

| API | Purpose |
| --- | --- |
| POST `/api/echo/preflight` | Readiness only; same request fields as `echo-start` |
| POST `/api/echo/runs` | Explicitly start one echo; returns its shared radio ID |
| POST `/api/echo/distribution` | JSON array of 1–1000 distinct saved echo IDs |
| GET `/api/radio/runs/{id}` | Saved full record, raw events and timing findings |
| POST `/api/radio/runs/{id}/stop` | Existing bounded stop/cleanup |
| GET `/api/radio/runs/{id}/export` | Existing hashed raw/transfer/content bundle |

## Independent evidence checks

The common runner configures both nodes, provisions fresh source keys when
selected, retires host keys immediately after provisioning, prepares both sides,
arms the responder first and explicitly starts the requester. The existing bound
adapter rejects changed devices, boots or USB connection IDs. Cleanup attempts
both original bindings independently and never closes a replacement connection.
After verified readback, echo cleanup retires only fresh artifacts created by that
run, checked against an initial artifact listing. Pre-existing files and failed
readbacks remain intact. Retirement failure stays explicit, still closes both
sessions and prevents a successful timing finding. This permits repeated echoes
without exhausting the four node slots. Issue #210 extends the same policy to
generated DATA; encoded references and downstream voice objects keep their own
lifecycle. See [physical radio retention](physical_radio_runs.md).

The firmware result now includes `reply_hex`: at most 215 actual accepted
known-data bytes (430 hex characters), null when unavailable. This is public
experiment content, never keys or arbitrary private voice content. The existing
pending wire buffer retains the validated bytes; one bounded terminal copy serves
the summary after cleanup. The generated execution v4 digest changes accordingly;
host and firmware must match that exact revision. Old saved records are not
rewritten or relabelled. Other wire profiles remain independent.

The host independently generates the expected seeded bytes, retrieves the actual
source and responder's recovered request, compares the returned reply bytes, then
reconciles request/reply frame identities, roles, session, sizes, confirmed TX,
receive observations and insertions. The echoed request reference and payload
hash must match. The requester result must match its queried terminal summary.
Both timing records use the same captured acceptance instant; serialization does
not take a second timestamp.

A timing sample requires complete, identity-consistent evidence, confirmed cleanup
and a completed execution. Invalid or duplicate result events, inconsistent
references/bytes/times, missing receive evidence, changed clocks, telemetry gaps,
failed cleanup and stopped/interrupted runs retain reason-coded exclusions.
Ordinary duplicate/late rejection events remain visible; a rejection does not
invalidate a later legitimate matched reply. Missing replies are a completed
finite observation with a `timeout` exclusion and unavailable latency. They do
not become zero-delay successes or require a fabricated recovered file.

## Statistics and clock scope

Each valid interval is `reply_accepted_us - tx_command_us` on the same requester
boot. No peer clock or host arrival timestamp enters that subtraction. Reports
include n, median, minimum/maximum and nearest-rank p95: sorted element
`ceil(0.95 × n)`, using one-based indexing. With no valid samples these statistics
are null. Exclusions and rejections remain separate from the successful sample
count; measured delay has no invented pass threshold.

Cohorts remain separate by requester/responder role, both device/boot identities,
radio/link settings, security, byte length, source seed, timeout and execution
schema. Reversing direction or changing either boot cannot pool clock domains.
Each sample keeps raw local timestamps and request/reply identities. Overall host
transaction time uses host monotonic nanoseconds from configuration through
readback, cleanup and file fingerprinting; it is labelled separately and is not
RTT. A restarted partial run has no invented transaction end or elapsed time.

Aggregation streams at most 1000 selected records and verifies finalized source,
wire and applicable recovered file hashes before accepting their evidence.
Missing/changed files produce explicit exclusions. More than 64 MiB of selected
saved evidence rejects the request; select a smaller cohort. Projections retain
at most 128 rejection rows per run/cohort with the full count and a truncation
flag. Every original rejection remains in the individual raw record/export.
Hashing/analysis runs in one tracked saved-evidence worker, rejects concurrent
requests and joins on request cancellation/shutdown before the store closes.
Campaign exports reuse the same worker implementation with their own owner.

## Code walkthrough

- `radio_runs.py`: `EchoRadioRunRequest` and the existing physical lifecycle,
  independent byte readback, terminal timing and selected-record integrity checks.
- `echo_accounting.py`: pure identity/reference/content/time reconciliation,
  reason-coded exclusions and separate clock/settings cohorts.
- `evidence_worker.py`: bounded concurrent work and cancellation/shutdown joining;
  `physical_campaign_evidence.py` keeps its existing export interface.
- `app.py` / `cli.py`: thin shared endpoints and commands. Existing radio status,
  stop, raw content and exports retain the evidence.
- `radio/rf_echo.c`, `rf_execution.c` and `rf_events_v2.py`: actual reply bytes and
  one captured acceptance instant in the coordinated firmware/host contract.

## Repeatable checks and remaining hardware work

```sh
uv run --project testbed pytest testbed/tests/test_echo_accounting.py testbed/tests/test_echo_host.py -q
make check
source /Users/anken18/.espressif/v6.0.2/esp-idf/export.sh
idf.py -C firmware/lora_node build size
```

Expect exact known-time median/p95 values, distinct reverse/boot/settings cohorts,
null timeout statistics, one sample per exact confirmed exchange and exclusions
for inconsistent or corrupt evidence. Native API checks exercise both directions
and plain/protected profiles, actual source/request/reply bytes, exports, lost
request/reply, dropped result telemetry, cancellation/disconnect and worker
shutdown. Fixture scheduling is not a measured RF timing model.

Physical review still needs two identified matching board profiles and antennas,
released serial ports, applicable backups and approved images. Repeat the commands
in both directions, inspect raw bytes/references/timestamp phases, suppress one
reply and confirm null latency, then start a fresh intact control. Save real
observations, clock resolution, configuration and cleanup evidence. Printed
revision/RF-front-end and complete procedure qualification stay open. Do not
connect guessed pulse pins or infer calibrated one-way delay from these results.
