# Pinned Codec 2 dependency (#29)

The main ESP-IDF image now links Codec 2 1.2.0, mode 3200 only. It creates a
temporary context once during control initialization, queries the actual library's
frame dimensions, destroys that context and retains the result in public metadata.
The checked frame is 160 samples / 64 bits / 8 bytes at 8 kHz (20 ms). A three-second
reference therefore contains 150 codec frames and would occupy 1200 encoded bytes,
before any artifact or RF framing. At the #29 tip, encoding/decoding operations were separate work and
`codec2_3200` stayed false. [Finite encoding](codec_encoding.md) now adds the first
operation; decoding remains #41.

## Source, build and notices

The source is the official [1.2.0 release](https://github.com/drowe67/codec2/releases/tag/1.2.0),
commit [`06d4c11e699b0351765f10398abb4f663a984f36`](https://github.com/drowe67/codec2/tree/06d4c11e699b0351765f10398abb4f663a984f36).
The IDF component is `firmware/lora_node/components/loralab_codec2`.
`dependency.json` records upstream file hashes, retained/generated file hashes,
local patches, enabled mode and build options. Source notices remain in every
retained file; `vendor/COPYING` contains LGPL 2.1. The bundled KISS FFT has a BSD
three-clause notice in `vendor/src/kiss_fft.c`. Preserve both notices with binary
redistributions. Keep the corresponding library source, local patch, build recipe
and relinkable application objects available with distributed statically linked
firmware; the build/relink instructions accompany this source checkout.

Only thirteen codec/DSP source files and the differential-LSP codebook are compiled.
FreeDV, RF modems, demos, command-line programs, other codebooks and unit-test
programs from upstream are excluded from the target. `core.cmake` applies:

- `CODEC2_MODE_EN_DEFAULT=0`, `CODEC2_MODE_3200_EN=1`;
- embedded constant codebook storage, KISS FFT, floating point;
- `-O2`, `-fno-fast-math`, function/data sections and hidden library symbols;
- ordinary allocator aliases for the upstream embedded allocator interface.

ESP-IDF garbage collection and native dead stripping remove unused entry points.
The independent native executable calls the real upstream `codec2_create` for
all other declared modes and requires null, rather than trusting metadata alone.
`Kconfig.projbuild` can disable the startup probe. An unconfigured/unsupported mode
reports `library_ready:false` and zero dimensions; it cannot advertise an operation.

To reproduce the source import, clone the official release into a separate local
checkout, then run from this repository's root:

```sh
git clone --branch 1.2.0 --depth 1 https://github.com/drowe67/codec2.git /tmp/codec2-1.2.0
python3 scripts/vendor_codec2.py --source /tmp/codec2-1.2.0
python3 scripts/vendor_codec2.py --check
```

The importer verifies the exact clean Git revision, copies the declared subset,
applies the recorded local patch and runs the retained upstream codebook generator
with relative input names. It does not access the network. Repeated imports were
byte-identical; ordinary builds/checks use retained sources and need no download.
The generated table and version header keep their upstream license notices.

## Constructor failure correction

An allocator-boundary probe reproduced a real upstream leak: failure at allocation
2 returned unavailable while retaining the first 4480-byte context on this native
build. Later FFT allocations also had unchecked/asserting failure paths.
`patches/0001-unwind-mode3200-constructor-failures.patch` zero-initializes the
context, checks intermediate allocations and releases partial context/NLP state.
It changes construction/cleanup only; codec signal processing and codebooks are
unchanged. This is an explicit local patch to the pinned release, not a pristine
upstream claim.

All eleven actual constructor allocation positions now return unavailable with
zero retained allocations, followed by a successful fresh query in the same
process. The extra index after the final allocation checks the ordinary path.
The successful native probe observed 31,308 requested live heap bytes at peak,
excluding allocator overhead. Native pointer sizes and allocator behavior differ
from ESP32; this is not target heap/stack qualification.

## Public metadata and responsibilities

`capabilities.resource_limits.codec2_library` reports version, source commit,
`library_ready`, selected mode, actual frame dimensions, sample rate and options.
Hello retains immutable codec source/frame details and transport/workload limits.
Health reports fresh availability flags, operative profile declarations and
measurements; it uses the same cached startup result without repeating that
immutable enrollment metadata. Polling does not repeatedly allocate a codec. A library probe is distinct from a working codec command,
measured processing time or acoustic intelligibility. The diagnostic image and
all existing wire/schema fingerprints remain unchanged: this metadata uses the
existing main-control resource-limits extension point.

The component owns dependency configuration and public frame queries. Portable
control owns capability reporting; ESP32 initialization selects the configured
mode. Host production behavior is unchanged. Native fixture builders use the same
sources/options and separate test-only allocator instrumentation; no physical
port is opened by the suite.

## Review and verification

Read `dependency.json` / `core.cmake`, then `codec2_dependency.c`, the constructor
patch, and `main/control/node_control.c`'s metadata/startup call. The focused checks
live in `testbed/tests/test_codec2_dependency.py` and the two native probe sources.

```sh
uv run --project testbed pytest testbed/tests/test_codec2_dependency.py testbed/tests/test_node_control_native.py -q
make check
idf.py -C firmware/lora_node build size
```

The focused command passed 94 cases without skips (17 codec and 77 existing control
cases). Final `make check` passed 604 cases without skips, Ruff, frontend build,
byte-exact generated contracts, repository checks and the 55 retained resource
hashes. One existing Starlette/httpx deprecation warning remains.

The selected-board ESP-IDF v6.0.2 build passed without flashing: image 0x6c970 bytes,
58% of the 1 MiB application partition free. Compared with #63's 0x65480 image,
this is 29,936 additional bytes with the same local board/audio selection. The
linker reports 73,841 bytes total DIRAM use, including 13,530 data and 8,256 BSS
bytes; these are whole-image static accounting, not runtime free heap. The build
also reports 16,384 bytes dedicated IRAM use and separate RTC allocations. Target
startup behavior, temporary heap/stack peak and encode/decode performance still
need matching hardware validation. No codec image has been installed on a node.

## Required task stack

A same-toolchain stack report found `make_analysis_window` alone reserves 8272
bytes on ESP32-S3. That exceeds the previous 8192-byte main-task allocation before
its caller frames. The dependency now requires `CONFIG_ESP_MAIN_TASK_STACK_SIZE`
at least 32768 when `CONFIG_LORALAB_CODEC2` is enabled; tracked defaults select
32768. This reserves 24,576 additional runtime stack bytes relative to the old
configuration. Whole-image static DIRAM and image length remain as reported above.

A real IDF build with the old cached 8192-byte configuration failed at the guard;
the same selected V4.2 profile rebuilt successfully at 32768 (0x6c950, 58% app free).
Native library checks still passed 16 cases and generated contracts stayed exact.
For an existing checkout, use `idf.py -C firmware/lora_node menuconfig` and set
**Component config → ESP System Settings → Main task stack size** to 32768. IDF
can cache an alternate `SDKCONFIG` path; update the configuration actually used
by the build. Runtime stack high-water acceptance still needs hardware evidence.

The prepared peripheral-disabled hardware image was never flashed: the required
16 MiB backup stopped twice after 12,288 streamed bytes, at 460800 and 115200 baud.
The old temporary binary was marked superseded after this stack finding. Node B
was reconnected at boot104 with its unchanged original audio firmware fingerprint
`a5ecf08a…`. No codec startup/stack result is claimed on physical hardware.

### Bounded health records

Direct C-interface testing reproduced a missing reply with configured RF and both
audio paths: repeated immutable metadata pushed the health reply beyond 4096 bytes.
The main image now enrolls constant transport/workload bounds and codec source
details only in `hello`. `health` retains current flags, full operative profile
declarations, applied settings, errors and memory/traffic measurements. Consumers
continue to require fresh matching profiles; no record limit or watchdog deadline
was widened. A combined-peripheral/configuration/error regression checks both
correlated status and periodic health through the same bounded writer. Final
verification passed 604 cases and the selected 32 KiB IDF build (0x6c970).

With #36's working encoder, enrolled dependency details are combined under
`resource_limits.codec_io`; health carries its current profile/hash/commands.
An unavailable library still uses the `codec2_library` enrollment description.
Consult the command declaration for operation support; the mode flag alone does
not imply an implemented decoder.
