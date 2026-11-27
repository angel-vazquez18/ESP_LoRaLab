# Fixed-rate encoded source (#74)

A finite VOICE-03 source repeats one committed 1,200-byte Codec 2 mode-3200
reference. It produces eight bytes every 20 ms independently of the radio and
USB control loop. This is encoded-source feasibility, not continuous microphone
encoding or speaker playback. The sustained-source host procedure/assessment follows #105; shared host
lifecycle integration is #75.

## Behavior and reading order

1. `firmware/lora_node/main/source/encoded_source.c` owns the portable single
   producer/single consumer queue, actual frame times and 5 Hz audit.
2. `source/esp32_source.c` reserves a dedicated task before preparation completes,
   wakes it only at accepted start, and joins it within a bounded wait. It never
   calls the radio or JSON writer. It is pinned to the control caller's core so
   confirmed suspension followed by deletion retires all task accesses.
3. `radio/rf_execution.c` consumes complete messages through the existing GCM,
   fragmentation and exact-byte retry path. Reassembly is reserved once; later
   authenticated messages reuse that reservation even after a hash failure.
4. `testbed/src/lora_testbed/source_protocol_v2.py` and `run_protocol_v2.py` define
   the exact source policy and readback. `NodeSession.request` validates the same
   arguments/results and preserves the ordinary command/record evidence path.

The new execution profile is `finite_message_execution_v3`. Both enrollment and
current health must match its exact generated schema. Older execution firmware
is rejected, not silently upgraded. Numeric execution limits are reported in
current health; immutable encoded-source and worker support declarations appear
in enrollment. Current encoded-source availability is still explicit. The general
one-message limit remains one; the fixed VOICE-03 variant alone declares twenty
messages of 1,200 bytes. Diagnostic and main-control schemas remain separate.

## Timing, queue and drain

The first nominal frame is at elapsed zero; the last is at 59.98 seconds. The
first complete message is available at 2.98 seconds. All 3,000 scheduled frames
represent 24,000 bytes at 3,200 bit/s. The source deadline is a half-open interval:
no missing frame is generated at or after sixty seconds. Late wakeups inside the
window retain their actual time, including shared timestamps for catch-up work.
Missed frames/periods remain explicit; planned time is never substituted for a
measurement.

Four slots hold at most 4,800 encoded bytes, including the active immutable radio
borrow, completed waiting messages and the current partial message. At each new
message boundary, lack of a free slot drops that entire new message even if space
returns midway through it. Admission/overflow/sent/failed/discard masks identify
message IDs 1–20 (bit zero is ID 1). Overflow counts produced bytes; a cancelled
partial dropped message can therefore contain fewer than 1,200 actual bytes.

Quiescent payload storage is retired at terminal cleanup; the evidence metadata
remains until session close. Metadata is separately bounded: 3,000 32-bit frame times, at most 451 full audit
snapshots, four slot descriptors and the worker/task resources. These are not
encoded payload capacity. The named memory observer reports known queue/trace/
audit allocations; kernel stack/TCB allocation overhead remains untracked.

`max_duration_ms` is 60,000–90,000. The source drain is that duration minus sixty
seconds; `budget.reassembly_timeout_us` equals the complete declared run duration; the
receiver adds the five-second arm allowance on its own clock. Slow configurations
can prepare without promising complete delivery. `budget.drain_us` separately retains the radio retry/re-ACK horizon.
Generation stops at sixty seconds, ready messages drain within the selected
source bound, and remaining queued/partial bytes are discarded at cutoff. Active
bytes remain borrowed until the radio is stopped/finished. A message that cannot
fit its conservative remaining fragment/retry budget is discarded before TX.
Recoverable retry exhaustion fails that message and continues production; driver
or crypto failure stops the run. Stop/owner loss/disconnect cancels production.

The source task must confirm quiescence before source/reference retirement. A
failed join reports `SOURCE_STOP_FAILED`, retains its buffers and artifact borrow,
blocks new work and permits a later `session.close` cleanup retry. Frame/audit
metadata remains available until close; committed reference files remain intact.

## Evidence and reconciliation

Owned `run.source` queries require the current run ID, including after `run.stop`
and before `session.close`. It is a read command and remains available when radio
readiness has failed. Arguments:

```json
{"view":"status","offset":0,"limit":1}
{"view":"frames","offset":150,"limit":16}
{"view":"samples","offset":15,"limit":1}
```

Frame pages contain at most sixteen records; sample pages contain one full
snapshot to preserve the 4 KiB wire bound. `next_offset` advances by returned
records. EOF means no more records currently published; after terminal stop it is
final. Live reads can race producer/consumer updates, so each status reports
`consistent`. Snapshot attempts are bounded, rather than blocking production.
5 Hz rows use their actual timestamp and count skipped intervals; gaps are never
filled with backdated copies.

For a consistent terminal sender snapshot:

- `produced_bytes = admitted_bytes + overflow_dropped_bytes`.
- `admitted_bytes = sent_bytes + failed_bytes + consumer_discarded_bytes +
  queue_discarded_bytes + partial_discarded_bytes + occupancy_bytes`.
- `frames_produced + frames_missed + frames_cancelled = 3000`.

`sent_bytes` means the sender finished all fragments (and requested ACK policy).
Only receiver message results and `delivered_message_ids` establish verified
whole-message delivery. A lost final ACK may make sender failure and receiver
success coexist; neither replaces the other.

The receiver publishes a 24,000-byte **known_data evidence archive**, never a
playable Codec 2 artifact. Message ID n occupies slot `(n-1)*1200`; holes remain
zero. Only completed hash-verified messages enter it. Its actual final digest and
explicit delivered IDs distinguish a hole from legitimate zero-valued content.
Missing IDs alone cannot distinguish producer overflow from RF loss. Read both
nodes' evidence before closing and retiring source metadata.

Assess startup `[0,3s)`, production `[3s,60s)` and final drain separately. Frame
indexes 150–2999 provide the 22,800-byte post-startup nominal source. The snapshot
at exactly three seconds already includes the frame at that instant, so simple
subtraction of inclusive byte counters is not the interval calculation. Keep
planned and actual timing separate and preserve incomplete/late sampling. #105
adds the host procedure and interpretation; this change does not qualify a radio
configuration as sustainable.

## Verification and later physical checks

```sh
uv run --project testbed pytest testbed/tests/test_encoded_source_queue.py testbed/tests/test_fixed_source_rf_native.py -q
make check
source /Users/anken18/.espressif/v6.0.2/esp-idf/export.sh
idf.py -C firmware/lora_node build size
```

Expected isolated checks: no-consumer/slow-consumer overload still produces
24,000 bytes; occupancy never exceeds 4,800; whole-drop IDs and discarded bytes
reconcile; concurrent reads preserve immutable message bytes; late wakes do not
invent post-cutoff frames. The paired C-node checks deliver twenty real protected
messages with unique sequences, independently decrypt and hash their contents,
retain archive holes on loss/hash failure, recover from lost/exhausted ACKs,
page frame/audit evidence and retain resources after a failed join.

No physical port or flash is used by these checks. Later, identify two distinct
compatible nodes, confirm the selected PCB/radio variant and antennas, release
USB ownership and follow the verified backup/build procedure before installation.
Run the host procedure from #105 with both a fast and an overloaded configuration.
Save actual task pacing/jitter, 5 Hz backlog/drop evidence, both node identities,
radio settings and final hashes. Confirm bounded stop/USB-loss recovery, real
heap/stack headroom, retained telemetry loss and no automatic restart. RF/audio
qualification remains separate; do not infer it from the software fixture clock. Physical sustained-source qualification is #136.
