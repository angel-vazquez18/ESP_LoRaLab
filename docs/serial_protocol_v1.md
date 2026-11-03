# Legacy simulator protocol v1

> Historical document. The November 1 physical-only decision supersedes the
> simulator workflows and commands below; those implementations were removed.
> See [current status](status.md) and [host usage](../testbed/README.md).

Status: implemented by the current simulator, retained for migration/reference.
The user authorized provisional contract decisions on October 18. New host and
firmware implementation targets `testbed_contract_v2.md` and its selected defaults.
The remaining text records the earlier draft and its then-open questions; it
does not override v2 or require waiting for firmware-developer approval.

## Transport and records

UTF-8 newline-delimited JSON. One record per LF; CRLF is accepted. The maximum
encoded line, including LF, is 4096 bytes. Partial reads are buffered. Malformed
or oversized lines produce diagnostics and resynchronize at the next LF.
Do not mix ESP-IDF console logs into this stream; use a separate log channel or
define a structured diagnostic event before enabling logs on the protocol port.

Suggested physical settings: 115200 baud, 8N1. The eventual ESP-IDF transport
(USB CDC, USB Serial/JTAG, or USB-UART bridge) and port behavior need agreement.
Opening a port must not be assumed to preserve node reset/boot state.

Current machine-readable schema is served at `GET /api/protocol`, generated from
`testbed/src/lora_testbed/models.py`. JSON objects reject unknown fields. Version mismatch
is a protocol error. Host IDs are UUID strings; on-node uptime is integer
microseconds since boot. Current events use node labels A/B; stable hardware
identity must be added/agreed before physical-node integration.

Command example:

```json
{"v":1,"kind":"command","command_id":"unique-id","name":"hello","run_id":null,"args":{}}
```

Reply example:

```json
{"v":1,"kind":"reply","command_id":"unique-id","node_id":"A","boot_id":"boot-uuid","ok":true,"result":{},"error":null}
```

Each node starts a new boot ID after reboot. A repeated command ID with identical
contents returns its original reply without repeating side effects. Reusing an
ID with different contents is an error. The simulator retains the last 256
command IDs per pair; physical cache size/lifetime and timeout retry policy need
agreement. Do not retry a start after reboot under the old session.

## Implemented simulator commands

| Command | Meaning / reply |
| --- | --- |
| `hello` | Return identity, boot ID, protocol version, capabilities, and settings |
| `configure` | Validate radio fields and return `result.applied`; this is applied-state acknowledgment |
| `arm` | Prepare a receiver for `run_id`; reply `receiver_ready` |
| `start` | Start the corresponding sender only after its peer is armed for the same run |
| `stop` | Idempotently return to idle |

Radio fields: `frequency_hz`, `bandwidth_hz`, `spreading_factor`,
`coding_rate_denominator` (5 means 4/5), and `tx_power_dbm`. Current simulated
limits are expressed in the schema. They are not a validated hardware or
regulatory configuration profile. The first UI uses the default preset only.

The host simulation runner currently controls finite packet count/pacing; a real
node must receive and enforce the complete finite-run specification, maximum
duration, receiver-drain/summary policy, and stop behavior. Those firmware command
arguments and acknowledgments are still to be finalized.

## Implemented simulator events

Every event contains `v`, `kind`, `node_id`, `boot_id`, increasing `event_seq`,
`run_id`, `uptime_us`, `name`, and validated `data`.

| Event | Data |
| --- | --- |
| `tx_done` | `origin_node`, `packet_seq`, `payload_bytes` |
| `rx_valid` | Same packet identity/length plus `rssi_dbm`, `snr_db` |
| `run_summary` | `role: sender`, `measurement_window_us` |

Packet identity is `(run_id, origin_node, packet_seq)`. Duplicates do not increase
unique delivery or useful bytes. A zero-sent delivery ratio is unavailable.
Throughput is useful accepted bits divided by the sender measurement window;
live values are provisional. Simulator timings include artificial pacing and
must never be labeled radio airtime or hardware goodput. Receiver values for
signal strength are synthetic.

## Contract extensions required for the full CDR

All extensions remain in scope and must be agreed before their runners ship:

- Stable device identity, full capability schemas, structured error codes,
  settings ranges/units and incompatible-version handling.
- Sender and receiver final counters, event-gap/drop detection, bounded drain,
  start acknowledgment deadlines, real serial timeouts, and reset recovery.
- Protected/unprotected packet profiles, key readiness (no secret telemetry),
  nonce/session/replay policy, altered/replayed-frame injection and outcomes,
  node-local encryption/decryption timing.
- Message/fragment IDs, total lengths and digests, missing fragments, reorder/
  duplicate handling, retransmission/ACK semantics and completion timeouts.
- Node-local echo timing; later clock calibration, drift, timestamp phases,
  uncertainty, and calibration invalidation on reset.
- ESP-IDF heap/buffer accounting at capture/codec/security/reassembly/playback
  stages, allocation failures and reset causes. Instrumentation details must
  be selected with the firmware developer.
- Audio formats/codec modes and limits; capture/encode/send/decode/playback
  commands, stage events and retained artifact IDs. Reference upload/retrieval
  uses bounded chunks with IDs, offsets, checksums, length, and cancellation;
  transfer large audio outside the timed RF measurement window.

See `test_experiment_catalog.md` for the complete mapping of firmware capabilities
to experiments. The first implementation intentionally blocks unsupported cases.

