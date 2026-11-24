# Semtech SX126x driver

Unmodified `sx126x.c`, `sx126x.h`, `sx126x_hal.h`, `sx126x_regs.h`, and
`sx126x_status.h` from [Lora-net/sx126x_driver](https://github.com/Lora-net/sx126x_driver),
commit `a10c5dfdf89788c6ac805e9fe98889de44175aa2` (retrieved November 21, 2026).
Each file retains Semtech's full Clear BSD license and copyright. Include those
notices in distributions; the license grants no patent rights. LR-FHSS and BPSK
sources are omitted because this project uses LoRa. Our HAL is outside this folder.

Board control reference: Heltec's `board-config.h` and `sx1262-board.c`, commit
`6ab5cf916e01b0930eaa2245323c728f849705c4` of
[HelTecAutomation/Heltec_ESP32](https://github.com/HelTecAutomation/Heltec_ESP32).
No Heltec implementation code is copied. See `docs/radio_driver.md` for the
schematics, board-specific behavior and unverified physical assumptions.
