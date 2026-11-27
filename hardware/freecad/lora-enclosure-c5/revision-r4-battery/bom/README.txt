LoRa C5-R4 complete assembly bill of materials
24 November 2026

Use LoRa-C5-R4-Complete-BOM.xlsx for editable build quantities and the CSV
for interchange. The default is one complete enclosure assembly. Per-unit
quantities include retained hardware, so do not add the R1 BOM quantities
again. The workbook has 28 distinct procurement rows and five printed parts.
The CSV has source citations and the same one-unit quantities as the workbook.

Printed parts: one R4 base, one R3-fit lid, one PTT plunger, one PTT stop cup,
and one R4 battery cover. Use the five R4 Craftcloud files, unfilled MJF PA12.
Printed size entries are mesh bounds; nominal fit dimensions are in drawings.

Fasteners for the complete assembly:
  4 M3 x 22 socket cap screws for the upper lid
  4 M3 x 6 button-head screws for the battery cover
  8 RX-M3x5x4-compatible M3 inserts total (4 upper + 4 rear)
  2 M2 x 10 pan-head screws and 2 M2 full nuts for the PTT stop cup
  1 speaker cable tie, as in the original enclosure

Added battery items:
  1 Meshnology 3.7 V 3000 mAh 103665 pack
  2 soft nonconductive 10 mm retaining straps, about 160 mm starting length
  1 smooth insulating pad, about 36 x 68 mm and up to 1 mm thick
  Optional polarity-verified service extension, default quantity ZERO

The image states 68 x 35 x 10 mm; reserved CAD space uses 68 x 36 x 10 mm.
Actual pack tolerance, thickness, strap overlap and service slack must be
checked. Do not rigidly compress the pouch. Use M3 x 6 rear screws; M3 x 8
would bottom against the blind pilot end.

The existing C5 electronics rows are retained. External antenna/coax and
USB cable/power source are made explicit as one set each; exact variants
were not supplied and must be selected against owned hardware. These are
not extra internal modules and are not included by the printing supplier.
The external speaker and its paired wires appear once. No loose module
spacers or boost converter have been invented in this BOM.

Battery scope: Heltec BAT connection only. Amplifier remains USB-powered.
Normal local-node audio firmware enables AMP_SD without USB; battery-only
use requires a verified speaker-disabled Heltec build that holds AMP_SD
LOW while the amplifier is unpowered. Confirm actual plug keying/polarity,
simultaneous USB fit and permissible pack charge current before operation.
See ../research/BATTERY-CONNECTION-REVIEW.txt for the evidence and details.

Quantity changes and restoration were checked at 1, 2 and 3 assemblies.
The optional extension was tested at 1 then restored to 0. Formula-error
scan and all three workbook preview regions passed. The saved XLSX values,
formulas and quantities are independently compared with the JSON/CSV in
verify_bom.py. Source hashes and results are in BOM-VALIDATION.json.

No parts have been ordered and no physical fit or electrical qualification
is claimed by the BOM. Supplier prices and availability are not quoted.
