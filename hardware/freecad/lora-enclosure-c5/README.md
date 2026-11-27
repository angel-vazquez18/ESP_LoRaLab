# LoRa enclosure: FreeCAD development archive

## Current prototype: R4 battery housing

R4 is the adopted enclosure revision. It adds a separate rear compartment for
the Meshnology 3.7 V / 3000 mAh LiPo, a removable cover, soft-strap retention and
a cable route to Heltec BAT. The PCB and the R3 nominal 0.50 mm OLED clearance
remain fixed. This archive changes no firmware, PCB layout, or upstream hardware
profile. It records Homar's C5 carrier variant, which differs from the generic
ESP_LoRaLab bench wiring.

- [Editable FreeCAD model](revision-r4-battery/cad/LoRa-Enclosure-C5-R4-Battery.FCStd)
  and [five-part STEP](revision-r4-battery/cad/LoRa-Enclosure-C5-R4-Battery.step).
- [Battery integration and dimensioned section](revision-r4-battery/documentation/C5-R4-Battery-Integration.pdf),
  [manufacturing drawings and CNC-shop inputs](revision-r4-battery/manufacturing/),
  [cutaway](revision-r4-battery/documentation/battery-cutaway.png),
  [assembled](revision-r4-battery/documentation/battery-assembled.png) and
  [exploded view](revision-r4-battery/documentation/battery-exploded.png).
- [Complete R4 BOM](revision-r4-battery/bom/) and
  [hardware/assembly addendum](revision-r4-battery/HARDWARE-ADDENDUM.txt).
- [Craftcloud STL/3MF set](revision-r4-battery/craftcloud/upload/) and
  [order specification](revision-r4-battery/craftcloud/CRAFTCLOUD-ORDER-SPECIFICATION.txt).
  Upload five STL files **or** five 3MF alternatives, one of each, millimetres,
  100 percent scale. Proposed process: unfilled MJF PA12. No order was placed.
- [Revision notes](revision-r4-battery/REVISION-NOTES.txt),
  [mechanical audit](revision-r4-battery/audit/r4-battery-fit-validation.json),
  [export audit](revision-r4-battery/audit/r4-export-validation.json), and
  [current-release marker](CURRENT-RELEASE.json).

The conservative cell envelope is 68 x 36 x 10 mm, within a 14 mm-deep bay. A
continuous 2.4 mm separator protects the pouch from the carrier underside. The
printed shell is 78.8 x 104 x 41 mm including the local rear cable hood, excluding
button and screw-head projections. The cover adds four M3 x 6 screws and four
inserts outside the pouch footprint. Do not substitute M3 x 8 in the blind holes.

This is a **prototype release**, not physical qualification. Confirm the actual
pack envelope, noncompressive retention, polarity/keying, lead slack and
simultaneous USB/battery plug fit. The assumed battery plug clears modeled solids
but overlaps the generic USB-overmould reservation. Confirm the pack's permissible
charging current before qualifying Heltec charging. The battery supplies Heltec
BAT only; the C5 amplifier remains USB-powered. The reviewed local-node-homar
audio firmware enables AMP_SD without USB; battery-only commissioning requires a
verified speaker-disabled Heltec build. No firmware was changed or flashed.
See the [connection review](revision-r4-battery/research/BATTERY-CONNECTION-REVIEW.txt).
These C5 findings do not redefine the separate upstream bench profile.

## Revision history and design evidence

| Revision | Purpose | Native CAD / evidence |
| --- | --- | --- |
| Initial / fit-checked | Parametric enclosure, actual-model fit and PTT stop development | Root FCStd files and [fit studies](fit-checked/) |
| R1 | Lower shell, seven microphone holes, USB opening, revised fits and mounting | [Original manufacturing handoff](final-design/); historical, superseded |
| R2 | Bring OLED toward the exterior window face | [R2 CAD and section](revision-r2-oled/) |
| R3 | Reduce nominal OLED inner-rim gap to 0.50 mm | [R3 CAD and section](revision-r3-oled-gap/) |
| R4 | Add separate battery bay/cover and Heltec lead route; retain R3 top/PTT | [Current five-part release](revision-r4-battery/) |

R1's [engineering dossier](final-design/documentation/Enclosure-Engineering-Dossier.pdf)
and [technical drawings](final-design/documentation/Enclosure-Technical-Drawings.pdf)
retain earlier design decisions. Their dimensions/order files are historical;
use R4 for a new complete assembly. The assigned electronics mix manufacturer
CAD, authored supplements and representative models; the battery/plug are explicitly
packaging references, not manufacturer battery CAD. The PTT's 0.25 mm travel
remains a comparable-switch assumption awaiting the owned switch's qualification.

The [interactive PTT illustration](fit-checked/ptt-motion/ptt-cutaway-animation.html)
shows an earlier fit-checked mechanism and supports loop/speed, camera lock,
transparency, load-path guidance and keyboard controls. It is educational geometry,
not the R4 manufacturing source. Rebuild its fragment with:

```sh
node hardware/freecad/lora-enclosure-c5/fit-checked/ptt-motion/build_animation_fragment.cjs
```

## Verification and reuse

Native files were developed with FreeCAD 1.1. Edit their `Parameters` spreadsheet
and recompute before generating replacement exports. Parameter CSVs and operation
records are historical evidence, not independent replay programs.

Run the portable archive check from repository root with ordinary Python 3.10+:

```sh
python hardware/freecad/lora-enclosure-c5/tools/validate_archive.py
python hardware/freecad/lora-enclosure-c5/tools/extract_reference_assembly.py --verify-only
```

The checker validates manifest coverage/hashes, nine native document containers,
required artifacts, file scope and retained pass flags. It does not substitute
for CAD recomputation or physical checks. The reference helper can reconstruct
the ignored 76,201,161-byte detailed assembly STEP from its lossless ZIP; it never
overwrites mismatching data. Remove `--verify-only` to extract it.

R4 native geometry, exact STEP solids and closed print meshes were checked before
publication. Supplier uploads translate the mesh origin only, without scaling.
The CNC handoff provides exact solid models and drawings for shop review. Machine
selection, workholding, cutters, postprocessing and simulated/proved toolpaths
remain the shop's responsibility; no machine-specific G-code is supplied.

Some original generation recipes require FreeCAD Python, KiCad, ReportLab,
spreadsheet/browser tooling or the external C5 KiCad source project. Workstation
paths in historical reports identify provenance and may require local adaptation.
The exact printed models, PDF diagrams and source hashes are retained. The
portable archive check itself has no external CAD/runtime dependency.

## Archive scope

All upstream PR changes live under `hardware/freecad/lora-enclosure-c5/`. The
archive includes FreeCAD development, machining/printing exports, BOM assembly
context and supporting diagrams/audits. Gerbers, drills, PCB/schematic source,
firmware, runtime dependencies, private credentials and mixed full-release ZIPs
are excluded. The unchanged PCB fabrication set is prepared separately in the
local full engineering package; enclosure changes do not create a new PCB revision.

`ARCHIVE-MANIFEST.json` records the published bytes. Historical reports may name
files intentionally outside this CAD-only archive; `output/enclosure-c5/` maps to
this directory. [Source notices](SOURCE-NOTICES.md) retain component attribution.
No physical load, drop, acoustic, thermal, RF, sealing or battery qualification
is claimed by this release, and no purchase/order is represented.
