# Airtime model procedure

MODEL-01 C1 checks 90 exact numerical vectors with no connected nodes.
It crosses SF7/9/12, BW125/250/500 kHz and coding denominators 5/8 with
five unprotected/protected DATA lengths including the 255-byte limit.
The independent calculation uses the bandwidth/LDRO table and numerator
basis in the pinned [Semtech SX126x reference](https://github.com/Lora-net/LoRaMac-node/blob/cf779a46f52f9b22395a207c6853f3efb47f0e5b/src/radio/sx126x/radio.c#L917-L1010)
and exact rational arithmetic. It also checks the three independently
recorded procedure worksheet values. Each vector retains both results and
its inputs, including the model revision, LDRO and reference revision.

C2 sends isolated DATA frames using the common radio runner in both
directions. The procedure defaults collect ten observations per setting,
size and direction. It requires the actual frame length, applied LDRO,
exact source/recovered bytes and matched CRC-valid receive evidence.
The per-child residual subtracts predicted airtime from sender-local
TX command to TX done. The measured interval includes radio
startup/turnaround and interrupt delay. The residual is exploratory.
Physical airtime agreement requires a separately instrumented timing
reference and a declared tolerance.
C3 runs separate 64-, 160- and 1200-byte message cohorts with ACK disabled,
ACK enabled, or one observed retry. The retry case uses the lab-only receiver
drop and validates the actual retransmission and matching ACK. The report
retains modeled nominal and worst-case windows, confirmed DATA/ACK airtime
cost, and the sender-clock interval from its first TX command through its
last TX completion or accepted ACK. The reported interval excludes the
model's drain allowance. It does not establish on-air timing agreement.

In Experiments choose **MODEL-01**, **C1**, **Procedure defaults**
and preview. Start the numerical cases. Expect 90 saved arithmetic
comparisons with no device bindings. From the CLI use a file containing
`{"catalog_id":"MODEL-01","groups":["C1"]}`.

```sh
uv run --project testbed lora-testbed integration-matrix model.json --preview
uv run --project testbed lora-testbed integration-matrix model.json
```

For C2 plan and run the selected directions against two compatible radios.
The native fixture covers one unprotected and one protected frame and
confirms the saved evidence path. Physical markers, tolerance and the complete bench measurement set remain open.


## Compare saved predictions and observations

Open **Inspect cases** on a saved C2 or C3 procedure. The comparison
offers predicted versus observed duration and signed residuals.
Filter by configuration and protection. Isolated frames use predicted
airtime and observed TX command-to-done. Message completion uses the
nominal modeled interval without drain and the observed sender interval
through its last TX or accepted ACK. The expanded run budget and actual
retry/ACK evidence remain available separately.

The procedure ZIP includes `model-comparison.csv`, one row per
linked valid observation with its exact microsecond values, case ID,
child run ID and capture basis. The archive manifest hashes that CSV.
C1 saves the arithmetic vectors in its ordinary evidence without
inventing observed RF points. Instrumented agreement needs an
independent marker trace and a predeclared tolerance.
