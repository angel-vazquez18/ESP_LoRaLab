# One-node audio matrix

## Microphone capture and playback

VOICE-01 C1 reviews a three-second microphone recording and its raw
playback. C2 adds a Codec 2 encode/decode round trip and reviews playback
of the decoded file. The review can run from saved records after
disconnecting the node.

1. On **Bench**, capture 24,000 samples while speaking the selected
   utterance. Retain the capture operation ID and check its verified WAV.
2. For C1, play the recorded PCM on the same node. For C2, run the
   codec operation on that recording and play the decoded PCM. Retain
   the operation IDs. Record what you heard on the playback job.
3. In **Experiments**, select **VOICE-01**, **C1** or **C2**, and the
   role and workload used on the bench. Enter the saved operations in
   **Saved microphone and playback evidence (JSON)** and preview.
   Each utterance and repetition needs its own capture and playback
   records within that group.

```json
[
  {
    "group": "C2",
    "role": "B",
    "utterance": 1,
    "repetition": 1,
    "capture": "422ed491-22a7-4319-9949-aee83ab1739f",
    "codec": "20db796e-a60a-48fe-9fe9-34022180ee95",
    "playback": "09fae31a-4d41-4b87-a544-52cd0c5c8910"
  }
]
```

Omit `codec` for C1. The CLI takes the same array in
`local_voice_evidence` on the `integration-matrix` request. Save the
original WAV and the C2 encoded and decoded artifacts from the result.
Expect 48,000 PCM bytes and, for C2, 150 verified mode-3200 frames
totaling 1,200 encoded bytes. An audible playback with a verified
non-silent capture passes its case. A recorded inaudible result fails
the listening check. Near silence or missing listening evidence leaves
the case inconclusive. Complete digital evidence is retained in either
case. After saving the evidence, delete the test artifacts through the
node's file controls.

## Fixed reference

VOICE-01 C3 runs a saved three-second PCM reference on one selected node.
The runner verifies its staged upload, Codec 2 encode/decode, readback and
playback command completion. The expected sizes are 48,000 PCM bytes and
1,200 encoded bytes. The saved case links the codec and playback records.
It reports physical listening separately.

Choose VOICE-01 C3 and select a node and reference under **Experiments**.
A quick check needs one compatible node and one saved 24,000-sample clip.
Expect a source, encoded and decoded manifest, a playback command result
and confirmed cleanup. The node's existing saved files are preserved.

## Negative controls and recovery

In **Experiments**, select **VOICE-01**, **C4** and one connected role.
The node needs one free file slot and room for a 48,000-byte capture.
Each case sends the advertised capture limit plus one, a committed
non-PCM file, uncommitted/failed PCM, an incorrect chunk CRC and offset,
and an incorrect final SHA-256. Expect explicit rejection before
playback and an unchanged upload cursor after the rejected chunks.

The runner then cancels a capture after the node acknowledges it. The
result keeps the original cancellation, terminal reply, cleanup time,
verified 160-sample recovery WAV and following playback. Only the test
artifacts are retired. Compare the initial and final inventories and
the node's idle state. The fixture exercises all controls on one node.
Bench qualification still requires the full repetitions, measured
sample rate, and human listening observations.
