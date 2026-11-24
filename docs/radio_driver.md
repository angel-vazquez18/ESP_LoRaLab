# SX1262 initialization and board selection

The portable `radio/node_radio.c` owns finite BUSY waits, reset, standby, TCXO,
regulator/calibration, DIO2 switching and LoRa initialization. The pinned Semtech
implementation owns command encoding; `radio/esp32_radio.c` supplies GPIO and
4 MHz mode-0 SPI. The SPI boundary waits at most two 20 ms queue/result windows;
a timed-out transaction keeps static buffers reserved and is never reused.
BUSY waits have a 100 ms deadline and an iteration bound. Errors withdraw radio
availability, attempt standby when possible and disable front-end power/enable.
No initialization path starts TX or RX. Repeated stop returns to standby and
clears IRQs; initialization can be repeated through the portable boundary.

## Explicit build selection

Run `idf.py -C firmware/lora_node menuconfig`, then **LoRaLab radio board selection**.
Default is **Unselected**: no RF GPIO is configured. Select only the schematic
matching the actual standard board. This selection is recorded as a configured
variant in `hello` and health, with a generated reference-file hash; it is not an
automatically detected or independently verified PCB revision. Initialization
success is based on real SPI status; a disconnected/faulty radio stays unavailable.
No execution command is advertised by this initialization-only change.

| Signal | Both variants | Standard V4.2 GC1109 | Standard V4.3 R2 KCT8103L |
| --- | --- | --- | --- |
| NSS / SCK / MOSI / MISO | 8 / 9 / 10 / 11 | same | same |
| RESET / BUSY / DIO1 | 12 / 13 / 14 | same | same |
| FEM power / enable | 7 / 2 | same | same |
| Host-controlled FEM mode | revision-specific | GPIO46 → CPS | GPIO5 → CTX |
| Automatic radio switch | SX1262 DIO2 | CTX | CPS |
| TCXO | DIO3, 1.8 V, 5 ms startup | same reference | same reference |

The reference source is `hardware/boards/heltec_v4_radio_variants.json`; regenerate
its C header with `make contracts`. It does not replace the previous audio plan
or establish what is soldered on either node. In particular, standard V4.3 uses
GPIO5 for RF control. Building it with the old GPIO5 microphone-WS capture profile
fails deliberately. Keep GNSS disconnected where audio uses GNSS pins. The R8
variant is unsupported. Keep USB pins 19/20 and OLED pins 17/18/21 reserved.

## Review and verification

Read the small public bus interface in `node_radio.h`, initialization/cleanup in
`node_radio.c`, then the ESP-IDF boundary. Native checks compile the real Semtech
and portable driver, injecting only SPI/GPIO/time. Run:

```sh
uv run --project testbed pytest testbed/tests/test_radio_native.py testbed/tests/test_node_control_native.py -q
make check
idf.py -C firmware/lora_node build
```

Expected native cases cover standby initialization, both variants, absent/status
failure, stuck BUSY, SPI/GPIO failures and repeated stop/reinitialization. Full
host checks must report no skipped native cases. ESP-IDF builds prove integration,
not the clock, RF output or physical path. Later physical tests need matching
board/antenna identification, reset/BUSY/DIO1 traces and repeated stop/recovery.
Measure RF power before treating configured SX1262 dBm as antenna output: the
board has an external amplifier. No radio or audio hardware was accessed here.

## Primary references and reuse

- [Official standard V4.2 schematic](https://resource.heltec.cn/download/WiFi_LoRa_32_V4/Schematic/WiFi_LoRa_32_V4.2.pdf).
- [Official standard V4.3 R2 schematic](https://resource.heltec.cn/download/WiFi_LoRa_32_V4/Schematic/HTIT-WB32LAF_V4.3.pdf).
- [Heltec RF front-end control table](https://github.com/HelTecAutomation/HeltecWiKi/blob/main/news/lna/lna.md).
- [Pinned Heltec board definitions](https://github.com/HelTecAutomation/Heltec_ESP32/blob/6ab5cf916e01b0930eaa2245323c728f849705c4/src/driver/board-config.h).
- [Pinned official Semtech driver](https://github.com/Lora-net/sx126x_driver/tree/a10c5dfdf89788c6ac805e9fe98889de44175aa2).
  Its full Clear BSD license is retained in every vendored file; see `radio/vendor/README.md`.
