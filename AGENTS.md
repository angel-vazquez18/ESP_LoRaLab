# ESP_LoraLab agent instructions

## Start here

- Read `docs/project_brief.md`, `CONTEXT.md` and `docs/status.md`.
- Read `docs/architecture.md` before changing responsibilities or layout.
- Follow the scoped instructions below; all paths in this file start at repository root.

| Work | Instructions / authoritative references |
| --- | --- |
| Firmware | `firmware/AGENTS.md`; `docs/node_development_plan.md` |
| Host backend, CLI and tests | `testbed/AGENTS.md` |
| Dashboard | `testbed/AGENTS.md`; `testbed/frontend/AGENTS.md` |
| Shared wire interfaces | `contracts/AGENTS.md`; `docs/testbed_contract_v2.md` |
| Hardware | `hardware/README.md`; `hardware/boards/heltec_wifi_lora32_v4.json` |
| Documentation and context | `docs/agent_workflow.md` |

## Project rules

- Work in this repository, not the old `Lora_Testbed` workspace. Preserve existing
  user changes. No commits, pushes or publishing unless requested.
- When commits are requested, use small coherent scopes and descriptive one-line
  Conventional Commit subjects: `type(scope): specific change and purpose`.
- Keep all 23 CDR procedures, including voice. Use reusable capabilities as the
  development order; experiments define coverage and qualification.
- The host is physical-only. One node suffices for local checks; RF needs two
  distinct nodes. Isolated software fixtures never qualify physical hardware.
- Dashboard and CLI share one backend. Gate unavailable capabilities explicitly;
  do not substitute simulation or successful-looking stubs.
- Diagnostic, main-control, execution and legacy v1 wire surfaces are distinct.
  Check exact schemas/capabilities, not only a version number.
- Preserve identities, source bytes, configurations, clock domains, errors and
  hashed evidence. Execution outcome, assessment and hardware qualification differ.
- Session keys are fresh per source/run, RAM-only and excluded from logs/exports.
  Public conformance keys are fixtures, never production keys.
- Read the hardware references before changing pins or power. Update the profile,
  wiring table and Mermaid/PNG together; reported wiring is not validation.
- Do not flash, erase, reset, change eFuses/NVS or open a physical port merely to
  verify code. Hardware work needs task authorization, matching device identity,
  released port ownership and the applicable backup procedure.
- Never commit environments, build output, managed dependencies, runtime data,
  flash backups or secrets.

## Working and verification

- Inspect the implementation before editing. Keep interfaces small and add modules
  only for concrete responsibilities and callers; avoid empty future scaffolding.
- Coordinate shared-interface producers, consumers, generated outputs and checks.
- Preserve useful missing context in its authoritative document unless explicitly
  read-only. Follow `docs/agent_workflow.md`; keep status/history out of AGENTS.md.
- Run focused checks from `docs/development.md`; use `make check` for shared host
  changes and build affected ESP-IDF targets. Report skips and unavailable checks.
- Update `docs/status.md` for changed behavior or verification. Change qualification
  checklists only when evidence supports it. Use `docs/task_template.md` for work
  that needs a durable handoff.
