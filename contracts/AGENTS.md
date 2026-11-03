# Shared contract instructions

Read root instructions and `docs/testbed_contract_v2.md`. This directory is shared
by firmware, physical adapters, host validation and analysis.

- `v2/default_profile.json` is the selected provisional configuration baseline;
  `conformance_vectors.json` contains public, test-only bytes and keys.
- Generated schemas come from typed host models: `v2.py` (diagnostic),
  `experiments_v2.py`, `rf_events_v2.py`, and `run_protocol_v2.py` (execution).
  Do not claim these are all implemented by diagnostic firmware.
- Root `scripts/generate_contract.py` generates schemas and diagnostic C metadata.
  Run `make contracts` to update, `make contracts-check` to detect drift.
- Edit source models/defaults and prose deliberately, regenerate outputs and run
  producer/consumer checks. Never patch only a generated JSON file or digest.
- Keep units, signedness, byte order, maximum sizes, sequence rules, capability
  requirements, error behavior and version compatibility explicit.
- Breaking changes require a versioned migration. Additive changes need the
  applicable contract revision and consumer/capability updates. Coordinate updates
  across host and firmware, or explicitly reject unavailable behavior.
- Diagnostic schema compatibility is an existing physical milestone. Do not change
  its digest for execution-only additions.
- Conformance fixtures are not production secrets and never supply normal run keys.
