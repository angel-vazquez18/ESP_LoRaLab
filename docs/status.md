# Consolidated implementation status

Updated November 7, 2026. The host is now physical-only by user decision, replacing
the earlier simulation-first direction. All 23 CDR procedures, including voice,
remain required. See the [checklist](experiment_implementation_checklist.md).

## Current source capabilities

- November 7 PSRAM bring-up: terminal inspection confirmed initialization and
  detected capacity 2,097,152 bytes; free PSRAM 2,095,000 bytes; largest PSRAM
  block 2,064,384 bytes. Internal free heap was 395,431 bytes and largest
  internal block 294,912 bytes. Local sdkconfig enables Quad PSRAM at 40 MHz,
  startup initialization and memory testing. The user saved these settings in
  sdkconfig.defaults; read-only comparison confirmed they match. A USB power
  cycle and reopening the monitor restored startup output after reset attempts
  showed only boot output; the root cause of that interruption remains undetermined. This
  establishes startup availability, not sustained buffer/audio validation.
- November 7 internal-memory bring-up: inspected main-node source reports free
  internal 8-bit heap and largest allocatable block. The latest inspected build
  completed successfully. User-provided startup logs report 398,456 free bytes
  and a 335,872-byte largest block. These are startup observations, not workload
  capacity or audio validation. This baseline preceded PSRAM enablement.
- November 6 USB inventory observation: Espressif USB JTAG/serial device at
  `/dev/cu.usbmodem101`, serial `F8:5B:1B:A2:77:44`, matching `esp-f85b1ba27744`.
  No serial connection or firmware handshake was performed. See `hardware/README.md`.
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
- Separate diagnostic firmware provides the diagnostic subset. The main-node
  app_main now logs startup, ESP-IDF version, eFuse-derived device ID and numeric
  reset reason. November 6 flash output verified writes for device
  `esp-f85b1ba27744` on `/dev/cu.usbmodem2101`; after IDF Monitor reset via
  Ctrl+T then Ctrl+R, the user reported expected logging. Physical RESET had
  interrupted USB with Errno 6. This is startup bring-up only: no main-node NDJSON,
  RF, encryption, replay, ACK/retry, timing or audio. USB port names may change.
- No new physical RF/audio measurements. November 4 user report: one node is
  connected to the laptop and microphone/amplifier GPIO wiring is complete.
  Microphone L/R is GND, amplifier SD/MODE and GAIN are 3.3 V (6 dB hardware gain).
  Speaker rating remains 8 ohm / 1 W; GNSS is unused; PTT is assigned GPIO 47.
  Speaker/PTT operation, printed revision, rail headroom and audio operation remain
  unverified. See `hardware/README.md` for the current reported wiring.
- Firmware development now follows the capability roadmap in
  [node development plan](node_development_plan.md). The earlier proposed five-test
  code draft was interrupted in temporary staging and was not installed, built or
  flashed. The main-node startup logging above was implemented separately by the
  user during manual learning steps.

## Documentation checkpoint (November 7)

The documentation commit includes the capability roadmap, agent guidance, wiring
references and observed startup/memory results. Main-node C source and
sdkconfig.defaults remain separate uncommitted user work at this checkpoint;
the reported firmware behavior describes that inspected working tree and the
board image. Uptime logging has been proposed but not yet implemented.

Documentation checks: repository resources/GPIO checks, 19 local link targets
across 12 changed Markdown files and Git whitespace checks passed. The wiring
PNG was visually inspected. No new host tests or firmware builds were run for
this documentation-only change.

## Earlier physical-only cleanup verification

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

1. Use [node development plan](node_development_plan.md) as the node capability
   work order. Continue board identity/health with uptime, persistent boot count
   and build/board fingerprints; then add compatible bounded serial control and
   cancellable finite operations.
2. Bring up artifact transfer, known-reference speaker playback and microphone
   capture locally. Develop radio/link work alongside audio when the second node
   is available; add host integration with each real capability.
3. Build message transport, security, codec/secure voice, integrated recovery and
   measurement capabilities. Use the experiments to check complete coverage rather
   than creating separate firmware implementations for each experiment.
4. Complete the full physical procedure matrices as capabilities become ready.
   Preserve all 23 entries and their negative/recovery/evidence obligations.
