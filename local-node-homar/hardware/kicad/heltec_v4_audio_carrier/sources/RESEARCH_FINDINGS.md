# Current C5 reference findings

Sources checked 2026-11-24. Current track/via counts, ERC, DRC, connectivity and routing evidence are in `reports/`. Physical fit and hardware operation remain unverified.

## Assembly and geometry

- **Heltec:** the manufacturer R2 V4.3.1 reference gives a 25.4 x 51.69 mm body, two 18-pin headers at 2.54 mm pitch and 22.86 mm row spacing. USB-up puts J2 left and J3 right, pin1 nearest the top. Confirm actual header registration, hole fit, standoffs and USB/coax clearance.
- **INMP441:** the user image labels a 14 mm round body; its 12 mm annotation is not row spacing. [Community KiCad CAD](https://github.com/barafael/inmp441-breakout-kicad/blob/816ee4424e4765e0214c96a88f26b3a16a51b17a/inmp441.pretty/inmp441.kicad_mod) supplies the 2.54 x 7.62 mm grid. The adopted acoustic/solder-face-UP view has SCK/WS/LR above SD/VDD/GND. The author reported mechanical fit but did not use the microphone electrically. The 3 mm carrier opening, 2 mm all-copper exclusion radius and 3 mm standoff are engineering choices. See `footprint_reference/INMP441_REFERENCE_FOOTPRINT.md`.
- **MAX98357A:** the user drawing gives a 17.7 x 19 mm body, 2.54 mm header pitch, 12.6 mm mounting-center spacing, 16.7 mm mounting-center-to-bottom dimension and 15.4 mm speaker/header row spacing. JAMP1 is centered at user (54.5,66) mm; pads are y58.5, x46.88..62.12, VIN pin1 at the right through LRC pin7 at the left. Header centering, 2 mm header-to-bottom offset and 1.1/1.8 mm hole/pad sizes are provisional.
- **PTT:** SW1 is the fitted OCR 6 x 6 x 8 mm tactile. GPIO39/PTT_N connects directly to its normally-open contact, with the opposite contact grounded. C&K PTS645 and KiCad provide a representative 6.5 x 4.5 mm pattern; exact OCR fit and pairing require checking. See `PTT_SWITCH_RESEARCH.md`.
- **Speaker:** the nominal Alrhso 1 W / 8 ohm load is external and wires directly to amplifier SPK+/SPK-. Neither output is ground.

R8 is the user-selected EEEEE 1 kohm, 1/2 W, 5% carbon axial through-hole resistor, serving as the only carrier passive and the SD/MODE pulldown. Its mounting geometry is a reference until compared with the owned part. The matching [EEEEE assortment listing](https://www.amazon.com/dp/B0G4LVC5RY) provides no body drawing. A [Royal Ohm carbon-film reference](https://www.tme.eu/Document/29f58ab8e2ccd3fbcb10a82637aa83de/cfr.pdf) lists up to 10 x 3.5 mm for its half-watt body; it does not identify the EEEEE part. The adopted footprint reserves a 10.0 x 3.6 mm body, a 15.24 mm formed lead pitch and 1.0 mm drills / 2.0 mm pads. Signal and supply paths are direct copper. Module circuitry and all 13 test pads remain. The design relies on existing module bypassing; inspect actual fitted components.

`mechanical_measurements.csv` distinguishes manufacturer data, user-image dimensions, reference CAD and provisional choices. Primary evidence and licenses remain with the supporting references.

## Layout

The [Heltec R2 datasheet](https://resource.heltec.cn/download/WiFi_LoRa_32_V4/datasheet/WiFi_LoRa_32_V4.3.1_Datasheet.pdf) documents the FPC antenna on the J3/OLED side. The carrier reserves user x13..33, y54..85 mm by engineering choice. This is not a manufacturer numerical keepout; check the actual antenna, fasteners and enclosure. Filled copper is reviewed in `review/copper-layer-review.pdf`.

The microphone faces outward. The carrier opening provides additional underside clearance; verify the actual port, can, solder and standoff. Keep adhesive, solder and cleaning residue out of the acoustic path. L/R is grounded; no extra carrier SD pulldown is fitted.

Shortest planar I2S paths are MIC_BCLK 27.950 mm, MIC_WS 27.225 mm, MIC_DATA 46.420 mm, AMP_BCLK 17.964 mm, AMP_WS 18.557 mm and AMP_DATA 63.922 mm. Via-barrel height and testpoint branches are excluded. AMP_DATA exceeds the preferred 50 mm because it detours the RF reservation. I2S uses outer copper; In1 is GND and In2 carries GND/local 3V3 with a short AMP_SD crossover. See `reports/route_lengths.csv` and `reports/routing_audit.json`.

## Electrical and power references

The [INMP441 datasheet](https://product.tdk.com/system/files/dam/doc/product/sw_piezo/mic/mems-mic/data_sheet/inmp441.pdf) specifies 1.62-3.63 V supply and 24-bit I2S. At 3.3 V, normal current is 2.2 mA typical / 2.5 mA maximum. The IC's bottom acoustic port and 4.72 x 3.76 mm package do not locate the breakout's opening.

The [MAX98357A/B datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/MAX98357A-MAX98357B.pdf) specifies I2S for the A variant, 2.5-5.5 V supply, +12 dB with GAIN grounded and differential speaker outputs. At 5 V / 25 C, quiescent current is 2.75 mA typical / 3.35 mA maximum. Inspect breakout bypassing and straps; chip data do not establish the seller module's pin geometry.

The [Heltec V4.3 schematic](https://resource.heltec.cn/download/WiFi_LoRa_32_V4/Schematic/HTIT-WB32LAF_V4.3.pdf) connects the exported 5V header to VUSB before F1. The amplifier therefore cannot rely on F1 for protection. The published exported 5V@USB limit is 500 mA; total board and USB-source capacity must also be checked.

At nominal 8 ohms, 1 W is 2.828 Vrms, 0.354 Arms and 0.5 A peak. The amplifier budget is 260 mA at 5 V, using 80% assumed efficiency plus 10 mA reserve. Microphone and R8 add about 5.8 mA on 3V3. Manufacturer whole-board TX figures plus the amplifier and a provisional 30 mA reserve give 1.046 A for the cited 27 dBm / 868 MHz example and 0.586 A for the 14 dBm example. These are planning estimates, not guaranteed maxima or measurements of the configured 915 MHz radio.

The extracted amplifier positive supply path is 103.210 mm at 1 mm width and nominal 43.2 um outer copper. Estimated resistance at 20 C is 41.189 milliohm, giving 10.709 mV at 260 mA or 20.594 mV at 500 mA. This excludes return plane, pads, vias, pins, upstream USB path, temperature and transients. `power_budget.json` records assumptions; measure USB and amplifier rails under actual load.

## Acceptance

Use the 1:1 fit sheet to check contacts, holes, body datums, acoustic alignment, standoffs, solder access and enclosure clearance before fabrication. OSH Park four-layer source constraints are in `fabrication_source_rules.json`; final fabrication outputs and inspection remain pending.

Verify supply capacity, bypassing, microphone capture, audible speaker output and combined radio/audio load on hardware. Firmware remains `ENABLE_PTT=false`; its enabled path uses GPIO39 `INPUT_PULLUP`. Validate switch readings and debounce when enabling PTT. CAD changes do not upload firmware or establish hardware operation.
