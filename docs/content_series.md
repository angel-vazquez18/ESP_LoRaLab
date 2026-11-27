# Packet boundaries and protected comparison

PKT-01 and SEC-01 use the shared integration matrix command and ledger. Both
save the deterministic source recipe, case budget, applied settings, terminal
assessment and links to the actual wire and file evidence.

PKT-01 plans the declared lengths around 160-byte fragment boundaries, plus
the negotiated maximum minus one and maximum. The host selects the lower
advertised limit from the two nodes, deduplicates matching lengths and keeps
cases beyond supported limits visible. Each case records the expected number
of fragments and the final fragment length. The max-plus-one case sends one
prepare request to the limiting firmware under the selected security profile.
It requires an actual `RESOURCE_LIMIT` reply before arming, unchanged
configuration and artifact inventory, then a fresh verified 64-byte transfer.
Protected cases retire the prior session and provision fresh keys for recovery.

SEC-01 pairs unprotected and AES-GCM runs at 16, 64, 160 and 321 bytes
by direction, size, repetition and message ordinal. A pair requires
the same applied settings, node bindings and source recipe, a verified
matching payload digest, fresh sessions and complete frame evidence.
The retained TX records verify 16 extra bytes per protected DATA
fragment. Frame byte totals cover the DATA frame reported by the
driver. The local crypto benchmark measures processing separately.

Open **Inspect cases** on a saved SEC-01 run to see the protected and
unprotected comparison. Complete cohorts show unique-original delivery,
actual DATA frame bytes, total sender transfer duration and verified
payload goodput. Timing sums the observed windows from the first DATA
TX command through the last DATA TX completion for each message, using
that sender's clock. The backend retains zero and missing windows as
untimed observations. Frame overhead remains visible if every pair
matches and some timing is missing. Unmatched or missing pairs leave
their cohort inconclusive. The procedure ZIP includes the summary in
`procedure.json` and the detailed source observations in `evidence.jsonl`.

The wrong-key control requires both nodes to advertise the matching lab build.
It generates a fresh receiver key only in RAM and checks for a confirmed
transmission, matching CRC-valid reception, authentication-stage rejection and
zero delivered messages between fresh intact controls. The alternate key-set
identifier is retained with the evidence. A distinct peer-profile mismatch
case is rejected by host preflight before provisioning and arming. These two
results remain separate. Exports retain no private session key values.

## Preview and verify

For a short start, save the following as `content.json`:

```json
{
  "catalog_id": "PKT-01",
  "groups": ["C1", "C3"],
  "subset_sizes": [160, 161, 65537],
  "repetitions": 1,
  "messages_per_case": 1
}
```

```sh
uv run --project testbed lora-testbed integration-matrix content.json --preview
uv run --project testbed lora-testbed integration-matrix content.json
uv run --project testbed lora-testbed procedure-status RUN_ID
```

The example assumes the current 65,536-byte firmware limit. Read the advertised
value in preview and select its max-plus-one case. The short plan preserves
the indicated subset provenance. Full declared repetitions and hardware
acceptance use their separate ledger.

```sh
uv run --project testbed pytest testbed/tests/test_content_series.py testbed/tests/test_rf_sweeps.py testbed/tests/test_integration_matrices.py -q
make check
```

The isolated native pair verified boundary reconstruction, firmware refusal
and recovery for both security profiles, exact tag overhead by frame,
wrong-key authentication at the receiver, separate profile rejection and
redacted evidence. Read [integration matrices](integration_matrices.md) for
case evidence and shared ownership behavior.
