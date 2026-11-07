# ESP-IDF firmware instructions

Read root `AGENTS.md`, `hardware/README.md`, the selected v2 contract and the
relevant procedure before implementing command or measurement behavior. Use root
`docs/node_development_plan.md` to choose capability slices; experiments are the
coverage/qualification cross-check, not a requirement to organize firmware by test ID.

- ESP-IDF v6.0.2, ESP32-S3, C/C++. `lora_node/` is the main development scaffold;
  `diagnostic/` is a separate working diagnostic target. Do not confuse them.
- One image supports roles A/B assigned by the host. Physical identity persists
  independently of role; session keys and active runs do not survive reset.
- Hardware profile: root `hardware/boards/heltec_wifi_lora32_v4.json`. User-reported
  microphone/amplifier wiring and 6 dB gain are recorded; independent driver/audio
  validation is still pending. Do not confuse reported wiring with capability proof.
- PTT is GPIO 47. GPIO 7 controls the onboard RF front-end supply. GNSS is unused
  and disconnected so GPIOs 38/39/40 are available to the audio output plan.
  Preserve all onboard RF control pins; radio SPI alone is not full board support.
- Keep board-specific pins and power control separate from packet/security logic.
  `components/README.md` defines proposed module responsibilities. Create actual
  modules when implementing them; do not add successful-looking stubs.
- Keep `app_main` composition small. Put device I/O behind narrow interfaces, with
  packet framing, replay and reassembly logic independent of FreeRTOS where feasible.
- Bound allocations, queues, record size, retries, operation time and cancellation.
  No unbounded serial/radio callbacks. Keep state transitions and cleanup explicit.
- One serialized protocol writer emits bounded NDJSON. Logs must not corrupt the
  protocol channel. Report actual capabilities; unsupported commands reject clearly.
- Use generated protocol metadata and shared vectors. Do not hand-edit generated
  schema digests or copy wire definitions into another independently evolving spec.
- Use fresh per-source/per-run keys; unique nonces; authenticated metadata; no key
  logging, persisted run keys, nonce reuse or changed-byte retries under one nonce.
- Node clocks are independent. Calibrated one-way timing requires the selected
  wired-pulse method and uncertainty; host receipt timestamps cannot substitute.
- Audio capture format and application PCM format may differ; conversion and
  Codec 2 are explicit work. Verify memory, buffering, fragmentation and airtime.
- Commit `sdkconfig.defaults` and dependency manifests/locks, not build output,
  managed_components or local sdkconfig. Record reused-code versions and licenses.

Activate ESP-IDF, then run `idf.py -C firmware/lora_node build` from repository
root (or `make firmware-build`). Build `firmware/diagnostic` separately when changed.
Build success is not flash, RF or audio validation. Do not open ports or flash
unless the task explicitly authorizes that hardware action.
