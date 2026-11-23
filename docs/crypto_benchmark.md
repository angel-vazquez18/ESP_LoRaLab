# Local crypto measurements (#53)

The main image implements `diag.run` with `kind:crypto_benchmark` on one owned,
idle node. No peer, radio configuration or RF session is required. It uses only
fixed public diagnostic vectors, a separate volatile PSA key handle and the
same pinned Mbed TLS 4.1.0 / TF-PSA-Crypto 1.1.0 provider as the frame primitive.
Ordinary session keys and sequence owners are never borrowed or modified.
This does not enable the protected RF capability.

## Work and measured interval

Arguments are `kind`, `iterations` (1–10000, default host request 1000) and
`payload_bytes` (16, 64, 160 or 199). Each batch visits four separate paths:
AES-GCM encryption, valid decryption, invalid-tag rejection, and a copy baseline.
Every path has one **first call in this batch**, 50 warm-ups, then the requested
number of timed calls. The first call is not a claim of cold-boot/provider timing:
previous diagnostics and the preceding path may already have warmed the provider.

The timestamp pair immediately encloses one `psa_aead_encrypt` or
`psa_aead_decrypt` call. Key import, caller-buffer allocation, input construction,
output checks, wiping, JSON, USB and RF work are outside it. Work internal to the
one-shot PSA API remains inside; this is API cost, not an isolated AES block
instruction. Encryption/decryption output is compared with fixed independent
conformance bytes after every call, including warm-ups. Invalid-tag samples must
return `PSA_ERROR_INVALID_SIGNATURE` with zero output length. Scratch plaintext
is wiped and never exported.

The copy path encloses `memcpy` of `payload_bytes + 16` public ciphertext/tag
bytes to the same fixed-size output buffer, followed by a separate exact output
check. It has no authentication cost. Preserve this baseline separately; do not
automatically subtract it or present it as equivalent security work.

All buffers are non-overlapping, fixed-size members of a default-heap context:
215-byte output, 215-byte altered ciphertext, borrowed read-only public source
vectors and at most 16 pending samples. PSA may allocate internally. There is no
caller allocation per sample and no message/audio buffer. At most 16 operations
or approximately 2 ms of work occur per control tick; one slow crypto call cannot
be preempted by this loop. Normal USB/health/keepalive and cancellation remain
available between slices. The existing 30-second operation deadline applies;
large batches can honestly end with partial counts on a slower target.

## Records and compatibility

The additive `local_crypto_benchmark_v1` supplement has its own generated schema
and exact public-vector SHA-256 in identity/current-health resource limits.
The diagnostic, main-control, artifact, audio and execution schema hashes are
unchanged. Old images without this declaration fail before a benchmark command
is sent. A decoder accepts benchmark pages only after matching main-node identity
and current capability negotiation. The planned per-frame `crypto.sample` event
has not been substituted or advertised.

`crypto.benchmark` pages identify operation, payload size, path, phase, page index
and first sample index. Each contains up to 16 `[start_us,end_us,checked]` entries
in the node's monotonic boot clock. Both timestamps are retained, even when their
difference is zero at 1 µs resolution. Zero-resolution samples are not invented
or rounded upward. Queue pressure pauses generation; a failed enqueue retains
its page for another attempt. Telemetry-drop counters remain honest.

The terminal `operation.result` includes exact checked counts per path/phase,
pages emitted, any discarded pending samples, requested size/count, schema/vector
fingerprints, configured CPU MHz, dynamic-frequency and hardware-AES settings,
timer resolution, buffer/measurement policy and stop reason. `hardware_aes_configured`
records a build setting, not proof that every size took a hardware path. CPU MHz
is the configured frequency, not a measured instantaneous clock under power
management. The build identity remains attached to the node evidence.
A failed benchmark may carry this typed partial result alongside its error;
other failed control operations retain their null-result rule.

Stop, lease loss, USB loss, reset and deadline expiry destroy the diagnostic key
and temporary buffers. A backend key-destruction failure retains the context for
cleanup retry and reports failure. As elsewhere, USB loss, reset or an exhausted
writer may prevent a terminal record from reaching the host: missing evidence
stays incomplete. It never implies completion or zero work.

The host stores raw pages/terminal records in `node_observations`. Evidence lookup
is operation/role scoped and bounded at 40,500 rows. `assess()` independently
reconciles every page, sample index, clock ordering, node/boot/role/run identity,
checked output and terminal count. Cancelled, failed, lost, duplicate, reordered
or missing evidence returns explicit reasons and **no timed distribution**.
First calls and warm-ups never enter the timed-only lists. This service does not
supply full SEC-04 procedure qualification or a new dashboard panel.

## Review and software checks

Read in this order:

1. `firmware/lora_node/main/security/crypto_benchmark.c`: actual timed calls/checks.
2. `firmware/lora_node/main/control/node_control.c`: ownership, bounded pages and cleanup.
3. `testbed/src/lora_testbed/crypto_benchmark_v2.py`: typed supplement and evidence assessment.
4. `testbed/tests/test_crypto_benchmark_native.py`: public serial/API checks against real PSA.

From repository root, with the pinned IDF sources and CMake installed:

```sh
uv run --project testbed pytest testbed/tests/test_crypto_benchmark_native.py -q
make check
idf.py -C firmware/lora_node build
```

The focused cases must run without skips. All four sizes must show exactly 4204
checked samples for 1000 iterations: four paths × (1 + 50 + 1000). Missing pages,
cancelled work and a regressing timer must never yield a complete distribution.
The API case uses a test-only C-backed serial fixture; it opens no physical port.
Native clock/provider results are not ESP32 performance measurements.

## Later physical checks

After normal identity/revision/wiring/backup checks, install the matching image
and start the matching backend. Do not send this command to the older audio image
or assume the currently running backend includes a pending PR. Attach A or B with
the existing `node` command; the backend owns serial and renews the lease.

```sh
uv run --project testbed lora-testbed crypto-benchmark A --payload-bytes 16 --iterations 1000
uv run --project testbed lora-testbed crypto-benchmark-result A OPERATION_UUID --records
uv run --project testbed lora-testbed operation-stop A OPERATION_UUID
```

The start command returns an accepted operation UUID, not a completed batch.
Use that UUID in the result command; `assessment.complete` becomes true only after
all matching evidence arrives. Redirect `--records` output to a private local JSON
file to retain each batch. Its timed lists must contain 1000 entries for each
of the four paths. The same API is `POST /api/nodes/A/crypto-benchmark`, with
`{ "iterations":1000, "payload_bytes":16 }`, and
`GET /api/nodes/A/crypto-benchmark/OPERATION_UUID?include_records=true`.

Repeat each 16/64/160/199-byte batch **three times on each physical node**, retaining
separate operation IDs, device/boot/build identity and CPU/acceleration settings.
Check every output/count and inspect quantization; do not pool different builds,
clock domains or failure paths. Stop a longer batch and verify partial counts,
idle state and recovered heap/key capacity before a following successful batch.
Disconnect/reset recovery must be recorded as interrupted/incomplete if the final
record is unavailable. These physical repetitions, acceleration attribution,
loaded-target stack/heap checks and full security qualification (#67) remain
pending; no board was flashed or queried for this implementation.
