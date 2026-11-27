"""Independent FreeCAD DXF-reader round trip of CNC reference projections."""
from pathlib import Path
import json
import FreeCAD as App
import Part
import importDXF

root=Path(__file__).resolve().parent
folder=root/"cnc-reference"
manifest=json.loads((folder/"DXF-REFERENCE-MANIFEST.json").read_text())
records=[]
for source in manifest["records"]:
    path=folder/Path(source["file"]).name
    doc=App.newDocument("DXFReadBack")
    importDXF.insert(str(path),doc.Name)
    shapes=[o.Shape for o in doc.Objects if hasattr(o,"Shape") and not o.Shape.isNull()]
    b=Part.makeCompound(shapes).BoundBox
    xy=[b.XMin,b.YMin,b.XMax,b.YMax]
    delta=max(abs(a-b) for a,b in zip(xy,source["top_projection_bounds_mm"]))
    assert len(shapes)==source["polyline_entities"]
    assert delta<=.02501
    records.append({"file":path.name,"imported_shapes":len(shapes),"bounds_mm":xy,"max_bound_deviation_mm":delta,"ok":True})
    App.closeDocument(doc.Name)
report={"method":"Read back through independent FreeCAD importDXF reader in an unsaved headless document; compare entity count and XY bounding dimensions.","ok":all(r["ok"] for r in records),"records":records}
(folder/"DXF-READBACK-VALIDATION.json").write_text(json.dumps(report,indent=2)+"\n")
print(json.dumps(report,indent=2))
