# Named memory observations

Issue #73 adds an optional finite observer alongside the existing control owner.
It collects idle, data and local audio/codec/diagnostic stages without claiming a
continuous heap trace or true allocation peak. Existing ordinary health remains
available. Physical memory qualification and the assessment/dashboard workflows
remain following work under #82/#88/#132.

## Reading order

- `memory/observations.c`: fixed observer state, 100 ms schedule, actual sample
  times, observed lifetimes/minima, bounded stop and missing/drop accounting.
- `memory/buffers.h`: bounded owned ranges, exact-alias suppression and overlap/
  truncation flags. Addresses stay private and never enter JSON.
- Module `*_memory` functions: each opaque owner reports its own actual pointer
  and requested size. `control/node_control.c` composes those inventories and
  stage/ownership hooks, while the common writer serializes their records.
- `platform/esp32_platform.c` and `audio/esp32_audio.c`: actual internal/PSRAM
  address classification and the allocated playback stereo buffer.
- `memory_observation_v2.py`, generated schema/header and `nodes.py`: independent
  exact-profile controls, typed evidence and bounded host observation history.

## Control and lifetime

Use the backend's already-owned `NodeSession` for these calls:

```python
started = await node.request("memory.start", {"duration_ms": 90000})
status = await node.request("memory.status")
await node.request("memory.stop", {"observation_id": started["observation_id"]})
```

Start accepts 1,000–300,000 ms, returns a fresh observation UUID, deadline and
100,000 µs period, and rejects a second active observation. Commands require null
`run_id` and the existing USB control owner. Mutation retries use cached replies
without restarting sampling or repeating stop; status uses fresh read sequences.
Wrong IDs reject. Stop, deadline, control release, lease loss, USB loss and shutdown
end observation; reconnect/reset never resumes it. Status retains actual start/
stop times, reason, deadline overrun, counts and observed minima for reconciliation.

The observer can remain active across `run.stop`/`session.close` to collect the
required recovery window under the same control owner. It owns fixed metadata,
not application payloads or session keys. Owner loss ends it. Data/voice continue
to use the ordinary finite workload and bench ownership paths. API/CLI procedure
controls and plots follow #82/#88. The full-v2 `instrumentation.memory_10hz` run-spec
flag remains unsupported by the current finite RF subset; these independently
fingerprinted commands provide the implemented observation path.

The supplement is `stage_memory_observation_v1`, SHA
`4004d7803a7a4f04f4a1da3fb7d1425a1200293ce60b6a62887075a8858730b5`.
Enrollment declares profile/hash; fresh current health repeats the exact hash.
Missing or mismatched identity/current declarations block commands before writing.
Other diagnostic/control/execution/artifact/audio/codec/PTT/OLED hashes are unchanged.
Static radio board reference/qualification and IRQ-phase metadata stay in identity;
current health keeps live driver errors and all existing typed capability gates.
This avoids repeating enough static data to exceed the existing 4 KiB record bound.

## What a sample means

`memory.sample` records actual boot-local `taken_us`/`finished_us`; heap queries and
inventory inspection occur in that interval and are not atomic. Periodic samples
are scheduled every 100 ms from observation start. Stage entry/exit samples are
additional. A delayed tick records its actual time and missed intervals, without
fabricated catch-up rows. Stop/expiry accounts for unobserved intervals too.

The stage names describe observation points around actual work: preparing,
prepared, arming/armed, starting/running, draining/stopping/closing, capture,
encode/decode, play, waiting PTT, diagnostic and idle. Arming/starting are attempted
transitions, not successful RF evidence. Release hooks sample before working
buffers are freed. Local workload IDs are originating command UUIDs; RF workload
IDs are run UUIDs. Host traces and child links retain their relationship to
operation/job IDs. A new workload resets its observed minimum; the measurement
minimum spans the entire observer lifetime, including baseline and recovery.

| Field | Scope |
| --- | --- |
| `memory.internal` / `memory.psram` | Separate 8-bit-capable platform heap snapshots; absent PSRAM stays null |
| Heap `minimum_free_bytes` | Platform's boot-lifetime low-water mark |
| `measurement_minimum` | Minimum among heap snapshots actually taken in this observation |
| `workload_minimum` | Minimum and sample count for the named workload, retained after it exits |
| `known_buffers` | Up to 16 actual nonoverlapping requested ranges, region, generation and first observed time |
| `known_requested_bytes` | Sum of that known set, separately internal/PSRAM/unknown |
| `aliases_omitted` / `overlap_detected` / `inventory_truncated` | Explicit inventory limits rather than overlapping totals |
| `memory.allocation_failures` | Platform cumulative allocation failures; start/work samples preserve the baseline |
| `samples_dropped` / `missed_periods` | Serialization/queue losses versus scheduled periods that were never observed |

Names include controller/store metadata, artifact slots, RF source/sender/
reassembly/ACK owners and data, session/crypto wrappers, local codec owner/root
state, diagnostic buffers and real playback stereo storage. Borrowed artifact
references are not counted again. Exact aliases are omitted; partial overlap is
flagged and excluded from the sum. Unknown classification stays explicit.

These are requested bytes, excluding allocator bookkeeping/alignment. Provider
internals, nested DSP allocations, I2S private DMA rings/handles, task stacks,
other workers and transient JSON allocations are outside this named set; actual
heap snapshots still reflect platform allocations. `untracked_allocations:true`
keeps that limitation visible. Never add requested-byte totals to heap totals or
claim they explain every heap byte. Generation/first-observed time establish
observed lifetimes, not exact allocation timestamps. Activity wholly between
samples or inside a constructor can be missed; workload minima are not true peaks.

Counts/minima include snapshots taken even if their event could not be retained;
status reports the losses separately. The host retains at most 512 recent typed
samples, marks retention loss, exposes one last sample in live snapshots and makes
it stale after disconnect/health loss or observation age. Raw events retain boot/
device identity through the ordinary evidence callback; readiness is not physical
memory qualification. Observation serialization failure cannot poison primary
control serialization or prevent workload cleanup.

## Reproduce software verification

From repository root:

```sh
uv run --project testbed pytest testbed/tests/test_memory_observation_native.py testbed/tests/test_memory_observation_host.py testbed/tests/test_oled_host.py -q
make check
source /Users/anken18/.espressif/v6.0.2/esp-idf/export.sh
idf.py -C firmware/lora_node build size
```

Expected: actual 100 ms fixture timestamps, independent boot/measurement/workload
minima, matching named requested bytes, no exported addresses or borrowed-buffer
alias totals, finite capture/RF stop and restored known-buffer baseline. The
30-second idle/recovery fixture uses an explicit injected clock, not elapsed target
measurements. Allocation failure, delayed ticks and full telemetry preserve their
limits and cleanup. Profiles block before writes; reconnect never resumes work.

Twenty dedicated cases and full `make check` pass: 828 total, no skips, plus lint,
frontend build, generated contracts and repository/vendor checks. The selected
V4.2 / 32 KiB-stack ESP-IDF build passes: 0x711a0 bytes, 56% app free and 73,841
static DIRAM bytes. Static link size is not runtime heap/stack headroom. No flash
or physical acceptance occurred. The configured all-peripheral health check also
covers an active RF run, retained error and wide boot/uptime values within 4 KiB.

## Physical acceptance still required

After PCB/pin identification and the deployment backup procedure, record node/
boot/build/profile identities and predeclare the recovery band. With the observer
owned by the common backend:

1. Record 30 seconds idle, separating internal/PSRAM and boot versus observation
   minima; retain actual timestamps, named ranges and allocation-failure baseline.
2. Run finite known data and local/secure voice stages. Keep 10 Hz and additional
   stage observations; compare known requested sizes/lifetimes with actual paths.
3. Cancel at each relevant stage and inject supported allocation/driver failures.
   Record 30 seconds recovery before stopping the observer. Confirm owned buffers
   retire and compare the observed free/largest blocks with the declared band.
4. Record missed/dropped/retention counts and actual sampling intervals. Treat
   incomplete evidence and untracked/short-lived allocations explicitly; measure
   task-stack margins and instrumentation cost on target separately.

Software fixtures cannot establish target PSRAM placement, real low-water/stack
margins, sampling cost under load or a successful physical recovery band.
