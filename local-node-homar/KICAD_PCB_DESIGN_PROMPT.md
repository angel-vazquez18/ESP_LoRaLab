# KiCad design prompt for the Heltec V4 audio and LoRa carrier PCB

Use this entire document as the design instruction for a KiCad designer or engineering agent. Create a four-layer carrier PCB that replaces the prototype's jumper wires with copper traces and soldered module interconnects. The starting outline is **70 mm wide by 90 mm long**. One identical carrier is used for each node.

Design for the existing **Heltec WiFi LoRa 32 V4.3, ESP32-S3R2**, round INMP441 microphone breakout, purple MAX98357A amplifier breakout, and nominal 8-ohm speaker. Provide space for future PTT, initially unpopulated. Use OSH Park's **4 Layer Super Swift** process.

This is a module carrier: retain the Heltec's MCU, SX1262, RF circuitry, USB connector, power management and OLED, and retain the microphone/amplifier breakout boards. Do not replace them with bare ICs. The supplied photograph establishes the desired arrangement and soldered construction; it is not a dimensioned footprint drawing.

## 1. Scope and source of truth

Work in `esp32-audio-chunker-test`. Put the resulting design in `hardware/kicad/heltec_v4_audio_carrier/`. Preserve existing firmware and test evidence. This task does not authorize fabrication orders, firmware uploads, or device tests.

Read these local sources before drawing the schematic:

- [include/pins.h](include/pins.h): current Heltec external GPIO assignments.
- [include/config.h](include/config.h) and [platformio.ini](platformio.ini): audio configuration and supported board variants.
- [Rev B wiring schematic](output/schematics/Heltec_V4_R2_Wiring_RevB.svg) and [README.md](README.md): module connections and header locator.
- [BENCH_VALIDATION.md](BENCH_VALIDATION.md): hardware observations and outstanding speaker issue.
- [LoRa bench instructions](docs/LORA_INTEGRITY_BENCH.md): onboard radio connections.

Use this project's Rev B mapping. **GPIO47 is amplifier DIN; GPIO39 is reserved for PTT.** The separate `ESP_LoRaLab` project has different assignments; do not import its GPIO47 PTT connection. Do not substitute ESP-WROOM-32, Heltec V3, or V4-R8 pin maps.

The stored-message LoRa transfers were verified, but audible Heltec speaker output remains unresolved in the local checkpoint. A carrier can improve interconnect reliability; it is not evidence that the amplifier issue is resolved.

## 2. Electrical net list

For the header positions below, view the Heltec with its **display facing you and USB-C at the bottom**. J3 is the left side, J2 the right side, and position 1 is nearest USB. These are header positions, not GPIO numbers. Keep these identities when rotating the module in the PCB layout.

| Carrier net | Heltec connection | Other endpoint or connection |
| --- | --- | --- |
| `+3V3_MIC` | J3 position 2 or 3, 3V3 | INMP441 VDD; never connect it to 5V |
| `GND` | J3 position 1 and J2 position 1 | Microphone GND, amplifier GND and carrier ground plane |
| `MIC_LR` | GND | INMP441 L/R, selecting the left channel |
| `MIC_BCLK` | GPIO4, J3 position 15 | INMP441 SCK/BCLK |
| `MIC_WS` | GPIO6, J3 position 17 | INMP441 WS |
| `MIC_DATA` | GPIO38, J3 position 11 | INMP441 SD/DATA; direction is microphone to ESP32 |
| `+5V_AMP` | J2 position 2, USB-derived 5V | MAX98357A VIN |
| `AMP_BCLK` | GPIO40, J3 position 9 | MAX98357A BCLK |
| `AMP_WS` | GPIO41, J3 position 8 | MAX98357A LRC/WS |
| `AMP_DATA` | GPIO47, J2 position 13 | MAX98357A DIN |
| `AMP_SD` | GPIO48, J2 position 14 | MAX98357A SD/MODE |
| `AMP_SD` pulldown | No separate GPIO | **1 kOhm from amplifier SD/MODE to GND**, in parallel with the control input |
| `AMP_GAIN` | GND | MAX98357A GAIN, preserving Rev B |
| `SPK_P` | No ESP32 GPIO | Amplifier SPK+ to speaker positive terminal |
| `SPK_N` | No ESP32 GPIO | Amplifier SPK- to speaker negative terminal |
| `PTT_N`, future | GPIO39, J3 position 10 | Normally-open switch to GND, through an initially unpopulated isolation link |

Make each signal traceable by net label in the schematic and silkscreen. Match terminals by the actual module labels, not their visual order in a generic breakout drawing. A microphone terminal labelled `SD` is data; amplifier `SD` is shutdown/mode control.

Keep microphone and amplifier clock nets separate. They use separate interfaces even when their nominal clock rates match. Current Heltec audio firmware uses 8 kHz word select and 512 kHz bit clock with 32-bit stereo slots; stored audio is 16-bit mono PCM. Do not add an MCLK connection or level shifters to this 3.3V signaling interface.

Reserve the following onboard functions:

- **No added carrier connections to auxiliary GPIO15-18.** OLED SDA17/SCL18/reset21 and Vext-control36 retain their onboard roles; the display needs no external wiring.
- Preserve internal SX1262 GPIO8-14 and V4.3 front-end control GPIO2/5/7. Do not use them for carrier peripherals.
- Leave GNSS/expansion accessories disconnected: GPIO38-41 are used by audio and future PTT.
- Do not connect the J2 `Ve` positions 3/4 as though they were USB 5V or the unswitched 3V3 rail.
- Leave unused exposed signals unconnected externally and mark them accordingly in ERC. Do not change boot, USB, flash, PSRAM or power-control connections.

Cross-check the final module symbol against the [official standard V4 pin map](https://resource.heltec.cn/download/WiFi_LoRa_32_V4/Pinmap/V4_pinmap.png) and [V4.3 schematic](https://resource.heltec.cn/download/WiFi_LoRa_32_V4/Schematic/HTIT-WB32LAF_V4.3.pdf).

## 3. Power, audio and future button circuitry

Use one power source initially: the Heltec USB-C connector. Take microphone power from its 3V3 pin and amplifier power from its USB-derived 5V pin. Keep the USB connector available for both programming and power. Battery-only operation, solar operation, a second USB connector and an independent amplifier supply are outside this revision; do not assume the 5V header remains powered from a battery.

Prepare a current budget for ESP32, LoRa transmit peaks, OLED, microphone and amplifier together. Verify the USB cable/source and the Heltec's existing 5V path can carry that load. Wider carrier traces cannot increase the current rating of the upstream board, connector or cable. Calculate expected voltage drop at the proposed operating load and measure it during subsequent bring-up.

For the amplifier, implement these requirements from the [MAX98357A/B datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/max98357a-max98357b.pdf): use the MAX98357A I2S variant; its supply range is 2.5-5.5V. GAIN tied to GND selects +12dB. Preserve the differential speaker connection: **neither speaker lead is GND**. Provide short, wide supply and output paths. Check the breakout's existing bypassing against the recommended 100nF plus 10uF supply capacitors. Output switching can appear even without an audible tone; a switching waveform alone is not an audio acceptance test.

Place carrier footprints for 100nF and 10uF close to amplifier VIN/GND, plus an optional 47-100uF bulk capacitor. Choose capacitor voltage ratings and effective capacitance for the rail; use at least 10V-rated parts on 5V. Decide the populated combination after inspecting existing breakout capacitors and checking USB inrush. Keep the high-current loop local to the amplifier and its supply return, away from the microphone supply route.

Relocate the existing 1kOhm SD/MODE pulldown to the carrier; do not accidentally duplicate the breadboard resistor. It draws approximately 3.3mA when driven to 3.3V. Inspect any pull-up or fixed strap already on the actual amplifier breakout. Confirm reset/shutdown voltage at the amplifier terminal; the bench target is below 0.08V while reset is held. Preserve firmware-controlled enable and startup sequencing.

For the microphone, the [INMP441 datasheet](https://product.tdk.com/system/files/dam/doc/product/sw_piezo/mic/mems-mic/data_sheet/inmp441.pdf) specifies a bottom acoustic port, 24-bit I2S output, and local 100nF supply bypassing. Its SD output tri-states outside the selected channel; provide a 100kOhm SD-to-GND resistor if the breakout does not already include one. Keep the acoustic path open and keep solder, adhesive and cleaning residue out of it. The bare IC's 4.72 x 3.76mm package is **not** the circular breakout's footprint.

Use a common continuous ground reference. Avoid a shared narrow supply/return path in which amplifier current must pass through the microphone connection. Do not introduce a split analog/digital ground plane for this digital microphone.

Provide series-resistor footprints on the six I2S signal paths, initially populated with 0Ohm. Locate clock and amplifier-data resistors near the ESP32; locate the microphone-data resistor near the microphone. Values such as 22-47Ohm are tuning options only after edge measurements. Add a separate 0Ohm isolation link in the GPIO48-to-amplifier SD path, with the 1kOhm pulldown on the amplifier side. These are soldered components, not required jumper cables.

For future PTT, provide a labelled switch footprint or two-pin connector and a **DNP 0Ohm link** between it and GPIO39. DNP means do not populate. Keep the switch and link unpopulated for the initial build. Enable the connection only with compatible firmware configuring GPIO39 as an input with pull-up. Choose the exact switch and verify its pin pairing before assigning a footprint.

## 4. Mechanical dimensions and footprint verification

Use these manufacturer dimensions for initial Heltec placement. The reference is the standard R2 [V4.3.1 datasheet, mechanical drawing on page 15](https://resource.heltec.cn/download/WiFi_LoRa_32_V4/datasheet/WiFi_LoRa_32_V4.3.1_Datasheet.pdf); check the actual V4.3 assembly for differences.

| Heltec feature | Published dimension |
| --- | --- |
| Drawing outline | 51.69 x 25.40mm |
| Nominal assembly dimensions | 51.7 x 25.4 x 10.7mm |
| Main side headers | Two 1x18 rows, 2.54mm pitch |
| Row center spacing | 22.86mm |
| First-to-last pin span in each row | 43.18mm |
| OLED/bracket envelope | 33.00 x 18.60mm; **not a mounting-hole pattern** |
| Small retention holes | Diameter 1.90mm; complete XY coordinates still need verification |

The drawing also includes a 15.60mm vertical envelope involving fitted pins. Measure actual installed height and underside clearance; neither this value nor nominal module height specifies the carrier standoff. Use the [manufacturer STEP resource](https://resource.heltec.cn/download/WiFi_LoRa_32_V4/3D/) to check interference where applicable.

The exact supplier drawings for the round microphone and purple amplifier are not established. Use the following **space reservations, not fabricated module dimensions**:

| Assembly | Initial reserved area | Information required for the real footprint |
| --- | --- | --- |
| Heltec and access margin | 30 x 56mm | Header-to-outline datum, installed height, underside parts, USB and antenna access |
| Round INMP441 breakout | 25 x 25mm | Actual diameter, two pin-row locations, terminal order, sound-hole location and mounted height |
| MAX98357A breakout | 30 x 30mm | Board width/length, header position, terminal block overhang, speaker pads and mounted height |
| Speaker or its mounting area | 25 x 25mm initially | Actual diameter/body, depth, mounting method, impedance and power rating |
| Future PTT | 12 x 12mm initially | Exact switch body, pin pairing, pitch, actuator height and access |

For each module, create a mechanical measurement record containing the exact part/vendor/revision, outline dimensions, pad-center coordinates, pin pitch, row separation, finished-hole requirement, mounting points, total height, underside protrusions and connector insertion clearances. Identify every value as manufacturer-documented, physically measured or provisional. Do not derive production hole coordinates from this angled photograph.

Build a project-local composite Heltec footprint with uniquely identified pads for both headers, for example `J3_01` through `J3_18` and `J2_01` through `J2_18`. Do not give both headers the same unqualified pad numbers. Match the symbol and footprint pin table one-to-one. Auxiliary GPIO15-18 need no carrier pads.

Model the actual two-row microphone arrangement and the amplifier's actual header/terminal arrangement. Generic INMP441/MAX98357A IC footprints and unrelated breakout footprints are unsuitable substitutes. Include module outlines on fabrication layers, courtyards, pin-1 markings, connector envelopes and simple 3D bodies if vendor models are unavailable.

Use soldered through-hole interconnect pins, with both module and carrier joints accessible during assembly. Select standoff height from underside component clearance; do not let the module rest on exposed solder joints. For example, a measured 0.64mm square header pin may warrant approximately 1.1mm finished holes with approximately 1.8mm pads, subject to pin and drill tolerances. Do not apply these starting dimensions blindly to every module.

Use independent carrier mounting holes. Do not repurpose the OLED's small retention holes or replace its existing screws without a verified mechanical plan.

## 5. Initial placement within 70 x 90mm

Use millimeters, with the carrier origin at its lower-left corner, x increasing right and y increasing upward. This coordinate convention is for the placement proposal; convert it consistently to KiCad's drawing coordinates.

| Item | Provisional reservation, x range | Provisional reservation, y range |
| --- | --- | --- |
| Heltec module and access margin | 8-38 | 34-90 |
| Amplifier module | 39-69 | 51-81 |
| Microphone module | 42-67 | 18-43 |
| Speaker mounting reservation | 8-33 | 5-30 |
| Future PTT | 45-57 | 3-15 |

These blocks demonstrate a possible allocation; they are not footprint origins or final component placements. Place the Heltec's USB mating face toward the top board edge. The module is rotated relative to the USB-at-bottom pin-reference view in section 2. Adjust its exact location or add a connector-access cutout so the real USB plug can be fully inserted and removed. Leave PRG/RST buttons and the OLED accessible.

Start with four 3.2mm NPTH carrier mounting holes at (4,4), (66,4), (4,86), and (66,86). Reserve a 7mm-diameter hardware clearance around each. Relocate a hole if a verified module, antenna, plug or enclosure interferes; keep all mounting hardware clear of conductive parts.

Use remaining spaces for bypass capacitors, resistor links, speaker connections and test pads. Maintain practical soldering and inspection access between actual module bodies. Check the speaker's real geometry: if it fits the reserved area, provide its actual mounting and solder-pad arrangement, including electrical isolation of any conductive frame. If it cannot fit, document that result and use a labelled two-wire speaker connector with an external enclosure-mounted speaker. All module-to-module connections must still be PCB traces; speaker leads and antenna coax are load/RF connections, not replacements for missing routed nets.

Keep the amplifier and speaker switching routes away from the microphone opening. Preserve the microphone's intended acoustic direction: add a measured carrier opening or use edge overhang if its module's sound path faces the carrier. Do not place copper, components, adhesive or an enclosure wall across that opening.

Preserve the Heltec's antenna assemblies and leave access for the LoRa coax connector and bend. The [Heltec product FAQ](https://heltec.org/project/wifi-lora-32-v4/) identifies a 2.4GHz FPC antenna on the OLED bracket and discusses plastic screws. Avoid metal hardware and copper close to that antenna. A numerical carrier keepout has not been established: locate the actual antenna and define the keepout from manufacturer guidance or RF validation. Do not label an invented clearance as a Heltec requirement. Keep the external matched LoRa antenna and coax; no 915MHz feedline is routed on this carrier.

Reserve an initial 20mm enclosure-height budget above the carrier for planning, then replace it with the measured assembled maximum, cable clearance and tolerances. If verified footprints and required keepouts cannot fit 70 x 90mm, report the minimum practical outline and the specific interference. Do not shrink footprints or remove acoustic/RF clearances to force a fit.

## 6. OSH Park material and stackup

Configure the fixed [OSH Park 4 Layer Super Swift service](https://docs.oshpark.com/services/four-layer-swift/), checked 2026-11-23:

| Property | Service specification |
| --- | --- |
| Laminate | FR408-HR, 190 Tg |
| Nominal board thickness | 1.6mm |
| Copper | Four layers; 1oz outer, 0.5oz inner |
| Finish | ENIG |
| Soldermask | Purple, both sides |
| Minimum trace/spacing | 0.127mm / 0.127mm |
| Minimum annular ring | 0.1016mm |
| Minimum drill | 0.254mm |
| Minimum drilled slot | 0.508mm |
| Routing cutters | 1.72mm outline; 1.01mm internal cutouts |
| Copper-to-outline distance | 0.381mm |
| Plated drill-to-inner-copper clearance | 0.254mm |
| Minimum mask web | 0.1016mm |
| Maximum drill-size tolerance | +/-0.0635mm |

Published copper/dielectric sequence, top to bottom, in millimeters:

`0.0432 Cu / 0.1999 prepreg / 0.0175 Cu / 0.9906 core / 0.0175 Cu / 0.1999 prepreg / 0.0432 Cu`

The prepreg reference Dk is 3.61 at 1GHz. Use ordinary through vias; blind/buried and filled/plated via-in-pad are unavailable. Recheck the service at manufacturing handoff; the fabricator's fixed construction governs.

For [KiCad rule setup](https://docs.oshpark.com/design-tools/kicad/kicad-design-rules/), use 0.0508mm soldermask expansion, minimum hole-to-hole clearance 0.127mm and silkscreen stroke at least 0.127mm. Keep the fabricator's special inner-layer drill clearance separate from ordinary track clearance. Retain unused annular rings or implement and inspect adequate inner-layer antipads; do not assume a normal DRC pass automatically checks this manufacturing detail.

## 7. Layer assignment and routing rules

Use the following carrier layout choices, which are intentionally more generous than the fabrication minima:

| Layer | Assignment |
| --- | --- |
| F.Cu | Modules, short I2S/control routes, local bypass connections |
| In1.Cu | Continuous GND reference, except necessary acoustic, mounting and RF keepouts |
| In2.Cu | Local 5V/3V3 distribution zones with surrounding GND; avoid unnecessary fragmentation |
| B.Cu | Power/slow interconnects and GND fill; avoid I2S routing over a split reference |

| Net class | Starting track width | Starting clearance |
| --- | ---: | ---: |
| I2S and logic | 0.25mm | 0.20mm |
| Microphone 3V3 distribution | 0.50mm | 0.20mm |
| Amplifier 5V and speaker outputs | 1.00mm, or wider pours | 0.25mm |

Use 0.80mm pad / 0.40mm drill through vias as a conservative starting pair, 0.50mm copper-to-board-edge clearance, and at least 0.254mm clearance from plated drill edges to unrelated inner copper. Check component pad breakout separately. Size power paths from the actual current, permitted temperature rise and voltage drop, including neck-downs, vias, thermal spokes and module pins; the starting widths are not a verified current rating.

Route each I2S net directly, preferably on F.Cu over In1 ground. Keep clocks short, avoid stubs, and add nearby ground stitching when a signal must change reference. A practical initial target is below 50mm per I2S route where placement allows; list actual routed lengths and any longer paths. Do not add serpentine length matching merely to equalize unrelated microphone and amplifier buses. Do not claim 50-ohm impedance from trace width alone; calculate any needed impedance using the confirmed stackup and edge rates.

Route `SPK_P` and `SPK_N` together, short and wide, away from mic/data traces. They are bridged Class-D outputs, not a specified 100-ohm data pair. Do not connect either to a ground plane or add arbitrary shunt capacitors. Use thermal reliefs suitable for hand soldering without creating undersized high-current paths. Keep a clear, continuous return beneath signal routes and avoid routing signals across acoustic or antenna keepouts.

## 8. Test access, labels and assembly

Provide accessible test pads for GND, 3V3, 5V, microphone BCLK/WS/DATA, amplifier BCLK/WS/DIN/SD, and future PTT. Put ground test pads adjacent to clock/data test areas for short probe grounds. Provide a removable soldered 0Ohm link in the amplifier supply branch for isolation/current measurement. Keep the speaker output terminals accessible and label them `SPK+` and `SPK-`, with neither labelled ground.

Power off before changing any supply or signal link. Whenever amplifier VIN is isolated, also open its four signal links, or use verified firmware holding GPIO40/41/47/48 LOW throughout that condition. Keep the amplifier-side SD pulldown connected. Do not run audio initialization with VIN absent; ordinary serial IDLE is insufficient because the existing audio firmware may keep clocks and enable active.

Label module orientation, pin 1, supply voltages, revision and mounting holes on silkscreen. Label the PTT link `DNP INITIAL`. Keep text off pads and module mating surfaces. Use text approximately 1mm high or larger where space permits. Provide a writable node-identification area rather than permanently assigning COM6/COM7, which are computer-dependent port names.

Create a BOM for the three modules, measured interconnect headers/pins, resistor links, 1kOhm SD pulldown, any required 100kOhm microphone-data pulldown, bypass/bulk capacitors, speaker connection, mounting hardware and future DNP PTT parts. Record exact footprints, ratings, quantities and population states. Identify bypass parts already fitted on modules so the final assembly is intentional.

Explain the assembly order, module standoff, soldering access and microphone contamination precautions. Before soldering modules, print the PCB at **1:1 scale with scaling disabled** and physically check every pin row, connector, mounting point and acoustic opening against the real parts.

## 9. KiCad deliverables and checks

Deliver editable `.kicad_pro`, `.kicad_sch`, `.kicad_pcb` and any `.kicad_dru` files; project-local symbol/footprint libraries and library tables; available STEP models; BOM; a dimensioned mechanical sheet; the measured footprint record; assembly drawings; a schematic PDF; and top/bottom/3D review images. Use relative paths and state the KiCad version.

Run schematic ERC and PCB DRC, resolve unintended violations and record justified exceptions. Check symbol-to-pad mapping independently of visual routing. Verify zero unintended unrouted nets, net ties, supply shorts, mirrored module pin orders, copper in keepouts, blocked sound ports and connector interference. Refill zones before final checks and export.

For the [OSH Park manufacturing handoff](https://docs.oshpark.com/design-tools/kicad/generating-kicad-gerbers/), export all four copper layers, both soldermasks, both silkscreens, Edge.Cuts and appropriate plated/nonplated drill files. Include paste only where relevant to assembly. Use Gerber X2, inspect the resulting layers and holes in a separate Gerber viewer, and confirm the chosen drill/slot settings with the current OSH Park guide. OSH Park also accepts `.kicad_pcb`; saved copper pours must be current because uploaded boards are not refilled automatically.

Do not release manufacturing files as production-ready while module geometry, pad order, acoustic-port geometry or antenna clearance remains provisional. Continue the schematic and dimensioned placement work with clearly marked placeholders, and list the exact measurements needed to finish. A schematic/DRC pass cannot validate a guessed footprint.

## 10. Subsequent hardware acceptance plan

Include this procedure with the design; do not claim it was performed during CAD work:

1. Unpowered: inspect soldering, verify each pin-to-module connection, and check resistance between unrelated supplies/ground and neighboring signal nets. A continuity beep by itself does not prove the absence of shorts.
2. With power off, isolate the amplifier supply and its four input signal links, or establish the verified LOW-state firmware condition described in section 8. Then power the Heltec and confirm normal boot, USB communication, OLED, 3V3 polarity and GPIO mapping.
3. Power off, restore amplifier supply and signal links, and then power up for the audio checks. Measure VIN and SD/MODE at the actual amplifier under reset and playback, and inspect supply droop under the intended load.
4. Run the existing audio test firmware explicitly: confirm microphone capture, then a short low-level 1kHz speaker tone. Verify clock/data at module terminals and actual audible output. Probe grounds connect only to circuit GND, never a speaker output.
5. Run the existing known-recording LoRa integrity test with matched antennas attached. Compare source and recovered bytes at the computer. The radio-only test firmware does not exercise the microphone or speaker.
6. Test audio and radio together only after compatible integrated firmware exists and the total supply budget is confirmed. Leave PTT unpopulated until its separate firmware and input checks are ready.

Finish with a clear distinction between completed CAD checks, measured mechanical fit, unresolved items and actual hardware results. The target outcome is a repeatable soldered carrier with verified footprints and accessible diagnostics, ready for deliberate fabrication and bring-up.
