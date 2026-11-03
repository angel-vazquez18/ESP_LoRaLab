# Task: Physical-only host with procedure-specific node requirements

Status: done

## Context

The November 1 user decision supersedes simulation-first development: remove the
simulated implementation and accept one physical node for tests that do not need
a peer. Two-node RF tests retain their full requirements. No flash or physical
port operation was authorized for this cleanup.

## Scope and acceptance

- Remove simulator engines, simulated procedure/run/campaign execution, presets,
  operator controls and CLI commands. Preserve all 23 physical procedure entries.
- Make A/B connections independent; reject duplicate port/device assignment.
- Run a bounded diagnostic subset of IF-01 with A alone, B alone or explicitly
  both in sequence. Preserve exact command/reply evidence, identity/profile,
  cancellation, interruption, errors and hashed exports.
- Keep full IF-01 and all missing physical runner/firmware support blocked.
- Keep reference WAV tools, budget calculations and historical evidence readable
  with original provenance. No old evidence is promoted to physical qualification.

## Decisions

See [physical-only host ADR](../adr/0002-physical-only-host.md). Local checks use
one node; MEM-01/OPS-01 distinguish local and RF workloads. Future campaigns derive
requirements from the actual selected cases. Shared wire models, generated digests,
defaults and public vectors remain compatible; legacy provenance is retained only
for history and rejection of nonphysical connections. OPS-01 C7 retains 100 cases
but now requires physical campaign execution (procedure revision 2.1).

## Work and verification

Removed simulator/runtime modules and their simulator-specific tests/controls;
retained independent framing, math/vector, diagnostic-session and audio tests.
Added physical host API/CLI/lifecycle regressions using isolated serial peers.
Updated current project guidance; obsolete workflow documents are labeled historical.

- `make check`: passed, **73 tests**, lint, frontend build, contracts, repository checks.
- `npm --prefix testbed/frontend run format:check`: passed.
- Browser verification unavailable: `iab` was unavailable and browser inventory was empty.
- No firmware source changes/builds, flash, physical port access, hardware
  measurements, commit or push. Existing workspace consolidation changes preserved.

## Handoff

Implement main-node board identity/health and bounded diagnostic control next;
then complete physical IF-01 and radio/physical execution integration. Current
check is partial IF-01 coverage. Hardware RF/audio qualification and interactive
browser QA remain open.
