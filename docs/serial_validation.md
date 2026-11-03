# Serial interface validation in simulation

> Historical document. The November 1 physical-only decision supersedes the
> simulator workflows and commands below; those implementations were removed.
> See [current status](status.md) and [host usage](../testbed/README.md).

Implemented October 26, 2026. IF-01 now has a saved procedure runner, not just
individual regression checks. It exercises the existing virtual nodes through
the public byte-stream probe interface. It never opens a physical serial port
or starts radio/audio transmission. Physical USB and UART qualification remain
separate required work.

## Run from the dashboard

1. Select **Simulation** in the header and open **Experiments**.
2. Select **IF-01 - Serial interface validation**.
3. Leave both roles, all six groups and the procedure counts selected for full
   coverage. Preview the procedure: 218 case executions, including ten valid
   command cycles on each role and three repetitions of every other variant.
4. Start serial validation. The runner owns the same bench lock as known-data
   runs and campaigns. Navigation/refresh does not stop execution.
5. Inspect group progress, the case ledger, expected/observed assertions,
   recovery checks and virtual exchange waits. Select a case to load its wire
   evidence. Full exports retain every evidence row.
6. Stop if needed; partial records and skipped cases remain saved. Exports are
   enabled only after recovery/close completes.
7. Find saved runs in the same panel or **Results & exports**. JSON, case CSV,
   evidence JSONL and a SHA-256-manifest ZIP are available.

Quick checks, a single selected role or a subset of groups are explicitly partial.
They cannot close the full simulation procedure. The catalog's **SIM PASSED**
indicator requires the latest finalized full run for the current implementation
profile to pass. Changed source/profile hashes invalidate earlier readiness.

## Implemented case matrix

| Group | Cases across both roles | Observations |
| --- | --- | --- |
| C1 | 2, each containing 10 cycles | Correlated hello/claim/status/keepalive/release; actual 1 Hz virtual health and continuous event sequences |
| C2 | 24 | Invalid arguments/configuration, unknown commands, known unavailable commands; applied settings unchanged |
| C3 | 84 | Oversized, split at every byte boundary, concatenated, duplicate-key, invalid UTF-8, malformed/deep/nonfinite/unknown-field/wrong-type input; exact 4096-byte boundary, CRLF, startup noise and rate-limited diagnostics |
| C4 | 30 | Unsupported wire records, incompatible advertised wire/contract major/minor/schema; rejection and close before claim/run |
| C5 | 60 | Lost/delayed/deadline-late/absent replies, exact-byte mutating retry, conflicting ID/sequence, reply-cache eviction, reset/stale boot and mismatched reply correlation |
| C6 | 18 | Competing clients, lease expiry to idle, stale/unresponsive health without fabricated samples and observed recovery |

Every case attempts a fresh valid recovery exchange, checks idle/buffer release,
releases its claim and closes the adapter. C5 checks actual configuration
readback as well as cached replies, so duplicated side effects cannot pass merely
because the cached reply looks correct. Missing required handlers remain blocked;
observed incorrect behavior fails assertions. Execution outcome and experimental
assessment remain separate.

## Timing and evidence boundaries

Injected delays and lease/health silence use virtual microseconds. A lost reply
advances the fixture to the two-second response deadline; three absent read
replies exhaust the policy after six virtual seconds. Deadline-late responses
are withheld by the fixture. These checks exercise host policy and node side
effects, not operating-system serial timing or a physical late-byte queue.
Sub-deadline delays return an observed reply. Real host monotonic/UTC receipt
times are recorded independently.

The runner uses the existing known-data virtual node's command processor, which
supports configuration readbacks. Its radio capabilities describe simulation;
no physical radio is claimed. Diagnostic firmware and its schema digest remain
unchanged. Compatibility and health-freshness policies are shared with the
physical diagnostic session implementation.

Raw evidence includes TX chunk boundaries, redacted bytes as Base64, SHA-256,
RX bytes, decoded diagnostics, clock/fault/reset controls, node events and host
receipt times. Store record/procedure/analysis versions, identities, before/after
configuration, source hashes and per-case cleanup results. Never persist key
values in wire evidence. The ZIP contains procedure JSON, case CSV, evidence
JSONL, explicit simulation provenance and a file-hash manifest.

Unfinished procedures become interrupted on host restart, preserving completed
case evidence and marking unstarted cases skipped. They never resume implicitly.

## CLI

With the local backend running:

```sh
uv run --project testbed lora-testbed serial-check --preview
uv run --project testbed lora-testbed serial-check
uv run --project testbed lora-testbed serial-check --quick --role A
uv run --project testbed lora-testbed procedure-status RUN_ID
uv run --project testbed lora-testbed stop
```

Run one start command at a time. The default is full IF-01; `--quick` uses one
valid cycle and one repetition per variant. `--role A` or `--role B` is partial
coverage. Commands return an accepted run summary; inspect the dashboard/status
for completion.

## HTTP

- `GET /api/procedures`: active summary and recent procedure runs.
- `POST /api/procedures/serial/preview`: read-only validated case plan.
- `POST /api/procedures/serial`: start with `roles`, `groups`,
  `positive_cycles` and `repetitions`; omitted values select the full procedure.
- `POST /api/procedures/stop`: bounded stop and finalization.
- `GET /api/procedures/runs/{id}`: complete case ledger and assertions.
- `GET /api/procedures/runs/{id}/evidence?after=0&limit=100&case_id=...`:
  paginated evidence, optionally restricted to one case.
- `GET /api/procedures/runs/{id}/export/{json,csv,jsonl,zip}`: finalized exports.

The next implementation work is the complete simulated IF-02 known-data and
IF-03 campaign procedure matrices. The full 23-experiment checklist remains in
`experiment_implementation_checklist.md`.
