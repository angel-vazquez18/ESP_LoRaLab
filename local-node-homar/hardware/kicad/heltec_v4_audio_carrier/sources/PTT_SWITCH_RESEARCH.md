# PTT switch reference

SW1 is the selected **6 x 6 x 8 mm normally-open four-lead tactile** from [OCR TPBS02 kit B01MRP025V](https://www.amazon.com/dp/B01MRP025V?th=1). It is **FIT** and connects GPIO39/PTT_N directly to GND when pressed.

The reference pattern uses 6.5 x 4.5 mm contact centers, 2.0 mm pads and 1.1 mm carrier holes. Sources are the [C&K PTS645 drawing](https://www.littelfuse.com/assetdocs/littelfuse-ck-tactile-pts645-series-datasheet?assetguid=d58fc8a8-f6e1-4527-ab68-27635e632e39) and [KiCad SW_PUSH_6mm footprint](https://gitlab.com/kicad/libraries/kicad-footprints/-/blob/master/Button_Switch_THT.pretty/SW_PUSH_6mm.kicad_mod). C&K specifies 1.0 mm holes; this design adopts KiCad's 1.1 mm holes. No exact OCR manufacturing drawing was found.

At user coordinates (51,9) mm, the upper pair is contact1/PTT_N and the lower pair is contact2/GND. Each pair spans 6.5 mm; the groups are 4.5 mm apart. Copper joins each same-net pair. Before soldering, verify permanent continuity within each pair, open between groups when released and closed when pressed. Confirm pin fit and actuator access.

The 3D assembly uses KiCad's standard `SW_PUSH_6mm_H8mm.step` as a representative fitted switch, not an OCR manufacturer model. Firmware remains `ENABLE_PTT=false`; the enabled path uses GPIO39 `INPUT_PULLUP`. Verify debounce and LOW-when-pressed behavior when enabling PTT.

Supporting evidence is under `footprint_reference/switch/`. No physical switch test has been performed.
