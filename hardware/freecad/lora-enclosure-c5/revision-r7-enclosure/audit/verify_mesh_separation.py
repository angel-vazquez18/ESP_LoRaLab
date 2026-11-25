"""Read-only in-memory probe of the bridge's combined mesh export structure.

It writes only an audit JSON. No FCStd, STEP or manufacturing mesh is saved.
The approved master must still pass derive_print_files.py after export.
"""
from pathlib import Path
from fractions import Fraction as F
import json, sys
import FreeCAD as App, Part, Mesh, MeshPart

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import derive_print_files as d

plan=json.loads((ROOT/'release-plan.json').read_text())
TOLERANCE=.02
source=ROOT.parent/'revision-r6-speaker/cad/LoRa-Enclosure-C5-R6-Speaker.FCStd'
doc=App.openDocument(str(source))
compound=Mesh.Mesh();native={};references={};counts={}
for part in plan['parts']:
    if 'candidate_brep' in part:
        path=ROOT/part['candidate_brep'];shape=Part.Shape();shape.read(str(path))
    else:
        path=source;shape=doc.getObject(part['name']).Shape
    references[str(path.relative_to(ROOT.parent))]=d.sha(path)
    mesh=MeshPart.meshFromShape(shape,LinearDeflection=TOLERANCE)
    compound.addMesh(mesh)
    bounds=shape.BoundBox
    native[part['name']]={'bounds_mm':[bounds.XMin,bounds.YMin,bounds.ZMin,bounds.XMax,bounds.YMax,bounds.ZMax],'volume_mm3':shape.Volume}
    counts[part['name']]={'vertices':mesh.CountPoints,'triangles':mesh.CountFacets}
vertices,faces=compound.Topology
chunk=d.Chunk([tuple(F.from_float(x)for x in point)for point in vertices],faces,[],{})
islands=d.split_connected(chunk)
validator=d.load_validator()
checks=[d.topology(mesh,source,validator)for mesh in islands]
for part,check in zip(plan['parts'],checks):
    target=native[part['name']]
    print(part['name'], 'bounds_error_mm',max(abs(a-b)for a,b in zip(check['bbox_mm']['min']+check['bbox_mm']['max'],target['bounds_mm'])), 'volume_relative_error',abs(check['absolute_volume_mm3']-target['volume_mm3'])/target['volume_mm3'],flush=True)
assignment,comparisons=d.unique_assignment(islands,plan['parts'],native,checks)
report={'ok':len(islands)==8 and all(c['ok']for c in checks),'scope':'Read-only candidate geometry; in-memory mesh tessellation only. Does not replace approved master validation.','mesh_tolerance_mm':TOLERANCE,'source_hashes':references,'source_parts':counts,'combined_vertices':len(vertices),'combined_triangles':len(faces),'index_separated_parts':len(islands),'assignment':assignment,'matched_comparisons':{name:comparisons[i][name]for i,name in assignment.items()},'manufacturing_files_written':False}
(ROOT/'audit/mesh-separation-probe.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
App.closeDocument(doc.Name)
