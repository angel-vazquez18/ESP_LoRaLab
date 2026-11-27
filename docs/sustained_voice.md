# Sustained encoded voice feasibility

VOICE-03 uses a single three-second PCM reference across the whole series.
The testbed uploads it and verifies the sender's Codec 2 mode 3200
encoding. Both nodes exchange protected data. The sender's device-side
worker produces 8 encoded bytes every 20 ms for 60 seconds, independent
of radio progress. The queue holds at most 4,800 bytes including partial
and active messages. The testbed retains startup from 0–3 seconds, the
3–60 second assessment window, and up to 30 seconds of drain.

| Case | Radio | Reliability |
| --- | --- | --- |
| C1 | SF7 and 500 kHz | No ACK |
| C2 | SF7 and 500 kHz | Stop-and-wait with up to two retries |
| C3 | SF12 and 125 kHz | No ACK |

These selected profiles provide a matched ACK comparison and a slower
link condition. Feasibility depends on measured delivery, occupancy and
loss. An observed overload can be a valid result. Full defaults repeat
each profile three times in both directions, using the same reference.
The sender must advertise the independent worker. The receiver needs the
fixed-source execution and archive readback commands. A microphone and
speaker are not required for the fixed reference workload.

## Run and review

In Experiments, choose **VOICE-03**, one saved 24,000-sample reference,
and the case group and direction. Use a quick check for one repetition.
Every individual case keeps the full 60-second producer schedule.

For the equivalent CLI request, save this in `sustained.json` with your
reference ID.

```json
{
  "catalog_id": "VOICE-03",
  "groups": ["C1"],
  "directions": ["A_TO_B"],
  "repetitions": 1,
  "voice_reference_ids": ["REFERENCE_ID"]
}
```

```sh
uv run --project testbed lora-testbed integration-matrix sustained.json --preview
uv run --project testbed lora-testbed integration-matrix sustained.json
```

Open the saved case and its linked source assessment. The radio archive
contains the 1,200-byte encoded reference, 24,000-byte receiver archive,
wire evidence and source assessment. The receiver's delivered IDs must
match its terminal summary and delivery events. The testbed verifies every
delivered slot against the reference and every missing slot against zero.
Receiver delivery during the sender's 3–60 second window stays unavailable
without calibrated clocks. Eventual verified delivery, the source rate,
queue occupancy and drop counts remain available separately.

See [source accounting and plots](workload_assessments.md) for the exact
window, evidence fields and limits. Bench validation still requires the
complete physical series with both node identities and the declared setup.
