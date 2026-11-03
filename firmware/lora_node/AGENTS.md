# Main node target

This target currently contains the user's initial, empty `app_main` scaffold.
It does not implement the v2 serial contract, RF, encryption, audio or experiments.
Keep that fact explicit until actual behavior and checks exist.

Read `../AGENTS.md`, root `docs/architecture.md`, `hardware/README.md` and
`docs/testbed_contract_v2.md`. Use root `contracts/v2` for shared fixtures/defaults.
The saved defaults select ESP32-S3, 16 MiB flash and native USB Serial/JTAG console
for bring-up. A future protocol implementation must arrange console/log separation.
PSRAM configuration is not enabled here until memory bring-up is implemented.

Suggested first slice: board profile and actual identity/health, then bounded
serial framing and diagnostic-compatible hello/ownership/status. Add capability
families incrementally with their conformance checks. Do not advertise RF/audio
just because peripherals appear in a wiring plan.
