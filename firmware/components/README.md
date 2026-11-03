# Planned reusable firmware modules

This directory is an architecture map, not implemented drivers. Add an ESP-IDF
component only when implementing its first behavior and caller. Until then the
main scaffold remains buildable without fake module implementations.

| Planned module | Responsibility | Interface / evidence |
| --- | --- | --- |
| `board` | Pins, USB, power controls, button/display and memory bring-up | Board initialization and observed availability |
| `serial_control` | Bounded NDJSON, identity, ownership and command routing | Command/reply and event interface; malformed input checks |
| `radio` | SX1262 and board RF-front-end control | Configure/read back, transmit, receive, stop; real IRQ/timestamp evidence |
| `packet_link` | RF header, fragmentation, reassembly and ACK/retry | Byte messages in/out with bounded outcomes; shared vectors |
| `security` | GCM, source/run key lifecycle and replay checks | Protect/accept/reject; known-answer and negative vectors |
| `audio` | I2S capture/playback, PCM conversion, codec and buffering | Finite artifacts and outcomes; memory and timing evidence |
| `run_control` | Session state, preparation, arming, start/stop and telemetry | Contract lifecycle with bounded cancellation and cleanup |

The main target composes modules; modules do not open host files or perform host
analysis. Serial routing does not duplicate packet/security logic. Packet/security
logic should accept bytes/configuration and return results that can be checked
without physical hardware. Configure EXTRA_COMPONENT_DIRS in consuming projects
when the first shared component is added; it is not wired in prematurely.
