# RF setting sweeps

The shared procedure runner executes four one-factor series using the same
finite known-data path and saved child evidence.

| Procedure | Settings | Baseline |
| --- | --- | --- |
| RF-01 | SF7 through SF12 | SF7 |
| RF-02 | 125, 250 and 500 kHz | 125 kHz |
| RF-03 | Coding 4/5 through 4/8 | 4/5 |
| RF-04 | 2, 5, 8, 11, 14, 17 and 20 dBm transmitter settings | 2 dBm |

Every direction and repetition has its own before/after baseline controls.
The factor order is seeded, and the two directions reuse the same source seeds
within a repetition. Plans retain all requested values and a recomputed budget
for each finite child. Standard requests use 64 useful bytes, 160-byte fragments
and ACK disabled. The default security mode is unprotected. Select
`rf_security: "aes128_gcm"` for a separately identified protected series.
RF-04 holds the receiver power setting at 2 dBm. Review the driver's applied
setting as a configuration observation. Bench qualification supplies radiated
power and saturation evidence separately.

For a short preview, save the following as `sweep.json`:

```json
{
  "catalog_id": "RF-04",
  "directions": ["A_TO_B"],
  "repetitions": 1,
  "messages_per_case": 1
}
```

```sh
uv run --project testbed lora-testbed integration-matrix sweep.json --preview
uv run --project testbed lora-testbed integration-matrix sweep.json
uv run --project testbed lora-testbed procedure-status RUN_ID
```

The fixture verifies applied settings and holds independent settings
fixed. A complete observation is either exact independently verified
delivery or matched bounded non-delivery. For non-delivery the host
requires a confirmed original, complete receiver timeout and missing
index evidence, an independent source readback, current settings and
confirmed cleanup. A missing observation stays unresolved. When every
planned message has evidence, the case reports the delivery ratio and
verified useful bits per summed sender TX second. That rate uses the
node-local transmit command-to-completion windows for the finite children.

RSSI and SNR require a CRC-valid receive frame matched to the confirmed
transmission. Signal stays absent when that record is absent. The case
ledger keeps the sample count, medians, duration/model outputs and the
linked raw evidence. The dashboard shows the delivery percentage or the
unresolved count. A case can pass evidence verification with zero delivery.

The current software covers schedule generation, finite execution, setting
checks and the observation projection. Comparison plots and baseline-drift
assessment, matched RTT comparisons and bench verification remain
separate work. See [the integration runner](integration_matrices.md) for the
shared lifecycle and export instructions.

```sh
uv run --project testbed pytest testbed/tests/test_rf_sweeps.py testbed/tests/test_integration_matrices.py -q
make check
```

Expect 15 focused cases. The native fixture covers actual readbacks, the
transmitter/receiver split, planned budgets, observed signal fields and
inconclusive missing observations.
