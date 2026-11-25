# Reference voice comparison matrix

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

C2 remains blocked until microphone cases have a coordinated utterance
schedule. The reference matrix keeps listening pending until a person
records playback observations. Cross-node one-way delay requires
separately qualified calibration.
