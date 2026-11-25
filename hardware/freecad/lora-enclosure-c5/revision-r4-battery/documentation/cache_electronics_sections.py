"""Read-only section cache for the unchanged, corrected actual component assembly."""
from pathlib import Path
import hashlib,json
import FreeCAD as App
import Part

root=Path(__file__).resolve().parent
source=root.parents[1]/'detailed-import/C5-detailed-assembly.step'
cfg=json.loads((root/'view-config.json').read_text())
x=float(cfg['section_x_mm'])
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
initial=sha(source)
doc=App.newDocument('BatteryDocumentationElectronicsCache')
Part.insert(str(source),doc.Name)
objects=[o for o in doc.Objects if hasattr(o,'Shape') and not o.Shape.isNull()]
assert len(objects)==2949
families={'carrier':list(range(889,1068))+[2947,2948], 'heltec':list(range(1,889))+list(range(2145,2811)), 'oled':list(range(2811,2831))}
sections={}
for name,indices in families.items():
    lines=[]
    for i in indices:
        shape=objects[i].Shape.copy();shape.translate(App.Vector(0,0,6.4814))
        bb=shape.BoundBox
        if bb.XMin-1e-7<=x<=bb.XMax+1e-7:
            for wire in shape.slice(App.Vector(1,0,0),x):
                points=[[round(v.y,7),round(v.z,7)] for v in wire.discretize(Deflection=.025)]
                if wire.isClosed() and points[-1]!=points[0]:points.append(points[0])
                lines.append(dict(points=points,closed=wire.isClosed()))
    sections[name]=lines
assert sha(source)==initial
cache=dict(reference_file=str(source),reference_sha256=initial,section_x_mm=x,
           method='Exact B-rep slices of original corrected assembly; Z translation +6.4814 mm; no source file saved.',sections=sections)
(root/'electronics-section-cache.json').write_text(json.dumps(cache,indent=2)+'\n',encoding='utf-8')
App.closeDocument(doc.Name)
print(json.dumps(dict(ok=True,counts={n:len(v) for n,v in sections.items()},source_unchanged=True)))
