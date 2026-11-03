# Hardware planning instructions

Read root instructions, `README.md` and `boards/heltec_wifi_lora32_v4.json`.

- These records describe planned wiring. No external microphone, amplifier,
  speaker or button has been connected or validated in this session.
- User decisions: all peripherals powered from Heltec; amplifier 3.3 V; speaker
  8 ohm / 1 W; GNSS unused. GPIO 47 replaces the earlier PTT GPIO 7 assignment.
- GPIO 7 is reserved for RF-front-end supply control. Follow the actual board
  revision's RF controls and schematic; do not assume SPI pin correctness is
  sufficient to enable the full front end.
- GPIO 38/39/40 are audio output pins with GNSS disconnected. Do not enable GNSS
  silently or assign another device to those signals.
- Microphone L/R-to-GND, amplifier SD/MODE-to-VIN and open GAIN/9 dB remain proposed
  starting straps, not user-confirmed physical connections.
- Verify actual breakout parts/resistors, board revision and power headroom before
  treating the manifest as a validated board support package. Speaker rating is
  not measured delivered power. Neither speaker terminal connects to ground.
- Update the JSON profile, wiring table and diagram together if assignments change.
  The profile is planning data; firmware consumption/generation is future work.
- Keep device observations and hashed flash backups out of source control. Original
  backup location and its required checks are in root `docs/migration.md`.
