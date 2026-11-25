# Physical campaign dashboard (#115)

Open **Campaigns** in the same backend used by the CLI. Saved plans and execution
history are separate: importing settings saves intent; **Start available cases**
creates a new execution. All lifecycle decisions, readiness checks, ownership,
case order and assessment stay in the shared physical services.

## Operator workflow

Choose a saved plan or import a JSON settings file matching `CampaignSpec` (up to
1 MiB). The repository example `testbed/examples/local_and_radio_plan.json` is a
settings file. A saved plan's full exported document is not an import settings
file. Import starts no node work. Current requirements are checked for the visible
32-case page without rewriting the original readiness snapshot. Every case repeats
its checks during execution; unavailable cases remain blocked with reasons.

Connect compatible devices in Bench overview. Local cases can use A or B alone;
link cases require distinct A/B devices. Start is unavailable without a
connection or while another workload/campaign owns the bench. Mixed plans retain
every blocked case instead of silently omitting it. Scheduling reserves are
labelled as declared limits, not measured durations.

The selected execution shows current counts, stage, reason codes and the saved
case ledger. **Pause after current case** finishes that case and its cleanup,
then parks the queue while retaining ownership. **Keep running** withdraws a
pending pause; **Resume campaign** resumes an actual live pause. **Stop campaign**
uses the shared cancellation service and retains partial children and skipped
queued cases. Finishing cleanup remains a separate stage before the final outcome.
Each child link opens its actual detailed record; settings, enrolled bindings and
cleanup can be inspected without starting work.

On a terminal execution, select individual cases or the current page and choose
**Rerun selected cases**. This creates a new execution, preserves original settings
and order, and repeats fresh backend preflight. Follow the original-history link
or **View active campaign** without transferring ownership. The original's failed,
cancelled, interrupted or skipped outcomes are retained. See
[linked reruns and evidence](campaign_reruns_evidence.md).

## Refresh and recovery

The browser stores only the selected plan/execution IDs as optional session UI
preferences. Checkbox selections and page positions are local view state. No
browser mount, refresh, navigation, reconnect or history read issues a start,
resume or rerun command. Changing a view does not alter the active owner.

During backend disconnect, retained views remain visible with an unavailable
banner and disabled controls. After host restart, saved unfinished executions
show interrupted outcomes and unconfirmed prior cleanup. They remain interrupted
after another reload. The browser does not reconnect a device or resume RF.
Reconnect through Bench overview as needed, then explicitly start fresh work.

Historical legacy/v2 campaign records remain accessible below the physical
workspace; no simulator execution mode is restored. All 23 CDR matrices remain
required, and unavailable full matrices retain their explicit reasons.

## Evidence and bounds

Plan and execution ledgers use read-only `physical_campaign_view_v1` projections:

- GET `/api/physical-campaigns/plans/{id}/view?offset=0`.
- GET `/api/physical-campaigns/executions/{id}/view?offset=0`.

Pages contain at most 32 cases; offsets accept 0–4,096. Compact live headers omit
full selected-ID/source inventories. The original full detail and export endpoints
remain available to CLI/review callers. Historical UI views fetch only on a view,
page, connection or selected execution revision change. They never grow an
unbounded browser case history.

**Export campaign evidence** uses the shared terminal bundle service. The browser
verifies the received bytes against `X-Content-SHA256` before offering the ZIP,
then releases its temporary object URL. Download failure remains visible. Full
archive member/count/saved-file checks occur in the backend and can be repeated
offline with `campaign-verify`; display pagination never truncates the export.
The displayed download SHA-256 identifies that exact ZIP. Execution completion,
child assessment, export integrity and physical qualification remain separate.

## Review and observed software checks

Read `frontend/src/PhysicalCampaigns.tsx` for view state and explicit actions,
`campaign_views.py` for bounded backend projections, `physical_campaigns.py` for
the actual owner and `physical_campaign_evidence.py` for exports. `main.tsx`
connects the existing Host state; GUI and CLI use the same endpoints. The sidebar
also gives its icon controls accessible names on narrow layouts.

From repository root:

```sh
uv run --project testbed pytest testbed/tests/test_campaign_views.py -q
make check
npm --prefix testbed/frontend run format:check
```

Three dedicated native/ASGI cases check current requirements versus unchanged
saved intent, 100-case pagination/identities and repeated active views that create
no duplicate child. Existing campaign/radio/worker/restart cases remain required.

Interactive browser checks on November 24 used an isolated backend at port 8874,
a SOFTWARE FIXTURE banner, real portable C diagnostics and temporary stores.
The normal backend at port 8000 and physical USB ports were untouched:

| Action | Observed result |
| --- | --- |
| Select a 100-case plan / next page | Bounded 32-row page and preserved original order |
| Start three-case saved order, then pause | One completed child, two pending; bench remains owned |
| Refresh and visit Bench then Campaigns while paused | Same execution and one actual diagnostic start; no duplicate command |
| Resume and refresh during the next case | Exact saved three-case order completed; three unique child starts |
| Stop a separate two-case execution | One cancelled partial child, one skipped case, confirmed cleanup |
| Rerun only its skipped case | New one-case execution/child with parent link; original two outcomes unchanged |
| Follow original / active history links | Correct old and active ledgers; no extra starts |
| Export selected rerun | Downloaded ZIP independently verified: 1 case, 1 child, 2 files, 7 members, matching full/member hashes |
| Import repository settings | Nine cases, one batch, 600-second scheduling reserve; no diagnostic start |
| Cold-stop fixture during an active child / restart on same store | One interrupted child, one skipped case, unconfirmed cleanup; no auto device connection or work |
| Reload interrupted history | Still interrupted; start disabled while node disconnected; exactly six total unique fixture diagnostic starts |
| Inspect bindings/settings and light/dark appearance | Actual saved identity/reasons remain readable; no invented cleanup confirmation |
| 390-pixel layout and selection refresh | No page overflow; tables scroll internally; selected plan/execution retained |
| Final captured console | No warnings/errors |

The browser download/chooser tools were slow; that wall time is not an application
throughput or hardware measurement. Fixture artifacts and native clocks do not
qualify physical RF, audio, USB timing, PTT/OLED or resource recovery.

Physical acceptance remains #132 and the relevant individual procedure issues.
On identified compatible nodes, repeat start/pause/resume/cancel, page refresh and
host restart, then verify original/rerun IDs, actual stop/cleanup and following
valid work. Export/count/hash actual files. Measure the declared radio-frame/
audio-DMA stop bound and resource behavior with the applicable setup; UI behavior
alone cannot establish those measurements.
