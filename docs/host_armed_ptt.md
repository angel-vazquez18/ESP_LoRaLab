# Host-armed finite PTT capture (#30)

PTT is an optional input for one host-selected finite microphone capture. It does
not start an autonomous voice/radio mode. The current planned normally-open switch
connects GPIO47 to GND with an internal pull-up. GPIO7 remains reserved for the RF
front end. No pin or power assignment changes in this issue.

## Read the code

1. `firmware/lora_node/main/input/ptt_gate.c`: allocation-free 50 ms debounce. Each
   arm requires a stable release, then a stable press. There is no interrupt queue.
2. `main/control/node_control.c`: `ptt.arm` validates ownership, geometry, idle state
   and configured input/capture. It reserves a private capture artifact and returns
   the normal correlated accepted operation before arming. The ordinary finite
   operation deadline includes the button wait. Only the accepted fresh press
   starts the audio driver. Stop, ownership loss, disconnect and deadline release
   the reservation before any queued button work; an unstarted DMA is not polled
   or stopped. Duplicate commands reuse their reply without repeating capture.
3. `main/platform/esp32_ptt.c`: optional polling input driver. Disabled builds do
   not configure GPIO47. Enabled builds configure input/pull-up without interrupts,
   and only if the microphone driver is also configured.
4. `ptt_contract_v2.py` and generated `ptt_capture.schema.json` / `ptt_profile.h`:
   independent exact supplement. Fixed wiring/action/debounce/deadline policy is
   fingerprinted instead of repeated in every hello/health record. The generator
   rejects a board pin/active-level/pull-up mismatch. Other wire digests stay intact.
5. `nodes.py`, `node_audio.py`, `app.py`, `cli.py`: exact current capability checks,
   asynchronous operation tracking and the existing single-bench capture/readback/
   cleanup service. Saved records distinguish `host_armed_ptt` from direct capture.

## Enable deliberately

`CONFIG_LORALAB_PTT` defaults off and depends on `CONFIG_LORALAB_AUDIO_CAPTURE`.
Its menu option explicitly requires a verified board revision and GPIO47-to-GND
switch wiring. The printed PCB revision and PTT wiring remain unverified on the
physical bench, so this work does not enable or flash that input on either node.
Verify those prerequisites under #1 before selecting it for a physical image.
Unknown board revisions do not become verified through a successful build.

An enabled matching image advertises `resource_limits.ptt_io` only when it has an
input callback and microphone capture. The supplement is `ptt_capture_v1`, SHA
`547a3d502ecd47b17bdb197fb35350bd7056b5ff73bbfc44d3e770acb3a87def`.
No diagnostic/control/audio/execution/artifact/codec schema change is required.
An older or unconfigured image remains available for its existing capabilities,
but the PTT API rejects it before reserving a capture.

## Use from the shared host

With an identified, compatible, deliberately enabled node connected through the
backend:

```sh
uv run --project testbed lora-testbed audio-ptt A --samples 24000
uv run --project testbed lora-testbed audio-status "$AUDIO_ID"
uv run --project testbed lora-testbed audio-stop "$AUDIO_ID"
```

Use the actual operation ID from the arm response. The API equivalent is
`POST /api/nodes/A/audio/ptt` with `{"sample_count":24000}`. `GET /api/state` exposes
current `ptt_support`; ordinary audio operation endpoints retain status, WAV and
stop. The job waits in `waiting_ptt`, advances to capture when current matching
node health reports it, then retrieves/verifies the exact unchanged PCM/WAV.

Release the button for at least 50 ms after arming, then press for at least 50 ms.
One accepted press captures exactly the selected 1–24,000 samples. Holding or
releasing it does not change clip length. The full operation has a 30-second node
deadline, including the wait. An arm issued while held needs a new release/press.
A second arm while busy is rejected. Stop and a fresh arm never reuse an old
press. Source bytes/count/hash, driver result and microphone quality remain
separate findings. No RF session or transmission is created.

PTT controls are API/CLI in this slice; the existing local-audio inspector can
show the saved capture. Integrated control UI follows the M7 host/UI work.

## Checks and physical acceptance

```sh
uv run --project testbed pytest testbed/tests/test_ptt_native.py testbed/tests/test_ptt_host.py testbed/tests/test_node_audio_native.py testbed/tests/test_node_audio_host.py testbed/tests/test_node_control_native.py -q
make check
```

Twenty dedicated cases cover bounce, duplicate arms, disabled/unowned/busy input,
missing microphone, stop/lease/disconnect/deadline while pending, held rearm,
invalid geometry, driver failure, 80 admission-allocation failure positions with
following successful work, shared API/CLI ownership/readback, unavailable and
mismatched identity/current-health fingerprints. Native fixtures use actual C
control/artifact/audio lifecycles with injected GPIO and DMA, never physical pins.
A fully configured radio/audio/codec/PTT hello is exercised through bounded serial.
The serial fixture preserves compact JSON instead of inflating records with spaces.

ESP-IDF verification builds both normal PTT-disabled and isolated selected V4.2,
32 KiB-main-stack, microphone/PTT-enabled configurations. They are build checks,
not compatible images selected for unverified physical boards. See `status.md`
for observed sizes and final shared results. No flash or physical acceptance.

After board/pin/solder checks and the applicable deployment backup, verify the
real switch, pull-up and idle level; arm/release/press, bounce and hold; listen to
or inspect an exact finite capture. Exercise stop, USB disconnect, lease loss and
reset while held. Reclaim/rearm deliberately: no old press may start work. Confirm
missing/disabled input does nothing, no RF is started and following capture works.
Record node/boot/build/wiring identities and actual observations separately from
these software checks. Physical qualification remains open.
