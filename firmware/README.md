# Firmware

Two standalone ESP-IDF v6.0.2 projects live here:

| Project | Current behavior | Purpose |
| --- | --- | --- |
| `lora_node/` | Main-control NDJSON, identity/health, ownership, memory probe | Main node development, one image for A/B |
| `diagnostic/` | v2 diagnostic serial/health subset | Existing hardware diagnostic reference |

The original scaffold was relocated from root `lora_node/` without replacing its C source.
Old build output and sdkconfig were preserved under ignored `local/migration/`.
The old sdkconfig selected only 2 MiB flash; the new tracked defaults select the
confirmed ESP32-S3 / 16 MiB flash, 2 MiB PSRAM and USB Serial/JTAG. The main
target now uses one NDJSON writer and suppresses ordinary application logs after
initialization. No RF/audio peripheral driver is initialized. The new control
image is not flashed or physically accepted yet; see
[Milestone 1 review](../docs/milestone_1_review.md).

From repository root, activate ESP-IDF then build either target:

```sh
source /Users/anken18/.espressif/v6.0.2/esp-idf/export.sh
idf.py -C firmware/lora_node build
idf.py -C firmware/diagnostic build
```

Building either target may fetch its pinned cJSON dependency. Neither command
flashes hardware. For firmware checks, build only the target changed unless shared
firmware or generated protocol content affects both.

Future reusable module placement is documented in `components/README.md`.
Use one board profile and one shared contract. The host accepts one physical node
for local tests and requires a pair for RF tests; no simulator is available.

## Main target organization

`lora_node/main/lora_node.c` only composes the running node. Its `platform/` module
owns ESP-IDF callbacks and persistent identity; `transport/` owns USB I/O;
`control/` owns the portable state machine; `protocol/` owns strict JSON parsing.
The root generator maintains `generated/contract_schema.h`. These remain source
modules inside one main component; see root `docs/architecture.md` for the tree.
