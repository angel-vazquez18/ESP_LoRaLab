# Hardware planning instructions

Read root instructions, `README.md` and `boards/heltec_wifi_lora32_v4.json`.

- November 4 user report: one ESP is connected to the laptop and microphone/
  amplifier wiring is complete. Independent electrical/audio validation is pending;
  speaker/PTT connection and operation are not explicitly confirmed.
- User decisions: all peripherals powered from Heltec; amplifier 3.3 V; speaker
  8 ohm / 1 W; GNSS unused. GPIO 47 replaces the earlier PTT GPIO 7 assignment.
- GPIO 7 is reserved for RF-front-end supply control. Follow the actual board
  revision's RF controls and schematic; do not assume SPI pin correctness is
  sufficient to enable the full front end.
- GPIO 38/39/40 are audio output pins with GNSS disconnected. Do not enable GNSS
  silently or assign another device to those signals.
- User confirmed microphone L/R-to-GND, amplifier SD/MODE-to-3.3 V and
  GAIN-to-3.3 V. Hardware gain is 6 dB. Earlier open-GAIN/9 dB suggestions are superseded.
- Verify actual breakout parts/resistors, board revision and power headroom before
  treating the manifest as a validated board support package. Speaker rating is
  not measured delivered power. Neither speaker terminal connects to ground.
- Update the JSON profile, wiring table and diagram together if assignments change.
  The profile is planning data; firmware consumption/generation is future work.
- Keep device observations and hashed flash backups out of source control. Original
  backup location and its required checks are in root `docs/migration.md`.
