# ESP_LoraLab

One repository for the ESP-IDF node firmware and the macOS LoRa laboratory testbed.
One or two physical nodes share one firmware codebase; the host assigns roles A/B.
Local checks work with either node alone. RF tests require two distinct devices.
The dashboard and CLI use the same Python backend and experiment lifecycle.

```text
ESP_LoraLab/
├── AGENTS.md                  Start here for agent-assisted work
├── CONTEXT.md                 Shared domain vocabulary
├── contracts/v2/              Shared defaults, vectors and generated wire schemas
├── firmware/
│   ├── lora_node/             Existing node scaffold; app_main is currently empty
│   ├── diagnostic/            Working serial/health diagnostic target
│   └── components/            Planned shared firmware module locations
├── testbed/
│   ├── src/lora_testbed/       Python backend, CLI, physical sessions and analysis
│   ├── frontend/              React/TypeScript dashboard
│   ├── tests/                 Host, procedure and adapter regression checks
│   └── pyproject.toml         Python project and dependency lock beside it
├── hardware/                  Planned wiring, board profile and reference diagram
├── docs/                      Architecture, status, CDR, contracts and procedures
├── scripts/                   Shared generation and verification tools
└── local/                     Ignored local migration artifacts, if present
```

## Start the host

From this repository root:

```sh
make setup
make frontend
make serve
```

Open http://127.0.0.1:8000. For dashboard development use `make frontend-dev`
in another terminal while the backend runs. Requires Python 3.12+, uv and Node/npm.
The host's ignored data directory is `testbed/data/` when started with `make serve`.
Use one backend per data directory and release serial ports before IDF Monitor.

Individual commands from the repository root:

```sh
uv run --project testbed lora-testbed status
uv run --project testbed lora-testbed serial-check --preview
uv run --project testbed lora-testbed preflight IF-02
uv run --project testbed lora-testbed serial-check --role A
```

The host has no simulation mode. Connect each node from Bench overview. The
physical diagnostic check covers only part of IF-01; other experiment runners
remain blocked pending firmware and physical execution support. Historical
records retain their original provenance and exports.

## Build firmware

ESP-IDF v6.0.2, target ESP32-S3. Activate your local installation first:

```sh
source /Users/anken18/.espressif/v6.0.2/esp-idf/export.sh
make firmware-build
```

`make diagnostic-build` builds the existing diagnostic target. These targets only
build; flashing is a separate operator action. The node scaffold has no radio,
security or audio implementation yet. See [firmware guide](firmware/README.md).

## Verify

```sh
make check
```

This runs all host tests, Ruff, the dashboard production build, generated-contract
consistency and the repository checks. Firmware builds are separate toolchain
checks. See [development workflow](docs/development.md) for exact commands.

## Read next

- [Agent instructions](AGENTS.md) and [task routing](docs/agent_workflow.md)
- [Architecture](docs/architecture.md) and [shared vocabulary](CONTEXT.md)
- [Project brief and confirmed decisions](docs/project_brief.md)
- [Current status](docs/status.md) and [23-experiment implementation checklist](docs/experiment_implementation_checklist.md)
- [Hardware wiring](hardware/README.md)
- [Migration and retained local artifacts](docs/migration.md)
