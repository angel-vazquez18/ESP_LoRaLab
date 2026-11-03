# Workspace consolidation

The user selected `~/Documents/ESP_LoraLab` as the shared development home and
asked to include the working testbed from `~/Documents/Lora_Testbed`.

## Changes

- Existing root `lora_node` sources relocated to `firmware/lora_node`; the user's
  empty app_main is preserved. The root IDE CMake path points to the new target.
- Existing host source/tests/frontend/presets/pyproject/lock copied to `testbed/`.
- One copy of shared contracts, docs and generation/hardware-check scripts at root.
- Existing diagnostic firmware copied to `firmware/diagnostic` without old build
  output, local sdkconfig or downloaded managed dependencies.
- Host checkout resource discovery and test fixtures adapted for shared root
  contracts/docs/firmware. Procedure source hash keys use new repository-relative
  paths and include the layout module, so readiness profiles change.
- Existing tracked node build output and local sdkconfig preserved under ignored
  `local/migration/initial-lora_node/`; old build paths are not reusable after moves.
  The old sdkconfig used 2 MiB flash. Main target defaults now select 16 MiB and USB
  Serial/JTAG console; PSRAM and functional peripheral support are not implemented.
- Root README before restructuring is retained in `local/migration/README.before.md`.
- Imported source hashes before adaptation are retained in
  `history/imported-source-manifest.json`; original root context is archived as
  `history/prior-workspace-context.md`, not active instructions.

The original workspace is left intact. No Git commit, push, flash, port access,
run replay or physical experiment is performed by consolidation. Existing target
Git history/remotes are retained; generated files previously committed at root
lora_node/build appear as deletions and their preserved local copies are ignored.

## Data and evidence remain local

The old `~/Documents/Lora_Testbed/data/`, `output/`, `.venv/` and frontend dependencies
are not copied. In particular the verified full flash backup for device
`esp-f85b1ba27744` remains at:

`/Users/anken18/Documents/Lora_Testbed/data/hardware-backups/`

Keep its manifest, exact device identity and verified hashes with that backup.
Do not flash or restore a board merely to test the new layout. Consult the original
backup before an explicitly authorized physical firmware change.

The host starts with a fresh local data store under `testbed/data/` via `make serve`.
Do not import old passing-procedure flags as current readiness: changed source paths
and code/profile hashes require fresh full-procedure evidence. Historical host
observations remain documented in `implementation_status.md`, with their original
scope and provenance. They are not new measurements from this checkout.

Standalone wheel packaging of shared docs/contracts/firmware has not been added.
Run and develop from this source checkout; resource lookup is centralized in
`testbed/src/lora_testbed/paths.py`.
