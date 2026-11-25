# Source and model notices

The enclosure development, native feature history, drawings, illustrations,
and checks are archived here with their source records. Third-party component
geometry embedded in native documents or the compressed reference assembly
retains its original provenance. This archive does not assign a new blanket
license to third-party models or assert additional rights over them.

## Heltec board and OLED supplement

The Heltec board, connectors, headers, and electronic components originate in
the manufacturer's [V4.3.1 STEP reference](https://resource.heltec.cn/download/WiFi_LoRa_32_V4/3D/HTIT-WB32LAF_V4.3.1%281%29.step).
The separately authored OLED/bracket supplement uses the manufacturer's
drawings and [V4 R2 product imagery](https://heltec.org/project/wifi-lora-32-v4-r2).
The supplement's visual detail is not a measurement of the owned assembly.
The [V4.3.1 datasheet](https://resource.heltec.cn/download/WiFi_LoRa_32_V4/datasheet/WiFi_LoRa_32_V4.3.1_Datasheet.pdf)
is dimensional reference evidence, not verification of the installed header gap.
Heltec model and product-image attribution remains with Heltec.

## Audio, resistor, and switch references

The round INMP441 and purple MAX98357A models are project-authored visual
approximations based on user-supplied photographs/dimensions. The microphone
diameter is corrected to 14 mm. Its acoustic face, port registration, minor
features, and thickness are still reference assumptions. The microphone and
amplifier notes are retained under
[`detailed-import/source-project/models`](detailed-import/source-project/models/).
TDK's [INMP441 product information](https://product.tdk.com/en/search/sw_piezo/mic/mems-mic/info?part_no=INMP441)
describes the IC; it does not establish the orientation or dimensions of the
complete round breakout.

The PTT reference `SW_PUSH_6mm_H8mm.step` is the standard model assigned by the
KiCad project. KiCad library model attribution remains with its contributors;
it represents the installed footprint's intended envelope, not an identified
manufacturer model of the owned switch. The axial resistor is project-authored
reference geometry. These sources are described in
[`3D_MODEL_NOTES.txt`](detailed-import/source-project/models/3D_MODEL_NOTES.txt).
Consult the originating model/library notices when reusing third-party geometry
outside this project; no model license is inferred from the repository license.

## Corrected assembly interchange

[`C5-detailed-assembly.step.zip`](detailed-import/C5-detailed-assembly.step.zip)
contains one corrected KiCad-exported reference assembly. The source file has
SHA-256 `65143fecb376c40ac75cf7b3b2ffdf477c9ff656706a80c1fda63717d1041a19`.
Project VRML components were converted to colored presentation surfaces;
the microphone footprint's 1/2.54 scale was baked into its STEP geometry.
Some converted objects are open surfaces. The assembly is a reference input
for fit checking and illustrations, not a manufacturing solid for the PCB.
The correction and limitations are documented in the
[detailed import record](detailed-import/READ-ME.txt).

## Hardware and manufacturing references

Fasteners and inserts are dimensional envelopes with representative drives,
bevels, and surfaces; thread helices and knurls are not modeled. R1 uses the
[ruthex RX-M3x5x4 product](https://www.ruthex.de/en/products/ruthex-gewindeeinsatz-m3-100-stuck-made-for-voron-rx-m3x5x4-messing-gewindebuchsen-fur-3d-druck)
and [manufacturer RX-series dimensions](https://www.igo3d.com/mediafiles/Sonstiges/Ruthex/ruthex_Datenblatt_RX-Serie.pdf)
as its insert basis. The selected closure screw is a standard
[M3 x 22 DIN 912 / ISO 4762](https://www.accu.co.uk/metric-cap-head-screws/2803-SSC-M3-22-A2).
Other source links are retained in the BOM and engineering dossier.

The proposed printing process is described by
[Craftcloud's unfilled MJF PA12 guide](https://craftcloud3d.com/en/material-guide/hp-mjf-nylon-pa12).
Supplier catalog data, CAD fit calculations, and the comparable-switch travel
assumption do not qualify the actual printed/assembled mechanism. Review the
prototype acceptance conditions before physical use or production release.

## R4 battery packaging reference

The battery envelope is project-authored packaging geometry based on the user's
Meshnology product image (68 x 35 x 10 mm) with a conservative 36 mm width. It is
not a manufacturer CAD model or a qualified expansion allowance. Product artwork
is not republished in this archive. See the [Meshnology battery specifications](https://meshnology.com/collections/frontpage/products/3-7v-3000mah-rechargeable-battery-for-arduino-esp32)
and the R4 connection review for source links, connector and charging limits.

## R5-R7 antenna, speaker and enclosure development

The antenna, fixed rear connector hex, coax route, speaker frame and cable-tie
geometry are project-authored fit references. The owned antenna kit has no
verified bulkhead drawing. The R7 key's 8.4 mm gap uses an illustrative 8 mm rear
hex; a mounting-nut dimension does not establish the rear-body fit. R10 coax
curvature and the assumed cable diameter remain physical fit assumptions.

The enclosure carries one speaker. The seller's body dimensions and lead length
inform its envelope; no supplier speaker CAD was available. Speaker power limits,
frame-only soft retention and service slack are documented in the R6/R7 notes.
Product artwork and the user's screenshots are not republished. Source URLs and
review notes are preserved in the revision research/assembly documentation.

R7 preserves the assigned electronics and mounting datums, including the nominal
0.50 mm OLED gap. Strength improvements are geometric changes supported by fit
checks; no physical impact, torque, sealing, RF, acoustic or thermal rating is
claimed. All manufacturer/component attribution in the earlier archive remains.
