# Current C5 design decisions

- **PTT:** fit SW1, the selected OCR TPBS02 / Amazon B01MRP025V 6 x 6 x 8 mm normally-open tactile. Pressing it connects GPIO39/PTT_N directly to GND. The 6.5 x 4.5 mm reference grid comes from C&K PTS645 and KiCad; verify the actual OCR switch's fit and contact pairing. See PTT_SWITCH_RESEARCH.md.
- **Carrier passives:** R8 is the only carrier passive: the user-selected EEEEE 1 kohm, 1/2 W, 5% carbon axial through-hole resistor, mounted horizontally as the amplifier SD/MODE pulldown. Use `Carrier:R_Axial_Carbon_0p5W_P15p24_Horizontal`: 15.24 mm formed pitch, 1.0 mm holes and 2.0 mm pads with a 10.0 x 3.6 mm reference body envelope. Verify the owned body and lead dimensions before forming leads; the reference is not an exact EEEEE drawing. Power and signals use direct copper. Existing module components and all 13 test pads remain.
- **Speaker:** external leads connect directly to amplifier SPK+/SPK-. Neither terminal is GND. The carrier has no speaker connector or reserved speaker area.
- **Amplifier:** the user drawing specifies 17.7 x 19 mm and seven contacts at 2.54 mm pitch. Header/body registration and hole fit require physical verification. GAIN is grounded for +12 dB.
- **Microphone:** 14 mm body with a community-reference 2.54 x 7.62 mm grid. The image's 12 mm annotation is not row spacing. Acoustic/solder face is up; the 3 mm gap and central aperture need physical confirmation. L/R is grounded. No additional carrier SD pulldown is fitted.
- **Annotations:** retain useful reference, signal, supply and orientation labels, with concise schematic notes.

The carrier is 70 x 90 mm with four copper layers, USB power and the project GPIO mapping. The RF reservation is an engineering allowance. Fit, acoustic/RF clearance and hardware operation remain untested.

Firmware remains `ENABLE_PTT=false`. Enabling the existing option configures GPIO39 with `INPUT_PULLUP`; validate debounce and released/pressed behavior during bring-up. CAD population does not enable firmware or perform physical assembly.
