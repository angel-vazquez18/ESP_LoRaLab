# Implementation status

> Historical document. The November 1 physical-only decision supersedes the
> simulator workflows and commands below; those implementations were removed.
> See [current status](status.md) and [host usage](../testbed/README.md).

Updated October 31, 2026. The baseline shared v2 simulation workflow is
implemented. This is not completion of all 23 CDR experiments or physical
RF/audio qualification. The active work order is
`experiment_implementation_checklist.md`; usage is in `v2_execution.md`.

## Available now

- IF-02 full 30-case simulated procedure: 1/64/159/160-byte payloads, 100
  messages, both directions and three repetitions, plus incompatible-peer
  rejection and corrected controls. It preserves 36 child runs and 3,000
  verified messages in the no-loss control.
- IF-03 full 25-fixture simulated procedure: six-case baseline, three repeats
  of pause/resume, active cancellation, configuration failure, page/state reload,
  active/paused application restart, selected reruns, export integrity and
  exclusive ownership. Real production ASGI routes and isolated persisted hosts
  exercise the existing execution engine; original child events/artifacts and
  receipt timestamps remain available in normal results and nested ZIP evidence.
- Integration procedure UI/CLI, prerequisite/profile gating, per-group progress,
  current virtual-node status, case assertions, links, saved-result tabs and
  direction/payload-size goodput charts. Physical validation remains separate.
  See `integration_procedures.md` for full counts, evidence and scope limits.

- IF-01 simulated serial procedure runner: all C1-C6 groups, 218 case executions
  with ten valid cycles per role and three repetitions per other variant.
  Persistent expected/observed assertions, every-byte input splits, wire evidence,
  retry side-effect readbacks, compatibility rejection, ownership/lease expiry,
  health freshness and recovery. UI/CLI, group progress, case filtering and
  JSON/CSV/JSONL/hashed ZIP exports are implemented. Quick/subset checks do not
  close full readiness; current-profile full passing evidence does. See
  `serial_validation.md`. Physical USB/UART qualification remains pending.

- Common node adapter for discovery, connect, request/reply, events, snapshots
  and close. The reusable runner uses that interface rather than simulator
  internals or direct serial access.
- Two virtual v2 nodes with distinct device/boot identities, claims/leases,
  command deduplication, typed baseline arguments/results, asynchronous outcomes,
  applied-setting readbacks, capability/resource gates and bounded NDJSON.
- Actual deterministic payload bytes, unprotected 40-byte DATA framing,
  fragmentation/reassembly, independent complete-message hashes and bounded
  missing-fragment reports. The first source/recovered message is retained as a
  binary sample; all delivered messages have recorded hashes.
- Finite IF-02 lifecycle: configure, prepare, receiver-first arm/start, collect,
  drain, verify chunks/complete artifact hashes, stop and release. Preparation,
  cancellation, reset, transport loss, lease loss and cleanup errors are visible.
- Explicit deterministic loss, duplicates, within-message reversed ordering,
  corruption, reset/disconnect/lease expiry, preparation faults, command delay,
  lost replies and missing/duplicated telemetry. Synthetic clocks use explicit
  wall pacing, health and lease renewal. Signal and memory remain synthetic.
- Independent PDR/verified-message goodput, summary/event reconciliation,
  telemetry-gap invalidation and separate execution/assessment outcomes.
  Corruption fails content; missing evidence remains inconclusive.
- Separate v2 SQLite run/campaign/event records, stable device enrollment IDs,
  per-run boot/session identities, requested/applied settings, UTC/monotonic host
  event receipt times, paginated history and restart replay without resuming TX.
- V2 campaign preview, single-factor settings sweeps, repetitions, directions,
  seeded ordering, between-case pause/resume, cancel, linked selected-case
  reruns and skipped/interrupted evidence. Oversized case groups automatically
  form linked batches without shortening counts or changing saved case order;
  a 100-case fixture verifies every run, session and delivery. Individual oversized
  run workloads still require explicit splitting.
- Bench, Experiments, Campaigns and Results default to v2 workflows. Live/result
  progress, node identity/configuration/health, assertions, up to four-run metric
  comparisons and passing-case repetition statistics are visible. Persistent
  light/dark appearance applies to the new views.
- JSON/CSV/streamed JSONL and ZIP evidence with raw events, sampled artifacts,
  provenance and independently checkable SHA-256 manifests. Finalized cleanup
  is required before export. CLI and UI share the backend and bench lock.
- All 23 CDR entries remain visible with simulation status, full-procedure
  completion and hardware validation recorded separately. IF-01/IF-02/IF-03 can record full
  simulated procedure completion; the remaining 20 complete procedure matrices
  and every physical procedure validation remain open.
- Existing legacy v1 metadata simulation/campaigns/results remain accessible
  through explicit legacy controls and retain their separate records.
- Reference WAV validation, storage, waveform inspection, browser playback and
  hashes work. Virtual audio/codec/RF voice delivery are still pending.

The generated virtual execution schema is separate from the installed diagnostic
schema, whose hash remains unchanged. GCM/ACK previews are calculations only;
virtual execution advertises those capabilities as unavailable. Radio settings
change calculated airtime, while loss and signal are explicit fixtures. No RF
propagation or measured ESP32 performance is inferred.

## Existing hardware diagnostics

- Independent A/B USB connections, strict diagnostic schema matching, command
  ownership, timeout/retry handling, reset detection and actual health storage.
- Hardware bench with identity, firmware, uptime, RAM/PSRAM, capability details,
  freshness/errors and bounded memory history. A single board works independently.
- ESP-IDF 6.0.2 diagnostic firmware was previously installed on ESP32-S3 device
  `esp-f85b1ba27744` after a verified full-flash backup. A 20-second acceptance
  check covered identity/schema, errors, malformed-input recovery and health.
  A subsequent 3 h 40 min observation retained 13,147 samples from one boot with
  no event gaps or firmware telemetry drops; free internal heap stayed at
  349,567 bytes. These are diagnostic observations, not RF/audio evidence.
- Build/flash instructions and opt-in hardware checks remain in
  `firmware/diagnostic/README.md`. No firmware was built/flashed and no physical
  RF/audio experiment was performed in the October 26 simulation work.

## Verification

- 99 software tests: 89 previous checks plus ten integration-procedure checks.
- Integration checks execute the full 30-case IF-02 and 25-fixture IF-03 matrices,
  verify prerequisites, content, negative/recovery controls, real child records,
  nested manifest hashes, pagination, corrupted-evidence rejection, shutdown,
  interruption, ownership, partial coverage and shared CLI dispatch.
- Serial checks execute the full 218-case matrix; validate counts, every-byte
  boundaries, wire/ZIP hashes, partial/profile readiness, exclusive ownership,
  cancellation, shutdown/restart, redaction and CLI dispatch. Intentionally bad
  adapters prove that incorrect errors, duplicated side effects, unavailable
  handlers and failed close cannot yield a passing procedure. A public-interface
  wrapper verifies runner isolation from simulator internals. Diagnostic schema
  compatibility remains unchanged.
- New checks cover real RF bytes against the existing conformance vector, both
  directions, fragmentation, artifact contents/chunk CRC/final SHA, pagination,
  JSONL/ZIP integrity, determinism, command deduplication and lease renewal.
- Fault checks cover content mismatches, full loss, telemetry loss/duplicates,
  delayed/missing preparation, resets/disconnects/lease expiry, resource/schema
  and readback rejection, damaged artifacts and adapter-close failure.
- Lifecycle checks cover cross-mode exclusive ownership, receiver-first order
  through a wrapper exposing only the public adapter, pause/resume, cancellation
  including artifact collection/paused campaigns, reruns, shutdown and durable
  v2-only restart replay. Linked batches execute all 100 fixture cases with
  distinct sessions. Terminal exports are blocked before cleanup completes.
- Required verification: `uv run --project testbed pytest testbed/tests`, `uv run --project testbed ruff check testbed/src testbed/tests`,
  `npm --prefix testbed/frontend run build`. Frontend formatting and schema regeneration
  are also checked. The earlier baseline UI inspection was unavailable while
  the workstation was locked. The new IF-01 browser path has now been checked:
  full procedure start/completion, refresh, case assertions, evidence loading,
  navigation to saved Results and light/dark appearance, with no browser console
  errors. Proof images are under `output/ui`. October 31 IF-02/IF-03 browser
  re-verification remains pending: browser discovery failed and the native-app
  fallback timed out. Their production builds and backend/page-retrieval
  procedure checks pass; no new browser screenshot proof is claimed.
  A live CLI/API IF-01 run also verifies all 218 cases, cleanup and export hashes;
  its local record is `data/serial-validation-acceptance.json`.
  The October 31 live acceptance sequence passed all three full procedures:
  218 IF-01 cases, 30 IF-02 cases (3,000 verified messages), and 25 IF-03
  fixtures. Its procedure manifests and all 609 nested evidence-file hashes
  were independently checked. Current-profile records and counts are saved in
  `data/integration-procedures-acceptance.json`. This is backend simulation
  evidence, with interactive browser and physical validation explicitly false.
  A real CLI/API six-case campaign verified 24 reconstructed
  messages, clean resource release and all 27 evidence-file hashes; its local
  record is `data/v2-smoke-acceptance.json`. This is simulation evidence.

Environment: macOS; Python 3.14.6; Node.js 25.2.1; npm 11.18.0. Dependencies are
locked in `testbed/uv.lock` and `testbed/frontend/package-lock.json`.

## Remaining implementation

1. Complete interactive IF-02/IF-03 browser verification when computer access
   recovers. Their complete simulated backend procedure matrices are implemented.
   Physical validation remains separate.
2. Add dedicated RF-01 through RF-04 case generators, baseline controls,
   assertions and plots using the shared campaign path.
3. Implement SEC-01 through SEC-04, PKT-01 through PKT-03, TIME-01/TIME-02,
   MEM-01, VOICE-01 through VOICE-04, MODEL-01 and OPS-01. Existing unprotected
   fragmentation/fault/model support is a foundation for their full procedures.
4. Validate every simulated procedure configuration/repetition and preserve
   its independent readiness ledger. Keep all 23 entries and negative/recovery
   requirements in `experiment_implementation_checklist.md`.
5. Later implement the serial-backed execution adapter and matching ESP-IDF
   firmware. Enable physical provenance explicitly, verify compatibility and
   capabilities, then repeat all physical procedures. Diagnostic firmware alone
   cannot execute the richer RF/audio contract.

The October 18 contract/defaults remain the provisional baseline authorized by
the user; review with Homar can revise them through a versioned update. The
October 18 roadmap remains planning context, superseded for shared work by the
October 26 simulation-first direction. Hardware and audio availability do not
block the remaining simulated implementation.
