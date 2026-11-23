# LoRa audio: encryption comparison bench

This separate bench compares ten PLAIN transfers with ten AES-128-GCM transfers
using the same firmware, radio settings, recording and two physical Heltecs.
It does not capture microphone audio, drive speakers or enable PTT.

The recording is three seconds of uncompressed 8 kHz, 16-bit mono PCM: 48,000
audio bytes, or 48,044 bytes inside the source WAV. The user-reported separation
is approximately 24 inches (60.96 cm). Trials 1-10 use PLAIN; trials 11-20 use
GCM. Each group alternates direction, giving five transmissions per node.

## Completed physical run: 2026-11-23

All 20 trials passed: ten PLAIN and ten AES-128-GCM. All 4,000 unique DATA chunks
were reconstructed and all twenty received PCM messages were byte-for-byte
identical to the original. All ten encrypted trials authenticated successfully;
both nodes' exported ciphertext matched an independent live computer-side
AES-GCM calculation. Both serial ports were closed after the run.

| Mean per message | PLAIN | AES-128-GCM |
| --- | ---: | ---: |
| Sender transaction | 29.460997 s | 29.537397 s |
| Receiver DATA span, first to last DATA arrival | 29.318462 s | 29.295282 s |
| Receiver ready, from first transport arrival | 29.321783 s | 29.458354 s |
| Calculated DATA + metadata + ACK airtime | 22.201715 s | 22.214118 s |
| Chunking, summed over 200 unique chunks | 116.7449 ms | 116.6299 ms |
| Dechunking, summed over 200 unique chunks | 72.5171 ms | 72.4831 ms |
| Encryption | Not used | 17.5981 ms |
| Authenticated decryption | Not used | 17.6618 ms |
| TX requested message buffers | 48,000 bytes | 96,000 bytes |
| RX requested message buffers, including chunk tracking | 48,036 bytes | 96,036 bytes |
| TX allocated message blocks | 48,116 bytes | 96,232 bytes |
| RX allocated message blocks | 48,116 bytes | 96,232 bytes |
| Transmitted radio payload bytes, including ACKs and retries | 53,404.4 bytes | 53,408.2 bytes |

The sender mean increased by 76.3993 ms (about 0.259%). The PLAIN group had 16
DATA retries and 12 receiver radio CRC errors; GCM had 14 retries and nine CRC
errors. Both had two duplicate DATA receptions, no metadata retries and no
application errors. Retry recovery left zero changed PCM bytes. These blocked
cohorts do not isolate encryption as the cause of the total transfer difference.

The deterministic addition without retries is one 40-byte metadata payload and
one 14-byte ACK: 54 additional radio payload bytes and 32.128 ms of calculated
airtime. Ciphertext remains 48,000 bytes; ciphertext plus nonce and tag is
48,028 bytes. The final received PCM remains 48,000 bytes (48,044-byte WAV).
Each node's extra message-buffer allocation is 48,116 bytes, including allocator
rounding. The observed PSRAM free-space decrease was 48,132 bytes in PLAIN and
96,264 bytes in GCM; these are distinct from allocation-block sizes.

Both successful builds used 490,406 bytes of linker-reported flash and 26,692
bytes of static RAM; each firmware binary was 502,800 bytes. Physical storage
capacity is 16 MiB flash and 2 MiB PSRAM per node. The same binary supports both
modes, so this experiment does not measure the incremental firmware size of
adding encryption to an otherwise crypto-free build.

Evidence: [seven-page PDF](../output/pdf/Heltec_LoRa_20_Trial_Encryption_Comparison_Report.pdf),
[physical run](../captures/20261123-lora-crypto-comparison-run01/summary.json),
[independent audit](../output/validation/lora-crypto-run01-independent-audit.json),
and [frozen archive](../20-lora-encryption-comparison-tests/20261123-run01/).
The host did not retain the key after the live comparison; the saved evidence
contains hashes, ciphertext and authentication events, not the secret key.
The stopped nodes retain their session key in volatile RAM until reset or
replacement; stopping the radio does not wipe device memory.

## What encryption changes

AES-128-GCM runs on the ESP32 through its supplied Mbed TLS implementation.
The computer generates one ephemeral 128-bit key for the run and provisions it
over USB to both nodes. The key is not transmitted by LoRa, saved in the report,
or included in command logs. Each encrypted message receives a new 96-bit nonce;
the runner checks nonce uniqueness. A fresh nonce is sent only to the transmitter
over USB. It then travels to the receiver over LoRa.

The sender encrypts its entire 48,000-byte recording once. Its ciphertext has
the same length. One additional 40-byte radio payload carries an eight-byte
authenticated header, the 12-byte nonce, a 16-byte authentication tag and a
four-byte CRC32. The header binds the message ID and audio length. This packet
has its own 14-byte acknowledgement. The 200 existing audio-data packets carry
ciphertext instead of plaintext; their sizes and stop-and-wait retry mechanism
remain unchanged. Retries reuse the same sealed message.

The receiver reconstructs ciphertext, verifies the GCM tag and decrypts into a
separate buffer. It acknowledges the final data packet only after successful
authentication. An invalid tag cannot produce a successful PCM export. CRC32
still detects transport corruption; metadata and ACK CRCs are not cryptographic
authentication. This is a bench protocol, without production key management or
persistent replay protection.

For straightforward verification, each GCM role allocates an extra 48,000-byte
PSRAM buffer. TX keeps source plus ciphertext; RX keeps ciphertext plus verified
plaintext. This extra buffer is an implementation choice, not an AES requirement.
Actual allocator sizes, PSRAM changes, crypto context and packet scratch sizes
are recorded separately in bytes. One KiB is 1,024 bytes. The same binary holds
crypto code in flash in both modes; no recording is written to flash.

## Measurements and checks

- Device-local encryption and authenticated-decryption elapsed time, measured
  separately from chunking and reassembly. Key setup is measured separately.
- Sender transaction time, receiving span, receiver message-ready time, USB
  loading/export intervals and calculated LoRa airtime including metadata/retries.
- Payload lengths, frame and ACK bytes, retries, CRC errors, duplicates, and
  per-role memory allocations with explicit units.
- Exact comparison of received PCM against the source for every trial.
- Independent computer-side AES-GCM computation, compared with both nodes'
  exported ciphertext, metadata, tag, and packet CRCs in encrypted trials.
- On-device known-answer and altered-key/tag/ciphertext rejection self-tests
  before the measured cohorts. These are labeled preflight checks, not extra
  radio trials in the 20-trial comparison.

Processing values are elapsed timer intervals, including scheduling or interrupt
overhead within the measured regions. They are not pure CPU-cycle measurements.
Transfer intervals overlap and must not be added together. The two groups run
in blocks, so radio retry variation and time-dependent bench conditions can
affect their average transfer times; the entire difference is not necessarily
caused by encryption. Isolated RAM-write latency and complete peak memory use
are not measured.

## Repeat the comparison

Use the two explicitly selected environments. Match MACs before uploading:
Heltec-A / COM6 is `8C:FD:49:B5:B7:8C`; Heltec-B / COM7 is
`44:1B:F6:6F:99:E4`. Keep antennas connected and close other serial monitors.

```powershell
pio run -e heltec_crypto_com6 -e heltec_crypto_com7
pio run -e heltec_crypto_com6 -e heltec_crypto_com7 -t upload
powershell -NoProfile -ExecutionPolicy Bypass -File tools/run_lora_crypto_comparison.ps1 -Check
powershell -NoProfile -ExecutionPolicy Bypass -File tools/run_lora_crypto_comparison.ps1 -Start
```

Without `-Start` or `-Check`, the launcher only describes the test. `-Check`
performs local checks without opening serial ports. The runner saves raw serial
logs, per-trial summaries, PCM WAVs and ciphertext exports in a new capture
folder. It closes both serial ports when finished. Previous evidence is retained.

The separate original audio and unencrypted radio targets remain available.
Build/upload success and cryptographic self-tests alone do not prove radio
delivery; only the saved physical trial evidence supports that result.

Reference: [Mbed TLS GCM API](https://mbed-tls.readthedocs.io/projects/api/en/v3.6.7/api/file/gcm_8h/).
