# INMP441 footprint reference

The carrier uses a 14 mm round module with 2.54 mm column pitch and 7.62 mm row separation. These dimensions come from the user image and [Rafael Bachmann's community CAD](https://github.com/barafael/inmp441-breakout-kicad/tree/816ee4424e4765e0214c96a88f26b3a16a51b17a). The original CAD, README, MIT license and commit record are retained here. They are reference evidence, not a measurement of the owned module.

U2 center is carrier (54.5, 30.5) mm, measured from the lower-left corner with Y up. Acoustic/solder face points up. The top row is SCK / WS / L/R; the bottom row is SD / VDD / GND. See inmp441_reference_pad_mapping.csv for all contact coordinates.

Carrier contact holes are 1.1 mm with 1.8 mm copper pads. The centered 3 mm opening, 2 mm-radius copper exclusion and 3 mm module gap are engineering choices pending actual fit. The image's red 12 mm dimension is not contact-row separation.

MIC_BCLK, MIC_WS and MIC_DATA connect directly to the Heltec. VDD uses 3.3 V; L/R is grounded. No extra carrier microphone pulldown or bypass capacitor is fitted; the design relies on existing module circuitry.

Before fabrication, compare the actual module with the 1:1 fit sheet: contact positions, facing, pin size, underside clearance and acoustic alignment. The IC datasheet does not dimension the breakout. Keep the sound path clear of solder, adhesive and cleaning residue.
