# Offline paired-pulse evidence

The TIME-02 offline check accepts saved observations from named A and B
device, boot and capture identities. It requires 32 to 64 consecutive paired
pulse indexes at 100 ms intervals within the declared capture tolerance.
It fits A time as scale times B time plus offset and exports the exact
rational coefficients. After the first 32 paired edges, each new edge updates
the fit using the latest 32. A frame uses the latest update available at its
sender-local TX command. Reports retain that window's ending pulse index.
An invalid newer fit leaves its dependent observations unavailable.
An absent, repeated, skipped or reordered edge invalidates the capture. A boot or capture change invalidates dependent
frame observations.

For a frame, the assessor retains separate command-to-RX-done and
command-to-application-acceptance values. It combines observed fit
residual, both quantization bounds, the declared instrument skew bound
and age-based drift. It excludes frames outside the 2-second update
window or above 1,000 microseconds of total uncertainty. Invalid or
missing phases are recorded with no delay value and a reason.

In **Experiments**, open **TIME-02** and select a saved JSON file
under **Review saved pulse evidence**. Choose **Evaluate evidence**
to see pulse-fit eligibility, residual, uncertainty, and the two
receiver phases for each observed frame. Invalid frame rows keep their
reason and show unavailable delay. **Download timing report**
preserves the original input fingerprint, submitted records, and exact
fit coefficients. The file limit is 1 MiB.

The CLI applies the same evaluator to the original file bytes.

```sh
uv run --project testbed lora-testbed clock-evaluate pulses.json > timing-report.json
```

The input contains a UUID `calibration_id`, `a` and `b` capture
objects, `pulse_interval_tolerance_us`, declared `capture_bounds`
and up to 600 `observations`. Each capture holds an `identity`
with `device_id`, `boot_id`, and `capture_id`, a `quantum_us`, and
`edges` with `index` and `local_us`. The bounds hold `evidence_sha256`,
`skew_us` and `drift_ppm`. Each observation identifies its frame and
sender role, both clock identities, and the observed command, receive
and optional application-acceptance times in the original node domains.
See the [typed fixture](../testbed/tests/test_clock_analysis.py) for a
complete example.

The report retains the submitted evidence and file SHA-256. Eligibility
applies to the input dataset. Physical qualification still requires the
capture and marker wiring, review of the referenced instrument evidence,
live mapping, and loaded bench checks.
