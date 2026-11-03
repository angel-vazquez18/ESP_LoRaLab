# Host testbed instructions

Read root `AGENTS.md`, `docs/status.md` and the applicable experiment procedure.
Paths below are relative to this directory unless identified as root paths.

- Existing Python project: `pyproject.toml` / `uv.lock`; package `src/lora_testbed`.
- UI and CLI drive one backend. Do not implement experiment state in browser code.
- `nodes.py` owns physical diagnostic serial sessions; `adapters.py` contains
  compatibility checks and the future execution interface. Full RF execution is
  still planned. Never instantiate virtual devices or add a simulation bench mode.
- `procedure_runs.py` owns physical diagnostic lifecycle and saved procedure
  evidence; `serial_validation.py` defines its bounded request/partial scope.
  `analysis_v2.py` / `run_records_v2.py` / `reports_v2.py` preserve evidence and assess it.
- `paths.py` is the single source-checkout layout seam. Shared docs/contracts are
  at the repository root; dashboard files are under this directory. Source-checkout
  execution is supported; standalone wheel resource bundling is not yet established.
- Procedure readiness depends on source/schema/profile hashes. Layout or source
  changes can invalidate prior readiness; do not copy or rewrite a passing ledger
  to bypass this. Repeat full procedures with the new profile.
- One owner holds the bench. Cancellation, leases, reset, shutdown and restart
  must end work safely and retain evidence. Never auto-resume transmission.
- Keep legacy v1 code explicit. New procedures use the shared v2 execution path.
- Local tests accept A or B independently; only RF cases require both nodes.
  Unit tests use isolated serial peers and never open physical ports. Historical
  simulated evidence remains readable under its original provenance.
- Preserve Python compatibility declared in pyproject and lock dependency changes.

From this directory: `uv run pytest`, `uv run ruff check src tests`, and
`npm --prefix frontend run build`. From repository root: `make check`.
Host data defaults to the invocation's `data/`; `make serve` selects `testbed/data/`
by starting here. Use explicit temporary directories in tests.
