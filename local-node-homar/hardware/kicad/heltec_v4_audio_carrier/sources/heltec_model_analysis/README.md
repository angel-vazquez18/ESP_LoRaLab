# Heltec model registration

The official AP214 STEP imports successfully and passes OpenCascade BRep validity. It includes colored components, USB and two 18-pin headers, but no OLED glass or bracket. Original STEP bytes remain unmodified. `step_inspection.json` records geometry and bounds.

Use scale 1, KiCad rotation Z +90 degrees and offset (0,23.749,6.55871926) mm. This registers the 36 header axes and puts USB toward the carrier top. The body center is 0.8255 mm below the provisional symmetric 2D outline. USB reaches user y90.40034 mm, about 0.400 mm beyond the carrier; cable sweep requires checking.

The preview uses a 5 mm module-PCB underside gap. Reference CAD gives 1.400 mm underside P3 connector clearance above the carrier and header tips extending 1.900 mm below its 1.6 mm bottom. Verify the actual header assembly, underside parts and solder clearance.

Attach `Heltec_V4_R2_OLED_BRACKET_VISUAL_5mm_GAP.wrl` at scale 1, offset/rotation 0. Its 33 x 18.6 mm frame and 22 x 11.4 mm window follow the manufacturer drawing and STEP retention axes. Case, screen, supports, screws and side FPC patch are approximate visuals based on official R2 photographs. They do not establish powered operation, exact mounting or RF clearance.

The STEP retention holes measure 2.8 mm diameter while the drawing labels 1.9 mm. This reference discrepancy remains unresolved.

Primary URLs and numeric transforms are in `model_placement_and_addon.json`. Model/photo attribution remains Heltec; no explicit permissive license was identified. Analysis dependencies are kept outside the project deliverable.
