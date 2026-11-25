"""Read-only BREP projections for R7 drawings; never saves or exports CAD.

Requires the approved R7 native/STEP and original saved-native validation.
Nested components use global placement, including their parent assembly datum.
No historical enclosure model is needed and no CAD files are saved or exported.
"""
from pathlib import Path
import hashlib,json
import FreeCAD as A,Part,TechDraw

HERE=Path(__file__).resolve().parent;REV=HERE.parents[1]
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
plan=json.loads((REV/'release-plan.json').read_text(encoding='utf-8'))
native=REV/plan['native_file'];step=REV/plan['step_file']
v=json.loads((REV/'audit/saved-r7-validation.json').read_text());assert v['ok']
assert v['native_sha256']==sha(native) and v['source_hashes']['step']==sha(step)
sources={p.relative_to(REV).as_posix():sha(p) for p in [native,step]}
doc=A.openDocument(str(native))

def globally_placed_shape(obj):
 s=obj.Shape.copy()
 s.Placement=obj.getGlobalPlacement()
 return s
def bounds(s):
 b=s.optimalBoundingBox(False,False);return[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def curves(s,d):
 g=TechDraw.projectEx(s,A.Vector(*d))
 def points(e):
  if e.Length<1e-7:return []
  out=[]
  for p in e.discretize(Deflection=.005):
   q=[p.y,-p.x] if d==(0,-1,0) else ([-p.y,p.x]if d==(1,0,0)else[p.x,p.y])
   out.append([round(v,6)for v in q])
  return out
 return {'visible':[p for group in g[:5]for e in group.Edges if(p:=points(e))],
         'hidden':[p for group in g[5:]for e in group.Edges if(p:=points(e))]}
out={'ok':False,'release_ready':True,'source_mode':'approved R7 native and STEP; global assembly placements',
 'source_hashes':sources,'parts':{},'sections':{},'method':'FreeCAD TechDraw hidden-line projection of exact BREP, displayed curves sampled at 0.005 mm deflection; source solids unchanged.',
 'datum':'Carrier lower-left X0 Y0, USB +Y; original base floor exterior Z0. All nominal mm.'}
shapes={}
try:
 for p in plan['parts']:
  n=p['object']
  s=globally_placed_shape(doc.getObject(n))
  assert s.isValid()and s.isClosed()and len(s.Solids)==1,n
  shapes[n]=s
  out['parts'][n]={'bounds_mm':bounds(s),'volume_mm3':s.Volume,'optional':p['optional'],'views':{k:curves(s,d)for k,d in [('top',(0,0,1)),('front',(0,-1,0)),('right',(1,0,0))]}}
  print(n+' projected',flush=True)
 installed=[shapes[p['object']]for p in plan['parts']if not p['optional']]
 actual_objects=[o for o in doc.Objects if o.Name.startswith('C5_detailed_assembly') and hasattr(o,'Shape') and not o.Shape.isNull()]
 actual=[globally_placed_shape(o) for o in actual_objects]
 assert len(actual)==2949
 placement_offsets={round(o.getGlobalPlacement().Base.z-o.Placement.Base.z,7) for o in actual_objects}
 assert placement_offsets=={6.4814},placement_offsets
 out['global_placement_check']={'ok':True,'component_count':len(actual),'parent_z_offsets_mm':sorted(placement_offsets),'method':'Copy Shape and replace Placement with object.getGlobalPlacement(); no extra transform or CAD mutation.','first_object':actual_objects[0].Name,'first_local_bounds_mm':bounds(actual_objects[0].Shape),'first_global_bounds_mm':bounds(actual[0])}
 assert abs(actual[0].BoundBox.ZMin-4.5)<1e-6 and abs(actual[0].BoundBox.ZMax-16)<1e-6
 refs=[]
 for n in ['ReferenceBatteryEnvelope','ReferenceSpeakerEnvelope']:
  o=doc.getObject(n)
  if o is not None and hasattr(o,'Shape'):refs.append(globally_placed_shape(o))
 out['actual_component_objects']=len(actual)
 for title,normal,offset,d in [('battery_x27_2',(1,0,0),27.2,(1,0,0)),('ptt_y9',(0,1,0),9,(0,-1,0)),('speaker_y47',(0,1,0),47,(0,-1,0))]:
  rec={'plane_normal':normal,'offset_mm':offset,'groups':{}}
  for label,items in [('enclosure',installed),('actual_electronics',actual),('reference_hardware',refs)]:
   wires=[]
   axis=0 if normal[0]else 1
   for s in items:
    b=s.BoundBox;lo=[b.XMin,b.YMin,b.ZMin][axis];hi=[b.XMax,b.YMax,b.ZMax][axis]
    if lo-1e-7<=offset<=hi+1e-7:wires.extend(s.slice(A.Vector(*normal),offset))
   rec['groups'][label]=curves(Part.makeCompound(wires),d)if wires else {'visible':[],'hidden':[]}
  out['sections'][title]=rec;print(title+' assembled section extracted',flush=True)
finally:A.closeDocument(doc.Name)
out['source_unchanged']={p:sha(REV/p)==h for p,h in sources.items()};assert all(out['source_unchanged'].values())
out['ok']=True;target=HERE/'manufacturing-geometry.json'
target.write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'ok':True,'release_ready':out['release_ready'],'output':str(target),'parts':len(shapes),'actual_components':len(actual)}))
