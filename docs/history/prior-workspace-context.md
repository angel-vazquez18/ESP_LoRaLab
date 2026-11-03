# Historical context from Lora_Testbed

Archived during consolidation. This is not an active agent instruction file.
Current layout and hardware decisions are in ../../AGENTS.md and ../project_brief.md.

# Project context

The user designated `docs/secure_lora_comms_testbed_cdr.pdf` as context for ongoing work.
Read that document when a task needs details beyond this summary. It is the
22-page October 12, 2026 Critical Design Review for the **LoRa-Based Encryption
and Communications Testbed**, EN.525.743 Fall 2026, by Homar A. Rodriguez and
Angel K. Vazquez. It describes a planned design, not verified implementation.
Later user decisions take precedence over this baseline.

## User decisions (October 17, 2026)

- Host platform: macOS.
- Support both a graphical interface and CLI, prioritizing the graphical interface.
- No node firmware exists yet; coordinate the serial contract with firmware work.
- Node firmware will be developed using ESP-IDF (confirmed by the user).
- Voice is included in the planned version, together with every experiment and
  validation category described in the CDR. This supersedes the earlier voice
  exclusion and reduced experiment scope.
- The user is comfortable with Python and web development.
- Deadline: first week of December 2026.
- Automation details are open to recommendations; do not omit CDR experiments
  from the plan to simplify the first version.
- `docs/host_testbed_design.md` records a proposed design, including suggested
  stack, scope, and milestones. Those suggestions are not user-approved decisions.
- `docs/test_experiment_catalog.md` maps CDR experiments and integration checks
  to host workflows, firmware requirements, measurements, and acceptance evidence.

## Current implementation

- October 26 user direction: shared implementation work is simulation-first.
  Finish the common adapter, two virtual v2 nodes, reusable run/campaign
  lifecycle, evidence, assessments, UI/CLI and regression checks without
  requiring physical hardware or reference firmware builds. Keep each of the
  23 individual experiment implementation steps. Build their host workflows and
  virtual-node behavior first, with separate simulation-ready and
  hardware-validated status. The intended transition reuses runners/UI/analysis
  through a serial-backed adapter; matching firmware, compatibility checks and
  physical validation are still required before hardware results are accepted.
  See `docs/experiment_implementation_checklist.md` for the active work order.

- On October 18 the user delegated all provisional contract decisions; do not
  block implementation awaiting Homar's review. `docs/testbed_contract_v2.md`
  and `contracts/v2/default_profile.json` are the selected baseline, subject to
  later revision. `CONTEXT.md` defines domain terms. Major choices: ESP-IDF
  v6.0.2, NDJSON v2, AES-128-GCM with fresh per-source/per-run RAM-only keys,
  40-byte RF header, 160-byte fragments, stop-and-wait/two retries when enabled,
  Codec 2 1.2.0 mode 3200 and wired pulse calibration for one-way timing.
  The diagnostic subset is implemented in `v2.py`, `nodes.py` and
  `firmware/diagnostic`; physical RF/audio and remaining v2 commands are not.
  The legacy known-data RF simulator remains v1 in a separate explicit mode.

- `docs/full_implementation_plan.md` is the October 18 implementation roadmap:
  complete CDR coverage, modern UI/UX, live physical-node data, result
  visualizations and phased hardware validation. It is a plan, not implemented
  functionality; its schedule supersedes the earlier proposed milestone order.
- User clarification on October 18: the initial attachment will be one ESP32
  with no microphone or speaker. Exact board/radio model and second-node/audio
  availability are unconfirmed. Begin hardware integration with single-board
  serial/telemetry checks; retain all two-node RF and physical audio requirements.

- See `README.md` for setup and `docs/implementation_status.md` for completed
  work versus remaining milestones. Do not confuse the design with implemented
  capabilities.
- Host package: `src/lora_testbed`; dashboard: `frontend`; checks: `tests`.
- Attached device `esp-f85b1ba27744` is ESP32-S3 rev 0.2, 16 MiB flash,
  2 MiB embedded PSRAM, native USB `/dev/cu.usbmodem1201`. Diagnostic firmware
  was built/installed after a verified full flash backup under ignored
  `data/hardware-backups`. See `firmware/diagnostic/README.md`.
- Hardware mode supports independent A/B connections, real health/memory history,
  a detail drawer and strict matching diagnostic schema hashes. Disconnect the
  host's slot before opening that port with esptool/IDF Monitor.
- The baseline shared v2 simulation path is implemented in `adapters.py`,
  `virtual_nodes.py`, `execution_v2.py`, `analysis_v2.py` and `run_records_v2.py`.
  Two virtual nodes process actual unprotected DATA bytes, fragmentation,
  reassembly and independently verified hashes through bounded NDJSON. Runs and
  campaigns share the adapter lifecycle, evidence, assessments and UI/CLI.
  `docs/v2_execution.md` documents usage, limits and fault fixtures. The diagnostic
  schema remains unchanged; execution has its own generated schema/profile.
  GCM/replay, ACK/retry, echo, clock calibration and audio remain unavailable;
  20 dedicated procedure matrices remain open. IF-01 now has a complete simulated
  C1-C6 runner in `serial_validation.py` / `procedure_runs.py`, with 218 default
  case executions, raw-byte probing, UI/CLI and persisted assertions/evidence.
  IF-02/IF-03 now also have full simulated procedure matrices in
  `integration_procedures.py`: 30 known-data cases (36 child runs, 3,000 verified
  positive/control messages) and 25 campaign fixtures. Production ASGI APIs and
  isolated Host lifespans exercise the common engine, preserve child records,
  raw events/artifacts and nested hashed exports, and test active/paused restart.
  See `docs/integration_procedures.md` for API/page-retrieval versus browser scope;
  IF-02/IF-03 interactive browser verification on October 31 was unavailable.
  CLI `integration-check` and the UI use the same procedure service with strict
  current-profile full passing prerequisite gates and separate hardware status.
  `docs/serial_validation.md` documents scope and virtual timing. Full readiness
  requires a matching finalized full passing run; quick/subset checks cannot
  close it. Physical USB/UART IF-01 validation remains pending. Linked campaign batches
  preserve oversized case groups; the 100-case workflow fixture passes.
  Simulation readiness and hardware validation are separate catalog fields.
- Legacy simulated IF-02 and the IF-03 campaign workflow remain available. Campaigns have
  presets, repetitions/directions, seeded ordering, pause/cancel, selected-case
  reruns, comparisons and evidence exports; see `docs/campaigns.md`. Radio sweep
  settings in that legacy path are recorded only. The v2 path uses calculated
  airtime and explicit loss/signal fixtures, without RF propagation predictions.
  Other CDR runners and
  all physical RF/audio validation remain pending.
  Voice reference upload/inspection/playback is implemented; node audio/RF voice
  delivery is not implemented. Keep simulation and reference artifacts explicit.
- `docs/serial_protocol_v1.md` documents the legacy simulator wire contract;
  migrate host and firmware to the selected v2 baseline together.
- Run `uv run pytest`, `uv run ruff check src tests`, and
  `npm --prefix frontend run build` for implementation verification.

## Purpose and scope

- Build a controlled laboratory testbed with two bidirectional embedded nodes
  exchanging encrypted and authenticated packets over a configurable 915 MHz
  point-to-point LoRa link.
- A host computer connects to both nodes over USB serial for configuration,
  experiment orchestration, telemetry collection, run storage, and analysis.
- The CDR baseline success is secure data communication with repeatable
  measurements. The user additionally requires voice and all CDR experiments in
  the host plan now. Voice feasibility must be measured, not assumed.
- Scope is two active bench-connected nodes. Five boards are available for
  spares and subsystem work. Field deployment, autonomous operation, and battery
  optimization are outside the primary objective.

## Hardware and software direction

- Planned hardware: Heltec WiFi LoRa 32 V4 / ESP32-S3 nodes, LoRa radios and
  antennas, INMP441 I2S microphones, MAX98357A I2S audio output, speakers,
  displays/buttons, and stable bench power.
- Confirmed node framework: ESP-IDF. Expected languages: C/C++ firmware and
  Python host automation/analysis.
- Node modules cover radio control, packetization/reassembly, packet security,
  replay checks, serial commands/telemetry, and application/audio handling.
- Host flow: scenario settings -> test runner -> serial transport -> nodes;
  telemetry -> event collector -> run records -> analysis.

## Ownership and shared contracts

- Homar owns embedded nodes, hardware/peripherals, radio/packet firmware,
  authentication/encryption, audio, and local controls.
- Angel owns the host testbed, serial handling, experiment automation, run
  records, analysis/plots, and experiment procedures.
- Shared interfaces have provisional decisions in the v2 contract: serial framing, command/reply
  formats, protocol versions, telemetry fields/units, error codes, sequence
  rules, packet headers, security state, replay metadata, and retry/timeouts.
- The CDR did not finalize wire/security/codec parameters; the user's later
  delegation makes the v2 decisions authoritative for current implementation.
  Review with Homar can change the baseline through an explicit versioned update.

## Implementation and validation priorities

- Bring up hardware and serial, establish known-data LoRa exchange, freeze
  interfaces, add encryption/authentication, sequencing/fragmentation/reassembly,
  replay rejection, host automation, integrated experiments, then feasible audio.
- Integration progresses through serial interface tests, integrated RF link
  tests, and fully automated experiment runs.
- Measure unique-packet delivery ratio, useful delivered payload throughput,
  initial round-trip delay, RSSI/SNR, security processing overhead, integrity and
  replay rejection, reassembly behavior, and memory use.
- Vary spreading factor, bandwidth, coding rate, transmit power, security mode,
  message/fragment size, acknowledgments/retries, and payload type.
- Preserve configuration, node IDs, timestamps, sequences, and errors per run.
- Do not assume synchronized clocks for initial delay measurements.

## Constraints and open details

- Audio baseline is a three-second, 8 kHz, 16-bit mono recording (48,000 raw
  bytes). Compression, memory use, fragmentation, security overhead, and radio
  airtime must be considered together; continuous high-quality voice is not promised.
- Validate numerical examples and airtime formulas before implementing them.
  Fragment capacity must include all framing and security overhead; raw audio
  size and compressed transmitted size are different quantities.
- Final deliverables should include reproducible wiring, environment setup,
  build/flash/run instructions, measured results, known issues, and citations
  for reused libraries/code and their licenses.
