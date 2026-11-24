# Optional actual-state OLED status (#37)

The OLED observes real node control state. It cannot claim successful delivery,
intelligible audio, physical pixels or synchronized clocks. The driver defaults
off; selecting a PCB profile and compiling does not verify the physical board.

## Read the code

1. `main/display/node_view.h` / `.c`: fixed nonsecret view, state labels, bounded
   text and a project-drawn four-column/six-row font in a 1024-byte bitmap.
2. `main/control/node_control.c`: derive ownership, USB connection, finite audio/
   codec/diagnostic progress and RF phases from their actual owners. State/owner/
   connection/error changes post immediately; otherwise progress posts at most
   four times per second. Only a small copied view crosses the platform seam.
3. `main/display/oled_panel.c`: SSD1315-compatible setup and complete-frame output
   through a bounded I2C seam. Setup keeps the panel off. A frame sets its address,
   sends eight 128-byte data pages and enables the display after complete writes.
   Every transaction has a 5 ms timeout; a failed write stops without retry.
4. `main/platform/esp32_display.c`: an independent worker, one-slot overwrite
   queue, one static framebuffer and a 4096-byte task stack. The control loop only
   copies a view without waiting. Worker writes run at most four times per second;
   intermediate views coalesce. GPIO reset/power and I2C stay in the worker.
5. `oled_status_v2.py`, generated profile and `nodes.py`: passive exact-fingerprint
   worker observations. Ready means a complete I2C frame was acknowledged, not
   that someone saw correct pixels. Stale/disconnected observations are not ready.

The fixed view contains state, role, ownership/link flags, bounded counts, uptime
and symbolic recorded error codes. It has no command body, payload, session key,
artifact bytes, recording, message text or key identifier. Recorded errors are
separate from the current phase; no sticky success screen replaces real state.
Idle views clear active-link counters. RF labels describe the run direction/phase,
not instantaneous radio transmit/receive hardware mode. USB loss publishes an
unowned, disconnected view after cleanup. A failed display may retain its last
physical image; use current USB health when the screen is absent or stale.

## Standard V4 R2 reference and opt-in configuration

Both inspected standard V4.2 and V4.3 R2 schematics route OLED SDA17/SCL18, reset21
and switched Vext power. GPIO36 LOW enables Vext through its transistor/regulator
control. These are manufacturer references, not observation of the user's PCB.
The V4-R8 has a different map and is unsupported by this option.

`CONFIG_LORALAB_OLED` defaults off and requires a selected standard V4.2 or V4.3
board option plus explicit confirmation of its OLED pins/power. The driver uses
SSD1315-compatible 128x64 addressing at I2C 0x3c, 400 kHz, with clock-stretch wait
2000 us and per-transaction timeout 5 ms. Physical SDA/SCL quality and OLED response
remain unmeasured. No pin, reset, rail or I2C access occurs from the disabled driver.

The planning board profile is version 3, still `planned_not_hardware_validated`.
It now reserves GPIO36 as onboard power control and records the standard OLED
controller/geometry/reference sources. Generated bindings, wiring table, Mermaid
and PNG agree. Microphone, amplifier, speaker and PTT signal assignments are
unchanged. The amplifier remains on the Heltec 3.3 V rail, separate from Ve.
GPIO7 remains reserved for the RF front end. Printed revision/physical acceptance
remain open under #1; nothing was flashed for this issue.

The worker starts only after queue/task allocation succeeds. Setup or I2C failure
is explicit and stops the worker without an automatic retry/reinitialization.
Driver handles are released in that worker; the bounded queue remains allocated
for the firmware lifetime. Cleanup never turns Vext off; after successful initial
power enable it stays enabled so other Ve-powered peripherals are not power-cycled. No main-control error/panic is raised merely
because the display is absent. Queue/task allocation failure is also observable.
Control never waits for display initialization, reset delays, transfers or cleanup.

## Passive host observation

Current health may contain `resource_limits.oled`, profile `oled_status_v1`, SHA
`e57d4c95bcf81dcf33047296845e796635e84ac5764c8a1ae8d440b78188a8c7`:

- `starting`: worker initialization or first frame has not completed;
- `ready`: the last complete frame write succeeded;
- `setup_failed`, `io_failed`, `allocation_failed`: the observed worker failure;
- `physical_qualified:false`: never inferred from I2C acknowledgments.

There is no display mutation command or extra operator mode. Existing status/API/
CLI health exposes the observation; NodeSession snapshots add a fresh/compatible
`display` interpretation. Missing support is `not_advertised`; incompatible
fingerprints are unavailable, and disconnect makes a previous ready result stale.
Static enrollment is unchanged; only the current passive observation adds data.
Diagnostic/control/audio/artifact/codec/execution/PTT wire identities stay intact.
The board manifest fingerprint changes with the documented reference addition.

## Verification and physical acceptance

```sh
uv run --project testbed pytest testbed/tests/test_oled_native.py testbed/tests/test_oled_panel.py testbed/tests/test_oled_host.py -q
make check
npm --prefix testbed/frontend run format:check
```

Eighteen dedicated cases cover real ownership/capture/codec/play/RF/cancel/USB
state transitions, argument exclusion, text/bitmap bounds and page layout, each
frame-write failure position, a failed display sink with continuing serial and
memory diagnostics, and fully configured radio/audio/codec/PTT/OLED health with
stale readiness on disconnect. Actual portable C runs behind isolated GPIO/DMA/
SPI/I2C seams. These fixtures do not exercise an ESP32 scheduler or physical bus.
The software bitmap and updated wiring PNG were visually inspected. Mermaid CLI
12.2.0 rendered the PNG using a temporary local headless Chrome; no project
JavaScript dependency changed. Release test/build results are in `status.md`.

Build verification uses both the normal OLED-disabled image and an isolated V4.2,
32 KiB-main-stack image with microphone/playback/PTT/OLED enabled. Declared display
resources include the one-slot queue, 1024-byte framebuffer and 4096-byte worker
stack; target heap/stack high-water and actual serial response under bus failure
remain physical measurements, not inferred margins.

After identifying the actual PCB, confirming its matching pin/power map and
following the deployment backup procedure: compare the OLED with USB status through
claim/release, armed PTT, capture, encode/decode, RF and playback. Stop and fail
operations, disconnect/reset, and verify the resulting phase without stale success.
Check physical orientation/legibility and Vext behavior. Exercise missing/NACKed/
stalled display safely in the bench fixture, verify bounded failure reporting and
continuing USB/control, and measure serial responsiveness. Retain observations
with node/boot/build/pin identities. Physical screen qualification remains open.

## Primary references

- [Heltec V4.2 datasheet: SSD1315, 128x64](https://resource.heltec.cn/download/WiFi_LoRa_32_V4/datasheet/WiFi_LoRa_32_V4.2.0.pdf)
- [Heltec V4.2 schematic](https://resource.heltec.cn/download/WiFi_LoRa_32_V4/Schematic/WiFi_LoRa_32_V4.2.pdf) and [V4.3 R2 schematic](https://resource.heltec.cn/download/WiFi_LoRa_32_V4/Schematic/HTIT-WB32LAF_V4.3.pdf)
- [Heltec Vext polarity](https://github.com/HelTecAutomation/Heltec_ESP32/blob/master/src/heltec.h) and [vendor display initialization/addressing](https://github.com/HelTecAutomation/Heltec_ESP32/blob/master/src/HT_SSD1306Wire.h)
- [Solomon SSD1315 controller datasheet hosted by Espressif](https://dl.espressif.com/dl/schematics/SSD1315.pdf)
- Pinned ESP-IDF v6.0.2 `components/esp_lcd/src/esp_lcd_panel_ssd1306.c` and
  `components/esp_driver_i2c/include/driver/i2c_master.h` provide local API/protocol
  references. This implementation uses its own bounded transport and font; no
  Arduino display library or third-party font was vendored.
