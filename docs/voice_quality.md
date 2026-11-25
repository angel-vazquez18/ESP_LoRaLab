# Saved voice timing and intelligibility review

The VOICE-04 review accepts saved voice run IDs. It checks encoded
transport integrity and both PCM artifacts before creating playback
entries. A seeded order gives each clip a stable code. The report
retains the corresponding source/decoded role, SHA-256, WAV endpoint
and waveform. It keeps each named stage in its original node clock
domain and preserves unavailable one-way timing.

Start with a JSON document such as
`{"run_ids":["a-saved-voice-run-uuid"],"seed":743}` and run:

```sh
uv run --project testbed lora-testbed voice-review review.json > review-plan.json
```

Use the returned order when presenting clips. Add a `ratings` list to
the same request to evaluate listener observations. Each rating
includes `listener_id`, `clip_code`, `audio_sha256`, `score` from 1
through 5 and optional `notes`. The same backend also exposes
`POST /api/voice/review`. Re-running the request with its ratings
produces a report with individual scores, counts, and the listeners
who rated both the source and decoded clip.

The saved artifact hash must match the rated clip. The report keeps
operator listening separate from playback command completion. Attended
speech, physical listening, timing calibration and the complete
direction/repetition bench study remain open.
