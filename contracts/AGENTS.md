# Shared contract instructions

Follow root instructions and `docs/testbed_contract_v2.md`.

- `v2/default_profile.json` is the selected baseline; conformance vectors contain
  public test-only bytes/keys. Preserve units, limits, identities and state rules.
- Typed host models own generated schemas: `v2.py` (diagnostic), `control_v2.py`
  (main control), `experiments_v2.py`, `rf_events_v2.py` and `run_protocol_v2.py`.
- Root `make contracts` generates schemas and C metadata; `make contracts-check`
  detects drift. Main metadata lives in `firmware/lora_node/main/generated/`;
  diagnostic metadata remains in its separate target. Never patch generated digests.
- Coordinate producers, consumers, models, prose and checks. Breaking changes need
  versioned migration; additions need the applicable contract revision. Explicitly
  gate missing capability support.
- Keep diagnostic, main-control and execution compatibility separate. An unrelated
  execution change must not alter the existing diagnostic digest.
