from pathlib import Path
import json
import FreeCAD as A,Part,Import
OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[3]
p=ROOT/'output/heltec-v4-carrier/design/models/reference/heltec-v4_3_1-reference.step'
d=A.newDocument('IPEXReadOnly');Import.insert(str(p),d.Name)
def bb(s):
 b=s.optimalBoundingBox(False,False);return[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
rows=[]
for o in d.Objects:
 if 'IPEX' in o.Label.upper() or o.Label=='PCB' or 'BOARD' in o.Label.upper():
  row={'name':o.Name,'label':o.Label,'type':o.TypeId}
  if hasattr(o,'Shape'):row['bounds']=bb(o.Shape)
  if hasattr(o,'Group'):row['children']=[{'name':a.Name,'label':a.Label,'bounds':bb(a.Shape)}for a in o.Group if hasattr(a,'Shape')]
  rows.append(row)
(OUT/'ipex-reference-location.json').write_text(json.dumps(rows,indent=2))
print(json.dumps(rows),flush=True)
A.closeDocument(d.Name)
