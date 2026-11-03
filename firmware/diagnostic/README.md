# Single-board diagnostic firmware

ESP-IDF v6.0.2 target for ESP32-S3 native USB Serial/JTAG. Implements the
diagnostic subset of contract 2.0: hello, ownership/lease, status, 1 Hz health,
persistent boot counter, heap statistics, command deduplication, bounded NDJSON
and explicit errors. RF/audio/security-session commands remain unavailable.

Validated device: `esp-f85b1ba27744`, ESP32-S3 rev 0.2, 16 MiB flash, 2 MiB quad
PSRAM, USB `/dev/cu.usbmodem1201`. The external board model/pin map is unverified.
Verify another board's target/memory/USB routing before using these defaults.
The UART firmware transport is a remaining adapter; this target uses native USB.

Build from the repository root:

```sh
uv run --project testbed python scripts/generate_contract.py
source /Users/anken18/.espressif/v6.0.2/esp-idf/export.sh
idf.py -C firmware/diagnostic build
```

`main/idf_component.yml` and `dependencies.lock` pin Espressif cJSON. Generation
writes the diagnostic schema digest into `main/contract_schema.h`; rebuild both
sides after schema changes. ESP-IDF 6's PSA hash interface fingerprints commands.

Disconnect the dashboard slot before esptool/IDF Monitor or the opt-in check:

```sh
uv run --project testbed python scripts/check_hardware.py --port /dev/cu.usbmodem1201 --device-id esp-f85b1ba27744 --seconds 20
```

This verifies identity/schema, normal/error replies, malformed-input recovery
and live health with no observation-period framing errors/gaps. Startup boot text
is counted separately. It does not close all IF-01 cases or establish RF/audio results.

The original complete 16 MiB image remains in the original workspace under ignored `data/hardware-backups/`;
`manifest.json` records exact size/SHA-256. The fast stub reader stalled, so the
successful backup used esptool `--no-stub read-flash`. The installed image also
used ROM mode and was verified by esptool. No eFuses were changed.

To reproduce the installation on the validated device after preserving its flash:

```sh
python -m esptool --chip esp32s3 --port /dev/cu.usbmodem1201 --no-stub --baud 460800 write-flash --flash-mode dio --flash-size 16MB --flash-freq 80m 0x0 firmware/diagnostic/build/bootloader/bootloader.bin 0x8000 firmware/diagnostic/build/partition_table/partition-table.bin 0x10000 firmware/diagnostic/build/lora_diagnostic.bin
```

To restore the original image, disconnect the dashboard, verify the backup hash,
and explicitly write the full backup at address zero with flash mode, frequency
and size set to `keep`, then reset. Keep the local backup with this device.

Sources: [Espressif cJSON](https://components.espressif.com/components/espressif/cjson/versions/1.7.19~2/readme),
[ESP-IDF](https://github.com/espressif/esp-idf/tree/v6.0.2).
Retain the managed component's upstream MIT license and ESP-IDF notices when
redistributing the source or firmware.
