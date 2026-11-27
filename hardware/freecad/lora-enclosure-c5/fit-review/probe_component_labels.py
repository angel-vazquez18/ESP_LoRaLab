from pathlib import Path
import json
import FreeCAD as App, Import

root=Path(__file__).resolve().parent
source=root.parent/'detailed-import/C5-detailed-assembly.step'
doc=App.newDocument('ComponentSemanticProbe')
Import.insert(str(source),doc.Name)
records=[]
for obj in doc.Objects:
    d={'name':obj.Name,'label':obj.Label,'type':obj.TypeId,'parents':[p.Name for p in obj.InList]}
    if hasattr(obj,'Group'):d['group']=[o.Name for o in obj.Group]
    if hasattr(obj,'Shape') and not obj.Shape.isNull():
        s=obj.Shape.copy()
        if hasattr(obj,'getGlobalPlacement'):
            delta=obj.getGlobalPlacement().multiply(obj.Placement.inverse())
            s.Placement=delta.multiply(s.Placement)
        b=s.BoundBox
        d.update(bbox=[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax],faces=len(s.Faces),solids=len(s.Solids),area=s.Area)
    records.append(d)
(root/'semantic-import-probe.json').write_text(json.dumps(records,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'objects':len(records),'types':{t:sum(x['type']==t for x in records) for t in {x['type'] for x in records}},'top':[x for x in records if not x['parents']]}))
