# C5 enclosure - current release R7

R7 is the adopted enclosure fit prototype as of November 25, 2026. It combines
the separate battery housing, SMA antenna mount, internal speaker holder and
enclosure reinforcement. The PCB already in fabrication, its mounting datums,
component positions and nominal 0.50 mm OLED clearance are preserved.

Start with the [R7 revision notes](revision-r7-enclosure/REVISION-NOTES.txt),
[native FreeCAD model](revision-r7-enclosure/cad/LoRa-Enclosure-C5-R7-Reinforced.FCStd),
[STEP master](revision-r7-enclosure/cad/LoRa-Enclosure-C5-R7-Reinforced.step),
[manufacturing drawings](revision-r7-enclosure/documentation/manufacturing/C5-R7-Manufacturing-Drawings.pdf),
[changed-feature diagrams](revision-r7-enclosure/documentation/LoRa-C5-R7-Enclosure-Improvements.pdf),
[complete BOM](revision-r7-enclosure/documentation/bom/LoRa-C5-R7-Complete-BOM.xlsx),
and [assembly/inspection record](revision-r7-enclosure/documentation/R7-ASSEMBLY-AND-INSPECTION.txt).
The machine-readable entry point is [CURRENT-RELEASE.json](CURRENT-RELEASE.json).

Seven printed parts are installed: base, lid, battery cover, PTT plunger, PTT
stop cup, speaker retainer and removable SMA key. The optional fit coupon is a
separate eighth part. The STEP and master 3MF include the offset coupon; the
individual [Craftcloud upload files](revision-r7-enclosure/craftcloud/upload/)
keep it separate. Upload one STL set OR one 3MF set, units mm, scale 100%, one of
each installed part. See the [order preparation](revision-r7-enclosure/craftcloud/ORDER-SPECIFICATION.txt).
The prototype process is unfilled MJF PA12. No order has been placed.

R7 strengthens the speaker nut roofs and OLED rim regions, adds a noncontact
microphone shroud and loose cable-tie guides, and supplies a replaceable SMA
anti-rotation key. The illustrative 8 mm rear-body hex and 8.4 mm key gap need
checking against the owned connector. Actual cable slack, switch travel,
printed fits and simultaneous battery/USB plug fit still require inspection.

The current [interactive inspection viewer](revision-r7-enclosure/interactive/qa/r7-preview.html)
supports assembled, exploded and cutaway inspection. Its reference hardware and
display cuts are inspection aids; use the released CAD/print files for making.

CNC STEP geometry and the [shop handoff](revision-r7-enclosure/cnc-shop/CNC-SHOP-HANDOFF.txt)
are shop inputs, not machine-executable G-code. The shop must
select its tools, workholding, stock and controller and assess internal-feature
access. Earlier revision folders and drawings remain historical records.

The original C5 Gerbers and drills are unchanged. The complete local manufacturing
handoff carries a byte-identical copy; the published FreeCAD-only archive excludes
PCB/Gerber/drill payloads to keep this revision separate from PCB fabrication.

The C5 amplifier remains USB powered. Battery-only commissioning still requires
a separately verified speaker-disabled Heltec build and the existing connector,
USB/plug-fit and charging checks; see the [connection review](revision-r4-battery/research/BATTERY-CONNECTION-REVIEW.txt).
No PCB or firmware behavior changed in this enclosure release. Digital checks
do not establish strength, ingress, thermal or acoustic ratings.

## FreeCAD development archive

This archive preserves the original enclosure, detailed-component fit and PTT
studies, and R1-R7 native milestones. R5 added the SMA mount; R6 added the internal
speaker; R7 reinforces the lid and retainer, adds a noncontact microphone shroud,
loose cable guides and a removable SMA key. Earlier revision order files are
historical. Use the complete seven-part R7 set, with the fit coupon kept separate.

Open [the standalone R7 viewer](revision-r7-enclosure/interactive/qa/r7-preview.html)
in a current desktop browser to rotate/zoom the populated assembly, explode it,
inspect cutaways and click clearance dimensions. It contains its display meshes.
The viewer is inspection geometry; the native CAD/STEP and individual print files
are the manufacturing sources.

All upstream changes remain under `hardware/freecad/lora-enclosure-c5/`. This
records Homar's C5 carrier variant without adopting its wiring into ESP_LoRaLab's
separate generic bench hardware profile. PCB, Gerber/drill and firmware payloads
are excluded. The unchanged fabrication set and mixed full engineering package
are prepared separately and are not part of this archive.

Run the portable checks from the repository root with Python 3.10 or later:

```sh
python hardware/freecad/lora-enclosure-c5/tools/validate_archive.py
python hardware/freecad/lora-enclosure-c5/tools/rebuild_r7_viewer.py
python hardware/freecad/lora-enclosure-c5/tools/extract_reference_assembly.py --verify-only
```

These checks validate archived bytes, recorded pass flags, current export binding
and exact reconstruction of the viewer fragment. They do not recompute CAD or
qualify physical hardware. See [reproducibility requirements](REPRODUCIBILITY-R7.md),
[source notices](SOURCE-NOTICES.md), and [the archive manifest](ARCHIVE-MANIFEST.json).
