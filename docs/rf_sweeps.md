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

The fixture verifies that the testbed applies and reads back every supported
value, and holds all independent settings fixed. Each measurement joins a
confirmed transmission to an actual CRC-valid reception for the same run and
frame. Signal values remain absent when no matched reception exists.
Sender command-to-completion duration and modeled airtime are separate
fields. The per-case median, sample count and evidence links remain in the
ledger. Review the raw runs for failures and missing observations.

The current software covers schedule generation, finite execution, setting
checks and the observation projection. Full performance and baseline-drift
assessment, plots, matched RTT comparisons and bench verification remain
separate work. See [the integration runner](integration_matrices.md) for the
shared lifecycle and export instructions.

```sh
uv run --project testbed pytest testbed/tests/test_rf_sweeps.py testbed/tests/test_integration_matrices.py -q
make check
```

Expect 13 focused cases. The native fixture covers actual readbacks, the
transmitter/receiver split, planned budgets, observed signal fields and
inconclusive missing observations.
