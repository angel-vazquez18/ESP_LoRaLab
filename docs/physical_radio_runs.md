# One-message physical radio bring-up

The shared backend now configures two owned, compatible physical nodes, prepares
both, waits for receiver-ready, starts the sender and verifies actual source and
recovered bytes. This workflow checks one unencrypted known-data fragment; it does
not qualify the complete IF-02 procedure or pretend to support fragmentation,
retries, GCM or voice. The node's advertised limits and exact execution/artifact
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
front end, not calibrated antenna power. The existing budget includes a two-second
drain allowance and one-second headroom; too-short windows reject before RF.

With no boards connected, preview explains the disconnected nodes and start
rejects. No port is opened by preview, status or export. Firmware still needs
explicit matching [board selection](radio_driver.md) before real use; the printed
revision remains unconfirmed, and standard V4.3 RF conflicts with the old GPIO5
microphone profile. Antenna/band/supply/wiring validation is still required.

## Evidence and outcomes

Each run preserves device/boot identities, firmware and host source fingerprints,
session ID, requested/applied settings, calculated budget, raw command/reply/event
records, node summaries, readback manifests and independently compared files.
Events retain node-local clocks; host timing only establishes command order.
Receiver-ready must precede sender start, whose reply must arrive within one
second. Applied settings, session/revision attribution and expected source hashes
must agree before successful completion is reported.

`verification.bytes_equal` proves that actual retrieved source/recovered bytes
match the independent source recipe. Evidence completeness is checked separately:
a missing RX observation can fail the run while the verified bytes remain visible.
Missing telemetry is never automatically called RF loss. RSSI/SNR are taken only
from observed RX records, never calculated for a missing frame. No software case
automatically sets `hardware_qualified`.

The export contains the run, source/recovered files when available, RF NDJSON,
linked artifact-transfer records/traces and a SHA-256 manifest. It is bounded to
2 MiB; RF trace retention is bounded to 1 MiB/128 event observations for this
single-message subset. Live snapshots contain compact summaries, while the detail
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
`make check`. The 16 new cases exercise two real C cores through test-only serial/
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
IF-02 matrix. No ESP was connected during this implementation.
