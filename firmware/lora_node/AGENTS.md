# Main node target

The user is implementing this target manually to learn ESP-IDF. Provide small,
explained coding steps and inspect their work; do not type firmware changes or
perform hardware operations on their behalf unless specifically requested.

The current app_main logs startup, ESP-IDF version, the eFuse-derived device ID
and numeric reset reason, plus internal/PSRAM memory statistics. It does not
implement the v2 serial contract, RF, encryption, audio or experiments. See root
docs/status.md for validation scope.

Read `../AGENTS.md`, root `docs/architecture.md`, `hardware/README.md` and
`docs/testbed_contract_v2.md`. Use root `contracts/v2` for shared fixtures/defaults.
The saved defaults select ESP32-S3, 16 MiB flash and native USB Serial/JTAG console
for bring-up. A future protocol implementation must arrange console/log separation.
Local sdkconfig and saved sdkconfig.defaults enable Quad PSRAM at 40 MHz,
startup initialization and memory testing. Initialization and 2 MiB capacity
were observed November 7. Startup availability alone does not validate sustained
allocation, audio or RF workloads.

Use root `docs/node_development_plan.md` as the node work order. Start with observed
board identity/health, bounded diagnostic-compatible serial control and cancellable
operations; then local artifacts/audio and physical radio. Build shared capabilities,
not five separate experiment implementations. Do not advertise working RF/audio
from reported wiring alone. The earlier temporary code draft was not installed.
