# Regression and evidence instructions

Read root and testbed instructions. Tests run from `testbed/` via `uv run pytest`.

- Exercise public adapter and backend interfaces used by actual callers.
- Cover lifecycle failures and negative controls when changing run behavior:
  timeouts, cancellation, reset, ownership loss, partial framing, bad artifacts
  and incomplete cleanup. Do not merely assert the same counters used by producers.
- Use deterministic seeds and isolated temporary stores. Never open real hardware
  in the normal test suite. Physical checks must be explicit operator actions.
- Keep test-only clocks and measurements clearly identified as fixtures. Prove message content,
  hashes and evidence provenance independently where relevant.
- Tests needing shared contracts/firmware resolve the repository root, not the
  current working directory. Host resources use `lora_testbed.paths`.
- Do not restore a simulated application runner to support tests. Use isolated
  serial fixtures through the actual physical session API. Passing unit tests or
  partial diagnostic checks cannot close physical procedure qualification.
