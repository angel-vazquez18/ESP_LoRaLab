# Task: implement the remaining Milestone 1 software

Status: software implemented; physical acceptance pending

## Context and authorization

November 8, 2026: the user delegated the complete remaining Milestone 1 checklist
for later code review. This overrode manual typing for this task only. Source was
initially left uncommitted and the board image/serial connection was preserved.
The user subsequently requested small scoped Conventional Commits for all work.

## Scope and decisions

The scope is one node's reliable board/control foundation and host integration.
`docs/milestone_1_review.md` contains the full implementation and physical checklist.
The control profile has its own generated schema; no diagnostic/execution digest
migration is needed. Only the selected `memory_probe` diagnostic is enabled.
No radio/audio/security/artifact operations are introduced.

Use cooperative 512-byte work slices, four reply/eight event queue slots, a
16-reply duplicate cache and 16 non-evicting client sequence fences per boot.
Preserve NVS boot state. A 30-second operation deadline bounds oversized workloads.
Treat a missing terminal event as missing evidence, never fabricated completion.

## Work and verification

Portable C protocol/parser, ESP-IDF composition, generated profile, existing
host session/procedure compatibility, GUI/API/CLI operations and native checks
are implemented. See `docs/status.md` for final verification results and
`docs/milestone_1_review.md` for code-reading order and test provenance.

## Handoff

Review the scoped commits, confirm the printed board revision, then deliberately
flash and run the physical acceptance checklist. Do not mark Milestone 1 or IF-01
hardware-qualified from native fixtures, build success or dashboard QA.
Return to the user's manual small-step learning workflow unless instructed otherwise.
