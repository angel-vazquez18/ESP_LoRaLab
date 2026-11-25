# Round-trip and local crypto procedures

TIME-01 C1 runs single-fragment echo at 16, 64 and 160 bytes in unprotected and
AES-128-GCM modes. The default plan has 36 cohorts of 100 requests, covering
three repetitions in both directions. Each child is a finite request with a
fresh session, verified echo bytes and requester-local timing. Repetitions
have separate source seeds. Results retain the original run IDs, cohort,
request and reply references, raw timestamps, exclusions, median and
nearest-rank p95. Missing samples stay out of statistics. TIME-01 C2 is
listed as blocked until a controlled missing-reply fixture is available
through the production adapter. TIME-02 calibration and one-way timing are
separate procedures.

SEC-04 runs batches of 1,000 timed operations plus one first call and 50
warmups at 16, 64, 160 and 199 bytes, with three repetitions per size and role.
It can use a single node. Public known-answer checks guard every sample. The
report keeps encryption, valid-tag decryption, invalid-tag rejection and
copy separate. It retains sample count, first-call latency, spread,
per-byte cost, timer resolution, CPU and acceleration settings, as well as
pre/post node status and memory. The diagnostic child stores node/build
identity, command-evidence fingerprint, checked raw timing pages and cleanup.

For a quick local check, save this input in `timing.json`.

```json
{"catalog_id":"SEC-04","roles":["A"],"repetitions":1,"diagnostic_iterations":10}
```

```sh
uv run --project testbed lora-testbed integration-matrix timing.json --preview
uv run --project testbed lora-testbed integration-matrix timing.json
```

With one compatible, owned and idle Node A, expect four cases and four
separate timing paths with ten checked timed samples each. For two-node
echo, use `{"catalog_id":"TIME-01","groups":["C1"],"repetitions":1,"messages_per_case":2}`.
Expect a separate requester-clock series for each size, direction and
protection profile. Read child IDs and evidence links in the saved
procedure. A short native fixture run establishes software behavior.
Final physical distributions, performance charts and hardware qualification
still require bench evidence.
