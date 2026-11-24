# Snapshot validation

Validated offline on November 23, 2026, before publishing the folder-only PR:

- Both standalone PlatformIO targets built successfully: `heltec_lora_com6`
  and `heltec_lora_com7`. Pinned platform/dependencies are in `platformio.ini`.
  The inherited OLED library emits overloaded-virtual compiler warnings; neither
  firmware target had a build error.
- 48 Python tests passed, including eight mocked USB identity cases and the
  command start gate, upload/export framing, CRC checks, failure cleanup,
  readiness-only behavior and incomplete-report handling.
- Four C++ test suites passed with warnings treated as errors: diagnostic CRC,
  chunking/reassembly, radio framing and OLED display model.
- The packaged launcher's `-Check` passed with `ports_opened: false`, using the
  bundled source WAV (PCM CRC32 `46248425`).
- Archived evidence is checked against its original SHA-256 manifest. The
  firmware/protocol/library implementation is preserved from the tested source.
- Build output, dependencies, virtual environments and test caches are excluded
  from this snapshot. Git attributes preserve archived byte streams and PDFs.

These are packaging checks. No serial port, flash/reset, RF transfer, speaker
test or additional physical qualification was performed while preparing this
PR. The ten successful physical trials are the pre-existing recorded run in
`10-lora-message-tests/run/`; they are not newly performed package tests.

The containing ESP_LoRaLab build, dashboard, backend and contracts are unchanged,
so its unrelated integration checks were not run for this independent folder.
