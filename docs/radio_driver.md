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

## Match the bench firmware to the board

The Bench overview shows USB connection and radio readiness separately. An
older audio image can answer USB control while lacking an RF execution profile.
The radio readiness message distinguishes an older image, an unselected board,
a driver error and an incompatible execution schema. A ready radio has reported
successful initialization and can accept configuration.

Use a fresh SDK configuration for the chosen revision. From the repository root
with ESP-IDF active, the following example builds the standard V4.2 image with
the original documented microphone and amplifier wiring.

```sh
build_dir="$(mktemp -d /tmp/lora-v42-radio.XXXXXX)"
idf.py -C firmware/lora_node -B "$build_dir/build" \
  -DSDKCONFIG="$build_dir/sdkconfig" \
  '-DSDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.heltec-v42.defaults;sdkconfig.audio.defaults' \
  build
```

For a confirmed V4.3 R2 board with the original wiring, use
`sdkconfig.heltec-v43.defaults;sdkconfig.playback.defaults` in place of the
last two defaults above. This enables RF and the existing amplifier. GPIO5 drives
the V4.3 radio front end and conflicts with the original microphone WS assignment.
Capture needs a revised pin map and matching wiring. Review the configured board
profile in the node details before using the radio on the bench.

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

## Modem configuration (#15)

`config.set` is now the first advertised execution command. It requires ownership,
an initialized idle radio and a non-exhausted configuration revision. Its radio
object uses the shared v2 names/defaults: 902–928 MHz in 1 kHz steps, bandwidth
125/250/500 kHz, SF7–12, coding-rate denominators 5–8, configured SX1262 power
2–20 dBm, preamble 8–32 symbols, explicit header, PHY CRC on, normal IQ, sync word
0x1424 and automatic LDRO (symbol duration at least 16 ms). The initial link accepts
ACK disabled/zero retries only, fragment capacity 16–215 bytes and guard 0–1 s.
Unsupported values, fields and JSON types reject before any SPI transfer.

The driver confirms command status and reads back the LoRa packet type and exact
sync-word register bytes. Other returned fields are a committed record of
successfully applied commands: SX1262 does not offer a general getter for all
modem parameters. They are not measured frequency, bandwidth, antenna power or
RF performance. Applied power refers to the SX1262 setting before the board's
external front end. Physical verification must characterize that complete path.

Success increments `config_revision`; health reports the applied radio/link
objects. Duplicate commands return their cached reply without applying again.
Both success and failure replies are allocated/encoded before touching hardware;
allocation failure cannot silently apply settings. A driver failure invalidates
configuration and withdraws radio readiness, retains the revision, and reports
`INTERNAL_ERROR`. It never claims that a partially applied setting is active.
Reinitialize/reconnect after a fault before issuing new work.

The host requires exact advertised `config.set` support and fresh health, normalizes
typed arguments and validates the applied result. It still refuses arm/start,
fragmentation, retries and security until those handlers are implemented.

Additional checks: `pytest` native cases cover NDJSON round trips and duplicates,
invalid requests preserving revision and SPI count, all 220 pre-acceptance JSON
allocation positions, coding 4/5 → driver enum 1, sync word 14/24, frequency/power/
preamble bounds, representative LDRO boundaries and host stale-health/radio-loss
handling. Physical parameter/antenna measurements remain pending.

## Finite transmission (#19)

`node_radio_tx` accepts one 1–255-byte frame, a nonzero session/frame/message
reference and attempt index 1–6, and a deadline of 1–30,000,000 microseconds.
Acceptance is separate from completion. It programs the exact FIFO bytes, packet
length and finite chip timeout, clears/maps IRQs, selects the transmit front-end
path and records the node-local command time immediately before SetTx.

`node_radio_poll` resolves TX-done, hardware timeout, software deadline or error
once. TX-done time is the observation of DIO1 and the matching TX-done IRQ, not
an assumed airtime or an ISR-edge timestamp. Completion requires standby cleanup;
failed/absent completion never receives an invented TX-done timestamp. Stop emits
cancellation and disables the front end. The hardware timeout is finite even if
the control task is delayed; software observes outcomes on its next poll. BUSY/SPI
cleanup has the separate bounded waits described above, so the deadline is not a
promise of zero scheduling/cleanup latency.

There is one retained terminal-result slot. Polling with a null result advances
the state without consuming that slot; new work/configuration rejects until the
consumer takes the result. This prevents silent loss under consumer backpressure.
Frame identity and attempt index are copied, not regenerated on retry. Packet
construction and retaining original bytes across retries belong above the driver.

Run `uv run --project testbed pytest testbed/tests/test_radio_native.py -q`.
Expected TX cases: exact FIFO bytes and attributed completion; empty/oversize/
zero-timeout rejection; concurrent-start rejection; missing IRQ/deadline, chip
IRQ timeout, unexpected IRQ, I/O failure, cancel, retained result and following TX.
No direct radio-transmit operator command is introduced: `run.start` remains
unadvertised until the finite message engine and receiver are integrated. Later
physical validation must inspect actual IRQ/timestamp/stop behavior and delivered
bytes on two identified nodes with matched antennas.

## Finite reception (#20)

`node_radio_rx` accepts a 1–255-byte software frame ceiling and a finite
1–30,000,000 microsecond window. It programs a finite chip timeout, maps
RX-done/CRC/header/timeout IRQs and enables the receive front-end path. Receive
results use a distinct event kind; sender frame identities remain unknown until
the received header is validated above the driver.

An RX-done result keeps the actual FIFO length, copied valid bytes, observed
RX-done time, PHY CRC state and the same packet's signal status together. RSSI
retains half-dB and signed SNR quarter-dB precision from the raw chip response.
CRC/header errors and oversized/empty input cannot produce a successful receive
result or application bytes. Missing frames, header-only faults and timeout/cancel
carry no invented signal measurement. A FIFO/SPI failure withdraws readiness;
clearing the fault requires driver reinitialization and reconfiguration. Ordinary
timeout/cancel and terminal-result consumption permit rearming directly.

The ISR does no radio/JSON work: this initial driver observes DIO1 from polling
and reads IRQ/FIFO/status in task context. Thus its times are polling observations,
not exact interrupt-edge timestamps. The later timing milestone must measure or
replace that latency before using it for precision timing claims. The retained
result slot and finite hardware window still bound memory and radio activity if
the event consumer is delayed.

Run the native radio checks. Expected cases include valid bytes at a nonzero FIFO
offset with RSSI -86.5 dBm/SNR -1.25 dB, CRC/header rejection, empty/oversize input,
chip/software timeout, cancel, FIFO failure, held result and a subsequent receive.
Physical validation still needs actual frame/IRQ traces and signal checks on two
identified compatible nodes. The host cannot yet start an RF run: frame validation
and execution integration follow in #25/#27.
