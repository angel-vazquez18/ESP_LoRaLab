# LoRa enclosure: FreeCAD development archive

This directory records the parametric enclosure development for Homar's C5
Heltec carrier, including the PTT stop mechanism, actual-component fit review,
interactive mechanism illustration, and R1 manufacturing handoff. It adds CAD
development assets and supporting evidence; it does not change firmware,
electrical connections, PCB layout, or hardware qualification status.

## Start with revision R1

- [Editable FreeCAD model](final-design/cad/LoRa-Enclosure-C5-R1.FCStd)
  and [four-part STEP](final-design/cad/LoRa-Enclosure-C5-R1.step).
- [Dimensioned technical drawings](final-design/documentation/Enclosure-Technical-Drawings.pdf)
  and [engineering dossier](final-design/documentation/Enclosure-Engineering-Dossier.pdf).
- [Four-view assembly sheet](final-design/views/C5-R1-assembly-views.png),
  [assembly cutaway](final-design/views/assembled-cutaway.png), and
  [view provenance](final-design/views/VIEW-NOTES.txt).
- [STL exports](final-design/printing/) and [Craftcloud STL/3MF files](final-design/craftcloud/upload/).
  Each supplier file contains one part, at millimetre scale. Upload four STL
  files **or** four 3MF alternatives, with quantity one each for one prototype.
- [Craftcloud specification](final-design/craftcloud/CRAFTCLOUD-ORDER-SPECIFICATION.txt)
  and [supplier notes](final-design/craftcloud/production-notes.txt).
- [Assembly BOM](final-design/bom/LoRa-C5-R1-Complete-BOM.xlsx),
  [CSV companion](final-design/bom/LoRa-C5-R1-Complete-BOM.csv), and
  [CNC-shop STEP/DXF handoff](final-design/cnc/).
- [Revision record](final-design/DESIGN-REVISION.txt),
  [final geometry/export checks](final-design/audit/final-export-validation.json),
  and [final actual-component clearance checks](final-design/audit/final-actual-clearance.json).

R1 reduces the shell height to 24.6 mm, adds seven diameter-1.6 mm microphone
openings, opens the USB notch to the lid seam, increases sliding/registration
allowances, and specifies M3 x 22 closure screws and ruthex RX-M3x5x4 inserts.
The model leaves approximately 1.00 mm from the reference display glass to the
lid underside plane and 0.70 mm to the tallest modeled OLED screw.

This is a **first-article prototype**. The assigned models include manufacturer
geometry, authored supplements, and representative parts. The 0.25 mm PTT
switch depression remains provisional. Inspect the delivered dimensions,
owned display/header stack, microphone inlet, insert fit, USB cable access,
and gentle switch actuation/release before accepting a physical assembly.
Default printing tolerances do not establish the stop mechanism's accuracy.
No physical load, drop, acoustic, thermal, RF, or sealing qualification is claimed.

## Native development milestones

The six native documents retain the progression and feature history. Use the
R1 files above for the current prototype handoff. Presentation offsets and
cutaways in earlier documents are for inspection.

| Stage | Native document | Purpose |
| --- | --- | --- |
| Initial parametric case | [LoRa-Enclosure-C5.FCStd](LoRa-Enclosure-C5.FCStd) | Spreadsheet-driven base, lid, and plunger with reference envelopes. |
| Detailed electronics | [LoRa-Enclosure-C5-Detailed-Exploded.FCStd](LoRa-Enclosure-C5-Detailed-Exploded.FCStd) | Assigned PCB/component geometry and corrected 14 mm microphone, exploded for review. |
| PTT fit revision | [LoRa-Enclosure-C5-Fit-Checked.FCStd](fit-checked/LoRa-Enclosure-C5-Fit-Checked.FCStd) | Four printed parts, with the stop cup and component-clearance evidence. |
| Hardware assembly | [LoRa-Enclosure-C5-Exploded-With-Hardware.FCStd](fit-checked/exploded-view/LoRa-Enclosure-C5-Exploded-With-Hardware.FCStd) | Exploded cup, plunger, screws, nuts, and actual electronics. |
| Assembled section | [LoRa-Enclosure-C5-Assembled-Cutaway.FCStd](fit-checked/cutaway-view/LoRa-Enclosure-C5-Assembled-Cutaway.FCStd) | Assembled cutaway and PTT section used by the mechanism illustration. |
| Current R1 | [LoRa-Enclosure-C5-R1.FCStd](final-design/cad/LoRa-Enclosure-C5-R1.FCStd) | Lower shell, microphone pattern, updated fits and selected mounting hardware. |

The native files were developed with FreeCAD 1.1. Open the relevant document,
edit its `Parameters` spreadsheet, and recompute before generating replacement
exports. CSV parameter files are historical snapshots, not live-linked inputs.
The [initial operation record](native-build-operations.json) and
[stop-cup operation record](fit-checked/native-stop-operations.json) describe
native feature construction; they are not independent replay programs.

## Interactive PTT illustration

The [PTT viewer](fit-checked/ptt-motion/ptt-cutaway-animation.html) illustrates
the earlier fit-checked mechanism. It is **prior-revision educational geometry**,
not an R1 manufacturing model. It supports looping motion, speed control,
manual camera inspection, part/load-path explanations, guided highlighting,
camera locking, transparency, and keyboard navigation.

With the model focused, Left/Right step through the load path, Space controls
playback, L toggles camera lock, and T toggles shell transparency. Native form
controls retain their normal keyboard behavior. The HTML is a visualization
fragment; a normal browser host may supply the theme styles used by its UI.

The fragment builder is portable and needs only Node.js and the adjacent source
files. From the repository root:

```sh
node hardware/freecad/lora-enclosure-c5/fit-checked/ptt-motion/build_animation_fragment.cjs
```

It combines the template and the mesh, contact-patch, and load-path JSON into
the checked-in HTML. The checked-in geometry is self-contained and requires no
remote component library. Mesh regeneration uses the historical cutaway FCStd
and FreeCAD Python. Browser test recipes preserve their original workstation
runtime paths; they must be adapted to a local Playwright/browser installation.

## Verify and reproduce

Run the archive check with ordinary Python 3.10 or newer, from the repository root:

```sh
python hardware/freecad/lora-enclosure-c5/tools/validate_archive.py
```

The checker validates manifest coverage and hashes, required artifacts, archive
scope, file sizes, all six FCStd ZIP containers, and the saved final pass flags.
It does not rerun geometric calculations or claim physical qualification.

The corrected detailed assembly STEP is stored losslessly compressed. To
verify it without extracting, or to reconstruct the ignored local file:

```sh
python hardware/freecad/lora-enclosure-c5/tools/extract_reference_assembly.py --verify-only
python hardware/freecad/lora-enclosure-c5/tools/extract_reference_assembly.py
```

The helper checks the exact 76,201,161-byte member and its original SHA-256.
It never overwrites a mismatching existing STEP. The reconstructed file is
ignored by Git; its compressed source is tracked. Clearance audits and
component-section extraction use that reference assembly. The final export
checker also uses the prior fit-checked FCStd and its mesh checker.

Original recipes remain development evidence. Some require FreeCAD's Python,
KiCad, ReportLab, browser tooling, or an external copy of the unchanged C5 KiCad
project. For example, `final-design/views/build_final_views.py` references the
original `pcb-fabrication/source` location; supply that external project or
adapt the input path to rerun it. Already-generated native CAD, views, drawings,
and manufacturing models are included. PCB projects, Gerbers/drills, runtimes,
caches, installation repositories, and full engineering bundles containing
those files are deliberately excluded from this FreeCAD-only archive.

## Provenance and scope

`ARCHIVE-MANIFEST.json` records the repository payload bytes. Earlier reports
retain source hashes and the original `C:/Users/Homar/...` workstation paths.
Interpret `output/enclosure-c5/` in those records as this directory; paths to
the separate KiCad project and old runtime installations identify external
inputs. These historical paths are provenance, not portable execution paths.
Some historical documents mention full-package files or screenshot folders
that are intentionally not duplicated here. Start with the links in this README.

The BOM and PDF records retain assembly context, including unchanged electronics.
They do not introduce a PCB or firmware change. CNC files are a shop quotation
and process-planning handoff; the DXFs contain reference projections and no
machine toolpaths or controller G-code. Craftcloud notes describe a proposed
prototype configuration; no quote, order, or payment is represented by this archive.

See [source notices](SOURCE-NOTICES.md) for component/model attribution and
the limits of the reference geometry.
