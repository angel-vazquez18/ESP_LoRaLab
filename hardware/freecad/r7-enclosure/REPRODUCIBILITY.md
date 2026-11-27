# Current R7 validation and reuse

This directory contains one current FreeCAD document and its approved exports.
Older enclosure revisions are not runtime dependencies. Their publication commit
identities, comparison results and original source hashes remain in
`PROVENANCE.json` and the preserved audit records. No native CAD, component
placement, manufacturing mesh or PCB geometry was changed by consolidation.

From this directory, ordinary Python 3.10+ runs the current checks:

```sh
python tools/validate_release.py
python tools/rebuild_r7_viewer.py
python test_derive_print_files.py
```

The release checker writes `VALIDATION.json`. It checks the single native
container, approved geometry identities, exact individual 3MF geometry and STL
float32 conversion against the master, mesh topology, seven installed parts and
the separate coupon, drawings/BOM/CNC hashes, and the compact interactive viewer.
It accepts the component STEP either as the preserved raw reference or as its
verified lossless ZIP. PCB fabrication payloads are optional: the local package
can validate their copies; the FreeCAD-only publication excludes them.

To refresh the geometry proof, run the same script using FreeCAD 1.1's Python:

```powershell
& 'C:/Program Files/FreeCAD 1.1/bin/python.exe' tools/validate_release.py --cad
```

This opens R7 read-only, applies each object's global parent placement once,
compares all eight printed solids with the STEP export, checks the registration
of all 2,949 assigned component objects, and verifies that recomputation leaves
the printed geometry unchanged. The component assembly parent translation is
`(0, 0, 6.4814)` mm. The proof is written to
`audit/current-native-validation.json`; no FCStd, STEP or mesh is saved.
`--cad-only` refreshes just that geometry proof.

`derive_print_files.py` reads the already approved multipart 3MF and the current
native proof. It can reproduce individual printing files and translation-only
Craftcloud files without a CAD export. It now uses the local
`tools/mesh_validation.py`; it writes new derivative evidence to
`audit/current-print-validation.json`, preserving the historical derivation
report. Regenerating deliverables requires rebuilding the package manifest.

The original `audit/saved-r7-validation.json` records the completed comparison
against R6. It remains unchanged and its historical source is recoverable from
the commits in `PROVENANCE.json`; the current checker does not pretend to rerun
that comparison without the R6 file. Original absolute paths in historical
reports identify provenance. Current R7 paths are resolved by their relative
suffix; the metadata is not silently rewritten.

The manufacturing section drawings were regenerated with the component parent
transform applied. Their current report binds the corrected PDF, geometry,
native document and STEP. Earlier drawing evidence is preserved under the
documentation provenance directory. Complete BOM and battery/hardware reference
notes are under `documentation/`; model attribution remains in
`SOURCE-NOTICES.md` and `references/`.

The original 367-file PCB/firmware guard records and the relocation proof remain
preserved. Portable validation checks those records and any local preserved PCB
copies; it does not claim to reread external firmware files on a different
computer. A fresh protected-source check requires the complete original local
source scopes and `audit/verify_pcb_guard.py`.

The native feature tree and parameter tables remain editable. A later design
change requires new fit, export, drawing and print checks. The first-article
inspection requirements for the owned SMA hex, switch travel, speaker frame,
OLED stack and battery/USB plug combination still apply. No order or
machine-specific G-code is produced by these checks.
