# Two-node voice comparison matrix

## Reference voice

VOICE-02 C1 uses up to three explicitly selected three-second 8 kHz mono
PCM references. Each reference has 24,000 samples. The default plan
selects three repetitions per direction. Reference identity is recorded
before the case is armed. An incompatible length, altered source or
unavailable codec, RF or playback capability blocks the affected case.

The existing voice service uploads the source, verifies the Codec 2
artifact, transports and reads back 1,200 encoded bytes, decodes them,
and records playback command completion. It also runs two matched
known-data comparisons for 1,200 and 64 bytes. The matrix checks applied
radio and link settings, exact recovered content, and both comparison
workloads. The saved case links the original voice inspection, which
keeps local stage timings, waveforms and related radio evidence.

In **Voice workspace**, upload a three-second reference. Then choose
**VOICE-02** in **Experiments**, select C1, choose that clip and a
direction, and preview. With both compatible roles available, a quick
check runs one selected clip and retains the encoded/recovered hashes
and two distinct data comparisons. The CLI accepts the same reference IDs
as `voice_reference_ids` in an `integration-matrix` request.

The reference matrix keeps listening pending until a person records
playback observations. Cross-node one-way delay requires separately
qualified calibration.

## Microphone-origin voice

1. Connect both compatible roles in **Voice workspace**. Choose the
   microphone source, direction, 24,000 samples and both data
   comparisons. Speak the planned utterance into the transmitter's
   microphone when the run starts.
2. Listen to the receiver and record the result on the completed
   voice run. Keep its run ID. Repeat with the other node as the
   microphone source and use separate records for each utterance
   and repetition.
3. In **Experiments**, select **VOICE-02**, **C2** and the required
   direction and workload. Paste the saved run IDs into **Saved
   microphone voice runs (JSON)**. Preview and run the review. The
   saved review can run after both nodes are disconnected.

```json
[
  {
    "direction": "A_TO_B",
    "utterance": 1,
    "repetition": 1,
    "voice_run_id": "422ed491-22a7-4319-9949-aee83ab1739f"
  }
]
```

The CLI uses the same array in `voice_microphone_evidence` on the C2
matrix request. The full plan has 18 cases, with three utterances and
three repetitions in each direction.

Each reviewed case links the source and decoded WAVs, exact recovered
Codec 2 bytes, and the voice inspection. Expect a non-silent 48,000-byte
microphone capture, a verified 150-frame/1,200-byte protected transfer,
playback on the receiver, and separate 1,200-byte and 64-byte comparisons
with fresh sessions and matched settings. Missing listening or a damaged
archive leaves the case inconclusive. A saved report of inaudible
playback fails its listening assertion. Full physical repetitions and
cross-node timing qualification remain separate.
