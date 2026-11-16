# Single-node audio qualification — operator handoff

**Status: incomplete.** The implementation PRs provide finite local audio and
byte verification. They do not yet prove a functioning microphone/speaker path.
Issue #42 stays open/draft; physical USB recovery #21 is also still a prerequisite.
No PR is automatically merged and no packet tool closes a qualification issue.

The user confirmed documented wiring on November16 but is away. The exact
**printed board revision** means the version printed on the circuit board, such
as V4.2; it is different from ESP32 chip revision. It remains unobserved.

## Current evidence and gaps

| Check | Observed | Qualification |
| --- | --- | --- |
| Identity/build/control | Physical `esp-f85b1ba27744`, exact schema and ELF matched | Automated checkpoint only |
| Output | Quiet source consumed exact DMA/source counts; cancel/recovery passed | Nobody has reported hearing it |
| Input bytes | 24000 samples / 48000 bytes, independent SHA/readback/WAV verified | Every PCM sample was zero |
| Input signal probe | Both raw slots remained zero after startup; repeated 800-sample probe failed `SIGNAL_UNVERIFIED` | Microphone response unverified; physical cause unknown |
| Sequential workflow | Capture → retrieve → play, priority stop and following operation passed | No acoustic response claim |
| Invalid input | Real bad CRC/SHA, odd PCM and uncommitted playback rejected; following valid audio passed | Raw error/recovery evidence retained |
| UI availability | Actual disabled image disabled controls; audio image restored; history retained | Firmware configuration, not wiring proof |
| Wiring/revision | User-reported wiring; 8 Ω / 1 W speaker, amp VIN/GAIN/SD at 3.3 V | Printed revision/electrical inspection pending |
| Clock / 3.3 V rail | Configured/calculated rates only | Instrument availability and measurements unknown |
| USB loss/reset recovery | Normal reconnects observed | Full #21 procedure remains open |

See [driver behavior](node_audio.md), [host workflow](node_audio_workflows.md) and
[browser check steps](local_audio_ui.md). The source checkpoint is summarized in
[evidence/local_audio_2026-11-16.json](evidence/local_audio_2026-11-16.json); raw data
and WAVs remain on this laptop under ignored `local/m2-batch/`.

## Prepare the packet

An unattended packet is already prepared at `local/m2-batch/qualification-packet`.
Its operator observations are intentionally blank; actual automated invalid/cancel/
recovery reports and hashes are already copied into it. Instrument availability
remains unknown. To start another independent session:

```sh
python3 scripts/audio_qualification.py prepare local/audio-qualification/session-01 \
  --device-id esp-f85b1ba27744
```

This creates a known three-second 8 kHz/16-bit/mono raw PCM and WAV reference:
440 Hz, peak ≤1000 PCM units, 320-sample fades, no clipping, plus source SHA and an
observation form. The firmware applies its separate 1/8 output amplitude and
records the configured 6 dB amplifier gain. The generator does not open serial,
flash, start playback or assume anyone heard audio. Existing packets are not overwritten.

## Attended steps and expected results

1. **Inspect the board and connections before relying on audio.** Record printed
   revision/photo, physical identity, exact breakout markings, shared ground,
   microphone 3.3 V, SCK4/WS5/SD6 and L/R→GND; amp BCLK38/WS39/DIN40, VIN/SD/GAIN→3.3 V;
   8 Ω / 1 W speaker across OUT+/OUT−, with neither lead grounded. Compare with
   [the hardware reference](../hardware/README.md). The second board still lacks
   amplifier/speaker wiring; do not enable its playback path yet. GNSS stays disconnected.
2. **Investigate zero input.** Check delivered microphone enable/strap wiring,
   supply/ground and actual clock/data connections. With equipment, inspect WS,
   BCLK and SD at the microphone. Input is configured for WS8kHz, BCLK512kHz, two
   32-bit Philips slots, grounded L/R left slot. A capture discards 600 ms startup.
   Raw left/right nonzero counters are in its driver details. Current zero raw
   slots rule out fixing this observation merely by selecting the other slot or
   changing PCM scaling. The physical cause is not established. Record actual
   findings; do not rewrite a wiring profile or mark response passed by assumption.
3. **Check output independently.** Start `make serve`, connect the identified node,
   upload packet `quiet-reference.pcm` as **Raw PCM · 8 kHz, 16-bit mono** and wait
   for independent verification. Save its upload job/source hash. Choose **Play file
   on node**. Expect 24000 source samples, completed DMA and no missed-deadline
   indication. Listen at the speaker and record heard/not-heard, distortion and
   setup notes separately. A quiet reference may be faint; do not substitute a
   microphone capture for this independent output check or infer sound from counts.
4. **Record a known phrase, then a quiet interval.** In **Local audio**, choose
   **Capture 3 seconds**, speak a short recorded phrase after startup, and wait for
   retrieval. Repeat for quiet. Expect exactly 24000 samples/48000 PCM bytes and
   independent hashes, with 8kHz/16-bit/mono WAV headers. Speech should produce a
   changing, nonzero waveform without clipping. All-zero speech is a failed signal
   check even when its byte/hash checks pass. Write the actual phrase and response
   observations. Laptop playback is only inspection; it does not test the node speaker.
5. **Play the captured speech on the node.** Capture and playback are sequential.
   Record driver counts/gain and actual heard output/distortion independently.
   While playing, capture must be unavailable. Keep the source/upload, speech/quiet
   files, operation IDs and their build/boot identity together.
6. **Measure clocks/rail or state actual limitations.** If instruments are available,
   record instrument/model, setup, method, observed WS/BCLK and 3.3 V rail minimum/
   maximum under audio load, with traces. Output uses two 16-bit slots (configured
   BCLK256kHz), input two 32-bit slots (512kHz). Compare measured values to the
   configured values. If an instrument is unavailable, explicitly record that fact
   and the resulting limitation. Its availability is currently unknown; this form
   does not pre-fill it as unavailable. Speaker 1 W is a rating, not measured output.
7. **Check errors/stop/recovery.** Save a real invalid-CRC or wrong-hash rejection
   (raw artifact procedure or retained automated trace), and an odd/unsupported/
   unfinished PCM rejection; none may start audio. Stop a three-second capture or
   playback. Expect explicit cancelled/cleanup evidence, no partial usable capture,
   and a following valid capture/playback. Save all errors; never convert a missing
   result into successful completion. Follow [the #21 USB/recovery acceptance](milestone_1_review.md)
   separately, with matching physical evidence; ordinary reconnects do not close it.

## Collect and assess

After deliberately recording the phrase/quiet jobs, copy each completed capture
and its verified WAV into the packet using the running backend's GET endpoints:

```sh
python3 scripts/audio_qualification.py collect local/audio-qualification/session-01 \
  --kind speech --job-id SPEECH_JOB_UUID
python3 scripts/audio_qualification.py collect local/audio-qualification/session-01 \
  --kind quiet --job-id QUIET_JOB_UUID
python3 scripts/audio_qualification.py assess local/audio-qualification/session-01
```

Default backend is `http://127.0.0.1:8000`; `--base` can select another loopback port.
The collector never starts a capture or opens serial. It bounds reads, checks
identity/count/hash and refuses overwrites. Use a fresh packet for repeats.
Copy the associated raw `testbed/data/node_audio/JOB_ID.ndjson` and linked
`node_artifacts/TRANSFER_ID.ndjson` into the packet, along with reference upload/
playback records, captured playback record, errors, #21 evidence and any traces.
Those paths apply to `make serve`; use the actual store root if customized.

Fill `observations.json` only from actual observations. Evidence paths are relative
inside the packet. A measurement needs an instrument/method/observed/trace object;
configured text alone is not a measurement. Explicit unavailability needs a real
limitation note. Assessment exit2 means pending, exit1 means failed/inconsistent,
and exit0 means **ready for human review**, never automatic hardware qualification.
The helper checks consistency/counts/hashes/clipping/missing observations; a human
must still inspect the reference/playback/raw traces and physical observations.
Do not close #42 until the procedure passes and #21's prerequisite evidence exists.

## Software checks and reading order

`audio_qualification.py`: deterministic quiet reference, bounded read-only collection
and packet consistency checks. `test_audio_qualification.py`: synthetic packet
fixtures catch all-zero speech, clipping, corrupt/mismatched WAV/count/hash/build,
missing human/USB evidence and configured-only measurement claims. These fixtures
are never physical evidence.

```sh
uv run --project testbed pytest testbed/tests/test_audio_qualification.py
make check
```

Verification: **22 focused / 383 total tests passed**, no skips; lint, frontend,
generated-contract and repository checks passed. Both audio-enabled and default
ESP-IDF builds passed; the final audio-enabled image is installed with its port
released. No heard/speech response or measured clock/rail is claimed.
