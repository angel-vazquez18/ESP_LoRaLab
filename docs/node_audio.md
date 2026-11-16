# Finite local audio

Playback is a local board feature, separate from RF voice, codec support and
acoustic qualification. The first board is reported fully wired; the second has
no amplifier/speaker wiring yet. Never infer output availability from the model.

## Build configuration

Default builds disable audio. For the fully wired first bench board:

```sh
source /Users/anken18/.espressif/v6.0.2/esp-idf/export.sh
idf.py -C firmware/lora_node -B "$PWD/build" \
  -D SDKCONFIG="$PWD/firmware/lora_node/build/sdkconfig.audio" \
  -D 'SDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.audio.defaults' build
```

Use a separate build/config path for a board with different connected peripherals.
The profile describes connections; the explicit Kconfig setting enables drivers.
`make contracts` generates audio GPIO constants from the existing board JSON.
No GPIO or power connection changed. Printed board revision remains unobserved.

## Playback contract

The independent `audio_io_v1` supplement (`contracts/v2/audio.schema.json`) is
advertised under `resource_limits.audio_io`; original diagnostic/main-control/RF
schema digests are unchanged. Host requests require the exact supplement in both
hello and current health, plus the configured playback flag.

`audio.play {"artifact_id":"<UUID>"}` returns an accepted operation. Listen for
its correlated `operation.result`; acceptance is not completion. Only committed,
unused `pcm_s16le_8000_mono` files with 1–24000 complete samples can start. The file
stays pinned until DMA stops. Other operations/file commands reject while busy.
`operation.stop` cancels. Lease loss, detected USB loss, deadline and shutdown
stop DMA before releasing the file; committed files remain available in that boot.

Output is Philips I2S, master, 8000 Hz, two 16-bit slots, BCLK GPIO38, WS39, DIN40,
no MCLK. Signed little-endian mono samples are divided by eight (integer division
toward zero, −18.0618 dB) and duplicated to both slots. The documented hardware
GAIN strap is 6 dB; software metadata records the configured strap, not a measured
amplifier gain. No automatic gain control or normalization is applied.

The complete attenuated stereo clip is allocated in internal RAM (up to 96000
bytes); four 128-frame DMA blocks are preloaded. Each sent callback counts frames
and refills its finished block directly. The final block and subsequent blocks
are zero padded. Completion reports source samples separately from DMA frames;
DMA frames can exceed the source length because of block rounding and poll delay.
The single USB/control writer remains responsive. No background audio task or
unbounded blocking writer is used.

`underflows` counts observed callback intervals longer than the three-block refill
headroom (48 ms). This conservative deadline detector cannot prove every sample
appeared electrically; it is not a logic-analyzer measurement. A detected miss
fails the operation. Driver-start, missed-deadline and short-count failures return
an error; its message retains sample/frame/underflow counts. Stop disables/deletes
I2S before freeing its internal buffer. An unexpected driver cleanup failure uses
ESP-IDF's checked fatal path rather than freeing memory still owned by DMA.

Successful/cancelled results record sample counts, DMA completion, gain ratio,
duration and `heard_verified:false`. Only an operator can establish heard output.
The SD/MODE and GAIN straps are fixed to 3.3 V; software cannot mute the amplifier
with those pins. Stopped I2S and zero padding bound this finite playback path.

## Verification and reading order

1. `audio/pcm_samples.c`: signed conversion, fixed attenuation and slot duplication.
2. `audio/esp32_audio.c`: real IDF channels, preloading, callback progress and stop.
3. `control/node_control.c`: validation, pinning, accepted/result and cleanup.
4. `audio_contract_v2.py`, `nodes.py`: exact supplemental compatibility and operation tracking.

Paths above are under `firmware/lora_node/main` or `testbed/src/lora_testbed`.
Run `uv run --project testbed pytest testbed/tests/test_node_audio_native.py`:
17 cases cover boundary counts, invalid files, duplicate acceptance, injected
allocation/start/DMA faults, stop/lease/link/deadline recovery and signed sample
conversion. These use the real portable C core and an isolated driver callback
fixture; they do not qualify the physical amplifier. Run `make check` and the
ESP-IDF build above as well. Expected: all checks pass without native-test skips.

Physical listening, printed revision and measured clock/3.3 V rail remain pending.
The user is away; prepare quiet-reference and spoken-phrase procedures for later.
Do not use driver completion as proof of heard audio or speaker power.

## Primary references

- [ESP-IDF 6.0.2 I2S API](https://docs.espressif.com/projects/esp-idf/en/v6.0.2/esp32s3/api-reference/peripherals/i2s.html), and installed `esp_driver_i2s/i2s_common.c` callback/preload implementation.
- [MAX98357A/B datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/MAX98357A-MAX98357B.pdf): I2S slots, sample rates and hardware gain selection.

Uses the existing ESP-IDF driver (Apache-2.0); no additional audio library is added.
