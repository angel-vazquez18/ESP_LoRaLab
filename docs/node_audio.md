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

## Finite microphone capture (#24)

`audio.capture {"artifact_id":"<fresh UUID>","sample_count":24000}` reserves
48000 bytes before acceptance. It uses the same operation owner, deadline and
stop command as playback. Only one direction runs at a time. Driver/allocation/
DMA/count/hash failures and cancellation discard the private partial file.
Successful DMA completion stops I2S, hashes the complete bytes, and publishes a
committed PCM manifest in the operation result. No partial file becomes playable.
The node hash identifies captured bytes; host download must independently verify it.

The input is Philips I2S master on the other controller, 8 kHz, two 32-bit slots
(64 BCLK cycles per frame), GPIO4 BCLK / GPIO5 WS / GPIO6 DIN, no MCLK.
L/R grounded selects the left slot. INMP441's signed 24-bit data occupies the
high 24 bits of the 32-bit word. Conversion selects the high 16 bits, explicitly
sign extends, and writes little-endian PCM. Eight low data bits are discarded;
no normalization, AGC or additional capture gain is applied.

Every capture discards 4800 startup frames (600 ms at configured 8 kHz), then
records exactly the requested 1–24000 samples. This exceeds the microphone's
specified 2^18-clock startup interval (512 ms at configured 512 kHz BCLK).
These are configured/calculated rates, not instrument measurements. Each bounded
DMA callback selects/converts the left samples directly; the IDF receive queue is
not the consumer, so its queue-full notification is not treated as a sample loss.
`overflows` uses the same conservative callback-deadline detector as output.
No claim is made that it detects every possible electrical or DMA defect.

The trusted producer store API is separate from the committed consumer API.
Serial put/commit cannot mutate that private capture reservation. Shutdown stops
callbacks before freeing it. Input conversion/capture lifecycle tests live beside
playback tests: `test_node_audio_native.py` now has **43** passing cases, including
26 capture count/hash, rejection, fault/cleanup and signed-conversion checks.

[INMP441 manufacturer datasheet](https://product.tdk.cn/system/files/dam/doc/product/sw_piezo/mic/mems-mic/data_sheet/inmp441.pdf)
provides slot representation, startup and clock requirements. The existing
ESP-IDF driver remains the only audio dependency. Audio capture is separately
configured with `CONFIG_LORALAB_AUDIO_CAPTURE`; a microphone-only board can enable
capture while keeping `CONFIG_LORALAB_AUDIO_PLAYBACK` off.

## November 16 automated board checkpoint

Matched device `esp-f85b1ba27744`, boot `esp-f85b1ba27744:60`,
ELF `9ae1fce748ff5dc47d78841560bde8b682375bbd5843471716c6de1417e34496`. The cumulative image was flashed
after retained full-backup/USB-identity/port checks, with NVS and eFuses preserved.
Playback 1/128/129/24000 samples and capture 1/129/24000 samples passed actual
DMA/count checks; captured byte counts/hashes/readback matched independently.
Sequential capture/playback, cancel in each direction, private capture cleanup and
a following valid capture passed. Zero observed event gaps/framing errors.
Ignored evidence: `local/m2-batch/audio-hardware-report.json`, raw commands/events,
`quiet-reference.wav` and `room-capture.wav`. No speech/listening/instrument
observation is implied; full physical qualification remains pending.

Full source checks: **336 tests passed**, no skips, plus lint/frontend/generated
contracts/repository checks. Audio-enabled ESP-IDF image size 0x43e90, 73% app
partition free. Existing Starlette/httpx deprecation warning remains.

### Signal-path finding: not yet qualified

Inspection of the unattended capture found **all-zero PCM**, including the full
24000-sample clip. The smaller `local/m2-batch/check_capture_signal.py` reproduces
this explicitly as `SIGNAL_UNVERIFIED`, rather than accepting DMA success as a
working microphone. Targeted capture counters then showed zero nonzero words in
**both** raw slots after the startup discard (`raw_left_or=raw_right_or=0`).
Thus selecting the other slot or changing the signed-16 conversion alone would
not recover a signal in that observation. The physical cause is not established.
Check microphone supply/ground/SD/SCK/WS, breakout enable and the actual clock/data
signals when an operator/equipment is available. Do not change the wiring profile
or claim microphone qualification based on speculation. Raw slot counts are
retained in capture results for future checks. A silent file can be byte-valid
while providing no evidence of microphone response.
