# macOS physical LoRa testbed

The dashboard and CLI use one Python backend. There is no simulation mode.
Connect one physical ESP32 as A or B for local checks; connect two distinct
boards only for RF/link cases. Firmware/schema, ownership, freshness and
capabilities are checked before execution.

From the repository root:

```sh
make setup
make frontend
make serve
```

Open http://127.0.0.1:8000. In **Bench overview**, select the actual USB port for
A or B and connect that role. Neither startup nor listing ports opens hardware.
Connections happen only through an explicit connect action.

**Start diagnostic check** records hello, keepalive and status exchanges with
one connected node by default. Select A, B or A then B explicitly if needed.
This is partial IF-01 coverage: full framing, lease, fault and recovery
qualification still requires additional work. Stop retains partial evidence.
Bench connections stay owned after the check; disconnect releases control.

**Experiments** retains all 23 procedures and shows their node requirements and
blockers. SEC-04 and VOICE-01 are local one-node procedures; MEM-01 and OPS-01
have local and two-node RF cases. Other procedures currently need the pair.
All runners except the diagnostic subset remain unavailable. Node count alone
never enables missing firmware or a missing physical execution adapter.

**Voice workspace** still accepts, inspects and plays reference WAV files;
this does not establish node capture/playback or RF voice. **Results & exports**
and **Campaigns** retain historical records with their original provenance.
Simulated device engines, run/campaign runners and execution controls were removed.
Known-data budget calculation and public-vector checks remain numerical tools.

CLI examples from repository root:

```sh
uv run --project testbed lora-testbed ports
uv run --project testbed lora-testbed node A --port /dev/cu.YOUR_DEVICE
uv run --project testbed lora-testbed serial-check
uv run --project testbed lora-testbed serial-check --role B --cycles 3
uv run --project testbed lora-testbed preflight MEM-01 --workload local
uv run --project testbed lora-testbed preflight MEM-01 --workload rf
uv run --project testbed lora-testbed stop
uv run --project testbed lora-testbed node A
```

Omitting `--role` uses one connected node; it does not require B. No command
flashes hardware. Unit tests use isolated serial peers and never physical ports.
Run `make check` for tests, lint, frontend build, contracts and repository checks.
See [status](../docs/status.md), [procedures](../docs/test_procedures.md) and
[development commands](../docs/development.md).
