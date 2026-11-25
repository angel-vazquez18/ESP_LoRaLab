# R7 verification and reproduction

The portable archive checker requires Python 3.10+ and the standard library. It
checks the manifest, preserved historical files, twelve FreeCAD ZIP containers,
saved native/STEP and mesh audit bindings, seven installed print parts, the
separate optional coupon, documentation and viewer evidence. It reads all files
without modifying CAD or requiring FreeCAD, KiCad or network access.

`tools/rebuild_r7_viewer.py` independently decodes every compact display mesh,
checks triangle indices and dimensions, and reconstructs the published fragment
exactly from its template, packed inputs and dimension/focus tables. Its default
operation is read-only. `--output new-fragment.html` creates a new file exclusively.
The ready-to-open standalone viewer is
`revision-r7-enclosure/interactive/qa/r7-preview.html`.

The raw R7 display JSON arrays and intermediate packed/gzip duplicates are omitted
from Git because the compact transports reproduce the current viewer. R6's full
source mesh arrays are retained for its role as an R7 geometry-generation input.
This is display data, not manufacturing mesh decimation. The STL and 3MF files
come separately from the approved CAD export and have their own topology and
coordinate-round-trip validation.

Native CAD recomputation requires FreeCAD 1.1. `Parameters`, `AntennaParameters`
and `SpeakerParameters` remain editable; changes require renewed interference
and print checks. The retained development scripts document the actual workflow,
but original audit JSON contains absolute workstation paths and the CAD/viewer
generators refer to those paths. A different workstation must map those input
paths explicitly and retain the matching source hashes. Do not claim a fresh CAD
validation merely because the archived pass flags are present.

The detailed electronics STEP is preserved in the earlier lossless ZIP; the
existing extraction helper verifies its expected hash before reconstruction.
The R7 build also uses R6 native/reference shapes, R6 full display arrays and the
R4 tessellator. ReportLab/Poppler support drawing generation; Node/browser tooling
supports the recorded browser tests. The historical renderer/QA entry points may
require replacement runtime paths. These tools/runtimes are not vendored.

PCB, firmware and board-fabrication integrity reports record checks against the
original project. Their protected source files remain outside this FreeCAD-only
archive. The complete local engineering package contains the unchanged PCB
handoff and is deliberately not included in the upstream PR. Its source package
hash is retained in the publication dependency record. No Gerber regeneration,
PCB revision, order placement or machine-specific G-code is implied.

The saved-native/STEP and full-package validation must pass before this archive
can be built. First-article inspection remains necessary for the owned SMA hex,
speaker rim, switch travel, OLED stack, battery/USB plugs and lead slack.
