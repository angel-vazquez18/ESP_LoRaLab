# Project brief

The LoRa-Based Encryption and Communications Testbed is a controlled bench with
two bidirectional embedded nodes and a macOS host. Homar owns embedded hardware
and firmware; Angel owns the host, orchestration, storage, analysis and procedures.
Both work against shared versioned interfaces in this repository.

## User requirements

- Host platform macOS; graphical dashboard first, with a CLI for the same workflows.
- Node framework ESP-IDF. Include secure data, voice and every CDR experiment and
  validation category. Do not reduce the 23-procedure scope to simplify delivery.
- First-week-of-December 2026 delivery target. Field deployment, autonomous node
  operation and battery optimization are outside the primary bench objective.
- November 1: replace the earlier simulation-first direction with a physical-only
  host. Local/serial/subsystem checks must run with one node, A or B independently.
  Require two distinct nodes only for tests/cases that need a link. Keep all 23
  procedures; missing physical firmware/runner capabilities remain blocked.
  Automated software tests may use isolated serial fixtures, not an operator simulator.
- November 4: organize node firmware development around reusable capabilities and
  useful end-to-end node workflows. Use experiments as a coverage/validation
  reference, not the definitive initial implementation order. See
  `node_development_plan.md`; the earlier five-experiment firmware draft was not installed.
- The selected October 18 provisional contract decisions may be implemented now;
  review with Homar can revise them through a versioned update. Do not block on it.
- October 31: firmware and the existing working testbed belong together in
  `~/Documents/ESP_LoraLab`, with context and scoped instructions for coding agents.
  Import the current testbed, not a fresh host rewrite.

## Hardware decisions from this chat

- Heltec WiFi LoRa 32 V4 / ESP32-S3 / SX1262 915 MHz kit, 16 MiB flash / 2 MiB PSRAM.
  The exact printed board revision remains unobserved.
- GNSS will not be used; leave its module disconnected.
- INMP441 microphone, SATUY MAX98357A amplifier, Alrhso 8-ohm / 1-W speaker.
- All peripherals powered by the Heltec board; amplifier uses its 3.3 V rail.
- Microphone GPIOs 4/5/6; amplifier GPIOs 38/39/40. The corrected wiring reference
  uses PTT GPIO 47; GPIO 7 is reserved for onboard RF-front-end supply control.
- November 4 user report: one ESP is connected to this laptop; the microphone and
  amplifier are wired to the assigned GPIOs. Microphone L/R is tied to GND;
  amplifier SD/MODE and GAIN are tied to the Heltec 3.3 V rail. The gain setting is
  6 dB. These are reported physical connections, not independently verified operation.
- Speaker and PTT connection/operation have not been explicitly confirmed.
  Second-node availability, measured rail headroom, exact printed revision and
  actual audio performance remain to be established.

## Selected implementation baseline

ESP-IDF v6.0.2; bounded NDJSON v2; AES-128-GCM with fresh per-source/per-run,
RAM-only keys; 40-byte RF header; 160-byte default fragments; optional stop-and-wait
with two retries; Codec 2 1.2.0 mode 3200; wired-pulse one-way clock calibration.
These are specification choices. Current support is documented in `status.md`.

The three-second raw audio baseline is 8 kHz / 16-bit / mono: 48,000 bytes.
Encoded size, frame overhead, airtime, memory and feasibility must be measured or
calculated separately. Continuous high-quality speech is not an assumed outcome.

The original CDR is `secure_lora_comms_testbed_cdr.pdf`: October 12, 2026,
22 pages, Homar A. Rodriguez and Angel K. Vazquez, EN.525.743 Fall 2026.
It records a planned design, not verified implementation. Later user decisions
and the selected versioned contract take precedence over that baseline.
