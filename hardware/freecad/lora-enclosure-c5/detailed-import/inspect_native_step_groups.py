from pathlib import Path
import FreeCAD as App, Part, json, time

root=Path(__file__).resolve().parent
doc=App.newDocument('OfflineDetailedAudit')
print('IMPORT_START',flush=True)
Part.insert(str(root/'C5-detailed-assembly.step'),doc.Name)
print('IMPORTED',len(doc.Objects),flush=True)
rows=[]
for index,obj in enumerate(doc.Objects):
    if not hasattr(obj,'Shape') or obj.Shape.isNull(): continue
    b=obj.Shape.BoundBox
    rows.append({'index':index,'name':obj.Name,'label':obj.Label,'bbox':[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax],'faces':len(obj.Shape.Faces),'solids':len(obj.Shape.Solids),'shells':len(obj.Shape.Shells),'area':obj.Shape.Area})
(root/'native-import-object-audit.json').write_text(json.dumps(rows,indent=2)+'\n')
print('FIRST',json.dumps(rows[:16]),flush=True)
print('LAST',json.dumps(rows[-6:]),flush=True)
App.closeDocument(doc.Name)
