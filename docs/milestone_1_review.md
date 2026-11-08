# Milestone 1 review and physical acceptance

Updated November 8, 2026. The user delegated the remaining Milestone 1 software
implementation for review after returning. The user subsequently requested scoped
Conventional Commits for all the work. No board was flashed, reset or connected
by these implementation and cleanup tasks. The currently running
board image therefore does not contain these new control features.

**Software implementation is ready for review. Milestone 1 hardware acceptance
remains open.** Native checks execute the actual C control engine with a test clock,
heap and serial transport. They do not measure ESP32 timing, USB reconnection,
PSRAM stability or electrical behavior and do not qualify IF-01.

## Implemented checklist

- [x] ESP-IDF target composition, native USB transport and a single protocol writer.
- [x] Factory-MAC device ID, persisted NVS boot count and per-boot identity.
- [x] Reset cause, firmware/build/ELF fingerprint and board-reference fingerprint.
- [x] Actual internal/PSRAM free, boot minimum and largest-block queries.
- [x] Structured one-second health, current role/activity/operation and counters.
- [x] One image supports host-assigned A or B; identity is independent of role.
- [x] 4096-byte records including LF; CRLF, partial/multiple records and oversized recovery.
- [x] Strict UTF-8/JSON grammar, full consumption, depth eight and duplicate-key rejection.
- [x] Reject raw/escaped NUL, invalid surrogates, nonfinite numbers and invalid numeric syntax.
- [x] Exactly nine command fields; case-sensitive names, UUIDs, boot IDs and strict integer types.
- [x] Exact supported command arguments; correlated replies and structured errors.
- [x] `hello`, `status.get`, claim/keepalive/release and explicit capability gating.
- [x] Single owner with five-second lease and stale-boot rejection before side effects.
- [x] SHA-256 fingerprints, 16 cached mutating replies and changed-command conflicts.
- [x] Per-client high-water sequence fences survive release/expiry within the boot.
- [x] One finite asynchronous operation, progress through health and a terminal result event.
- [x] Actual memory-probe write/read verification, deadline, cancellation and bounded cleanup.
- [x] No automatic operation resumption after disconnect, lease loss or reset.
- [x] Bounded reply/event queues, reply priority, event sequence gaps and explicit drop counts.
- [x] No ordinary application logs on the protocol stream after initialization.
- [x] Separate generated main-control schema; original diagnostic/execution digests unchanged.
- [x] Existing host connection and partial serial procedure accept either exact known schema.
- [x] Dashboard, API and CLI start/cancel the same physical-session memory operation.
- [x] Host shutdown requests stop before release; reconnect preserves client sequence order.
- [x] Native software checks cover boundaries, invalid input, ownership, duplicates and recovery.

## Read the code in this order

1. `firmware/lora_node/main/lora_node.c`: composition only. It initializes the
   platform, creates the control engine and starts USB transport.
   `platform/esp32_platform.c` owns identity/NVS/heap/crypto callbacks and metadata
   lifetime; `transport/usb_transport.c` owns USB reads and the single writer.
   Bring-up information travels through `hello`/health rather than human-readable logs.
2. `firmware/lora_node/main/protocol/strict_json.c`: UTF-8 and grammar checks before cJSON,
   duplicate-key checking and integer-token tracking. cJSON alone accepts inputs
   outside the selected contract. Escaped NUL is rejected to avoid C-string aliases.
3. `firmware/lora_node/main/control/node_control.c`: framing, validation, owner/sequence/cache
   state, telemetry and cooperative diagnostic work. The public header exposes only
   feed/tick/output/link and platform callbacks; no ESP-IDF dependency is needed by
   the core's native tests.
4. `testbed/src/lora_testbed/control_v2.py`, `nodes.py`, `adapters.py`: generated
   control profile, exact schema negotiation, reply correlation and observed results.
5. `host.py`, `app.py`, `cli.py`, `frontend/src/HardwareBench.tsx`: one backend
   operation path used by GUI and CLI. Recorded command/reply observations and node
   terminal events are retained in the existing local store.
6. `testbed/tests/test_node_control_native.py`: actual C compilation, isolated serial
   fixtures and production session/API/procedure tests. The native cJSON allocation
   shim is test-only and is not linked into firmware.

## Limits and behavior

| Resource | Current limit / behavior |
| --- | --- |
| Record / JSON depth | 4096 wire bytes including LF / eight container levels |
| USB read | 128-byte chunk, up to 20 ms wait, one scheduler-tick yield |
| Reply / event queues | Four / eight queued records; replies drain first |
| Duplicate cache | 16 mutating-command replies, each less than 1024 encoded bytes |
| Client sequence table | 16 distinct successful claim clients per boot; no unsafe eviction |
| Owner lease / host renewal | Five seconds / one second |
| Diagnostic | Only `memory_probe`; 1–10000 iterations, 1–65536 bytes |
| Work per tick | At most 512 bytes written or checked; no busy wait |
| Operation deadline | 30 seconds, returned in node uptime; large requests can time out |
| Main-task stack | 8192 bytes, configured in defaults and local build |

The memory probe writes a deterministic pattern into a real temporary allocation,
then verifies every byte. Completed iterations and verified bytes are actual core
work, not a placeholder delay or a counter-only diagnostic. Cancellation, failure,
lease loss and disconnect free the buffer. The cooperative loop is asynchronous
with respect to commands; this milestone does not add a second operation worker.

A terminal event may be dropped if the bounded event queue is full; drops/gaps
remain visible and must invalidate evidence where required. Host health reconciliation
can recognize return to idle, but never fabricates a missing terminal result.

Client sequence fences are retained for the boot, including after lease expiry.
The host keeps its monotonically increasing sequence across reconnects. After 16
*different* backend client IDs successfully claim in one boot, another new client
gets `RESOURCE_LIMIT`; an existing client can still reclaim with a fresh sequence.
A deliberate board reset is the documented way to clear that bounded table.

USB SOF detection identifies cable/host-bus loss. Closing a serial program does not
necessarily remove SOF packets; a missed keepalive then causes five-second expiry.
Measured disconnect and cleanup latency remains a physical acceptance item.

Radio, audio, artifacts, encryption, replay checks, ACK/retry, clock calibration,
`serial_echo` and `crypto_benchmark` remain unavailable. No RF-front-end or audio
GPIOs are driven by this milestone. The printed board revision is reported as null.

## Verification performed

- Final ESP-IDF v6.0.2 main target build passed: 0x3a560-byte image after the module reorganization, 77%
  free in its app partition. No flash was performed.
- Final `make check` passed **147 tests**, including **74 native cases**, plus
  lint, production UI build, generated-contract and repository checks. Frontend
  formatting and Git whitespace checks also passed. The existing Starlette/httpx
  deprecation warning and upstream Kconfig notes remain.
- Native boundary and failure checks include LF/CRLF limits, oversized recovery,
  byte-at-a-time input, invalid UTF-8/numbers, eight/nine-level nesting, changed
  duplicates, cache eviction, expired claims, new boots, corruption, allocation
  failure, operation completion/cancel/lease/disconnect/deadline cleanup and queue pressure.
- 1000 valid/invalid record cycles left no tracked cJSON allocations. Failure was
  injected at 160 successive JSON allocation positions without an unacknowledged
  operation starting or a temporary probe buffer leaking.
- Browser interaction against a separate native-core fixture on a temporary local
  backend verified disabled invalid inputs, completed probe output, cancelled probe
  output and continued health with zero visible gaps/drops. This was test-fixture
  browser QA, not a physical-node measurement. The final inspector was checked
  against the final build with fixture-only ports; a screenshot was captured for
  the review handoff.

## Build and review

From the repository root, in an activated ESP-IDF shell:

```sh
idf.py -C firmware/lora_node build
make check
npm --prefix testbed/frontend run format:check
```

Native tests require the local C compiler and the locked IDF-managed cJSON source
(downloaded by the firmware configuration/build). When unavailable, those tests
explicitly skip; a skip is not native verification. On macOS the tests use
`xcrun --sdk macosx clang` to keep compiler and SDK matched.

After reviewing, close IDF Monitor and release any host connection before an
operator-authorized flash. Rediscover the current port; its path can change.
Do not erase NVS. The same `lora_diag` boot counter is preserved across images.
No flash command was executed by this task.

Then start the normal host with `make serve`, connect one physical role, and open
**Inspect node → Local memory probe**. CLI equivalents use the same running backend:

```sh
uv run --project testbed lora-testbed memory-probe A --iterations 10 --payload-bytes 4096
uv run --project testbed lora-testbed status
uv run --project testbed lora-testbed operation-stop A OPERATION_UUID
```

Do not run IDF Monitor and the backend on the same port. Manual NDJSON tests need
`python -m esp_idf_monitor --eol LF` with the target/port/ELF options from earlier
bring-up, or an explicit serial test tool; default ESP32 monitor input is CR.

## Physical acceptance checklist — still open

- [ ] Read the printed board revision and compare its schematic/pin map.
- [ ] Review and deliberately flash this new image; verify device, boot and fingerprints.
- [ ] Run real host hello/claim/status/keepalive/release with one node in A, then B.
- [ ] Observe structured health, internal/PSRAM behavior and no application-log corruption.
- [ ] Exercise valid/invalid/maximal/oversized NDJSON over real USB and retain recovery evidence.
- [ ] Exercise identical retries, changed duplicates and stale boot targets over real USB.
- [ ] Complete and cancel real memory probes; check released buffers and responsive control.
- [ ] Test deadline and lease loss, close/reopen serial, USB unplug/replug and board reset.
- [ ] Confirm reconnect always starts idle and requires fresh control; measure actual latency.
- [ ] Retain identities/configuration/raw records and run the existing partial IF-01 check.

Only this observed hardware evidence can close Milestone 1. Full IF-01 procedure
qualification is a separate, larger gate and remains open.
