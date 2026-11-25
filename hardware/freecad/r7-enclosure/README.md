# R7 enclosure — current project files

This is the single current enclosure folder. R7 includes the battery housing,
SMA antenna mount and removable anti-rotation key, internal speaker retention,
reinforced lid, microphone shroud and cable guides. The PCB mounting datums and
nominal **0.50 mm OLED clearance** are unchanged.

## Open the design and views

| Item | File |
| --- | --- |
| Editable FreeCAD assembly | [R7 native CAD](cad/LoRa-Enclosure-C5-R7-Reinforced.FCStd) |
| Rotate, zoom, explode and cut away | [Interactive viewer](interactive/qa/r7-preview.html) |
| Assembled isometric-style view | [PNG](interactive/views/R7-assembled.png) |
| Exploded view | [PNG](interactive/views/R7-exploded.png) |
| Cutaway view | [PNG](interactive/views/R7-cutaway.png) |
| Top/front/right part views and assembly sections | [Nine-sheet manufacturing drawing](documentation/manufacturing/C5-R7-Manufacturing-Drawings.pdf) |
| Reinforcement and load-path details | [Engineering improvement drawing](documentation/LoRa-C5-R7-Enclosure-Improvements.pdf) |
| Assembly and fit inspection | [Instructions](documentation/R7-ASSEMBLY-AND-INSPECTION.txt) |
| Complete BOM | [Spreadsheet](documentation/bom/LoRa-C5-R7-Complete-BOM.xlsx) · [CSV](documentation/bom/LoRa-C5-R7-Complete-BOM.csv) |

The drawing's first seven sheets contain individual part projections, sheet 8
contains assembly sections, and sheet 9 documents load paths and manufacturing
flow. The viewer includes the detailed assigned PCB/component geometry and
representative battery, antenna and speaker fit references.

## Fabrication files

- **Craftcloud:** use [craftcloud/upload](craftcloud/upload/) and the
  [order specification](craftcloud/ORDER-SPECIFICATION.txt). Seven installed
  parts, one of each, in unfilled MJF PA12. Choose STL **or** 3MF for each part;
  do not upload both formats as extra quantities. The
  [fit coupon](craftcloud/optional-coupon/) is optional and separate.
- **Print files in assembly coordinates:** [printing](printing/), including the
  all-parts 3MF. The shop upload set is translated for individual-part ordering.
- **CNC shop:** [STEP and handoff](cnc-shop/). These are shop-ready geometry and
  requirements for quoting/CAM planning; machine-specific cutting G-code is not
  supplied because the shop selects its machine, tools and workholding.
- **Existing PCB manufacturing files:** the local `pcb-fabrication/` folder
  preserves the already-issued Gerbers, drills and electronics BOM. No PCB or
  firmware changes are part of this enclosure revision or its upstream PR.

No order has been placed. These remain prototype fit files. Measure the owned
SMA connector/key fit, switch travel, speaker frame, battery leads and display
stack before production. The amplifier remains USB-powered; see the retained
[battery connection review](documentation/references/BATTERY-CONNECTION-REVIEW.txt).

## Folder guide

| Folder | Contents |
| --- | --- |
| `cad/` | One current native FreeCAD file and enclosure STEP |
| `printing/`, `craftcloud/`, `cnc-shop/` | Current manufacturing handoff |
| `documentation/` | Technical drawings, BOM, process and inspection instructions |
| `interactive/` | Viewer, images, current display inputs and viewer validation |
| `audit/` | R7 engineering evidence and integrity checks |
| `references/` | Component inputs, attribution and unchanged PCB preservation records |
| `tools/` | Portable validation and current viewer reconstruction |

Earlier enclosure revisions were removed from the active file set; their
development history remains in Git. Historical audit records deliberately keep
their original source paths and hashes. They are evidence of earlier checks,
not dependencies on deleted revision folders. See
[reproducibility](REPRODUCIBILITY.md), [provenance](PROVENANCE.json) and
[source notices](SOURCE-NOTICES.md).

During consolidation the assembly-section drawing was corrected to use each
electronic component's global placement. The native CAD, viewer geometry and
print parts did not change.
