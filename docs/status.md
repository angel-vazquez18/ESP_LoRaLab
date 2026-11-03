# Consolidated implementation status

Updated November 1, 2026. The host is now physical-only by user decision, replacing
the earlier simulation-first direction. All 23 CDR procedures, including voice,
remain required. See the [checklist](experiment_implementation_checklist.md).

## Current source capabilities

- Python/FastAPI backend, React dashboard, CLI, SQLite evidence and exports remain.
- One physical node, A or B, is enough for serial/local checks. Two distinct devices
  are required for RF/link procedures. MEM-01/OPS-01 expose local versus RF requirements.
  Future campaigns must derive node requirements from their selected cases.
- Simulator devices, synthetic run/campaign engines, simulation controls/CLI and
  simulation presets were removed. Old execution endpoints reject with HTTP 410;
  saved historical records remain readable/exportable with their original provenance.
- A bounded physical diagnostic check covers identity, ownership, idle status,
  advancing uptime and observed protocol/telemetry counters. It accepts one node
  by default or explicitly selected A/B nodes in sequence. Command/reply evidence,
  source/schema/profile hashes, partial results, cancellation and exports are retained.
  This is partial IF-01 coverage; full IF-01 qualification remains open.
- All other physical procedure runners remain blocked. Connecting two boards never
  substitutes for missing RF/security/audio firmware or a physical execution adapter.
- Numerical budget calculation, deterministic known-data/public-vector checks,
  reference WAV ingestion/inspection/playback and historical analysis remain.
- Separate diagnostic firmware provides the diagnostic subset. Main-node app_main
  remains empty: no main-node NDJSON, RF, encryption, replay, ACK/retry, timing or audio.
- No new physical RF/audio measurements. External audio/PTT peripherals are not
  connected. Planned hardware remains Heltec V4, no GNSS, PTT GPIO 47, amplifier
  on Heltec 3.3 V and 8-ohm/1-W speaker. Board revision, straps and power remain unverified.

## Cleanup verification

- Physical-path and retained conformance/audio regression suite: **73 passed**.
  Tests use isolated serial peers, not physical ports. Existing Starlette/httpx
  dependency deprecation warning remains.
- `make check`: passed (tests, lint, production frontend build, generated-contract
  consistency and repository checks). Frontend formatting also passed. Shared
  defaults, conformance vectors and generated schema/digests remain unchanged.
- Interactive browser verification unavailable: computer-use browser inventory is empty.
- No firmware changes, flash, physical port access, hardware experiment, commit or push.

## Historical consolidation verification (October 31)

These checks predate the physical-only cleanup. They do not describe current
simulation features, which were removed. Completed after consolidation:

- Full host suite: **99 passed** in 72.38 seconds. One existing dependency
  deprecation warning concerns Starlette TestClient's httpx integration; no lock
  versions were changed to suppress it.
- Ruff: passed for host source, tests and shared scripts.
- React/TypeScript production build: passed.
- Generated-contract read-only check: passed. Diagnostic schema digest and C header
  remain byte-for-byte identical to the imported baseline.
- Repository resources and nonconflicting planned external GPIO assignments: passed.
- Active local Markdown links: checked, no broken targets.
- Isolated ASGI smoke: built dashboard HTML/assets, state and diagnostic schema
  endpoints served successfully. This is not interactive browser verification.
- Main node scaffold: built successfully with ESP-IDF v6.0.2 / ESP32-S3 / 16 MiB
  flash defaults. app_main remains empty; no RF/audio capability is established.
  ESP-IDF emitted nonfatal upstream Kconfig default-value notes.
- Default profile, public vectors, diagnostic schema/header and both dependency
  locks are unchanged. User scaffold CMake/C source files are preserved byte-for-byte.
- Build output, local sdkconfig, dependencies, environment and migration backups
  were checked against ignore rules.

No flash, physical port access, hardware experiment, Git commit or push was performed.
The command results are retained locally in `local/migration/verification.json`.

## Next work

1. Bring up main-node board identity/health and bounded diagnostic serial control;
   build without flashing and advertise only actual capabilities.
2. Complete physical IF-01 framing/ownership/fault/recovery coverage on one node at
   a time, then implement radio firmware and the physical execution adapter/IF-02.
3. Add physical campaigns and each remaining dedicated procedure matrix, preserving
   full scope, negative/recovery cases, evidence and capability/equipment blockers.
4. Validate actual board revision, straps/power, two-node RF and audio separately
   when equipment and explicit hardware-operation authorization are available.
