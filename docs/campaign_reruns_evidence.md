# Linked campaign reruns and verified evidence (#107)

Selected-case reruns create a **new execution** from the original immutable plan.
They preserve the original campaign, case outcomes, child links and evidence.
They are explicit operator work, never automatic restart recovery. Campaign
controls in the dashboard follow #115; these API/CLI paths share the existing
physical controller.

## Rerun selected cases

With the existing backend running, from repository root:

```sh
uv run --project testbed lora-testbed campaign-result ORIGINAL_EXECUTION_UUID
uv run --project testbed lora-testbed campaign-rerun ORIGINAL_EXECUTION_UUID CASE_UUID ANOTHER_CASE_UUID
uv run --project testbed lora-testbed campaign-result NEW_EXECUTION_UUID
```

The request must contain one or more distinct case IDs belonging to that terminal
execution. Active parents, unknown cases and competing bench owners reject before
creating a new execution. A rerun of a rerun can select only cases from its direct
parent. Completed, failed, blocked, cancelled, interrupted and skipped original
cases may be selected explicitly.

Selection follows the original saved order, irrespective of request-list order.
Settings, repetition, matched source seed, direction, canonical index and original
batch links are copied without re-expansion or reshuffling. Planned case IDs stay
stable within the new execution's separate ledger; runtime `index` is contiguous,
while `saved_index` retains its original plan position. Each case and header link
`parent_execution_id`; `parent_snapshot_sha256` fingerprints the original header
plus case rows as read when creating the rerun. New child jobs, physical bindings,
radio sessions and source keys come from the ordinary fresh runner lifecycle.
No previous session or key is restored.

The selected roles are freshly enrolled and each case repeats current compatibility,
capability, freshness, idle and resource checks. A formerly blocked case remains
blocked if its node is still unavailable; connecting a compatible node before a
new explicit rerun can make it executable. New campaign ownership, pause/cancel,
child deadlines and cleanup rules are unchanged. Header/case documents written
by this version carry canonical SHA-256 fields, checked before reading detailed history or reusing it. Older finalized records without these fields retain that missing prior
integrity scope; historical hashes are not invented.

POST `/api/physical-campaigns/executions/{id}/rerun` accepts
`{"case_ids":["CASE_UUID"]}` and returns HTTP 202 with the new execution. Invalid
shape is 422, invalid selection is 400 and active/owned conflicts are 409.

## Restart is interruption

Host startup marks active or paused campaigns interrupted, active cases
interrupted and unstarted cases skipped with `host_restart`. Saved child records
retain their partial observations and the previous cleanup remains unconfirmed.
Startup opens no serial port and resumes no RF/audio work. Ordinary resume is
only for a live paused owner on its original connections. After restart, reconnect
as needed and explicitly select a new execution or rerun. A prior unconfirmed
cleanup result never proves a node is idle.

## Export and verify

```sh
uv run --project testbed lora-testbed campaign-export EXECUTION_UUID campaign-evidence.zip
# This command needs neither a backend nor a connected device:
uv run --project testbed lora-testbed campaign-verify campaign-evidence.zip
```

GET `/api/physical-campaigns/executions/{id}/export` returns a ZIP attachment and
`X-Content-SHA256` for its exact bytes. Campaign and linked children must be
terminal. Export is read-only, including for interrupted/failed records. A valid
negative experimental finding or incomplete physical qualification is not filtered
out. The CLI checks the HTTP digest and bundle before exclusively creating the
output file; an existing output is preserved.

The bundle uses `physical_campaign_bundle_v1` and the existing `sha256.json`
member-hash convention, with:

- `campaign.json`: exact execution, ordered case ledger and parent links.
- `plan.json`: complete original immutable plan and its saved hash, including
  unselected cases as intent, not additional executed cases.
- `children/{service}/{id}.json`: each directly or transitively linked diagnostic,
  procedure, audio, radio, voice or transfer record once.
- `evidence/` and `files/`: actual diagnostic command/operation rows, procedure
  rows/attachments, audio/transfer traces, verified payloads/WAV, radio source/
  recovered bytes and voice references. Child links preserve multiple uses of a
  shared transfer without duplicating its record or file.
- `manifest.json`: exact case/child/file counts, typed links, file inventory,
  saved-versus-export-time hash scope and exporter-source fingerprint.
- `sha256.json`: hash of every other member, including the manifest. It cannot
  hash itself. Fixed ZIP timestamps and stable traversal make unchanged evidence
  reproducible; later explicit child listening annotations change that snapshot.

Saved payload length/hash, transfer and codec manifests, reference hashes and
finalized traces are checked independently before packaging. New terminal radio
records persist source/recovered/trace fingerprints. Radio readback and both
radio/campaign exports reject corrupted declared files instead of omitting them.
If fingerprinting fails, the terminal record retains that error and original
cleanup rather than remaining running. Missing declared files fail the export;
failed operations with no produced payload remain valid partial records.

Interrupted or older traces can lack a finalized file hash. Their retained bytes
are labelled **export-time hash only**, rather than assigned a fabricated prior
checksum. Such bytes remain partial evidence, not a completeness or physical
qualification claim. Malformed/unsafe metadata is rejected. Session key material
is prohibited. The exporter reads only files inside its evidence root and never
opens a device to recover missing content.

Offline verification independently checks exact members, hashes, saved-file
manifests, child IDs/statuses, original plan hash, selected case order/counts and
complete reachable child links. It performs no extraction. Altered, missing,
duplicate, unsafe-path or malformed members fail. Compressed and expanded input
are bounded at 128 MiB, individual saved-file reads at 64 MiB and total members
at 20,000. Oversized campaigns reject without silently dropping evidence; retain
the original records and run smaller selected-case campaigns when appropriate.
One tracked export worker handles file reads, parsing and compression outside the
control loop. A competing export rejects instead of accumulating unbounded work;
node control remains responsive. Cancelled callers retain their worker until it
finishes, and shutdown joins it before closing storage. Export does not take or
release bench ownership.

These checks detect accidental corruption; hashes are not signatures or proof of
physical qualification. All export summaries keep hardware qualification false.

## Review and software checks

Read `physical_campaigns.py` for selection/ledger preservation, `host.py` for the
shared reservation lock, `physical_campaign_evidence.py` for graph collection and
offline verification, and `radio_runs.py` for finalized file fingerprints. HTTP
and CLI entry points live in `app.py`/`cli.py`.

```sh
uv run --project testbed pytest testbed/tests/test_campaign_reruns_evidence.py -q
uv run --project testbed pytest testbed/tests/test_physical_campaign_execution.py testbed/tests/test_radio_runs.py -q
make check
npm --prefix testbed/frontend run format:check
```

The dedicated cases use the actual portable C node core, pinned crypto/codec and
isolated serial transports. They cover failed-case reruns without original
mutation, saved order/current readiness, invalid selections/active ownership,
ledger corruption, real two-node DATA/voice child/file traversal, partial serial
rows, corrupted stored/downloaded files, CLI exclusive output, archive bounds and
cold process exits while actually active and paused, slow-export control
responsiveness and cancelled-worker shutdown joining. No physical USB port is
opened. Software fixture speech and RF completion do not qualify target audio/RF.

On hardware, retain a small campaign with an intentionally failed/blocked case,
then fix its physical prerequisite and rerun only that case. Compare unchanged
original IDs/outcomes with the new child, current device/boot/connection and
settings. Exercise host restart once active and once paused; require interrupted
records, no automatic RF, fresh reconnection/preflight and unconfirmed old cleanup.
Export both histories, run offline verification and independently count/hash the
ZIP members and compare recovered bytes with their source. Keep actual RF/audio
measurements and operator listening observations separate from export integrity.
