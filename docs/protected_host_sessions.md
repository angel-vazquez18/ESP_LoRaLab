# Protected physical-session workflow (#63)

The shared backend, dashboard and CLI now accept `security:none` or
`security:aes128_gcm` for a finite known-data message. Protected runs require two
distinct, owned nodes with fresh matching execution capabilities and GCM support.
They use the same receiver-first preparation, real file readback, byte/hash
verification, evidence and cleanup path as unprotected runs. Software fixture
checks do not qualify physical security or add an operator simulator.

## Firmware and host responsibilities

Firmware authenticates DATA before replay/insertion and authenticates referenced
ACKs before sender completion. It retains sealed DATA for exact retries and emits
fresh ACKs for eligible duplicates. The source-key owner and replay state remain
RAM-only and are retired by close, stop, ownership loss or reset. #63 adds
`ack.result` with `status:received` **after** successful ACK acceptance, separating
it from a raw `rx.frame` observation. No ACK acceptance is inferred from a parsed
header or a CRC-valid arrival alone.

The host generates independent 16-byte OS-CSPRNG source keys after both nodes
confirm the requested modem/link settings. A's TX key is B's RX key and vice versa;
direction never changes source ownership. A random key-set ID is independent of
both keys. Each run receives a new pair and session ID; failed/historical sessions
are never restored. The service offers no key-entry, key-file or fixed-key option.

`EphemeralKeySet` holds mutable buffers in a private local owner, outside run
records and request models. Only the existing trusted USB setup commands carry
hex key material. The host checks each node's owned idle state and loaded-key
readiness after setup. Its mutable buffers are overwritten and references retired
immediately after provisioning, or on any partial-setup exception/cancellation.
They are not needed for later RF orchestration. Python's temporary immutable hex/
wire copies and OS memory management do not provide a provable full-memory erase;
this is explicit application non-persistence and mutable-buffer retirement, not a
claim about swap/core dumps or every allocator copy. The host and USB bench remain
trusted parts of the selected design.

## What recorders receive

Before a recording callback runs, `NodeSession` constructs an explicit allowlist:
`session.setup` / `session.setup.result`, command/run/session IDs, role, peer and
boot IDs, security profile, random key-set ID, provisioning facts and safe outcome.
These are non-replayable setup facts. They contain neither key values nor
key-derived fingerprints. The private command is never dumped to a recorder and
then masked later. Invalid arguments, protected write errors and invalid/rejected
setup replies use safe errors that omit supplied values.

Current SQLite, node-event, file-transfer trace, radio trace and metadata export
boundaries independently reject non-null secret fields, including raw or repeatedly
JSON-encoded commands. An unsafe historical metadata/trace export is refused;
history is not silently rewritten. Public source/recovered binary artifacts remain
byte-exact. API validation also omits accidentally supplied key material from its
rejection response; the host API does not accept caller-provided run keys.

The run's `security` section retains profile, random key-set ID, acknowledged
per-node setup, host retirement and a final stage assessment. Cleanup separately
confirms remote key readiness is false and the node is idle/closed. A disconnected
node remains unconfirmed; peer cleanup is attempted, and the run is interrupted.
Reconnect requires new ownership/session/key state. No historical work resumes.

## Observed security stages

`radio_security.assess` reports actual retained DATA arrivals, CRC-valid arrivals,
authenticated fragments reported by the node, authentication/session/replay
rejections, accepted ACK results and independently verified readback. Host
configuration rejection before RF is distinct from wrong-key authentication
rejection after an RF arrival. Missing RF has its own inconclusive classification;
it never means successful authentication or a measured security rejection rate.

`radio_accounting` adds tag bytes to expected protected frame sizes and reconciles
accepted ACK events against actual outstanding DATA attempts, peer transmissions
and raw arrivals. Invalid raw ACKs remain in evidence and cannot count as accepted.
Originals, attempts, retries, accepted fragments, deliveries, RF observation and
telemetry completeness remain separate. Physical qualification remains pending.

## Matching profile migration

Explicit ACK acceptance adds a typed RF event and changes only the execution/RF
schema identity. Rebuild matching host and node source together:

- Previous execution SHA-256: `88ddc6ba2422af593c0ba91ad1350f9f4ba411a3f037fae09b31ee5c4fc1e775`.
- New execution SHA-256: `3e3073993d76a7133d3ef594d2147967936c1bdb6c4a770aebe9d5444f48e6a1`.

The main-control, diagnostic, file-transfer and local-audio hashes are unchanged.
Old evidence stays historical; it is not relabeled current. This does not require
flashing the separate diagnostic image. The current physical audio image is not
this protected-radio image; identify its board/revision/wiring before RF installation.

## Review walkthrough

1. `session_keys.py`: fresh source pair, retirement, safe setup facts and persistence fence.
2. `nodes.py`: private serial write versus allowlisted callbacks and safe setup replies.
3. `radio_runs.py`: setting checks, two-node setup, early host retirement, receiver-first
   orchestration, uncertainty tracking, cleanup and fresh restart.
4. `radio_security.py` / `radio_accounting.py`: separate RF stages and accepted ACK evidence.
5. `storage.py`, `artifact_transfers.py`, `app.py`: independent recording/export/API guards.
6. `RadioLink.tsx` and `cli.py`: profile selection and observed counts through one backend.
7. `radio/rf_execution.c`: accepted ACK events and the receive-drain boundary correction.

Paths 1–6 are under `testbed/src/lora_testbed` except the frontend component under
`testbed/frontend/src`; path 7 is under `firmware/lora_node/main`.

## Reproduce software checks

From repository root with the pinned IDF/native prerequisites:

```sh
uv run --project testbed pytest testbed/tests/test_private_sessions.py testbed/tests/test_protected_rf_execution_native.py testbed/tests/test_session_secrets.py -q
make check
npm --prefix testbed/frontend run format:check
idf.py -C firmware/lora_node build
```

Expected focused results: 31 cases without skips. Two successful protected runs
must use four distinct actual source keys, verified privately without printing
values. Scan saved files and decompressed exports for actual binary/hex key
material; none may appear. Verify wrong-key RF arrivals versus host setting
mismatch, cancel/disconnect and uncertain setup cleanup, fresh reconnection,
entropy failure, nested/serialized secret guards and API error redaction.
These checks use actual production C/PSA cores at isolated serial/SPI boundaries.
Native results do not qualify RF performance or target memory/acceleration.

### Drain-boundary regression

Repeated protected runs exposed a real firmware race: a message and all ACKs
could complete, but the clock could cross the drain deadline between the early
completion check and receive rearming. The later normal RX timeout then marked
the run failed. The minimized one-fragment regression varied nine public clock
crossings: only the crossing inside that interval failed before the fix.
Delivery was still reported and the radio was already receiving, ruling out
lost delivery state or an unfinished ACK.

The receive-continuation helper now completes an expired delivered drain after
ACK work has finished. It does not widen deadlines. All nine crossings pass;
a separate unfinished-ACK case must still fail at the drain deadline. Original
repeated protected runs pass with independent readback and secret-free exports.

### Live-state responsiveness

The browser fixture also exposed repeated immutable schema generation during
live state/catalog polling. One two-node refresh rebuilt diagnostic/control
schemas 1068 times. The same cumulative profile fell from 3.820 seconds to
0.017 seconds after caching only their immutable digest strings; the local crypto
supplement uses the same policy. This is a host fixture measurement, not node
crypto timing. Capability/health dictionaries and snapshots remain live. A public
two-node refresh check requires less than one second and verifies an immediately
subsequent disconnect changes the result. Exact generated digests are unchanged.

## Later operator checks

After reviewing/installing matching source and completing two-board identity,
revision, antenna/wiring and backup checks, start the matching physical backend
and connect both roles. The dashboard's known-data radio panel offers **Security**;
select AES-128-GCM, set message/fragment/ACK policy, inspect readiness and start.
No key entry is required. Inspect exact readback, observed security stages and
cleanup before another run. Unprotected remains an explicit baseline choice.

Equivalent CLI calls:

```sh
uv run --project testbed lora-testbed radio-start --preview --security aes128_gcm --message-bytes 321
uv run --project testbed lora-testbed radio-start --security aes128_gcm --message-bytes 321
uv run --project testbed lora-testbed radio-status RUN_UUID
uv run --project testbed lora-testbed radio-stop RUN_UUID
```

For ACK/retry settings use the existing `--config` JSON option, including
`"security":"aes128_gcm"` and `"link":{"ack_mode":"stop_wait","max_retries":2}`.
Protected fragment capacity is at most 199 bytes; default 160 is valid. API clients
send the same public configuration to `/api/radio/preflight` and `/api/radio/runs`.

Physical #67 still requires protected traffic/readback in both directions,
controlled bad-tag/old-session/ACK-disabled replay rejection, lost-ACK recovery,
cleanup/reconnect and loaded-target resource evidence. Observe actual RF arrival
before attributing an absent delivery to authentication. Retain safe records and
hash exports; never store keys as reproducibility evidence. Full ECHO, fault
operators and all CDR procedure qualification remain separate work.
