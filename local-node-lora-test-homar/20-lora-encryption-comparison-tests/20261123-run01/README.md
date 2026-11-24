# Twenty LoRa trials: plain audio versus AES-128-GCM

New physical run on 2026-11-23: ten PLAIN transfers followed by ten AES-128-GCM transfers, five in each direction per group. All twenty received recordings matched the source exactly.

Same source: 3.00 seconds of uncompressed 8 kHz, 16-bit mono PCM; 48,000 audio bytes (48,044 WAV bytes). User-reported distance: approximately 24 inches. No microphone, physical speaker or PTT test was performed.

| Mean per message | PLAIN | AES-128-GCM |
| --- | ---: | ---: |
| Sender transaction | 29.461 s | 29.537 s |
| Receiver DATA span | 29.318 s | 29.295 s |
| Calculated DATA + metadata + ACK airtime | 22.202 s | 22.214 s |
| Chunking | 116.745 ms | 116.630 ms |
| Dechunking | 72.517 ms | 72.483 ms |
| Encryption | 0.000 ms | 17.598 ms |
| Authenticated decryption | 0.000 ms | 17.662 ms |
| TX allocated PSRAM blocks | 48,116 bytes | 96,232 bytes |
| RX allocated PSRAM blocks | 48,116 bytes | 96,232 bytes |

One KiB is 1,024 bytes. Allocation totals sum the original role buffer and the separate crypto buffer, excluding shared static state. The extra 48,000-byte crypto buffer is an implementation choice. Audio is held in volatile PSRAM and is not written to flash.

The run uses one fresh session key, unique 12-byte nonces per encrypted message and 16-byte authentication tags. A 40-byte metadata packet and its 14-byte ACK carry the envelope through LoRa before the unchanged 200 DATA packets. Keys were kept only in RAM and command logs were redacted. Stopped nodes retain their session key in volatile RAM until reset or replacement. Offline evidence can recheck saved audio/ciphertext hashes and raw firmware authentication events; independent AES comparison was performed on the computer during the live run while its key was available.

The two groups ran in blocks. Retries and bench variability can affect transfer averages; do not attribute the entire elapsed difference to encryption. Processing timers measure local elapsed work, including scheduling overhead. Radio intervals overlap and must not be added.

Contents: the seven-page PDF and matching audit JSON; `run/` raw logs, WAVs, ciphertext and trial summaries; `readiness/` device checks; `validation/` build/upload logs and independent audit; `implementation/` measured source and analysis tools. The initial build failures are retained alongside the final successful build log. Firmware image hashes are in the implementation manifest.
