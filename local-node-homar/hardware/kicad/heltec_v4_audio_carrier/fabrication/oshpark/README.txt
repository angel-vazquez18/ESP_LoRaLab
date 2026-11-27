OSH PARK PCB SUBMISSION - HELTEC V4 R2 AUDIO CARRIER C5
Prepared 24 November 2026 from KiCad 10.0.8

UPLOAD THIS FILE
heltec_v4_audio_carrier_C5_OSHPARK.zip

Upload the ZIP intact at https://oshpark.com/ . It contains all fabrication
layers and drills for the bare carrier PCB. Components are soldered on after
the boards arrive. No BOM, placement file, paste stencil or assembly order is
needed for this submission.

BOARD AND SERVICE
Service: OSH Park 4 Layer Super Swift, as selected in the project brief.
Size: 70.00 x 90.00 mm (outline line centers).
Layers, top to bottom: F.Cu / In1.Cu / In2.Cu / B.Cu.
Nominal thickness: 1.6 mm. FR408-HR substrate; purple mask; ENIG finish.
Copper: 1 oz outer layers, 0.5 oz inner layers.
Quantity: OSH Park supplies multiples of three boards.
Area: 9.7650 square inches. Published Super Swift rate is $20 per square inch
for three copies: approximately $195.30 for three boards. The website quote
and checkout determine the final price and schedule.

UPLOAD CHECK
1. Upload only heltec_v4_audio_carrier_C5_OSHPARK.zip.
2. Confirm the website detects FOUR copper layers and a 70 x 90 mm board.
3. Compare its front/back previews with preview-top.png and preview-bottom.png.
   Look for the two Heltec header rows, seven amplifier contacts, six microphone
   contacts, two R8 resistor holes and four PTT switch holes. The board also
   has four mounting holes and one central microphone opening.
4. Choose the intended four-layer service, review quantity/quote and complete
   the order yourself. No order or payment has been submitted by this export.

CONTENTS OF THE ZIP: 11 FILES
heltec_v4_audio_carrier-F_Cu.gtl           Top copper (L1)
heltec_v4_audio_carrier-In1_Cu.g1          Inner copper (L2)
heltec_v4_audio_carrier-In2_Cu.g2          Inner copper (L3)
heltec_v4_audio_carrier-B_Cu.gbl           Bottom copper (L4)
heltec_v4_audio_carrier-F_Mask.gts         Top soldermask openings
heltec_v4_audio_carrier-B_Mask.gbs         Bottom soldermask openings
heltec_v4_audio_carrier-F_Silkscreen.gto   Top silkscreen
heltec_v4_audio_carrier-B_Silkscreen.gbo   Bottom silkscreen
heltec_v4_audio_carrier-Edge_Cuts.gm1      Closed board outline
heltec_v4_audio_carrier-PTH.drl            93 plated drill hits
heltec_v4_audio_carrier-NPTH.drl           5 nonplated drill hits

Keep the filenames and X2 metadata: KiCad's .g1 file is the second physical
copper layer, and .g2 is the third. All copper uses positive image polarity.
All layers and drills use the same absolute origin. Drill units are mm with
decimal coordinates, no Y mirror, and alternate slot mode (no slots present).
Silkscreen has been clipped away from soldermask openings.

DRILL SUMMARY
Plated: 38 x 0.40 mm vias; 2 x 1.00 mm R8 holes; 53 x 1.10 mm contacts.
Nonplated: 4 x 3.20 mm mounting holes; 1 x 3.00 mm microphone opening.
Total: 98 drill hits. All match native-board positions and sizes within the
0.001 mm coordinate precision of the exported Excellon format.

VALIDATION AND PROTOTYPE STATUS
Zones refilled; native board remained byte-identical to the current C5 PCB.
Fresh ERC: 0 violations. Fresh DRC: 0 violations, 0 unconnected items and
0 schematic parity issues. No DRC exclusions. Four copper layers, separate
PTH/NPTH drill files, closed outline, drill alignment and ZIP integrity were
checked independently with Gerbonara. Top/bottom CAM previews and all four
copper outputs were visually inspected. Detailed records are in checks/.

These are prototype fabrication files. Actual owned-part fit and assembled
hardware operation have not been measured or tested. Before spending money,
print ../../review/mechanical-check-1to1.pdf at Actual Size / 100% and compare
the owned modules, switch and resistor against it. In particular, confirm
the microphone's contact grid/orientation and sound path, amplifier header
registration, Heltec fit, PTT contact pairing and R8 formed lead pitch.
The current PCB's physical-fit hold remains documented; CAM checks do not
establish that the actual parts will fit. Firmware and BOM are unchanged.

SOURCE RECORD
This package is tied to the native PCB and schematic SHA256 values in
submission-manifest.json. If the PCB changes, regenerate the fabrication
package; do not reuse this ZIP for a later board revision.

OFFICIAL GUIDANCE CHECKED 24 NOVEMBER 2026
https://docs.oshpark.com/services/four-layer-swift/
https://docs.oshpark.com/design-tools/kicad/
https://docs.oshpark.com/design-tools/kicad/generating-kicad-gerbers/
https://docs.oshpark.com/submitting-orders/board-outline/
https://docs.oshpark.com/troubleshooting/naming-pattern/
