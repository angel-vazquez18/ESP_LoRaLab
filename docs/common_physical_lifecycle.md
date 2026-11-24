# Common physical lifecycle (#75)

Data, file, audio and diagnostic workflows now use the same physical request and
cleanup policy. `NodeSession` still owns the port, typed contracts, command lock,
correlation, retries and private provisioning. `PhysicalAdapter` binds each job to
its role, device ID, boot ID **and host connection ID**. Reopening USB creates a
new connection ID even if the ESP32 did not reboot. Old jobs cannot resume or
close that replacement connection.

## Responsibilities and reading order

- `physical_adapter.py`: small public `bind/current/request/cleanup` boundary.
  Requests verify the binding before and after awaiting a reply. Cleanup tries
  stop, close and fresh idle confirmation independently, with bounded request
  timeouts and no retries. Uncertain ownership is disconnected only on the same
  connection. Original workload errors are never replaced by cleanup errors.
- `nodes.py`: assigns a new host connection ID for each connect attempt and
  attaches the binding to accepted local operation observations. These are host
  metadata; firmware wire schemas do not change.
- `host.py`: constructs one adapter, injects it into the runners and retains one
  bench owner across acceptance, collection and cleanup. Dashboard/CLI share it.
- `radio_runs.py`: keeps radio settings, both-node preparation, receiver-first
  arming, five-second start bounds, packet evidence and verified readback.
  It uses common binding/cleanup and retains detailed per-node cleanup results.
- `node_audio.py` / `artifact_transfers.py`: keep finite DMA/codec/manifest rules,
  use the same binding and preserve completed child evidence after parent failure.
  Successful audio jobs also confirm idle before releasing the bench.
- `diagnostic_jobs.py`: gives memory probes and local crypto benchmarks durable
  finite jobs, a terminal node result, bounded collection and the same cleanup.
  Startup/shutdown and cancellation retain ownership until cleanup finishes.

Local operations keep their real preparation/start commands; the host does not
send artificial RF arm/session commands to microphones or memory probes. The
shared policy controls connection lifetime, safe requests and cleanup, while each
runner keeps its meaningful validation and state transitions.

## Failure, cleanup and recovery

The job's `error` is the initiating failure. `cleanup.confirmed` records actual
final idle/run/key observations, while `cleanup.errors` (or per-node details for
RF) preserves individual cleanup failures. A lost/failed stop reply can coexist
with a later successful session close and verified idle state. It remains in the
error list; it does not replace the original failure. Missing cleanup evidence
also remains explicit and cannot silently turn into a completed assessment.

Cleanup can stop a local command whose acceptance reply was interrupted only
inside the already owned local workload and exact connection binding. It does
not guess across a reconnect. A stale device/boot/connection or uncertain cleanup
requires a fresh physical connection, identity, ownership and readiness check.
No job automatically reconnects, reprovisions keys, retransmits or resumes.

A committed microphone capture now survives failed/cancelled host readback. The
failed job keeps `retained_capture` for explicit retrieval or deletion; `clip`
remains unavailable until a separate readback passes verification. Unfinished
private work still retires. Retained committed files consume the existing bounded
four-slot RAM store and must be explicitly deleted when no longer needed. A full
store blocks new work rather than silently deleting evidence.

## Diagnostic records and API

Existing memory-probe/crypto-benchmark requests still return the device
`operation_id`, and now also return `host_run_id`. The host ID identifies the
whole request/collection/cleanup job; the operation ID identifies device work.
A job records its physical binding, firmware identity, arguments, host source
hashes, terminal node result, original error and cleanup details.

- `GET /api/diagnostic-runs/{host_run_id}` retrieves the saved job.
- `GET /api/diagnostic-runs/{host_run_id}/evidence?include_records=true` retrieves
  bounded hashed command evidence and retained device operation events.
- `/api/state` includes the active diagnostic ID and twenty recent summaries.
- Existing CLI `memory-probe`, `crypto-benchmark` and `operation-stop` use these
  same backend jobs; firmware operation IDs remain valid for stop/results.

The command trace is bounded to 64 KiB and saved under the ignored
`diagnostic_runs` directory. Existing operation-event storage retains its own
benchmark bounds. Missing terminal events time out after 35 seconds and never
become a successful result just because health reports idle. Host restart marks
unfinished jobs interrupted, preserves partial evidence and opens no ports.
Shutdown also joins an in-flight acceptance write before closing the port/store.

Source fingerprints include the actual shared adapter/runner modules. Procedure
prerequisites include those sources too; historical passing records retain their
original provenance and do not qualify the changed implementation.

## Checks and expected results

```sh
uv run --project testbed pytest testbed/tests/test_common_physical_adapter.py -q
make check
npm --prefix testbed/frontend run format:check
```

The 21 dedicated public adapter/Host/ASGI cases check:

- Same-boot USB reconnect rejects old work and leaves the fresh connection alone.
- Cleanup still attempts close after a failed stop reply, retaining both facts.
- Configuration, session opening, preparation, receiver arm, sender arm and start
  failures each preserve the original error, with/without another cleanup error.
  Uncertain cleanup closes that connection; a new connection permits a valid job.
- A corrupt microphone readback preserves the committed capture and allows a
  later explicit verified retrieval.
- Diagnostics persist acceptance, exact connection provenance, terminal summary,
  hashed command evidence and idle cleanup through the actual API.
- Immediate stop, lost result plus cleanup failure, active shutdown, and shutdown
  during an acceptance write retain finite ownership and never resume on restart.

Existing data/audio/security tests continue to cover collection loss, timeouts,
partial files, cancellation during cleanup, database failure, receiver-first order
and fresh key retirement. Isolated serial/native peers are software evidence,
not hardware qualification. This host-only change does not require a new ESP-IDF
build or flash and does not change a wire digest.

Later physical acceptance should repeat normal data/audio/diagnostic work, stop,
USB loss, same-boot reconnect and backend restart on identified nodes. Retain the
original error, cleanup outcome, partial files and a subsequent fresh successful
operation. Keep board/RF/audio qualification separate from this lifecycle result.
