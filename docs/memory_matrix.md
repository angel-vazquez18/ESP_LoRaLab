# Sampled memory procedures

MEM-01 C1 runs a finite idle observation on either selected node. The
procedure defaults collect 30 seconds per repetition at the firmware's
100 ms sample period. The assessment checks an idle timeline and a normal
deadline on the same device and boot.

C2 runs known data at 64, 160, 321, 1200 and 48000 bytes, plus the pair's
negotiated maximum with duplicates removed. Start observers on both nodes
before the radio run. Save their observation IDs, require the same
radio run ID on recorded workload stages, and keep a post-run idle window.
The default window is 30 seconds. The runner uses the existing verified
known-data path for exact readback and stops both observers during cleanup.
Each memory report links its raw readback, independent sample reconciliation,
observed minima and named buffer lifetimes. Boot minima and sampled minima
stay distinct. A retained snapshot cannot resolve shorter allocation peaks.

For a quick one-node check, choose **MEM-01**, **C1** and **Quick check** in
Experiments. Select the connected role, preview the case and run it. Expect
a one-second idle observation followed by a saved case with a memory
assessment link. To preview a matching CLI request, save this as `memory.json`.

```json
{"catalog_id":"MEM-01","groups":["C1"],"roles":["A"],"repetitions":1,"memory_window_ms":1000}
```

```sh
uv run --project testbed lora-testbed integration-matrix memory.json --preview
uv run --project testbed lora-testbed integration-matrix memory.json
```

For a paired check select C2 and connect both compatible roles. Expect two
separate memory records linked to the same radio run. The intended operating
range, frequency of sampled observations and cleanup are explicit in each
result.

## C3 audio stages

Select either role to assess microphone capture, encoding, decoding and
playback. The capture case saves exactly 24,000 PCM samples. The codec and
playback cases use a reproducible silent 48,000-byte PCM fixture. Encoding
and decoding share a codec round trip and report separate stage samples
linked to the firmware's command identities.

Select both roles for reassembly and integrated voice. Reassembly captures
and encodes on the sender, then verifies independent readback of the
1,200-byte encoded artifact on the receiver. The receiver does not decode
or play it. Integrated voice continues through decoding and playback.
Both cases save separate observations for each node.

Each tracked stage includes its preceding sample, sampled internal and
PSRAM minima, the smallest sampled largest free block and the maximum
sampled bytes in named live buffers. Heap changes use the immediately
preceding baseline. Sampling may miss a short-lived allocation. Preexisting
artifacts are preserved. Native fixtures cover the workflows and ownership
cleanup. Physical microphone capture and speaker playback still require
bench confirmation.

C4 device-side allocation refusal and C5 deliberate cancellation/failure
with declared recovery bounds are still pending.
