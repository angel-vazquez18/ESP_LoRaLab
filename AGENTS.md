# ESP_LoraLab agent instructions

## Read first

1. Read `docs/project_brief.md`, `CONTEXT.md` and `docs/status.md`.
2. Read `docs/architecture.md` before changing module responsibilities or layout.
3. Follow the scoped `AGENTS.md` in each directory you change. Instructions here
   apply everywhere; scoped files add details for that area.
4. Read the relevant procedure and `docs/experiment_implementation_checklist.md`
   before implementing or claiming an experiment complete.

## Routing

| Task | Instructions / primary locations |
| --- | --- |
| Node firmware | `firmware/AGENTS.md`, `firmware/lora_node/AGENTS.md` |
| Host backend or CLI | `testbed/AGENTS.md`, `testbed/src/lora_testbed/` |
| Dashboard | `testbed/AGENTS.md`, `testbed/frontend/AGENTS.md` |
| Regression / integration evidence | `testbed/tests/AGENTS.md` |
| Host/firmware wire change | `contracts/AGENTS.md`, `docs/testbed_contract_v2.md` |
| Wiring / board profile | `hardware/AGENTS.md`, `hardware/README.md` |
| Plans, status or procedures | `docs/AGENTS.md` |

## Project invariants

- This repository is the development home for firmware and testbed. No source
  changes belong in the old `Lora_Testbed` workspace.
- macOS host, GUI first plus CLI; Python/FastAPI and React/TypeScript already exist.
- ESP-IDF v6.0.2 / ESP32-S3. One firmware codebase serves both host-assigned roles.
- `contracts/v2/default_profile.json` and `docs/testbed_contract_v2.md` are the
  selected provisional protocol baseline. The user delegated provisional choices;
  proceed with documented decisions rather than waiting for a colleague's review.
- Keep all 23 CDR experiments, including voice. The host is physical-only.
  Local procedures accept one node; RF/link procedures require two distinct nodes.
  Missing firmware or procedure support stays blocked; never substitute simulation.
- Diagnostic, execution and historical legacy v1 wire surfaces are distinct. Never
  claim compatibility based only on a matching version number.
- Execution outcome, assessment and full hardware qualification remain separate.
  Unit-test fixtures and partial diagnostic checks do not qualify RF/audio procedures.
- Future RF run/campaign logic must use the physical adapter interface. Dashboard and CLI use the same backend.
- Preserve source bytes, configurations, identities, clock domains, raw events,
  errors and hashed artifacts needed for repeatable assessments.
- Keys are fresh per source/run, RAM-only and excluded from traces, records and
  exports. Public conformance-vector keys are test fixtures only.
- Hardware planning: Heltec V4, no GNSS, INMP441, SATUY MAX98357A, 8-ohm/1-W
  speaker; audio modules powered from Heltec 3.3 V. PTT uses GPIO 47, not GPIO 7.
  Read `hardware/README.md` before editing pins or audio configuration.

## Working discipline

- Inspect existing code and status before designing a replacement. Preserve user
  changes; do not revert unrelated work. Avoid empty abstractions and blanket
  rewrites. Add a new module only for a concrete responsibility and caller.
- For shared-interface work, enumerate all producers/consumers and coordinate
  schema, generated outputs, host, firmware and conformance checks
  in the same change, or explicitly gate missing capabilities.
- For each task, state scope and acceptance evidence, implement a small coherent
  change, run appropriate checks, then update the relevant status and task notes.
- Record confirmed decisions separately from suggestions and unverified wiring.
  Keep implementation details out of the glossary. Capture significant design
  trade-offs in short `docs/adr/` records.
- Do not fabricate implementation, hardware measurements or browser verification.
  Unsupported features stay unavailable; do not replace missing work with counters
  or successful-looking telemetry.
- Do not flash, erase, change eFuses, restore NVS or open a physical port merely
  to check a code change. Hardware operations need task authorization, correct
  device identity, released host ownership and the applicable backup procedure.
- No commits, pushes or publishing unless requested. Never commit local data,
  flash backups, run keys, environments, build output or managed dependencies.

## Checks and handoff

Run `make check` for shared host changes. For focused work, start with the relevant
checks in `docs/development.md`; run the full host checks before declaring a host
migration or shared protocol change verified. Build changed ESP-IDF targets when
available; say explicitly if the toolchain or dependencies prevent the build.

Use `docs/task_template.md` when a task spans sessions. Update `docs/status.md`
when capabilities change and the experiment checklist only when its evidence
supports the change. Summarize changed behavior, checks actually run, limitations
and a concrete next step. Keep agent instructions concise and durable; put long
history and detailed evidence in docs, not here.
