# GitHub work tracking

The [development and validation Project](https://github.com/users/angel-vazquez18/projects/3/views/14)
is the team's private board for the public `angel-vazquez18/ESP_LoRaLab` repository.
It tracks the eight capability milestones in [the roadmap](node_development_plan.md).
The [repository milestones](https://github.com/angel-vazquez18/ESP_LoRaLab/milestones)
have no due dates until the team sets them. The first-week-of-December target in
[the brief](project_brief.md) still applies.

## Working a scoped issue

1. Choose an unblocked issue from the next capability slice. Confirm the owner,
   reviewer, milestone, area and priority. Firmware/hardware defaults to
   `homarrodriguez`; host/frontend/procedures defaults to `angel-vazquez18`.
   Reassign explicitly when pairing or changing ownership.
2. Move its card to **In progress** when work begins. Read its dependencies,
   implementation checklist, acceptance cases and linked authoritative documents.
3. Use one reviewable PR for the named outcome. Use descriptive one-line
   Conventional Commits, such as `feat(artifacts): reject CRC failures before advancing upload offsets`.
4. Move the card to **Testing** when implementation is reviewable but required
   checks, physical evidence or review remain outstanding. A merged implementation
   PR does not close a separate physical qualification issue.
5. Link actual commands/results, raw evidence and limitations. After the named
   reviewer verifies every applicable acceptance criterion, move to **Completed**
   and close the issue as completed. Close abandoned work as not planned; it does
   not count as successful acceptance. Reopened work must be moved to its actual
   To do/In progress/Testing status explicitly.

Milestone 1 software is already implemented at `7707b39`; its issues cover remaining
physical acceptance. Do not create retrospective unfinished implementation work.
The initial backlog contains 142 issues: 72 capability/bring-up slices and 70
procedure runner/qualification slices. Large IF-01, IF-03, PKT-02, PKT-03 and OPS-01
runners are split by case group. Each of all 23 procedures has a separate full
qualification issue. A capability demonstration or smoke run does not close that
procedure's complete matrix.

## Labels and views

Exactly one `status:` label mirrors the Project's Status field:

| Project Status | Label | Meaning |
| --- | --- | --- |
| To do | `status:todo` | Defined work waiting to start, possibly blocked |
| In progress | `status:in-progress` | Active implementation or validation |
| Testing | `status:testing` | Implementation ready; required acceptance outstanding |
| Completed | `status:completed` | Issue acceptance and review complete |

Use at least one of `area:firmware`, `area:testbed`, `area:frontend`,
`area:hardware`, `area:contracts`. Use a `type:feature`, `type:bug`, `type:docs`,
`type:test`, `type:refactor` or `type:chore` label for the work kind. Existing
repository default labels are preserved. `needs-hardware` describes evidence
requirements; it remains useful even after completion. `blocked` indicates an
open prerequisite. Priority is a Project field: P0 urgent blocker, P1 immediate
foundation/bring-up, P2 planned dependent capability. Reprioritize with the team.

The Kanban view groups work by Status. Additional filtered tables show each
milestone, each collaborator and blocked work, plus ready-to-start and testing queues. Cards/tables expose assignee,
milestone, labels, priority and status. Dependencies are explicit issue links in
bodies (`- Blocked by #NUMBER: description`); completion means closed with reason
completed. Missing or not-planned dependencies remain blocked pending an explicit
replan. Do not erase an unmet physical prerequisite to make a card look ready.

## Issue and PR templates

Use the implementation form for one observable behavior and the hardware form
for a defined physical case group. Both require scope, ownership, prerequisites,
observable tests and evidence. Add the actual assignee/milestone and area label
at triage; form text does not set those GitHub fields automatically.

[The filled artifact chunk-offset/CRC issue](https://github.com/angel-vazquez18/ESP_LoRaLab/issues/14) is the implementation example. It
requires unchanged buffer/offset on corrupt, repeated or skipped chunks, a
1024-byte boundary check and a subsequent successful write. Reservation, final
commit, reading, host transfer and hardware acceptance are separate tickets.
Templates become the repository's issue chooser after the setup PR is merged.

[The initial backlog manifest](planning/github_backlog.json) records the setup
snapshot and stable IDs, scope and prescribed procedure text. GitHub issues and
the Project own current assignments/status; do not edit this snapshot as a second
live task board. Contract and procedure source documents remain authoritative;
version and reconcile affected issues if those requirements change.

## Status synchronization

Project Status is authoritative. Changing only a `status:` label does not move a
card. Run these commands from the repository root with an authenticated `gh` CLI:

```sh
python3 scripts/github_project.py sync          # read-only preview
python3 scripts/github_project.py sync --apply  # reconcile changes
```

The tool paginates all issues/cards, adds missing issue cards, sets new cards to
To do, mirrors one status label and reconciles linked prerequisite blockers.
Closing an issue as completed moves its card to Completed. A not-planned closure
never creates a Completed status. Board completion does not itself close an issue
or verify evidence; the reviewer does that explicitly. Unrelated labels and
manual blockers without linked issue dependencies are preserved. Linked-dependency
blockers are maintained by the tool; keep additional equipment blockers in the
prerequisites and `needs-hardware` label. It never changes code, runs experiments,
closes milestones, or claims physical validation.

A scheduled workflow supports reconciliation every 15 minutes and manual dispatch
**after merge and credential setup**. It is inactive without repository secret
`PROJECT_AUTOMATION_TOKEN`. The ordinary Actions `GITHUB_TOKEN` cannot read/write
user Projects. Configure a dedicated credential with access only to the intended
owner's Project where supported (or the required `project` scope for a classic
personal token). Repository issue writes use the separate short-lived
`GITHUB_TOKEN`; no repository credential is committed. Do not copy the broad local
CLI credential into a repository secret. Rotate/revoke automation credentials
through normal account administration.

Local use can use the CLI's existing approved credentials. In automation,
`GH_PROJECT_TOKEN` is used only for Project GraphQL requests and `GH_TOKEN` for
repository REST calls. Scheduled runs use trusted default-branch code, least
repository permissions, serialized execution and no untrusted PR checkout. There
is no real-time Project webhook installed; expect up to the schedule interval or
run local sync after a move. Until the dedicated secret is configured, synchronize
locally and keep labels consistent when moving cards.

## Acceptance evidence

Each issue contains concrete expected observations, applicable invalid/boundary/
recovery checks and [validation commands](development.md). Physical evidence needs
device/boot IDs, printed board revision, firmware/host/schema/profile hashes,
requested/applied configuration, raw records, artifact hashes and instrument or
listening observations where applicable. Store large runtime evidence outside
Git; link hashed exports. Never persist ordinary session keys.

Native tests, fixtures and browser checks establish software behavior, not RF,
electrical, timing or audio performance. Preserve execution outcomes separately
from assertion assessments. Required incomplete cases remain blocked/inconclusive;
a negative feasibility result may be a valid completed experiment. All 23
[procedure matrices](test_procedures.md) and their repetition obligations remain.
