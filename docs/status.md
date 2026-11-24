# Consolidated implementation status

Updated November 23, 2026. The host is now physical-only by user decision, replacing
the earlier simulation-first direction. All 23 CDR procedures, including voice,
remain required. See the [checklist](experiment_implementation_checklist.md).

## November 23 — Host-armed finite PTT capture (#30)

Optional GPIO47 polling now starts only one explicitly host-armed fixed-length
capture after a stable release and press. Stop/lease/disconnect/deadline outrank
pending input; held rearm and duplicate commands cannot restart work. No DMA is
started/stopped while only armed. API/CLI reuse the ordinary bench/audio ownership,
PCM verification, WAV and cleanup. The exact `ptt_capture_v1` supplement is gated
independently; its fixed policy is fingerprinted to keep bounded enrollment.

Twenty dedicated native/API/CLI cases pass, including 80 admission allocation
failure positions with recovery, mismatched current/identity fingerprints and a
fully configured radio/audio/codec/PTT hello. The serial fixture no longer inflates
compact records with whitespace. Full `make check` passes 729 cases without skips,
plus lint/frontend/contracts/repository/vendor checks and frontend formatting. Both V4.2/
32 KiB IDF profiles build: PTT disabled 0x6e880, isolated microphone/PTT enabled
0x6e930, each 57% app free with static DIRAM 73,841 bytes. Normal configuration
remains off. No flash; PCB/GPIO47 switch acceptance remains unverified under #1.
Other wire fingerprints are unchanged. See [PTT walkthrough](host_armed_ptt.md).

## November 23 — Voice stage dashboard (#72)

The Voice page now controls the common reference/microphone workflow and inspects
verified source/encoded/recovered/decoded files, waveform/identity/counts, local
stage clocks, protected RF findings, comparisons and physical listening notes.
One-way latency and absent stage intervals remain unavailable. Saved-file
integrity is checked separately from historical delivery. Failed/cancelled work
retains its errors and never claims partial receiver playback.

Three new API inspection cases pass. Full `make check` passes 709 cases without
skips plus shared checks. Final file-identity/duration presentation changes also
pass the three inspection cases and frontend build/formatting. Browser acceptance with isolated native nodes covered both sources/
directions, loss/stop, navigation/refresh, notes, both themes and a 390 px layout
without page overflow. No console warnings/errors. No firmware/wire/build/flash
change or physical qualification. See [dashboard checks](secure_voice_workflows.md).

## November 23 — Shared secure voice workflows (#68)

Host/API/CLI now compose reference upload or microphone capture, verified local
codec preparation, common protected receiver-first transfer, separate receiver
decode/play and two labelled data comparison bases (equal encoded bytes versus
standard 64 bytes). Common radio readbacks occur after observed RF completion;
each RF child provisions fresh source keys through the existing private owner.
Job-created node artifacts retire after evidence retention; preexisting files are
preserved. Child-owner release and terminal-after-cleanup ordering prevent stage
races, and a cancelled stop caller cannot prematurely release the bench.

Twelve dedicated cases include both source types/directions, unavailable speaker,
source/RF failures and following-work recovery, API/CLI integrity/listening and
active shutdown without resume. Full `make check` passes 706 cases without skips,
plus lint/frontend/contracts/repository/dependency checks. Host-only;
no firmware/wire change or flash. See [secure voice workflow](secure_voice_workflows.md)
for reading order, comparison interpretation, commands and physical checks.
Dedicated dashboard follows #72; physical voice qualification remains #80.

## November 23 — Protected encoded message content (#64)

Committed encoded artifacts now use the existing protected message/retry/replay
path, with exact source metadata preflight, immutable borrowing, private receiver
output and complete hash-gated publication. Received codec manifests preserve
source ID/sample/frame metadata. Explicit decode/play remain separate; incomplete,
tampered and hash-mismatched content cannot publish playable input. Both-direction
lost-ACK retry delivers one complete clip. Source borrow and transfer/decode/play
cancellation recover cleanly.

Nineteen dedicated cases and final full `make check` pass: 694 total cases, no
skips, plus lint/frontend/contracts/repository/dependency checks. Selected V4.2/
32 KiB IDF build is 0x6e520, 57% app free; static DIRAM remains 73,841 bytes.
Execution SHA changes to b029707…; other wire identities stay unchanged. See
[protected voice content](protected_voice_content.md) for reading order, migration
and physical checks. No flash/physical acceptance. Next #68 adds common host voice
orchestration and clearly labelled matched data comparisons; #72 adds its UI.

## November 23 — Local codec provenance workflow (#45)

Shared host/API/CLI now retrieve and verify source, encoded and decoded artifacts
under one bench owner, retaining node stage results/timings and linked transfer
records. Explicit playback links require the same role/device/boot and full source
manifest; source-capture links also require hash agreement under artifact ID reuse.
Cancellation/failure preserves verified earlier files without round-trip success.
Codec results stay separate from existing audio DMA result fields.

Full `make check` passed 675 cases without skips, plus lint/frontend/contracts/
repository/dependency checks. Coverage includes 13 new codec and 25 existing audio
cases. No firmware source/build/flash changes in this issue. Matching #41
codec firmware remains required; physical voice, RF and instrument checks remain
open. See [workflow, reading order and physical checks](codec_provenance.md).

## November 23 — Complete-artifact codec decoding (#41)

Added finite fresh-state decoding into a separate hash-published recovered PCM,
explicit final-padding trimming, typed host tracking and before/ready/after heap
snapshots. A reproduced upstream process-global phase generator now belongs to
each codec context through a recorded vendor patch; repeated/interleaved contexts
are independent. Cancellation, ownership loss, timeout, allocation/final-hash
failure and duplicate commands preserve bounded cleanup and a following valid
clip. No implicit playback or lossless PCM comparison.

Focused 152 and full 662 cases pass without skips; selected V4.2/32 KiB IDF build
0x6def0, 57% app free. Exact codec supplement changed; other wire digests remain
unchanged from #36. See [decoding walkthrough and checks](codec_decoding.md).
No flash or physical codec/voice qualification. B remains on its original audio
image; A/printed PCB revisions and a successful deployment backup remain pending.
Next #45 adds shared API/CLI codec workflow with saved three-file provenance.

## November 23 — Finite committed-PCM encoding (#36)

Added a portable one-frame-per-step encoder with fresh Codec 2 state, immutable
source borrowing, separate hash-published output, partial counts/timing and bounded
stop/lease/disconnect/deadline/acceptance-failure cleanup. The shared serial session
negotiates the new compact codec profile and tracks its typed terminal result;
GUI/CLI workflow controls and decoding remain separate issues. Full/partial
reference clips match a separate public-library encoder; 24,000 samples produce
150 frames/1200 bytes and repeated fresh-state clips match.

Final `make check` passed 625 cases without skips plus lint/frontend/contracts/
repository/dependency checks; the focused command passes 141. Selected V4.2/32 KiB
IDF build: 0x6d870 bytes, 57% app free, +3840 bytes above corrected #29. Artifact
manifest compatibility changes; codec uses its own exact supplement fingerprint.
Existing control/diagnostic/audio/RF identities remain unchanged. See
[encoding review and physical checks](codec_encoding.md). No flash or physical
codec/voice qualification. B remains on the original audio image after the failed
backup attempts; A and printed PCB revisions remain unobserved.

## November 23 — Pinned Codec 2 mode 3200 (#29)

The main image now builds the pinned 1.2.0 codec/DSP subset and queries its actual
160-sample/64-bit/8-byte frame format once at startup. Safe capability metadata
reports the dependency version/revision/options and library readiness; codec
operations remain unavailable pending #36/#41. A recorded local patch corrects
partial-constructor leaks/asserts without changing signal processing/codebooks.
All eleven actual allocation failures release temporary state, then permit a
fresh query. Sources, codebook generation and LGPL/KISS FFT notices are retained.

Final `make check` passed 604 cases without skips plus lint/frontend/contracts/
repository/resource-hash checks; focused codec/control checks passed 94. The
selected-board IDF build passed: image 0x6c970, 58% app partition free, 29,936 bytes
above #63. Whole-image static DIRAM use is 73,841 bytes; native constructor peak
is not target heap evidence. No flash. See [Codec 2 review and checks](codec2_dependency.md).
The target compiler reports an 8272-byte constructor frame; the default main-task
stack is now 32 KiB with an enabled-codec build guard. The old 8192-byte cached
profile correctly fails; the 32 KiB V4.2 rebuild passes with unchanged image size.
The attempted 16 MiB backup failed twice at12,288 bytes, so no image was installed;
B reconnected at boot104 with the original audio fingerprint.

Static transport/workload bounds and codec source details are now enrolled only
in hello, keeping configured audio+RF health within 4096 bytes. Current flags,
operative profiles, applied settings, errors and measurements remain in health.
The direct missing-reply regression and full 604-case suite pass.

Physical backend8000 now identifies B `esp-f85b1ba27744:104` running the original
local-audio build (`a5ecf08a…`), with RF disabled. A has not appeared in USB inventory;
printed PCB revisions remain unknown. No physical RF/codec qualification claimed.

## November 23 — Protected host sessions (#63)

The shared GUI/CLI backend now provisions fresh independent source keys, retires
its private owner after setup, records allowlisted setup facts and rejects
secret-bearing metadata at storage/export/API boundaries. Protected messages use
the existing receiver-first/readback/cleanup path. Observed RF arrivals, node
reported authenticated fragments, rejection stages and accepted ACKs remain
separate. Explicit accepted-ACK events require the new execution fingerprint.

Full `make check` passed 587 cases without skips, lint, production frontend,
contract and repository checks; formatting passed. The selected-board ESP-IDF
image built (0x65480 bytes, 60% app free), without flashing. Isolated native-C
browser acceptance verified A→B 321 bytes with three authenticated fragments and
three accepted ACKs, B→A 161 bytes without ACKs, exact readback and idle cleanup.
Mobile width 390 had no horizontal overflow; the console had no warnings/errors.
These are software fixtures, not physical RF results. The delivered-drain clock
race and repeated schema generation during live polling were reproduced and
fixed through public regressions. See [review and checks](protected_host_sessions.md).
Physical #67 and board revision/installation checks remain pending.

## November 21 — Radio execution contract (#3)

The selected execution commands now have explicit per-command capability metadata,
exact host compatibility checks, shared literal lifecycle/settings/timestamp
examples and generated firmware metadata. New work requires current radio-ready
health; declared cleanup remains available after failure. Existing control,
diagnostic, artifact and audio digests remain unchanged. RF handlers are not yet
advertised. See [radio execution](radio_execution.md) and
[batch handoff](tasks/milestone_3_to_8_batch.md). No board is connected; physical
RF acceptance remains open. `make check` passed 366 tests with no skips, lint,
frontend build, generated-contract and repository checks.

## November 21 — SX1262 initialization (#12)

Added the pinned Semtech driver, bounded portable GPIO/SPI/time boundary, explicit
V4.2/V4.3 board selection, real status-based availability and standby/front-end
shutdown on failure. Default builds leave RF pins untouched. V4.3 plus the old
GPIO5 microphone capture profile fails at build time. Native checks cover actual
driver calls, absent/stuck/failing buses and repeated recovery; physical radio
qualification remains pending. See [driver details](radio_driver.md). Full `make check` passed 373 tests without
skips; an additional command-rejection native case passed afterward. Default and
V4.3 ESP-IDF builds passed; V4.2 selection is also checked before publishing.

## November 21 — Applied modem settings (#15)

Firmware now advertises only `config.set` from the execution profile. Strict
radio/link validation precedes all SPI effects; status-confirmed settings and a
revision are returned and reported in health. Exact sync-word/type readback,
invalid-request atomicity, duplicate handling, allocation-failure safety and
failed-driver availability withdrawal are covered through the real C core. Host
requests require fresh advertised support and typed applied results. Full
`make check` passed 378 tests without skips; the ESP-IDF build passed. No RF hardware or radiated-power measurement was
performed. [Details and later checks](radio_driver.md#modem-configuration-15).

## November 21 — Finite transmit driver (#19)

Added bounded exact-byte frame transmission, copied original/attempt references,
node-local command/TX-done observation times, finite chip/software deadlines,
retained one-shot terminal results and standby/front-end cleanup. Native cases
cover completion, missing/unexpected/timeout IRQs, I/O failure, cancellation,
consumer pressure and following transmission. Full `make check` passed 384 tests
without skips; ESP-IDF build passed. These are driver boundaries; operator
`run.start` is still unavailable pending RX and message integration. No board or
RF measurement was used. See [finite transmission](radio_driver.md#finite-transmission-19).

## November 21 — Finite receive driver (#20)

Added finite RX windows, exact valid FIFO bytes/offsets, RX-done polling observation,
PHY CRC/header state and fractional RSSI/SNR. Bad/oversized/empty frames remain
failed observations; missing frames have no signal values. Timeout/cancel,
retained-result pressure and rearm are covered; SPI failure withdraws readiness
until reinitialization. Native radio cases passed 24 scenarios and the ESP-IDF
build passed (0x4d630-byte image, 70% app headroom). Full `make check` passed 393
tests without skips, lint/frontend/contracts/repository checks. No board was
connected. Operator RF run support is still unavailable pending frame/execution
integration. See [finite reception](radio_driver.md#finite-reception-20).

## November 21 — Single-fragment DATA and finite node lifecycle (#25)

Added explicit-endian header/source-vector matching and exact once-only known-data
validation, plus real session/prepare/arm/start/stop/summary routing. The initial
node limit is one unprotected known-data message, one fragment (at most configured
capacity, 215-byte ceiling), within 30 seconds. Source/recovered artifacts reuse
verified RAM storage; bad frames cannot publish a delivery. Ownership loss clears
incomplete work and sessions. The physical serial reader accepts only negotiated,
known-run RF observations. [Current behavior and checks](radio_execution.md#implemented-single-message-subset-25)
explain the limits; host workflow/dashboard and physical qualification are pending.
Full `make check` passed 408 tests with no skips; ESP-IDF built successfully.
The original checkout's 19 preserved files still match their saved SHA-256 values.
No ESP was connected.

## November 22 — Receiver-first host radio workflow (#27)

Added a shared physical backend/API/CLI for one-message known-data bring-up. It
requires distinct compatible peers, matching applied settings and complete
preparation, arms RX before TX, retrieves actual files and independently verifies
bytes/hashes. Raw records, summaries, source fingerprints, linked readback traces
and hashed exports preserve partial outcomes. Verified bytes and missing telemetry
remain distinct. Stop/cleanup races and uncertain session-open recovery are covered;
restart never resumes. `make check` passed 424 tests without skips, including 16
new host-radio cases, lint/frontend/contracts/repository checks. No board access
occurred; physical qualification and dashboard controls remain pending. See
[operating/review guide](physical_radio_runs.md).

## Current source capabilities

- November 8 GitHub planning setup: repository labels, eight capability milestones
  and a private development/validation Project organize remaining work. The setup
  branch adds issue/PR forms, the scoped backlog snapshot and an optional status
  reconciliation tool/workflow. See [GitHub workflow](github_workflow.md). These
  are planning resources; no new firmware behavior or physical qualification is
  established. Seven focused status-sync tests, Ruff/format checks, form/workflow
  YAML parsing, all-23 coverage/dependency checks, local documentation links and
  repository/GPIO checks passed. Automation needs a dedicated Project credential
  after merge. No board access, firmware build or experiment execution occurred.

- November 8 commit checkpoint: at the user's request, the Milestone 1 software,
  native checks, host/dashboard integration, agent cleanup and modular firmware
  layout are recorded in separate Conventional Commits. Earlier "uncommitted"
  notes below describe the implementation checkpoints before this request.
  The previous 147-test and firmware-build verification applies to this source;
  physical acceptance remains open. No push or hardware action is part of committing.

- November 8 instruction/layout cleanup: consolidated nine AGENTS.md files into
  five (root, firmware, testbed, frontend and contracts), merging unique guidance
  and removing duplicate documentation/hardware/test/main-target copies. The agent
  workflow now maps authoritative documents rather than repeating project rules.
  Main firmware has `platform/`, `transport/`, `control/`, `protocol/` and
  `generated/` modules; its 16-line entry composes them. CMake, native test paths,
  generated-header output and live documentation were updated together. All shared
  schemas, vectors/defaults and generated digest contents remain byte-identical.
  `make check` passed **147 tests** (74 native firmware cases), lint, frontend build,
  contract generation and repository checks; the ESP-IDF build passed with image
  size 0x3a560 and 77% app-partition headroom. Documentation links and Git whitespace
  checks passed. No physical port access, flash, reset or commit was performed.
  See [architecture](architecture.md#main-firmware-layout) for the implemented tree.

- November 8 delegated Milestone 1 implementation: main-node source now provides
  strict bounded NDJSON, generated control-profile identity/health, correlated
  errors/replies, five-second ownership, duplicate-command caching/high-water
  fences and an actual bounded asynchronous memory probe with cancel/deadline/
  disconnect/lease cleanup. USB output has one writer, bounded priority queues
  and explicit counters; ordinary application logs are silenced after setup.
  The host recognizes exact diagnostic or main-control schemas, retains observed
  operation results and exposes shared GUI/API/CLI start/cancel controls. Existing
  partial IF-01 checks also accept the main-control profile. No RF/audio/security
  capability is advertised. See [review and acceptance](milestone_1_review.md).
  No flash, reset or physical serial access occurred. These changes remain
  uncommitted and are not the image observed previously on boot 46. Hardware
  acceptance and printed revision remain open.
- November 8 final software verification: `make check` passed **147 tests**
  (including 74 native firmware cases), Ruff, production frontend build,
  generated-contract checks and repository checks. Frontend formatting and Git
  whitespace checks passed. ESP-IDF v6.0.2 built the final main target successfully:
  image size 0x3a4f0 bytes, 77% of its 1 MiB app partition free. The local/default
  main-task stack is 8192 bytes and cJSON depth is eight. One existing
  Starlette/httpx deprecation warning and upstream Kconfig notes remain.
  Final interactive browser QA used a temporary native-C fixture only, with
  fixture-only ports, and verified bounds/completion/cancellation, inspector
  fingerprints/counters and zero visible gaps/drops. A screenshot was captured.
  None of these checks supplies new physical board evidence.

- November 8 serial bring-up: main-node source installs the USB Serial/JTAG
  driver, reads 128-byte chunks with a 20 ms timeout and keeps periodic
  health responsive. Terminal inspection showed received byte chunks while
  health advanced. The user then added a static 4096-byte LF/CRLF line buffer,
  discard-through-LF handling and an oversized-line counter, and reported
  the basic line test working with an explicitly LF-configured monitor.
  The installed monitor defaults to CR for the ESP32 target and converts
  Ctrl+J to CR; parser inspection reproduced that conversion. Manual tests
  use python -m esp_idf_monitor with --eol LF. Oversized-line recovery and
  framing boundary cases remain physically unverified. The delegated implementation
  above supersedes this parser-only stage; cJSON and Milestone 1 control are now
  present in source, with native boundary checks. Firmware remains uncommitted.
- November 7 identity/health follow-up: inspected source and terminal output
  confirm uptime, NVS initialization, a persisted unsigned 32-bit boot counter
  in the existing lora_diag namespace, and device:counter boot IDs. Observed
  boots advanced from 26 to 27, with boot 28 also captured later. During the
  visible 14-second idle health window, uptime advanced by 1,000,000 us per
  sample and memory stayed at 391,631 internal / 2,095,000 PSRAM free bytes.
  Startup also reports project/version/build metadata and a full 64-character
  ELF SHA-256 after setting APP_RETRIEVE_LEN_ELF_SHA=64 in local configuration
  and sdkconfig.defaults. Firmware C and the hash-length defaults change are
  uncommitted user work. CMake now hashes the board-profile JSON and supplies
  BOARD_PROFILE_SHA256 through the compiler command line; the generated compiler
  definition matches the reference file. A subsequent build completed and boot
  30 was observed running health logs. This identifies a reference file, without
  applying its GPIO assignments. Printed revision and structured serial control
  remain open. These are
  bring-up observations, not full milestone 1 or IF-01 qualification.
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
  interrupted USB with Errno 6. This describes the earlier startup image, not the
  later unflashed control implementation above. RF, encryption, replay, ACK/retry,
  timing and audio remain unavailable. USB port names may change.
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
board image. At that checkpoint uptime logging was proposed but not implemented;
the later observations above supersede that implementation status.

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
   work order. Confirm the printed board revision against the reference profile;
   then review and physically validate the implemented control/operation foundation
   using [Milestone 1 acceptance](milestone_1_review.md).
2. Bring up artifact transfer, known-reference speaker playback and microphone
   capture locally. Develop radio/link work alongside audio when the second node
   is available; add host integration with each real capability.
3. Build message transport, security, codec/secure voice, integrated recovery and
   measurement capabilities. Use the experiments to check complete coverage rather
   than creating separate firmware implementations for each experiment.
4. Complete the full physical procedure matrices as capabilities become ready.
   Preserve all 23 entries and their negative/recovery/evidence obligations.

## November 15 — Artifact interface definition (#2)

Defined `artifact_transfer_v1` for the six existing local artifact commands, with
strict arguments/results, four slots, 131072 bytes per file, 262144 reserved bytes
and 1024-byte chunks. Typed examples/checks preserve identical-chunk retries,
CRC/Base64/length validation, PCM counts, cleanup rules and committed lifetimes.
The host blocks missing/mismatched support before serial writes and validates
replies for explicitly advertised support. The three existing wire schemas and
firmware digests remain unchanged. Current firmware still advertises no artifact
transfer; storage, chunk handlers, final commit/readback and audio are not added.
`make check` passed 182 tests (35 new contract/session cases and the existing
74 native firmware cases), Ruff, the dashboard build, generated-contract drift
and repository checks. Frontend formatting, Markdown targets and Git whitespace
checks passed. Nine existing contract/profile/vector/header files are byte-identical
to main. The existing Starlette/httpx warning remains. No physical port was opened
and no board was flashed/reset by this contract work; firmware sources/headers are
unchanged, so an ESP-IDF rebuild was not required.

## November 15 — Bounded artifact reservations (#11)

Main firmware now implements `artifact.begin`, `artifact.list` and `artifact.delete`
through a portable RAM store: four slots, 131072 bytes per file and 262144 reserved
bytes total. Reserve the entire declared size, retain metadata without exposing
unfinished bytes, reject in-use deletion and free temporary reservations on claim
release, lease expiry or detected disconnect. Failed allocations/reply construction
leave existing files unchanged; exact command retries do not allocate/free twice.
Hello/health advertise only these three commands with generated artifact profile
metadata; health reports reserved bytes. Existing wire schemas/digests are unchanged.

`make check` passed **220 tests**, including **112 native C cases** (38 new artifact
cases), Ruff, the production dashboard build, generated-contract and repository
checks. Frontend formatting, local documentation links and Git whitespace checks
passed. ESP-IDF v6.0.2 built the main image: 0x3b3c0 bytes, 77% app-partition free.
All twelve existing contract/profile/example/header files match main byte-for-byte.
The existing Starlette/httpx warning and upstream Kconfig notes remain.

No physical port was opened or board flashed/reset. A native fixture explicitly
seeds committed/failed state only to test store lifetimes and consumer protection;
it does not validate final commit/hash or physical audio. Upload chunks (#14),
commit (#18), readback (#22), host workflow (#26) and RF-session-close integration
remain separate work. See the [walkthrough and checks](artifact_transfer_contract.md#reservation-implementation-and-review-11).
The user delegated remaining M2 implementation one issue/branch/PR at a time, with
small Conventional Commits, explanations and tests. Stop at each review-ready PR;
the user merges and confirms before the next issue starts. Physical checks require
coordination and their own evidence.

## November 16 — Artifact chunk admission (#14)

Added canonical Base64 decoding, CRC-32/ISO-HDLC and bounded contiguous chunk
writes. Matching written ranges can be retried with fresh identities without
rewriting/advancing; gaps, conflicts and partial appends fail unchanged. Writes
follow reply/cache admission, including under injected JSON allocation failures.
`make check`: 240 passed (20 new native cases), Ruff/frontend/contracts/repository
checks passed. Main ESP-IDF build: 0x3c0c0 bytes, 77% partition free. Original
flash backup verified; fresh pre-M2 snapshot running before the first batch flash.
No physical chunk qualification yet. User now authorizes builds/flashes/testing
and all remaining M2 PRs prepared as a stack without waiting for intermediate
merges. This supersedes the prior stop-after-each-PR instruction. All documented
audio wiring is confirmed; user is away, so listening/speech observations remain
for later. Printed board revision is still unobserved.

## November 16 — Verified artifact commit (#18)

Complete RAM bytes are hashed before immutable commit; short uploads remain
unfinished and incorrect final hashes become failed. Private prepared outcomes
are published only after reply/cache admission. Committed files survive release;
failed files require delete/restart. Removed the seeded committed-state fixture:
consumer guards now use actual upload and commit. `make check`: 250 passed,
including 10 new commit cases, lint/frontend/contracts/repository checks. Main
ESP-IDF build passed: 0x3c2c0 bytes, 76% app partition free. Physical validation
awaits completion of the fresh flash snapshot and the cumulative readback image.

## November 16 — Committed artifact readback (#22)

Added bounded reads with actual lengths, canonical Base64, CRC-32 and exact EOF.
Incomplete/failed/deleted files remain unreadable. All six artifact commands are
now advertised; their existing schemas/digests are unchanged. `make check`: 267
passed, including 17 new readback cases; lint/frontend/contracts/repository checks
passed. ESP-IDF build: 0x3c890 bytes, 76% app partition free. Fresh 16 MiB flash
snapshot SHA-256 verified, cumulative image flashed without NVS/eFuse changes.
Physical identity/schema/ELF matched and initial 1/1024/1025/48000/131072-byte
round trips passed. Negative/capacity/recovery checks are still being finalized.
Full M1/audio qualification remains separate; no operator listening is claimed.

## November 16 — Shared host artifact workflows (#26)

Added background upload/download jobs with exact readback length/bytes/SHA-256,
verified-only file persistence, bounded raw evidence/provenance and API/CLI
list/delete/progress/content/cancel. Restart records interrupted work without
resuming it. Cancellation retains the serial write lock until its bounded write
finishes, then cleans up; uncertain cleanup disconnects to release ownership.
`make check`: 290 passed (23 new host cases), lint/frontend/contracts/repository
checks passed. Firmware unchanged from #22. Physical host workflows passed at
1/1024/1025/48000 bytes plus cancellation/cleanup/recovery. Cumulative firmware
checks also passed full 131072-byte readback, raw negative/retry/hash/capacity
cases with zero framing errors/event gaps. Raw reports/stores/backups stay ignored
under local/m2-batch. Full audio/M1 physical qualification remains open.

## November 16 — Node file inspector (#33)

Added upload/list/retrieve/delete and verified host-byte saving in the node detail
view, with live progress, hashes, retained failure/cancel findings and exact
server-computed readiness. Disconnected, unsupported, busy, incomplete and in-use
actions are gated. Fixed a browser-observed fast-completion refresh race and
ignore stale list responses. `make check`: 293 passed; frontend build/format and
repository checks passed. Actual browser/node upload/retrieve/save at 1025 bytes
matched exact hash/bytes; invalid-ID failure, 131072-byte upload cancellation at
4096 bytes with cleanup, deletion, offline gating/history and reconnect passed.
QA server stopped and port released. Artifact image ran with advancing health and
zero observed gaps/framing errors through roughly six hours before intentional
reconnect; this is limited observed control evidence, not full M1/audio closure.
Screenshot: Codex visualization m2-file-inspector.png. Next is #23 playback.

- November 16 #23: implemented explicit per-board finite local PCM playback, committed-file pinning, fixed 1/8 software amplitude, configured 6 dB hardware gain, DMA completion/source counts and bounded stop/ownership cleanup. Separate audio supplement preserves existing schema digests. Full checks passed 310 tests with no skips, lint/frontend/contracts/repository checks; audio-enabled IDF build passed. Physical hearing, printed revision and instruments remain unobserved. See [audio behavior and checks](node_audio.md).

- November 16 #24: finite INMP441 left-slot capture converts 24-bit input to signed-16-bit LE without added gain, discards declared startup frames and publishes only complete hash-committed PCM. Capture failures/cancel stop DMA then remove partial reservations. Full checks passed 336 tests (43 audio), no skips, plus lint/frontend/contracts/repository; IDF image 0x43e90 with 73% free. Cumulative identified-board playback/capture counts, independent hashes, sequential/cancel/recovery passed on boot 60 with zero observed framing errors/event gaps. Printed revision, speech response, listening and instruments remain pending. See [audio checkpoint](node_audio.md).

- November 16 audio signal finding: inspecting captured PCM revealed all-zero samples. A minimal physical probe reproduced it; raw left/right slots were also zero after startup, so conversion/slot selection alone does not explain the observation. DMA counts/hashes pass but microphone response is unverified. Raw counters and evidence are retained. Physical supply/ground/data/clock/breakout investigation and speech/listening remain pending; #42 must stay incomplete.

- November 16 #32: shared physical audio jobs now expose capture/play/retrieve/stop through API/CLI, reuse verified file downloads, wrap unchanged PCM as WAV, inspect count/hash/waveform/silence/clipping and retain separate operator listening notes. Cancellation, lost-result idle reconciliation, live capability loss and interrupted restart preserve errors/evidence. Full checks passed 360 tests, including 24 new host cases, no skips; lint/frontend/contracts/repository checks passed. Actual host 24000-sample WAV/hash, explicit all-zero warning, quiet playback driver completion, cancel and recovery passed. Microphone response remains unverified. See [host audio workflow](node_audio_workflows.md).

- November 16 #38: node inspector now exposes shared local capture/play/stop, verified waveform/count/hash/silence/clipping findings, file playback/WAV inspection and separate listening notes/laptop preview. Busy/unsupported/previous-boot controls gate explicitly; reconnect starts with fresh health age. Full checks passed 361 tests (25 host audio), no skips, plus final frontend build/format. Real-board browser capture/play/cancel/error/recovery and actual disabled-firmware gates/history passed; audio image restored and port released. WAV endpoint bytes verified; in-app download location, light/mobile visual QA and acoustic/electrical qualification remain unconfirmed. See [UI check steps](local_audio_ui.md).

## November 22 — Radio dashboard (#34)

Experiments → IF-02 now exposes the shared one-message radio backend with live
preflight, start/stop, direction/modem settings, exact byte/hash findings, actual
receiver signal, retained history and evidence downloads. Missing peers, occupied
bench and invalid settings disable start. Full IF-02 and hardware qualification
remain pending. Browser checks used isolated real C cores with test-only serial/
SPI boundaries; both directions, missing observation versus verified bytes,
shared ownership, cancellation/idle cleanup, missing peer and light/dark/mobile
layout passed. Corrected a narrow-screen experiment grid overflow. No physical
port was opened.

`make check` passed 424 tests without skips plus lint, production frontend build,
generated contracts and repository checks; frontend format check passed.

## November 22 — Fragment planning (#28)

Added bounded, allocation-free packet planning and exact 40-byte header/body
encoding at 65,536 useful bytes/4,096 fragments, with sequence exhaustion checks
and 199-byte protected capacity. Existing single-frame encoding uses this public
module. Protected headers reserve a full tag; complete protected output remains
unavailable until GCM exists. Boundary/max/rejection checks compare independent
wire vectors and exact reconstructed bytes. Operator execution is still limited
to one fragment pending reconstruction and scheduling. No board is connected.
See [limits and checks](radio_fragments.md).

`make check` passed 435 tests without skips, lint, frontend build, contracts and
repository checks. The selected-board ESP-IDF build passed (0x51100-byte image,
68% app partition free); no flash or physical serial access occurred.

## November 22 — Bounded receiver reconstruction (#35)

Added opaque one-message reconstruction with fixed session/roles/expected hash,
bounded allocation/deadline, exact missing-index pages, reorder/duplicate handling
and once-only hash-verified output. Failures/cancel scrub and release bytes while
retaining missing indexes; old IDs cannot restart. Late conflicting packets leave
already borrowed delivered bytes valid. Existing single-frame reception now uses
the canonical multi-fragment parser. Multi-fragment scheduling/advertisement and
physical RF acceptance remain pending. See [reconstruction](radio_fragments.md).

`make check` passed 447 tests without skips plus lint, production frontend build,
contract and repository checks. Selected-board ESP-IDF build passed (0x511e0-byte
image, 68% app partition free). No physical port was opened.

## November 22 — Referenced ACKs (#40)

Added canonical ACK matching and a bounded receiver scheduler with fresh ACK
sequences, one pending response, 16 exact frame-hash cache entries and a declared
retry horizon. Wrong/unknown/stale references cannot match; replay classification
never schedules ACK. An eligible identical retry re-ACKs without another insertion
or delivery. Protected ACKs and full operator ACK/retry support remain unavailable
until security/scheduler integration. See [reliability](radio_reliability.md).

`make check` passed 452 tests without skips plus lint, production frontend build,
contract and repository checks. Five ACK-focused cases also passed after aligning
the cache test's timestamps monotonically. Selected-board ESP-IDF build passed;
no flash or physical serial access occurred.

## November 22 — Bounded stop-and-wait sender (#43)

Added a real-radio-backed sender that copies immutable originals, applies
applied-modem airtime deadlines and zero/one/two retry limits, validates exact ACK
references and reports attempts separately from originals. Cancellation at every
phase stops further work; exhaustion leaves the radio reusable. Source/session
sequence high-water state rejects restarts, and both undrained TX/RX observations
remain readable after bounded deadline cleanup. Nineteen focused public cases
pass. Multi-fragment execution/capability wiring and physical acceptance follow
in #47; no ESP is connected. See [reliability](radio_reliability.md).

`make check` passed 471 tests without skips, lint, production frontend build,
contract and repository checks. Selected-board ESP-IDF build passed. All 19 hashes
from the original checkout's preserved local changes still match; no flash or
physical port access occurred.

## November 22 — Soldered protoboard audio follow-up

The user connected Node A (`esp-a4cb8fa21878`, boot 25) after soldering the
protoboard and confirmed the original GPIO map. Using its existing
`b96c0ca-dirty` audio image (build `a5ecf08a0ce76daf85ae05f49464c549c2b094cb7a241048bd5bb5e35acf3041`),
with no flash/reset, three-second capture/readback produced 24,000 varying
signed-16 samples at configured 8 kHz. PCM length/hash matched independently;
RMS was 2375.69, extrema -5865/7213, with no clipping or reported overflows.
The user confirmed recognizable speech in laptop playback. This replaces the
earlier all-zero microphone response finding for this assembly.

The user then found an unsoldered amplifier VIN-to-3V3 connection and repaired
it with USB disconnected. On reconnect (boot 27), the lower-level reference was
not heard, but a three-second 2 kHz reference with source peak 24,000 was clearly
audible. Fresh raw speech was recognizable on the laptop, yet inaudible on the
node. A separate high-pass/boosted/soft-limited diagnostic copy produced audible
but faint or distorted speech. This supports the local audio path; intelligible
node playback and full audio qualification remain pending. DSP processing may
contribute to the diagnostic copy’s distortion.

Retaining four 48,000-byte artifacts reproduced two driver-start allocation
failures: the largest internal block was 90,112 bytes versus a 96,000-byte output
buffer. After removing three independently backed-up older test files, the same
recording played to completion with zero underflows. This is an operational
workaround; bounded playback buffering/level control still needs improvement.
Raw jobs, metrics and private recordings remain ignored under the original
checkout’s `local/audio-qualification/2026-11-22-protoboard-01`. No new RF image
was installed and no physical RF result is claimed.

## November 22 — Multi-fragment shared runs (#47)

One-message radio execution now composes the bounded packet modules and supports
up to 65,536 bytes/4,096 fragments, optional stop-and-wait with zero/one/two
retries, explicit preparation budgets and safe terminal cleanup. The shared
API/CLI/dashboard independently verify source/recovered bytes and reconcile DATA
originals, attempts, accepted fragments, delivery and ACK traffic. Telemetry gaps
leave byte verification visible but dependent accounting incomplete; missing-index
reports require every numbered part and matching receiver totals. See
[review commands and hardware obligations](physical_radio_runs.md).

`make check` passed 501 tests without skips, lint, production frontend build,
generated contracts and repository checks. The only warning is the existing
Starlette/httpx deprecation. Physical RF qualification remains pending.

Selected-board ESP-IDF build passed (0x53300-byte image, 68% app partition free);
frontend formatting passed. Browser checks on isolated C serial/SPI fixtures
verified both directions, a three-fragment ACK/retry run, exact missing index 0
after dropped DATA, over-limit rejection, history, light/dark appearance and
390-pixel layout without horizontal page overflow. No console errors or warnings
were observed. The final screenshot is an ignored Codex visualization named
`multi-fragment-radio-software-fixture.png`; it is not physical RF evidence.

## November 22 — Session-security contract (#44)

[Session security](security_sessions.md) now maps the selected key/nonce/header
contract to existing APIs, inventories secret fields and future persistence
guards, separates retry duplicates from replay, and defines cancellation/
exhaustion/retirement behavior. Protected DATA/ACK/ECHO and final-sequence public
examples have independent AES-GCM encryption/decryption checks, including every
AAD byte, ciphertext/tag mutation and wrong nonce/source key. The test oracle
is dev-only Cryptography 50.0.2; fixed public keys are not production provisioning.

A new public NodeSession regression reproduced rejected key values appearing in
validation-error text. Session argument errors now omit supplied values before
trace/error persistence; the regression passed after the fix. This does not
implement successful protected provisioning. Current schema/capability gates
still accept only unprotected sessions with null keys.

`make check` passed 511 tests without skips, lint, frontend build, generated
contracts and repository checks; the existing Starlette/httpx deprecation remains.
No firmware behavior or wire digest changed, so no new IDF build or physical
access was needed. GCM/session lifecycle/replay/host provisioning and physical
security qualification remain the following issues.

## November 22 — Authenticated-frame primitive (#48)

`security/frame_crypto` now imports volatile non-exportable AES-128 PSA handles,
seals exact protected frames and verifies into private scratch before returning
plaintext. Full 40-byte AAD, 12-byte header-derived nonce and 16-byte tag are
explicit. Temporary buffers are scrubbed; failed output is unchanged with zero
written bytes, and failed key destruction preserves ownership for recovery.
No public test key is built into the primitive. See [frame cipher](frame_crypto.md).

Ten native checks link the actual pinned IDF crypto source and cover all public
DATA/ACK/ECHO/max-sequence vectors, every changed frame byte, wrong source key,
valid recovery, empty ACK and buffer/key-owner bounds, plus 200 import/destroy
cycles. The first known-answer check was observed red before implementation.
The complete suite passed 521 tests without skips. A lint-only CMake-string
line length was corrected; the focused cipher checks and remaining lint/
frontend/contracts/repository stages then passed. The selected-board IDF build
passed (0x53300 bytes, 68% app partition free), without flashing.

Current sessions still accept only unprotected mode and report `security_gcm`
false. Key/nonce ownership, replay, host provisioning and physical acceptance
remain pending; native software crypto does not validate ESP acceleration/timing.

## November 22 — Owned keys and nonce lifetime (#52)

Firmware now binds separate private source key handles and monotonic sequence
reservations to owned run/session/role state. Close, stop, lease loss, disconnect
and controller reset retire readiness and keys; stale cached setup success cannot
recreate old state. Final-sequence reservation/encryption cannot wrap or repeat.
Temporary decoded keys, raw records and all owned JSON allocations are wiped,
including parser rejection, allocation failure and unfinished input at lease loss.
See [session lifecycle](session_key_lifecycle.md).

Public-boundary regressions were observed failing before their fixes for nonce/
setup ownership, parser deallocation and retained partial input. The focused
lifecycle/owner/host-gate checks pass 19 cases; 160 allocation-failure positions
and a real exhausted native key store exercise cleanup. The final `make check`
passed 539 cases without skips, lint, frontend build, contracts and repository
checks. The existing Starlette/httpx deprecation remains. Selected-board IDF
build passed (0x5b830 bytes, 64% app partition free), without flashing.

The execution vocabulary/digest changed with the selected protected setup shape;
main-control/diagnostic/artifact/audio digests did not. Protected RF and ordinary
host provisioning remain explicitly blocked; `security_gcm` stays false. Key
byte freshness is the trusted host’s OS-CSPRNG responsibility in #63, not a claim
that the node proves randomness or detects every cross-boot reuse. Physical
security, resource headroom and timing remain pending. Original 19 local-file
hashes still match the preservation snapshot.

## November 22 — Checked local crypto measurements (#53)

Added a bounded public-vector single-node benchmark with separately checked first
calls, 50 warm-ups and requested timed samples for encryption, decryption, invalid
tags and copy baseline at 16/64/160/199 bytes. Actual platform timestamps enclose
one-shot PSA calls; setup, output checks and USB/RF stay outside. The additive
profile, shared API/CLI, raw evidence and independent completeness assessment
preserve partial counts and block distributions after cancellation/sample loss.
Full `make check` passed 556 cases without skips, lint/frontend/generated-contract/
repository checks; the selected-board IDF image is 0x641a0 bytes with 61% app free.
No flash or physical benchmark occurred. Three batches per size per physical node
and target acceleration/resource qualification remain pending. All 19 preserved
files in the original checkout still match their hashes. See
[review and physical instructions](crypto_benchmark.md).

## November 22 — Protected replay and retry acceptance (#60)

The owned source-key context now authenticates before a 128-frame replay window
and commits only successful metadata/insertion policy. A 16-entry accepted-DATA
hash cache allows fixed-horizon exact retry re-ACKs, without second insertion or
delivery. Protected node execution retains sealed DATA for exact retries and
creates fresh referenced ACKs using the local source owner. Structural header
inspection never exposes ciphertext as plaintext; budgets/RX limits include tag
overhead and 56-byte ACKs. Available selected radios now advertise node GCM
support; shared host provisioning remains gated pending #63.

Full `make check` passed 562 cases without skips, lint/frontend/contracts/repository
checks; selected-board IDF build passed (0x65390 bytes, 60% app free). Six focused
window/node cases include a two-C-node lost-ACK exchange with one delivery and
independently identical recovered bytes/hash. No physical port or flash was used.
All 19 preserved original-checkout files still match. Physical #67 and protected
host provisioning remain open; see [review and validation](protected_replay.md).
