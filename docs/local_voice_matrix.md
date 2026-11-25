# One-node reference audio matrix

VOICE-01 C3 runs a saved three-second PCM reference on one selected node.
The runner verifies its staged upload, Codec 2 encode/decode, readback and
playback command completion. The expected sizes are 48,000 PCM bytes and
1,200 encoded bytes. The saved case links the codec and playback records.
It reports physical listening separately.

Choose VOICE-01 C3 and select a node and reference under **Experiments**.
A quick check needs one compatible node and one saved 24,000-sample clip.
Expect a source, encoded and decoded manifest, a playback command result
and confirmed cleanup. The node's existing saved files are preserved.

The controlled microphone schedule and complete invalid-artifact/cancel
series remain open. The native fixture verified the local reference path
without a second node and checked that a preexisting artifact survived.
