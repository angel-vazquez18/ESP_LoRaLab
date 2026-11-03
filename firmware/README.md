# Firmware

Two standalone ESP-IDF v6.0.2 projects live here:

| Project | Current behavior | Purpose |
| --- | --- | --- |
| `lora_node/` | Empty app_main scaffold | Main node development, one image for A/B |
| `diagnostic/` | v2 diagnostic serial/health subset | Existing hardware diagnostic reference |

The scaffold was relocated from root `lora_node/` without replacing its C source.
Old build output and sdkconfig were preserved under ignored `local/migration/`.
The old sdkconfig selected only 2 MiB flash; the new tracked defaults select the
confirmed ESP32-S3 / 16 MiB flash and USB Serial/JTAG bring-up console. The console
is not an implementation of NDJSON. No peripheral driver is initialized.

From repository root, activate ESP-IDF then build either target:

```sh
source /Users/anken18/.espressif/v6.0.2/esp-idf/export.sh
idf.py -C firmware/lora_node build
idf.py -C firmware/diagnostic build
```

Building diagnostic firmware may fetch its pinned cJSON dependency. Neither command
flashes hardware. For firmware checks, build only the target changed unless shared
firmware or generated protocol content affects both.

Future reusable module placement is documented in `components/README.md`.
Use one board profile and one shared contract. The host accepts one physical node
for local tests and requires a pair for RF tests; no simulator is available.
