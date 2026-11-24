# Snapshot provenance and scope

This independent folder was requested for review and eventual integration planning.
It adds no ESP_LoRaLab application functionality or protocol integration.

- Source repository: https://github.com/homarrodriguez/lora-walkie-talkie
- Source commit: `3e53d2ab614183ab08e6d9fadd647e5e94e4696a`
  (`feat(lora): add ten-trial voice transfer bench and results`).
- Source workspace: `esp32-audio-chunker-test`.
- Original physical run: `captures/20261123-lora-consistency-run01` on 2026-11-23.
- Frozen archive: `10-lora-message-tests/`, copied with byte-preserving Git rules.
- Target repository base: `angel-vazquez18/ESP_LoRaLab`, main commit
  `d781bd64dc0fc0ba61d7fe1bab27eead75c89b1c`.
- Target branch and only added top-level folder: `local-node-lora-test-homar`.

The ten physical transfers were performed with the source project's firmware.
The source, radio framing, chunker and OLED implementation in this folder retain
the tested implementation. Packaging adapts only the standalone PlatformIO
configuration, input/Python paths, local tool discovery, identity-only dependency,
documentation and focused host-test runner. The package is built and checked
offline; no additional hardware trial is claimed by those checks.

The containing repository currently uses ESP-IDF, a shared NDJSON contract and
an encrypted RF/session design. This experiment uses Arduino/PlatformIO,
RadioLib, a distinct serial protocol and CRC-protected PCM packets. It does not
qualify ESP_LoRaLab's encrypted voice, shared interfaces, CDR procedures or planned
hardware wiring. Future integration requires separate design and validation.

All source, input audio, offline tests, reports and archived measurements for
this snapshot remain below this folder. Existing `firmware/`, `testbed/`,
`contracts/`, `hardware/`, `docs/`, root build files and previous snapshots are
unchanged from the target base. Build caches, environments, managed dependencies,
compiled firmware and synthetic PDF fixtures are excluded. The frozen raw logs
and WAVs are intentionally retained as the test evidence requested by the user.

`SNAPSHOT_MANIFEST.json` identifies the packaged files and source comparisons;
the archive's own manifest independently identifies its original captured bytes.
Historical absolute paths, USB identities and clock readings inside copied logs
describe the original experiment and are not edited to resemble a new run.
