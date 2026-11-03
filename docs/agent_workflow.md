# Agent-assisted development workflow

Open the repository root in the coding agent so root AGENTS.md and the relevant
scoped instructions are discoverable. Agents that do not automatically load
AGENTS.md should be told to read root AGENTS.md before working. Do not maintain
separate, contradictory copies for each agent vendor.

## Starting a task

1. Read root AGENTS.md, the project brief, glossary and status.
2. Identify the affected area and read its scoped AGENTS.md.
3. Inspect actual source and the relevant procedure/contract/hardware profile.
4. State scope, what is already implemented and what evidence will establish done.
5. Implement a small coherent change through the existing module interface.
6. Run relevant checks and update status and a task note when work spans sessions.

Example task prompts:

- Firmware: "Read AGENTS.md and firmware instructions. Implement bounded identity
  and health in firmware/lora_node using the selected diagnostic contract. Preserve
  disabled RF/audio capabilities. Build the target; do not flash."
- Host: "Read AGENTS.md and the RF-01 procedure. Implement RF-01 through a physical adapter, retaining all
  procedure cases and honest firmware/capability blockers. Run host checks and update the implementation checklist."
- Shared contract: "Read root and contracts instructions. Add the command required
  by this procedure, update producer/consumer models and generated metadata, and
  add conformance checks. Gate firmware support if it is not implemented."

## Context maintenance

- Requirements and user decisions go in `project_brief.md` or the hardware profile.
- Existing behavior, blocked work and actual verification go in `status.md`.
- Detailed experiment readiness stays in the implementation checklist and saved
  procedure evidence, not an informal agent narrative.
- New domain terms go in root CONTEXT.md. Module/layout decisions go in architecture
  docs; significant trade-offs get a short ADR. Proposed choices stay labeled.
- Use `task_template.md` for a durable handoff; create `docs/tasks/` only when a real
  task note is needed. Include paths, acceptance criteria, checks and remaining work.
- If multiple agents are explicitly assigned, give each a concrete file/task scope;
  coordinate edits to shared contracts and generated files before integration.

## Instruction precedence

Current user instructions take precedence over historical documents and repository
instructions. Root AGENTS.md supplies shared invariants; scoped AGENTS.md adds local
rules. A plan is not implementation evidence. If instructions conflict, identify
which document is stale and update it as part of the authorized work.
