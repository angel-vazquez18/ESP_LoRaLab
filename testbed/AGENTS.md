# Host and test instructions

Paths below are relative to `testbed/`, unless marked as repository-root paths.
Follow root instructions and the relevant experiment procedure.

- Use the existing Python package `src/lora_testbed`, pyproject and lockfile.
  Preserve the declared Python compatibility; lock intentional dependency changes.
- `nodes.py` owns physical serial sessions and operation observations;
  `adapters.py` owns compatibility and the execution interface. Keep blocking serial
  I/O outside the event loop. Never add an operator simulation mode.
- `procedure_runs.py` owns procedure lifecycle/evidence; `serial_validation.py`
  defines the partial serial check. Keep GUI and CLI on the same backend path.
- `paths.py` owns checkout resource locations. Resolve shared contracts/firmware
  from the repository root, including in tests, rather than the current directory.
- Preserve one bench owner, bounded cancellation and safe shutdown/reconnect.
  Never automatically resume transmission or invent a missing operation result.
- Readiness depends on source/schema/profile hashes. Do not rewrite old passing
  records to bypass changed prerequisites. Preserve historical provenance.
- Keep diagnostic, main-control, full execution and legacy v1 handling explicit.
  Local checks accept A or B; RF cases require two distinct devices.
- Test public interfaces with isolated serial/native fixtures and temporary stores.
  Never open physical ports in the normal suite. Keep fixture clocks/data explicit.
- Cover relevant timeout, cancellation, reset, ownership, framing and cleanup
  failures. Verify contents/hashes independently; counters alone are not evidence.

From repository root use `make check`; focused commands are in `docs/development.md`.
`make serve` selects ignored `testbed/data/`. Tests must use isolated data directories.
