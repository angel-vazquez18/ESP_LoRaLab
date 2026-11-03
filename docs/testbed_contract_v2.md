# Testbed contract 2.0.0 — provisional implementation baseline

Decision date: October 18, 2026. The user authorized making the contract decisions
now and revising them after discussion with Homar. Implement against this
baseline without waiting for that discussion. This is a specification, not a
claim that firmware or host support already exists.

This document supersedes unresolved design choices in earlier plans. On November 1,
the user selected a physical-only host. The diagnostic path implements its limited
wire-version **2**, contract **2.0.0** subset; full RF execution remains pending.
The former v1 and virtual v2 simulators were removed. Historical records retain
their original versions/provenance. See `status.md` for implemented command families.
The schemas retain historical provenance values for compatibility; physical
connections require `hardware` provenance. Wire schemas/digests are unchanged.
`contracts/v2/default_profile.json` contains the selected starting values.
`contracts/v2/conformance_vectors.json` contains reference framing, encryption,
known-data and artifact examples. Its fixed public key is exclusively test data;
it is never the key for a normal run.

## 1. Decision register

| ID | Decision | Reason / revision point |
| --- | --- | --- |
| D01 | macOS, one local Python backend, independently attached A/B nodes | One owner for serial ports, UI and CLI |
| D02 | ESP-IDF **v6.0.2**, C/C++; ESP32-S3 production target | Matches the available toolchain; generic ESP32 diagnostic target has only its supported capabilities |
| D03 | Native USB Serial/JTAG where exposed; USB-UART otherwise, **115200 8N1** | Common serial interface; native USB ignores UART baud for physical transfer rate |
| D04 | UTF-8 NDJSON, **4096 bytes including LF**, protocol v2 | Inspectable, bounded framing; large content uses chunks |
| D05 | Persistent device identity separate from A/B; per-boot identity and per-run session | Prevent USB path changes or resets from corrupting attribution |
| D06 | One active bench run, firmware-controlled timing, receiver armed first | Repeatable measurements independent of browser/USB scheduling |
| D07 | Point-to-point LoRa, explicit header, CRC enabled, private sync word | Direct two-node experiment; no LoRaWAN dependency |
| D08 | **AES-128-GCM**, 96-bit nonce, 128-bit tag; fresh source-specific keys per run | Authenticated payload and header; reset-safe session lifecycle |
| D09 | **128-packet replay window**, exact-byte retry, no duplicate delivery | Supports bounded reordering and ACK-loss recovery without reusing a nonce for changed content |
| D10 | Fixed **40-byte RF protocol header**, 255-byte radio payload ceiling | Explicit identities and lengths; 199 protected useful bytes maximum |
| D11 | Default **160-byte fragments**, stop-and-wait when ACK enabled, **two retries** | Simple bounded implementation; ACK disabled for initial RF baselines |
| D12 | **Codec 2 1.2.0, mode 3200**, 8 kHz/16-bit/mono, three-second clips | One concrete codec target with small framed output; feasibility remains measured |
| D13 | **1024-byte** serial artifact chunks, CRC-32 per chunk and SHA-256 per artifact | Detect interrupted/corrupt transfers and preserve evidence |
| D14 | Node-local RTT; **shared wired pulse calibration** for one-way timing | Explicit clock domains and uncertainty; no USB-time substitution |
| D15 | 1 Hz node health, stage-based memory, at most 5 Hz aggregate UI updates | Useful live data with bounded telemetry load |
| D16 | Capability-gated execution, strict applied-setting readback, explicit unavailable values | One ESP32 can be useful without pretending it has radio/audio peripherals |
| D17 | Versioned stored evidence, separate execution outcome and assessment | Reproducible analysis and honest CDR coverage |

Board revision, actual wiring, available RAM, USB routing and peripherals are
observations to collect when hardware is attached. They are not unresolved
protocol choices. Use a versioned board manifest for actual pin assignments,
radio front-end control and peripheral presence. Do not guess those from the
name “ESP32”. A diagnostic build advertises `radio=false`, `audio=false` and
`sync=false` until its actual hardware and build support those capabilities.

## 2. Transport, ownership and versioning

Use one selected `/dev/cu*` port per device. Serial reads/writes have 100 ms
polling timeouts and run outside the host event loop. UART transport uses 115200
baud, eight data bits, no parity, one stop bit and no flow control. Native USB
uses the same record protocol. Start with DTR/RTS deasserted, do not deliberately
pulse reset on connection, and detect any actual reset through `boot_id`.

Each record is one JSON object, terminated by LF; accept CRLF. Reject invalid
UTF-8, duplicate JSON keys, NaN/Infinity, unknown fields and nesting deeper than
eight levels. No multiline records or JSON comments. An oversized record is
discarded through its next LF; count diagnostics and continue. Rate-limit
malformed-line diagnostics to one per second with an aggregate count.

Protocol traffic has a single serialized writer. Regular ESP-IDF log output goes
to a separate channel or a structured `diagnostic` event. Boot text is tolerated
only as non-protocol input and is never a measurement. Sensitive command bodies
are redacted before any serial trace, crash report or run record is persisted.

The first command is `hello`, accepted regardless of ownership. It reports
`supported_wire_versions:[2]`, `contract_version:"2.0.0"` and the schema digest.
Both sides require major/minor contract agreement; patch versions clarify the
same wire semantics. A breaking layout/meaning requires a wire-version increase;
an additive command/event requires a contract-minor change and updated schema.
No automatic downgrade. Unknown commands return `UNSUPPORTED_COMMAND`.

One backend-generated `client_id` UUID owns the device through `control.claim`.
Claims last five seconds and are renewed by `control.keepalive` every second.
Only the owner may issue commands other than `hello` and an idle `control.claim`.
An unexpired claim cannot
be stolen. A lost lease stops work, clears keys, invalidates sessions, and returns
the device to idle after the bounded stop process. Flashing/IDF Monitor requires
the backend to release/close the port first. A connection never flashes firmware.

After reconnect, obtain `hello`, claim, inspect status and open a new run/session.
Never resume an active RF run automatically, even if its boot has not changed.

## 3. Identity, numeric types and envelopes

- `device_id`: `esp-` plus twelve lowercase hex digits of the factory base MAC;
  physical USB serial number and port are separate metadata. Simulators use
  `sim-<uuid>` and always declare their provenance.
- `boot_id`: `<device_id>:<boot_count>`, with an atomically incremented persistent
  unsigned 32-bit boot counter. NVS failure/counter exhaustion disables runs;
  factory-resetting identity state requires re-enrollment and fresh sessions.
  Host re-enrollment starts a new persisted `device_enrollment_id` UUID; event
  deduplication includes that enrollment so erased counters cannot collide with
  old records. Re-enrollment is explicit maintenance, never automatic resumption.
- `node_role`: `A` or `B`, assigned by the host, not baked into firmware. Air IDs
  are 1 and 2 respectively. `run_id`, `command_id`, `client_id`, `operation_id`,
  `artifact_id` and `calibration_id` are lowercase UUID strings.
- `session_id`: nonzero random 64-bit value, represented by exactly sixteen
  lowercase hex digits in JSON. One session belongs to exactly one run and pair
  of boot IDs. The host creates a fresh session even for an unprotected run.
- `command_seq`, `frame_seq`, `message_id`: unsigned 32-bit integers, starting
  at 1; zero is reserved. Never wrap. `fragment_index` starts at zero.
- JSON counters/times are nonnegative integers no greater than 2^53−1; signed
  offsets and finite RSSI/SNR floats are explicit exceptions. `uptime_us` uses
  `esp_timer_get_time()` on the node. Wall-clock UTC belongs to host records only.
- Units are suffixes: `_us`, `_ms`, `_hz`, `_dbm`, `_db`, `_bytes`, `_samples`,
  `_bps`. Binary multibyte fields use network byte order; PCM alone is little-endian.
- Optional but supported measurements use `null` until observed. A capability
  flag explains unsupported measurements. Empty strings/zero are not substitutes.

Command (all shown fields required):

```json
{"v":2,"kind":"command","command_id":"11111111-1111-4111-8111-111111111111","client_id":"22222222-2222-4222-8222-222222222222","command_seq":1,"target_boot_id":null,"run_id":null,"name":"hello","args":{}}
```

Reply: `v`, `kind:"reply"`, `command_id`, `command_seq`, `device_id`, `boot_id`,
`uptime_us`, `ok`, `result`, `error`. Success has an object `result` and null
`error`; failure has null `result` and `{code,message,field,retryable}` error.
`field` is a JSON field path or null. Messages are at most 160 characters.

Event: `v`, `kind:"event"`, `device_id`, `boot_id`, `node_role` (nullable before
claim), `event_seq`, `uptime_us`, `run_id` (nullable outside runs), `name`, `data`.
`event_seq` increases for every attempted event, including dropped events, within
a boot. A host stores `host_received_at_utc` and monotonic receipt time separately.
Duplicate `(device_enrollment_id,device_id,boot_id,event_seq)` events do not repeat
analysis effects; the host attaches the enrollment ID when persisting events.

Except `hello`, every command specifies the current `target_boot_id`. A stale
value returns `STALE_BOOT` without action. Commands after claim use increasing
`command_seq` scoped to client and boot. Serialize ordinary commands; stop and
keepalive remain available while an asynchronous operation is executing.

Replies acknowledge acceptance within 500 ms under normal conditions. Host reply
deadline is two seconds. For a mutating command, retry the exact same encoded
record/ID/sequence at most twice after a timeout. The device retains the last
16 mutating-command fingerprints and replies (maximum 1024 bytes each) for the
claim lifetime. Repeated identical commands return their saved reply; changed
content under a reused sequence/ID returns `COMMAND_CONFLICT`. High-water sequence
tracking rejects evicted older commands as `COMMAND_EXPIRED`, never re-executing
them. Read commands use fresh IDs/sequences when retried; their samples may change.
Record sequence/fingerprint before invoking side effects. A reboot invalidates all
old commands; firmware does not promise to resume an interrupted side effect.

Long commands return `{operation_id,state:"accepted"}` and emit operation events.
Their completion deadlines are returned as `deadline_us` in node uptime. Stop
acceptance is distinct from radio/audio activity actually ceasing.

## 4. Command vocabulary and state rules

The table defines required argument members; `{}` means none. IDs, settings and
limits below refer to the exact structures in this document. Unknown arguments
are errors. Read commands are marked R; all others are mutating commands.

| Command | Args | Successful result / rule |
| --- | --- | --- |
| `hello` R | `{}` | Identity/build/board/provenance, contract/schema, capabilities, `claimed` and current state; never keys |
| `control.claim` | `node_role` | Lease plus current status; idle only unless renewing the same owner |
| `control.keepalive` | `{}` | `lease_expires_us`; owner only |
| `control.release` | `{}` | Idle only; clears ownership and session |
| `status.get` R | `{}` | Node snapshot described in section 5 |
| `session.open` | `session_id, peer_device_id, peer_boot_id, security, tx_key_hex, rx_key_hex` | Binds envelope `run_id`; security is `none` or `aes128_gcm`; keys null for none; idle only |
| `session.close` | `{}` | Idle only; zeroize keys, replay state and retained injection frames |
| `config.set` | `radio, link` | Atomic validation/application; return applied values and `config_revision` (incrementing u32) |
| `run.prepare` | `spec,budget` | Reserve buffers, validate capabilities, stage source; accepted operation, then prepared event with applied budget and expected lengths/digests if known |
| `run.arm` | `config_revision` | Receiver ready for this run/session, returns `receiver_ready`; refuse stale revision |
| `run.start` | `config_revision` | Sender operation accepted; both nodes must already be prepared and receiver armed |
| `run.stop` | `reason` | Idempotent stop request; `reason` is `operator`, `host_shutdown` or `peer_failure` |
| `run.summary` R | `{}` | Last run summary; available until the next prepare or reset |
| `artifact.begin` | `artifact_id,kind,length_bytes,sha256,format` | Reserve upload storage; expected offset zero |
| `artifact.put` | `artifact_id,offset,data_b64,crc32` | At most 1024 decoded bytes, contiguous writes; return next offset |
| `artifact.commit` | `artifact_id` | Verify exact declared length/hash; mark immutable or fail |
| `artifact.list` R | `{}` | At most four artifact manifests; no content |
| `artifact.get` R | `artifact_id,offset,length_bytes` | Up to 1024 bytes as Base64, offset, length, CRC-32, EOF flag |
| `artifact.delete` | `artifact_id` | Reject artifacts in use; free slot |
| `audio.capture` | `artifact_id,sample_count` | Bounded microphone capture operation; PCM format fixed below |
| `audio.encode` | `source_artifact_id,artifact_id,codec` | Encode operation; codec must be `codec2_3200_v1` |
| `audio.decode` | `source_artifact_id,artifact_id,sample_count` | Decode operation, trim padded final samples |
| `audio.play` | `artifact_id` | Output operation; PCM only; never overlap capture/playback in v2 |
| `operation.stop` | `operation_id` | Idempotent cancel for artifact/audio/diagnostic operations |
| `diag.run` | `kind,iterations,payload_bytes` | `serial_echo`, `crypto_benchmark`, or `memory_probe`; iterations 1–10000, bytes within negotiated limits |
| `fault.set` | `injections,replace` | Up to eight entries per command and 32 per session; replace=true clears previous entries, false appends; idle/prepared only |
| `fault.fire` | `injection_id` | Execute an armed retained-frame replay after the host observes legitimate RX; active run only, within the prepared fault/drain budget |
| `clock.arm` | `calibration_id,count,interval_us` | Arm sync capture; count 32 for a burst or 0 for continuous, interval 100000 |
| `clock.emit` | `calibration_id,count,interval_us` | Node A's wired pulse source; both capture inputs must be armed |
| `clock.install` | `calibration_id,reference_device_id,reference_boot_id,scale,offset_us,uncertainty_us,valid_until_us` | Install host-calculated mapping metadata, retain raw times in events |
| `clock.stop` | `calibration_id` | Stop pulse/capture operation; expire associated live calibration |

`run_id` is non-null for session/run commands, run diagnostics and run faults;
audio preparation and clock calibration may occur outside a run with null run ID.
Single-board `diag.run` is allowed without an RF session. Its crypto self-test/
benchmark uses explicitly public test-vector material from the diagnostic build,
never ordinary session keys, and cannot transmit RF. Radio runs require both peer
identities in `session.open`; health/serial/memory checks do not invent a peer.
Every run command must match the active run; summaries of an old run return
`UNKNOWN_RUN`. Session setup never arms or transmits. `run.prepare`/`run.arm`
have separate sender and receiver semantics according to the prepared direction.
The host enforces the cross-device arm ordering; a sender cannot independently
prove that a peer has acknowledged a USB command.

Device activity states: `idle`, `preparing`, `prepared`, `armed`, `running`,
`draining`, `stopping`, `faulted`. Asynchronous preparation emits readiness;
start is allowed only after it completes. Configuration and role changes are
forbidden after arming. Connection state, compatibility and activity are separate.
On node reset, peer loss or host lease loss, the host records `interrupted`,
requests peer stop and requires a new session. After final summary, activity is
idle; session keys are erased on close, expiry or reset.

Errors: `INVALID_ARGUMENT`, `UNSUPPORTED_VERSION`, `UNSUPPORTED_COMMAND`,
`MISSING_CAPABILITY`, `BUSY`, `NOT_OWNER`, `STALE_BOOT`, `COMMAND_CONFLICT`,
`COMMAND_EXPIRED`, `INVALID_STATE`, `UNKNOWN_RUN`, `CONFIG_MISMATCH`,
`KEY_NOT_READY`, `SESSION_MISMATCH`, `RESOURCE_LIMIT`, `ALLOCATION_FAILED`,
`ARTIFACT_NOT_FOUND`, `OFFSET_MISMATCH`, `CHECKSUM_MISMATCH`, `TIMEOUT`,
`IO_ERROR`, `RADIO_ERROR`, `AUDIO_ERROR`, `CLOCK_INVALID`, `INTERNAL_ERROR`.
Only transient `BUSY`, `TIMEOUT`, `IO_ERROR` are potentially retryable, and the
reply must explicitly set `retryable`. Retrying a rejected operation requires a
new command ID; wire timeout retry preserves the old ID to resolve ambiguity.

## 5. Capabilities, live state and event data

`hello` contains `device_id,boot_id,board_model,board_revision,chip_model,
firmware_version,firmware_commit,firmware_build_id,idf_version,board_manifest_hash,
provenance,supported_wire_versions,contract_version,schema_sha256,capabilities,
claimed,state`. Versions/identities are strings, provenance is `hardware` or
`simulated`, and unavailable physical metadata is null. Capabilities contain
booleans `radio,audio_capture,audio_playback,codec2_3200,security_gcm,fragmentation,
ack_retry,echo,clock_sync,memory_stats,fault_injection`, plus `radio_limits`,
`resource_limits` and `timestamp_resolution_us`. A disabled boolean cannot be
overridden by a UI switch. Report present peripherals separately from compiled
support in `status.get`.

`status.get` and `health` contain current role/state/run/operation IDs, uptime,
reset cause, applied radio/link settings and revision, capability availability,
memory, traffic counters, security readiness, audio state, telemetry drops,
last-error object and last RX sample. The RX sample contains value, timestamp
and packet identity, not just RSSI/SNR. `health` is emitted every 1000 ms.

Canonical event payloads:

| Event | Required data |
| --- | --- |
| `health` | Node snapshot above; no artifacts or secret material |
| `run.state` | `state,reason` (reason nullable), `config_revision` |
| `run.prepared` | `config_revision,budget,source_length_bytes,source_sha256`; source values nullable until capture/encode completes |
| `tx.attempt` | `session_id,frame_seq,message_id,fragment_index,attempt_index,frame_type,frame_bytes,tx_command_us,tx_done_us,status` (timestamps may be null on failure) |
| `rx.frame` | `session_id,source_role,frame_seq,message_id,fragment_index,frame_type,frame_bytes,rx_done_us,rssi_dbm,snr_db,crc_ok` (unparsed identity null on bad frame) |
| `rx.accepted` | Frame identity, `payload_bytes,accepted_us`; only first valid fragment |
| `rx.rejected` | Frame identity if parseable, `stage,reason,related_injection_id` (nullable) |
| `ack.result` | `acked_frame_seq,ack_frame_seq,attempt_index,status` (`received`, `timeout`, `repeat_sent`) |
| `message.missing` | `message_id,part_index,part_count,ranges`; at most 64 inclusive missing-index ranges per event, indexes zero-based |
| `message.result` | `message_id,status,message_bytes,sha256,fragment_count,missing_count,missing_parts,first_fragment_us,complete_us`; missing-parts events precede result |
| `memory.sample` | `stage,internal,psram,buffers,allocation_failures`; each heap object has free/minimum/largest bytes or is null |
| `crypto.sample` | `frame_seq,operation,payload_bytes,duration_us,status,implementation`; operation encrypt/decrypt |
| `audio.stage` | `operation_id,message_id,stage,state,sample_count,artifact_id,queue_bytes,dropped_source_bytes,underflows`; inapplicable values null |
| `artifact.ready` | Manifest: ID/kind/length/hash/format, codec build and sample/frame counts where applicable |
| `clock.sample` | `calibration_id,pulse_index,capture_us,capture_method` |
| `operation.result` | `operation_id,status,result,error` |
| `fault.applied` | `injection_id,stage,action,target_frame_seq,target_message_id,target_fragment_index,attempt_index` |
| `diagnostic` | `severity,code,message,related_command_id`; no raw command bodies |
| `run.summary` | Section 11 totals, measurement windows, stop reason, telemetry drops and validity |

Heap scopes are non-overlapping: `internal` = internal 8-bit-capable heap;
`psram` = external 8-bit-capable heap. Minimum-free values are boot minima; take
explicit run/stage samples for run minima. Never add overlapping capability
queries. Sample at 1 Hz and stage entry/exit; `MEM-01` can select 10 Hz. Buffer
entries name capture, codec, reassembly, radio, artifact and source queue bytes.

Packet/crypto events are loss-sensitive evidence; queue them for serial delivery
without printing/blocking in timing-critical handlers. Board queues are bounded;
count drops. Emit crypto samples only for SEC-04 or an explicitly instrumented
run. Make instrumentation part of the saved profile, including firmware build
and whether hardware crypto acceleration was enabled. Limit host UI updates to
5 Hz; it may coalesce display updates but not silently discard recorded events.

## 6. Radio and run configuration

Default radio: 915000000 Hz, SF7, 125000 Hz bandwidth, coding rate 4/5,
`tx_power_dbm:14`, eight preamble symbols, explicit header, radio CRC on,
normal IQ and SX126x private sync word **0x1424**. Low-data-rate optimization is
automatic when symbol time is at least 16 ms; return the actual applied flag.
Frequency is configurable from 902000000 through 928000000 Hz in 1000 Hz
requested steps, intersected with the board profile. These are project profile
limits; capability/readback determines actual hardware support.

Supported sweep values: SF7–12, BW125/250/500 kHz, coding denominators 5–8 and
power 2/5/8/11/14/17/20 dBm where supported. `tx_power_dbm` is the radio driver
setting, not an assertion about measured antenna output. A board with an external
front end must include its control/power mapping in the manifest and expose
calibrated output separately if available. Do not silently clamp a request.

`radio` keys: `frequency_hz,bandwidth_hz,spreading_factor,
coding_rate_denominator,tx_power_dbm,preamble_symbols,header_mode,crc_enabled,
iq_inverted,sync_word,ldro_mode`. Constants above are fixed in v2 except the five
sweep fields and `preamble_symbols` (8–32). `sync_word` is JSON integer 5156;
`header_mode` is `explicit`, `ldro_mode` is `auto`.

`link` keys: `fragment_payload_bytes` (16–199 protected or 16–215 unprotected;
default 160), `ack_mode` (`none` default or `stop_wait`), `max_retries` (0–5;
default 2 when ACK is enabled, must be 0 when disabled), `guard_us` (0–1000000,
default 50000), `ack_turnaround_us` (20000), `ack_margin_us` (80000).

`spec` keys: `catalog_id,direction,source,message_count,message_bytes,
source_seed,source_artifact_id,sample_count,security,max_duration_ms,
source_duration_ms,instrumentation,expected_sha256,playback`.
Direction is `A_TO_B` or `B_TO_A`; each reverse-direction case is a separate run.
`source` is `known_data`, `reference_pcm`, `node_microphone`, `encoded_source`
or `echo`. Inapplicable fields are null, not omitted. `security` matches the
session. `instrumentation` contains booleans `packet_events,crypto_samples,
memory_10hz,clock_samples`; packet events default true and other flags false.
`playback` is false except a voice case requesting receiver speaker output.
`expected_sha256` is null for generated/not-yet-captured content, or the hash for
the repeated reference message; generated data uses the independent seed recipe.

`budget` has integer `ack_timeout_us,reassembly_timeout_us,drain_us,
capture_budget_us,processing_budget_us,playback_budget_us,fault_budget_us` and
`model_version:"sx126x_lora_v1"`. No-ACK timeout is zero. Capture/playback each allow the
declared sample duration plus 500000 µs. Initial processing allowance is 10000 µs
per message plus 10000 µs per attempted frame; add 5000000 µs per voice message
for codec processing. Replace these with recorded validated upper bounds after
benchmarking. Fault budget includes planned injected airtime and host barriers.
Host computes the expanded worst case; nodes validate its inputs and limits
before preparation and return the applied budget. A disagreement rejects prepare.
All work fits `max_duration_ms` from sender start acceptance to final summary.
Host issues start within five seconds after receiver arm; the receiver's bounded
arm/run deadline is its arm time plus five seconds plus `max_duration_ms`.
For `node_microphone`, prepare reserves memory; capture begins on run start so
capture/encode time remains part of the voice transaction.

Default known-data run: 100 messages, 64 bytes each, seed 743, no ACK,
AES-128-GCM, maximum duration 120000 ms. IF-02 initial bring-up explicitly uses
`security:none`; secure operation is the application default once supported.
Allow 1–10000 messages, 1–65536 bytes per message, and 1000–3600000 ms maximum
duration, intersected with reported resources. The host rejects a preview whose
worst-case budget exceeds the selected maximum; it never silently reduces count.

Known data is generated in both languages without a platform PRNG dependency:
concatenate SHA-256 blocks of ASCII `lora-testbed-v2` followed by
`BE32(seed)||BE32(message_id)||BE32(block_index)`, starting block index at zero;
truncate to `message_bytes`. Verify actual reconstructed bytes/digest at RX.

Preset radio sweeps keep message size, security, ACK, placement and other radio
settings fixed. Start with 100 messages × three repetitions per configuration.
Security comparisons match useful bytes and fragment size so header/tag overhead
appears in measured airtime rather than being hidden by changing the workload.

## 7. Binary RF framing and fragmentation

One LoRa payload is `header || body || tag`. There is no tag in security `none`.
The radio's own CRC is outside this protocol layout. Maximum LoRa payload is
255 bytes, further reduced if the actual radio profile advertises a smaller limit.

| Offset | Bytes | Field |
| --- | --- | --- |
| 0 | 2 | Magic `0x4c54` (ASCII LT) |
| 2 | 1 | Wire version 2 |
| 3 | 1 | Type: DATA=1, ACK=2, ECHO_REQUEST=3, ECHO_REPLY=4 |
| 4 | 1 | Flags: bit 0 protected, bit 1 ACK requested; all other bits zero |
| 5 | 1 | Source role: A=1, B=2 |
| 6 | 1 | Destination role: A=1, B=2; no broadcast |
| 7 | 1 | Content: known bytes=0, codec2_3200_v1=1 |
| 8 | 8 | Session ID |
| 16 | 4 | Frame sequence, source-scoped across DATA/ACK/ECHO |
| 20 | 4 | Message ID |
| 24 | 2 | Zero-based fragment index |
| 26 | 2 | Fragment count |
| 28 | 4 | Complete message length in useful bytes |
| 32 | 2 | Body length in bytes, excluding tag |
| 34 | 4 | Referenced frame sequence for ACK/ECHO_REPLY; zero otherwise |
| 38 | 2 | Reserved, must be zero |

The complete 40-byte header is GCM additional authenticated data. Protected body
is ciphertext, followed by a 16-byte tag. Thus useful capacity is **199 bytes**
protected and **215 bytes** unprotected. The default 160-byte fragment leaves
headroom and is held equal across security comparisons.

Every fragment repeats consistent message metadata. Fragment count is
`ceil(message_bytes/fragment_payload_bytes)`, at most 4096. All non-final fragment
bodies have the configured size; the final body has the exact remainder. Enforce
DATA/ECHO length/count/index consistency before allocation and authenticate before inserting
plaintext into reassembly. A conflicting fragment or inconsistent authenticated
metadata fails the message. Never deliver partial or unauthenticated audio.

Keep one reassembly message per source; sender messages do not interleave. A new
message may retire an incomplete older one as failed. Maintain delivered/failed
message high-water tracking through the session to prevent old fragments from
starting a second delivery. Controlled reorder tests stay within one message
and within 32-fragment blocks, compatible with the replay window.

DATA has nonzero body. ACK has an empty body, ACK-request flag clear, referenced
frame sequence set and copied message/fragment/content fields from its DATA.
Protected ACKs still carry a tag and consume a fresh source frame sequence.
ECHO_REQUEST/REPLY are single-fragment known-data messages, ACK-request clear;
the reply echoes the exact bytes, references the request, and has a fresh frame
sequence under the responder's key. Echo payloads are limited to one fragment.

## 8. Security, replay and reliable retransmission

Use the ESP-IDF-supplied Mbed TLS authenticated GCM interface with AES-128 keys,
12-byte nonce and full 16-byte tag. Never release decryption output until tag
verification succeeds. The two profiles are `none` and `aes128_gcm`; no custom
cipher, authentication-only third mode or tag truncation in this version.

For each run the host uses its OS CSPRNG to generate two independent 16-byte
keys: one for frames sourced by A and one for frames sourced by B. The host sends
each node its TX and peer RX key through the locally owned USB control connection.
That USB connection and host are trusted parts of this laboratory design;
the RF protocol authenticates possession of the provisioned session key, not a
device certificate. Key material is held only in RAM, never ordinary telemetry,
SQLite, saved commands, profiles, exports or firmware source. Record only a random
non-secret key-set identifier. Failure/restart requires new keys, not persisted
session recovery. Store redacted setup facts instead of raw setup commands.

Nonce = `BE64(session_id)||BE32(frame_seq)`. The direction/source-specific key
separates A and B nonce spaces. All newly protected DATA, ACK and ECHO frames
consume a new source frame sequence. Before exhaustion, stop and open a new
session with fresh keys. Keys and counters cannot be reset independently. Do not
re-open or re-arm a completed run with its old key material.

Retries transmit the exact retained header/ciphertext/tag bytes; **never encrypt
modified content under the old sequence/nonce**. The attempt number is telemetry,
not an editable header field. Sender retention lasts through ACK/retry completion.

Receiver order: validate bounded framing/session/roles/profile → verify GCM →
check replay state → validate message metadata → accept a new fragment. The
128-bit sliding replay bitmap is per peer/session and covers all frame types.
Authenticated unseen sequences within the window can arrive out of order;
older or already-seen frames never cause application delivery. Invalid tags
never advance the window. Profile mismatch is rejected, preventing a protected
session from accepting a frame with its encryption flag cleared.

For stop-and-wait, retain a small cache of the last 16 accepted DATA-frame hashes
and their metadata for the current retry horizon. A repeated authenticated,
byte-identical DATA packet inside that horizon emits `retry_duplicate`, and
may cause a fresh ACK, but is not accepted again. Without ACK mode or outside
that cache/horizon, classify duplicates as `replay`. This classification does
not claim to distinguish a malicious retransmission from a legitimate identical
retry. Both have zero new application delivery. SEC-03 uses ACK disabled.

ACK mode is `none` or per-fragment stop-and-wait; there is one outstanding DATA
packet. ACK timeout, measured from DATA TX-done, is
`ack_turnaround_us + airtime_us(ACK) + ack_margin_us`. Defaults give 100000 µs
plus ACK airtime. On timeout retry up to `max_retries`, then fail that message
and continue only if the case's expected fault behavior permits it. New attempts
obey the guard interval. Wrong-session, wrong-source, wrong-reference or invalid
ACKs cannot acknowledge a packet. No ACK-of-ACK and no automatic message restart.

Default reassembly deadline is derived from all fragments' worst-case attempts,
ACK waits and guards, plus two seconds. It is sent as part of the expanded
prepared run budget and never exceeds the run deadline. Retain duplicate-ACK
eligibility at least through the sender's corresponding retry budget. Drain
after TX completion for `max(2000000, ack_timeout_us + guard_us)`; final summaries
and stop deadlines account for this explicitly. Firmware watchdog covers the
entire run including capture, processing, RF, drain and playback.

Stop prevents new frames/operations, allows at most the current noninterruptible
radio frame or I2S DMA block to finish, then emits summary. Stop completion bound
is `max(current_frame_airtime_us, audio_dma_block_us) + 2000000`; no further retry
is started. Record original failure and cleanup failure separately.

## 9. Controlled faults and CDR assertions

Each `fault.set` entry has `injection_id` (UUID), `stage`, `action`, `message_id`,
`fragment_index`, `attempt_index` (1-based), `byte_offset`, `xor_mask` and
`block_size`; unused selectors are null. Match exact selectors once and report
`fault.applied`. `reverse_block` uses `block_size` 2–32; other actions use null.

- `tx_after_protect` + `xor_byte`: mutate ciphertext or tag at a declared frame
  offset; radio hardware computes a valid physical CRC on the mutated bytes.
  Do not run GCM again. SEC-02 must observe receiver authentication rejection
  and a successful legitimate control; unobserved frames are inconclusive.
- `tx_retained` + `replay`: retransmit the retained exact protected frame once
  when the host sends `fault.fire` after initial successful delivery, same session
  and no new sequence. Receiver remains armed through the prepared fault/drain
  budget. SEC-03
  asserts initial delivery, replay rejection and unchanged delivered-message count.
- `rx_before_reassembly` + `drop`: discard a newly validated fragment for the
  selected fault case, report it separately from RF loss. ACK behavior for that
  injected drop is no ACK; do not mark it accepted/replay-consumed until insertion,
  allowing its exact retransmission to recover it.
- `tx_before_radio` + `drop_ack`: suppress one ACK transmission; the repeated
  DATA must be rejected as duplicate for delivery and acknowledged again.
- `tx_schedule` + `duplicate` or `reverse_block`: send the exact retained frames
  twice or in reversed blocks of at most 32 within one message. Account for
  injected attempts separately; require unique reassembly and bounded timeout.

Retain up to 16 injection frames for `replay`/mutation; use the message buffer to
prepare a bounded reorder block. Fault hooks exist only in a declared laboratory
test build and never silently activate in normal runs. Fault location is part
of saved evidence. Do not infer authentication correctness from a CRC failure.

## 10. Voice, artifacts, memory limits and timing

### Audio choice and representation

Pin Codec 2 release **1.2.0**, mode **3200**, with unmodified packed codec frame
bytes and default codec settings. Record release, resolved source commit and
build flags in the firmware manifest; the lockfile captures the exact downloaded
source digest. Use a fresh encoder/decoder state per message. Its mode uses 160
samples per frame and 64 encoded bits: at 8 kHz, 20 ms → 8 bytes. A three-second
clip is 150 frames → **1200 encoded bytes** before the RF header/tag overhead.
At the default fragment size this is eight DATA packets. These are format
calculations, not a guarantee of intelligibility or continuous RF feasibility.
[Pinned codec implementation](https://github.com/drowe67/codec2/blob/1.2.0/src/codec2.c)

Node artifact format is signed 16-bit little-endian mono PCM, 8000 samples/s;
host WAV is the container used for import/export. Capture exactly 24000 samples
for the baseline. Accept reference clips of 1–24000 samples, zero-pad only the
last codec frame, record the original count and trim after decode. Fixed gain,
no AGC/noise suppression in v2; record I2S conversion/gain in the board manifest.
Use board-correct I2S RX/TX conversion and calibrated sample-rate checks. Capture
and playback are sequential; auto-play is an explicit prepared-run option.

Encoded artifacts contain the raw sequence of eight-byte frames with metadata
in their manifest, not an extra undocumented file header. Manifests include
`kind,format,codec,sample_rate_hz,sample_count,frame_count,length_bytes,sha256,
source_artifact_id`. Codec is null for PCM and `codec2_3200_v1` for encoded data.
The receiver knows format and source count from the prepared run. Compare TX/RX
encoded-message SHA-256 before assessing transport correctness. Individual
authenticated fragments and consistent metadata gate reassembly; the host then
compares final digests, including when microphone output was not known beforehand.
Lossy decoded PCM is assessed by playback/listening, not source-byte equality.

`VOICE-03` is a 60-second paced encoded-source experiment at 8 bytes/20 ms,
forming 1200-byte messages every three seconds. The bounded encoded queue holds
4800 bytes including the current partial/active message. Source generation never
slows to match the radio; overflow drops a whole source message and reports its
bytes/samples. Record producer/consumer rates and occupancy at 5 Hz. Assess the
post-startup interval after three seconds, plus all startup/drain durations.
This measures sustained encoded-source feasibility; store-and-forward speaker
playback is a separate observed mode, not a claim of continuous audio streaming.

`VOICE-04` uses the same three fixed reference clips across configurations and a
five-point listening rubric: 1 unintelligible, 2 occasional words, 3 meaning with
effort, 4 mostly clear, 5 clear. Save listener identifier, clip order and notes.
No universal pass score is invented; correctness and feasibility are separate.

### Artifact transfer and resources

Use Base64 chunks of at most 1024 raw bytes, contiguous offsets, **CRC-32/ISO-HDLC**
(the standard `zlib.crc32` result) formatted as eight lowercase hex digits, and
SHA-256 lowercase hex over exact artifact bytes. Duplicate chunks with matching
offset/bytes return the same next offset; conflicting bytes fail. Final commit
checks length/hash. Cancelled/failed uploads remain uncommitted and are deleted
on session close. Content is immutable after commit. Artifact reads are outside
the timed RF window and cannot steal bandwidth during an active measurement.

Initial ceilings: 65536-byte RF messages, 4096 fragments, 131072 bytes per node
artifact, four node artifact slots and 262144 total artifact bytes. Nodes report
lower honest limits when necessary; prepare rejects oversized work before arming.
Artifacts remain until explicitly deleted or the node reboots; never silently
evict an artifact in use. Host retrieval after a run precedes session close.
Diagnostic-only boards need not allocate full RF/audio buffers. Full audio
capability requires successful buffer/codec preflight on the actual board.

### Timestamp definitions and synchronization choice

Record `tx_command_us` immediately before the radio transmit command and
`tx_done_us`/`rx_done_us` at the radio DIO ISR. Record `accepted_us` after auth/
replay checks and message/audio stage start/end timestamps at their named stages.
These are software observation points with measurable capture latency. Do not
label `tx_command_us` an exact on-air start. MODEL-01 records radio ramp/command
overhead separately when comparing command-to-done time with predicted airtime.

RTT is sender-local ECHO_REPLY acceptance minus request `tx_command_us`, including
both airtimes and peer turnaround. Report success count, timeouts, median and
nearest-rank p95 (`ceil(0.95*n)`), with sample count and low-sample caution.

TIME-02 uses a common 3.3 V pulse source from Node A routed to **capture inputs
on both nodes**, sharing ground. Capture the physical edge on A too; the software
command to generate it is not the reference timestamp. Pins live in the board
manifest and must be distinct from radio/USB/I2S/display assignments. Arm both
inputs in continuous mode (`count:0`), then collect the first 32 rising edges
100 ms apart; require matching counts and intervals. Isolated fixture checks
use `count:32` on capture and source. Any missed/extra edge invalidates the batch,
rather than shifting
pulse indexes. The host fits `time_A_us = scale * time_B_us + offset_us`.

Continue pulses at 10 Hz during timing runs and refit over the latest 32 paired
edges. Calibration expires after two seconds without a valid update, on reset,
on a changed capture configuration or on missed edges. Validate capture latency
and skew with a logic analyzer/scope using capture markers on both boards under
representative RF/audio load. Save the instrument trace and board build with the
calibration; fit residual alone is insufficient to establish the bound.

Reported uncertainty includes the validated capture-latency/skew bound, maximum
fit residual, timer quantization and drift extrapolation since the last pulse.
Require total uncertainty ≤1000 µs for a valid v2 one-way sample. Report both
command-to-RX-done and command-to-application-acceptance with their phases and
uncertainty. If the fixture/equipment is absent, TIME-02 is blocked and RTT remains
available. This quality limit is a chosen measurement requirement, not a claim
that the hardware has already achieved it.

## 11. Measurement, completion and persistence rules

Sender summary includes intended/started/finished messages, original DATA/ECHO
packets confirmed TX-done, all transmission attempts, retries, ACK successes/
timeouts, useful source bytes, stop reason and the first-TX-command/last-TX-done
window. Receiver summary includes radio observations, unique accepted fragments,
duplicates/replays/auth failures, delivered/failed messages, useful delivered
message bytes, missing ranges, allocation/audio errors and its local receive
window. Both include boot/session/run, config revision, telemetry drops and
measurement-validity reasons. ACKs and ECHO replies are separate traffic classes.

Wire summaries contain totals/validity, not unbounded message lists. Detailed
missing ranges use `message.missing` events; losing a part makes that message's
detailed evidence incomplete. All replies/events must fit the 4096-byte ceiling.

PDR = unique accepted original DATA/ECHO_REQUEST packets matched to confirmed
original TX-done identities / confirmed original packets. A retry adds an attempt,
not a denominator entry. Reassembly completion rate is a separate message metric.
Unmatched RX/TX identities and summary/event disagreements require reconciliation;
do not clamp away an impossible count or turn missing serial telemetry into RF loss.

Report two explicitly named rates: `accepted_fragment_bps` from unique fragment
bytes, and application `goodput_bps` from complete delivered message bytes. Both
use the sender first-command to last-DATA-TX-done interval for the finite-run
transfer-rate view. Include that interval and the drain policy. Also report
whole-transaction duration and, with valid clocks, delivery-window goodput; never
mix these definitions in one comparison. Voice sustained rate uses its declared
source/observation interval, not a later drain that hides backlog. Zero denominator
or invalid timing produces null with a reason, not zero.

The host retains raw validated events, diagnostic counts, requested/applied
configuration, build/schema/profile hashes, clock mappings, source artifacts,
analysis version and environment notes. Exports exclude keys and raw secret
commands. Missing/drop-corrupted evidence makes dependent assessments inconclusive.
Execution status is completed/cancelled/failed/interrupted/blocked; assessment is
pass/fail/inconclusive/not_assessed. Performance without an agreed target remains
exploratory. Every required direction/fault case has its own coverage record.

Airtime model `sx126x_lora_v1` inputs include full protocol header/body/tag length, preamble,
SF/BW/coding rate, CRC/header mode and applied LDRO. Use a versioned SX126x model
validated against the radio documentation, independent vectors and hardware;
include the constant payload-symbol term omitted/misrepresented in some informal
formulas. For the selected SF7–12, explicit-header profile, use symbol duration
`2^SF/BW` and payload symbols
`8 + max(ceil((8*PL - 4*SF + 28 + 16*CRC) / (4*(SF - 2*DE))) * CRden, 0)`.
`PL` includes all protocol header/body/tag bytes, `CRC=1`, `DE` is applied LDRO
and `CRden` is 5–8. Airtime in microseconds is the ceiling of
`(preamble_symbols + 4.25 + payload_symbols) * 2^SF/BW * 1000000`.
Keep quarter-symbol arithmetic exact until the final rounding. Reject unsupported
modem profiles instead of extrapolating this formula. Message prediction adds all fragment attempts, ACK airtime/waits,
processing and guards. Node-provided previews and host previews must agree on
inputs; conflicting budgets block prepare instead of selecting the shorter one.

## 12. Adoption and changes after Homar's review

Implementation order: schemas/conformance examples → diagnostic ESP-IDF target →
physical v2 execution adapter → live node UI → finite known-data runs →
remaining capability families. Implement unsupported commands as explicit
`MISSING_CAPABILITY`/`UNSUPPORTED_COMMAND` responses until the feature exists.
Do not advertise a capability before its conformance checks pass.

The current `/api/protocol/v2` describes the diagnostic subset. Execution
metadata is separate and advertises no execution modes until physical support exists. Preserve old run records with their original protocol/analysis versions;
v2 terminology must not retroactively relabel synthetic v1 timings as hardware.

Review D01–D17 with Homar. Changes update this document, default profile, schema,
golden fixtures, host adapter and firmware together. Record the decision date and
reason; bump versions according to section 2. No further architectural choice is
required to begin. Actual hardware capability, build success, calibration bounds
and performance still require measurement.

## Reference basis

These sources inform the implementation choices; this contract defines the
project's own wire format and operational policy.

- [ESP-IDF v6.0.2](https://github.com/espressif/esp-idf/tree/v6.0.2) and
  [USB Serial/JTAG](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-guides/usb-serial-jtag-console.html).
- [Mbed TLS GCM interface](https://mbed-tls.readthedocs.io/projects/api/en/v3.6.4/api/file/gcm_8h/);
  use the implementation supplied with the pinned ESP-IDF, with its known-answer tests.
- [Codec 2 pinned release](https://github.com/drowe67/codec2/releases/tag/1.2.0)
  and [upstream maintenance notes](https://github.com/drowe67/codec2): mode 3200
  is retained as the actively maintained legacy codec mode. Include upstream
  source/license notices and the exact build provenance with distribution.
- [Semtech SX1262](https://www.semtech.com/products/wireless-rf/lora-connect/sx1262)
  and [official SX126x C driver](https://github.com/Lora-net/sx126x_driver), adapted
  behind the firmware's radio interface with board-specific front-end handling.
- [Heltec hardware documentation](https://wiki.heltec.org/docs/devices/open-source-hardware/esp32-series/lora-32/wifi-lora-32-v4/)
  for the eventual identified revision; generic diagnostic firmware cannot assume
  this radio, USB route, pin map or RAM configuration.
