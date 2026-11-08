# Firmware instructions

References start at repository root unless a directory is explicitly named.
Read the root instructions, `hardware/README.md` and the selected v2 contract before
changing device behavior. Follow `docs/node_development_plan.md` for feature order.

- ESP-IDF v6.0.2, ESP32-S3, C/C++. `firmware/lora_node/` is the main image;
  `firmware/diagnostic/` is a separate reference target. One main image supports host-assigned A/B roles.
- For main-node teaching, give small explained steps for the user to type unless
  they request implementation. Keep comments short and mostly inline.
- Within `firmware/lora_node/`, keep `main/lora_node.c` as composition. ESP-IDF
  callbacks/identity belong in `main/platform/`, USB I/O in `main/transport/`, portable control in `main/control/`,
  JSON validation in `main/protocol/` and generated metadata in `main/generated/`.
- Keep board pins/power separate from packet/security logic. Preserve RF-front-end
  controls; GPIO 7 is not PTT. Consult the actual board revision before driver work.
- Bound memory, queues, records, retries, operation duration and cancellation.
  Maintain explicit state/cleanup and one serialized protocol writer; ordinary
  logs must not corrupt protocol output.
- Keep the portable core independent of ESP-IDF/FreeRTOS and test it through the
  same interface the real transport uses. Keep private details private.
- Generate schema metadata with root `make contracts`; never edit digests by hand.
- Preserve NVS identity across images; never automatically erase a failed NVS store.
  Active operations and session keys do not survive reset or ownership loss.
- Preserve nonce uniqueness, exact-byte retries and independent node clock domains.
  Audio format conversion, buffering and codec behavior must remain explicit.
- Track defaults and dependency manifests/locks, not local sdkconfig/build output.
  Record reused library versions/licenses.

From repository root, activate ESP-IDF and run `idf.py -C firmware/lora_node build`.
Build `firmware/diagnostic` only if affected. Native core checks are in
`testbed/tests/test_node_control_native.py`; they require a host C compiler and
locked managed cJSON sources. A skipped native check is not a pass.
For manual framing tests, use `esp_idf_monitor --eol LF`: ESP32's CR default also
converts Ctrl+J to CR. See `docs/milestone_1_review.md` for physical acceptance.
