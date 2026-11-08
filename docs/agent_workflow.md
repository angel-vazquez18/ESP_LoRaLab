# Agent workflow and document ownership

Root `AGENTS.md` is the entry point. Scoped files exist only for firmware, host,
frontend and shared-contract rules; descendants inherit them. Do not add another
instruction file for a status update, a short task or a duplicate vendor profile.
Current user instructions take precedence over saved guidance.

## Context maintenance

When useful durable context is missing, update its authoritative document unless
the user requires read-only work. This does not authorize unrelated implementation.
Keep the smallest useful change, with dates/provenance where needed. Separate user
decisions, proposals, source behavior and observed evidence; resolve stale guidance
without fabricating measurements. Exclude secrets and bulky/transient tool output.

| Information | Authoritative home |
| --- | --- |
| Durable agent behavior and task routing | Root or applicable scoped `AGENTS.md` |
| Requirements and user decisions | `project_brief.md` |
| Domain terms | Repository-root `CONTEXT.md` |
| Implemented layout and module responsibilities | `architecture.md` |
| Capability roadmap | `node_development_plan.md` |
| Current capabilities, limitations and checks | `status.md` |
| Detailed imported host history | `implementation_status.md` |
| All 23 experiment steps and qualification | `experiment_implementation_checklist.md` |
| Procedures and acceptance obligations | `test_procedures.md`, `test_experiment_catalog.md` |
| Wire rules and shared fixtures | `testbed_contract_v2.md`, repository-root `contracts/v2/` |
| Hardware decisions, pins and wiring evidence | Repository-root `hardware/README.md` and board profile |
| Significant design trade-offs | Short `adr/` record |
| Work spanning sessions | `task_template.md` and a concrete `tasks/` handoff |
| Historical context | `history/`; never current agent instructions |

## Handoff discipline

Use `development.md` for check commands. Keep command examples repository-root
relative or state another working directory explicitly. After moving files,
update generators, build definitions, test consumers and documentation links.
Hardware assignment changes also update the board JSON, wiring table and diagram.
Record only checks actually performed and distinguish software fixtures from
physical qualification. Mention material context updates in the handoff.
