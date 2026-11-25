"""In-memory execution of the native operation plan; never saves CAD."""
from pathlib import Path
import json,hashlib
import FreeCAD as A,Part
import evaluate_rear_bay as bay
out=Path(__file__).resolve().parent
plan=json.loads((out.parent/'native-battery-operations-plan.json').read_text())
src=out.parents[1]/'revision-r3-oled-gap/cad/LoRa-Enclosure-C5-R3-OLED.FCStd'
hash_before=hashlib.sha256(src.read_bytes()).hexdigest()
d=A.openDocument(str(src));p=d.getObject('Parameters')
for row,(label,value,note)in enumerate(plan['parameter_rows'],plan['parameter_start_row']):
 p.set('A'+str(row),label);p.set('B'+str(row),str(value));p.set('C'+str(row),note)
d.recompute()
for i,item in enumerate(plan['operations']):
 name=item['tool'];a=item['args']
 if name=='create_object':
  obj=d.addObject(a['type_id'],a['name'])
  for key,v in a.get('properties',{}).items():
   if hasattr(obj,key):setattr(obj,key,v)
 elif name=='cam_set_properties':
  obj=d.getObject(a['object_name'])
  for key,v in a.get('values',{}).items():
   typ=obj.getTypeIdOfProperty(key)
   if typ=='App::PropertyLink':v=d.getObject(v)
   elif typ=='App::PropertyLinkList':v=[d.getObject(x)for x in v]
   setattr(obj,key,v)
  for key,v in a.get('expressions',{}).items():obj.setExpression(key,v)
 elif name=='fillet_edges':
  obj=d.addObject('Part::Fillet',a['name']);obj.Base=d.getObject(a['object_name'])
  obj.Edges=[(int(e[4:]),a['radius'],a['radius'])for e in a['edges']]
 else:raise ValueError(name)
 d.recompute()
 if i%20==0:print('Operation',i,flush=True)
for objname,items in [('BaseWithSupports',plan['base_fuse_additions']),('BaseCutters',plan['base_cutter_additions'])]:
 obj=d.getObject(objname);assert obj,objname
 obj.Shapes=list(obj.Shapes)+[d.getObject(n)for n in items]
d.recompute()
expected_body=bay.body.fuse(bay.box(21,35,92,99.6,-14,11.1)).cut(bay.box(23.4,32.6,91.9,97.2,-14.1,13.2)).removeSplitter()
expected_cover=bay.cover.fuse(bay.box(21,35,92,99.6,-16.4,-14)).cut(bay.box(23.4,32.6,90.3,94.5,-14,-12.3)).removeSplitter()
report={'scope':'In-memory native feature operation-plan check. No CAD file saved/exported.','parts':{},'failures':[]}
for n,expect in [('EnclosureBase',expected_body),('BatteryCover',expected_cover)]:
 shape=d.getObject(n).Shape
 rec=bay.info(shape);rec['symmetric_difference_mm3']=shape.cut(expect).Volume+expect.cut(shape).Volume
 report['parts'][n]=rec
 if not(rec['valid']and rec['closed']and rec['solids']==1 and rec['symmetric_difference_mm3']<1e-5):report['failures'].append(n)
report['source_unchanged']=hashlib.sha256(src.read_bytes()).hexdigest()==hash_before
report['ok']=not report['failures']and report['source_unchanged']
(out/'native-plan-validation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,indent=2))
A.closeDocument(d.Name)
if not report['ok']:raise SystemExit(1)
