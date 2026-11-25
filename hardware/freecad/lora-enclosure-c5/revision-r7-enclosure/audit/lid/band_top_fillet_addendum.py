from pathlib import Path
import FreeCAD as A, Part,json
OUT=Path(__file__).resolve().parent
s=Part.makeBox(21,2.35,.7,A.Vector(12.5,42.2,22))
ids=[i for i,e in enumerate(s.Edges,1)if all(abs(v.Point.z-22.7)<1e-7 for v in e.Vertexes)]
assert len(ids)==4
ops=[{'tool':'cam_set_properties','args':{'object_name':'R7OLEDStrengthBand'+str(i),'values':{'Edges':[[k,.2,.2]for k in ids]},'recompute':True}}for i in[1,2]]
r={'reason':'Top-only fillet preserves a flat base and continuous roof; all-edge fillet is superseded.','top_edge_indices':ids,'operations':ops}
(OUT/'oled-band-fillet-addendum.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
