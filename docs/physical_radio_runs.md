# One-message physical radio bring-up

The shared backend now configures two owned, compatible physical nodes, prepares
both, waits for receiver-ready, arms and starts the sender and verifies actual source and
recovered bytes. This workflow checks one unencrypted known-data message with
bounded fragmentation and optional stop-and-wait retries. Full IF-02, GCM and
voice-over-radio qualification remain separate. The node's advertised limits and exact execution/artifact
profiles are checked before work starts.

## Operate through the backend

Run from a checkout containing the radio implementation stack. The current
isolated development checkout is `~/Documents/ESP_LoRaLab-milestones`; the original
checkout and its 19 local changes are preserved. Start `make serve`, connect two
identified nodes in Bench, then use the CLI against that same backend:

```sh
uv run --project testbed lora-testbed radio-start --preview
uv run --project testbed lora-testbed radio-start --direction A_TO_B --message-bytes 159
uv run --project testbed lora-testbed radio-status
uv run --project testbed lora-testbed radio-status RUN_UUID
uv run --project testbed lora-testbed radio-stop RUN_UUID
uv run --project testbed lora-testbed radio-export RUN_UUID ./radio-evidence.zip
```

Use `--direction B_TO_A` for reversal. `--config request.json` supplies the complete
request instead of quick CLI flags; the shape is `direction`, `message_bytes`,
`source_seed`, `timeout_ms`, `radio` and `link`. Radio/link use the shared v2 names.
Defaults are 915 MHz, SF7, BW125 kHz, CR4/5, configured SX1262 power 2 dBm, one
64-byte message and a 10-second window. Power is a setting before the external
front end, not calibrated antenna power. The run accepts 1–65,536 message bytes,
up to 4,096 fragments and a 1–3,600,000 ms window, subject to both nodes’ current
advertised limits. The budget includes applied-modem airtime, processing, ACK/
retry waits, receiver drain and one-second headroom; short windows reject before RF.
Drain is at least two seconds and covers the last original’s complete retry
horizon. Enable `link.ack_mode = "stop_wait"` and choose `link.max_retries` 0, 1
or 2 in the config; disabled ACKs require zero retries.

With no boards connected, preview explains the disconnected nodes and start
rejects. No port is opened by preview, status or export. Firmware still needs
explicit matching [board selection](radio_driver.md) before real use; the printed
revision remains unconfirmed, and standard V4.3 RF conflicts with the old GPIO5
microphone profile. Antenna/band/supply/wiring validation is still required.

## Dashboard

Open Experiments, select IF-02, and use the known-data radio panel. Direction,
message length, modem settings, ACK mode, retry limit and the run window use the same backend preflight
as the CLI. Start stays disabled with explicit blockers for a missing/incompatible
peer, invalid settings, an offline backend or an occupied bench. Stop targets the
active job even while a previous result is selected.

History separates exact byte verification, evidence completeness and pending
hardware qualification. Signal comes only from retained receiver observations.
Expand a record for requested/applied settings, node identities and summaries;
downloads appear only for files that actually exist. The full IF-02 procedure
remains separately pending.

## Evidence and outcomes

Each run preserves device/boot identities, firmware and host source fingerprints,
session ID, requested/applied settings, calculated budget, raw command/reply/event
records, node summaries, readback manifests and independently compared files.
Events retain node-local clocks; host timing only establishes command order.
Receiver-ready must precede sender arm/start; the conservative host interval
from receiver arm request through sender start reply must stay below five seconds.
The sender also enforces its own five-second local arm. See
[run lifecycle](run_lifecycle.md). Applied settings, session/revision attribution
and expected source hashes must agree before successful completion is reported.

`verification.bytes_equal` proves that actual retrieved source/recovered bytes
match the independent source recipe. Evidence completeness is checked separately:
a missing RX observation can fail the run while the verified bytes remain visible.
Missing telemetry is never automatically called RF loss. RSSI/SNR are taken only
from observed RX records, never calculated for a missing frame. No software case
automatically sets `hardware_qualified`.

The export contains the run, source/recovered files when available, RF NDJSON,
linked artifact-transfer records/traces and a SHA-256 manifest. It is bounded to
128 MiB; RF trace retention is bounded to 64 MiB/65,568 event observations.
Reaching a bound makes the affected evidence incomplete rather than fabricating
a result. Live snapshots contain compact summaries, while the detail
endpoint retains the complete record. Committed node files are not silently
evicted: export first, then delete only the generated files you no longer need,
using the node file inspector or `artifact-delete ROLE ARTIFACT_UUID`. Four slots
per node remain the artifact-profile ceiling.

Stop and failure cleanup attempt bounded stop/close on both associated sessions
and confirm idle. An attempted session-open is tracked before writing, so a lost
reply cannot leave an untracked session. Failed evidence writes do not block safety
commands. Stop waits for cleanup already in progress; cancelled callers cannot
cancel the worker's cleanup. Unconfirmed cleanup disconnects ownership and stays
explicit. Restart marks interrupted work and never reconnects/resumes it.

## HTTP and review entry points

- POST `/api/radio/preflight`, POST `/api/radio/runs`.
- GET `/api/radio/runs`, GET `/api/radio/runs/{id}`.
- POST `/api/radio/runs/{id}/stop`.
- GET `/api/radio/runs/{id}/content/{source|recovered|wire}` and `.../export`.

Read `radio_runs.py` for ownership/lifecycle/evidence, `Host.start_radio` for the
shared bench fence, then the small HTTP/CLI callers. `NodeSession` requires exact
capabilities, typed RF envelopes and known-run attribution; its read-only summary
retries use fresh command IDs/sequences.

## Software checks and later physical acceptance

Run `uv run --project testbed pytest testbed/tests/test_radio_runs.py -q`, then
`make check`. The host cases exercise two real C cores through test-only serial/
SPI boundaries: both directions, exact bytes and hashed exports, missing/duplicate
peers, configuration mismatch before arm, absent observations, immediate/during-
write/during-cleanup cancellation, caller cancellation, timeout, disconnect,
evidence failure, restart without resume and shared HTTP/CLI behavior. Native
fixture deadlines use injected node time. These are software checks, not radios.

Later, identify both actual boards and antennas, select the matching firmware
profile, repeat local control acceptance and keep placement/settings fixed. Run
1/159/160-byte checks in both directions, export each result and compare exact
files/hashes, actual CRC/signal, timeout and stop/idle recovery. Record printed
revision, USB identity, firmware/build/profile and antenna/supply observations.
Missing evidence remains pending; this bring-up alone does not close the complete
IF-02 matrix. These checks do not exercise physical RF. A separately connected audio node
retained its existing audio image and was not used for this implementation.

November 22 browser verification used two real C cores behind test-only serial/SPI
boundaries on an isolated localhost server. Both directions and 1/159/160-byte
records, missing RX observation with verified bytes, shared-API bench exclusion,
stop/idle cleanup, invalid size, missing peer, light/dark and 390-pixel layout
passed. A mobile grid overflow was found and corrected. No console errors or
warnings were observed. These are software fixtures, not physical RF results.

## Multi-fragment accounting and review (#47)

`radio_accounting.py` independently matches retained records with both node
summaries. Confirmed DATA originals, all DATA attempts, retries, unique accepted
fragments, delivered messages and ACK transmissions are separate totals. A retry
uses the original’s exact bytes and identity; it never enlarges the original-
packet denominator. Three delivered fragments with one retry therefore mean
three originals, four DATA attempts and 100% unique-original delivery.

Source and recovered bytes are independently read back and compared before
accounting. Losing an `rx.accepted` record can leave verified bytes visible while
accounting becomes incomplete. A failed message preserves exact missing-index
pages only when every numbered part and the receiver totals reconcile; a lost
part never supplies guessed missing indexes. These indexes describe receiver
insertion, not a diagnosis of RF loss versus framing, telemetry or other loss.

Read `radio/rf_execution.c` for module composition, bounded preparation, actual
radio observations and terminal cleanup; then `radio_runs.py` for shared host
ownership/readback and `radio_accounting.py` for the independent checks.
`frontend/src/RadioLink.tsx` presents the same results and backend readiness.

Run from the repository root:

```sh
uv run --project testbed pytest testbed/tests/test_multi_fragment_radio.py testbed/tests/test_rf_execution_native.py testbed/tests/test_radio_runs.py -q
make check
npm --prefix testbed/frontend run format:check
idf.py -C firmware/lora_node build
```

Expected: exact 161/321-byte messages in both directions and the 65,536-byte
maximum, lost-DATA/lost-ACK recovery with once-only delivery, maximum-plus-one
and excessive retry rejection before arming, exact paged missing evidence, and
stop/lease/disconnect cleanup. Native maximum reporting covers 2,048 missing
indexes across 32 pages without committing a partial artifact. The isolated
fixture pumps actual C node cores independently of the host event loop; its
20 ms SPI/IRQ scheduling allowance is not an RF propagation or timing model.
Physical acceptance must repeat boundary/max messages, losses, cancellation and
recovery on two identified, compatible boards with matched antennas.

The November 22 follow-up browser check passed 321-byte A→B with ACK/retries
(three originals, five observed attempts, two retries and one delivery), 161-byte
B→A without ACKs, a deliberately dropped DATA frame reporting exact missing
index 0, maximum-plus-one rejection and history. The 390-pixel light layout had
no horizontal page overflow; dark appearance and the default viewport were
restored. No console errors/warnings were observed. These are isolated software
fixture results, not physical loss or timing measurements.

## Protected sessions (#63)

The same receiver-first backend now supports AES-128-GCM with fresh per-source/run
keys, safe setup evidence, verified readback and separate RF/authentication/ACK
observations. Follow [protected host sessions](protected_host_sessions.md) for the
31-case focused command, matching execution fingerprint, GUI/CLI review and
remaining physical checks. Keys are never operator inputs or saved evidence.
