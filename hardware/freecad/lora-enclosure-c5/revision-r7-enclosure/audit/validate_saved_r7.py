"""Read-only R7 native and STEP verification against independently audited CAD.

Run after the approved bridge saves exist. Never saves a FreeCAD document.
"""
from pathlib import Path
import FreeCAD as A, Part
import hashlib, importlib.util, itertools, json, zipfile

ROOT=Path(__file__).resolve().parents[1];ENC=ROOT.parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
native=ROOT/'cad/LoRa-Enclosure-C5-R7-Reinforced.FCStd'
prior=ENC/'revision-r6-speaker/cad/LoRa-Enclosure-C5-R6-Speaker.FCStd'
step=ROOT/'cad/LoRa-Enclosure-C5-R7-Reinforced.step'
plan=json.loads((ROOT/'release-plan.json').read_text())
files={'native':native,'prior_R6':prior,'step':step}
before={k:sha(p)for k,p in files.items()}
assert before['prior_R6']=='baacc8eb79f0f1d200c74dd3d10f4605f5bcfd182ff7127c946ad74842a55e37'
with zipfile.ZipFile(native)as z:assert z.testzip()is None
def bounds(s):
 b=s.optimalBoundingBox(False,False);return[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def info(s):return dict(valid=s.isValid(),closed=s.isClosed(),solids=len(s.Solids),volume_mm3=s.Volume,bounds_mm=bounds(s))
def compare(a,b):
 bd=max(abs(x-y)for x,y in zip(bounds(a),bounds(b)));vd=abs(a.Volume-b.Volume)
 sd=abs(a.cut(b).Volume)+abs(b.cut(a).Volume)
 # OCCT numerical surface integration can differ between equivalent filleted
 # Boolean constructions. Exact Boolean difference and bounds remain gates.
 vt=max(1e-5,abs(a.Volume)*1e-6)
 return dict(bounds_difference_mm=bd,volume_difference_mm3=vd,
             volume_integration_tolerance_mm3=vt,symmetric_difference_mm3=sd,
             matches=bd<1e-6 and vd<vt and sd<1e-5)
old=A.openDocument(str(prior));doc=A.openDocument(str(native))
r={'ok':False,'native_sha256':before['native'],'scope':'Native/STEP shape identity, unchanged electronics, printable pair intersections; no strength qualification.',
   'source_hashes':before,'parts':{},'candidate_comparisons':{},'retained_comparisons':{},'step':{},'failures':[]}
def check(x,label):
 if not x:r['failures'].append(label)
try:
 shapes={p['object']:doc.getObject(p['object']).Shape.copy()for p in plan['parts']}
 for p in plan['parts']:
  n=p['object'];r['parts'][n]=info(shapes[n]);check(r['parts'][n]['valid']and r['parts'][n]['closed']and r['parts'][n]['solids']==1,'Native solid '+n)
  if 'candidate_brep' in p:
   path=ROOT/p['candidate_brep'];s=Part.Shape();s.read(str(path));r['source_hashes'][str(path)]=sha(path)
   result=compare(shapes[n],s);r['candidate_comparisons'][n]=result;check(result['matches'],'Candidate '+n)
  else:
   result=compare(shapes[n],old.getObject(n).Shape);r['retained_comparisons'][n]=result;check(result['matches'],'Retained '+n)
 # Confirm every original component/reference object and its transform. Only
 # explicitly changed mechanical hardware references are exempt from this list.
 electronics=[o for o in old.Objects if o.Name.startswith('C5_detailed_assembly')]
 changed=[]
 for o in electronics:
  q=doc.getObject(o.Name)
  if q is None or o.Shape.exportBrepToString()!=q.Shape.exportBrepToString() or str(o.Placement)!=str(q.Placement):changed.append(o.Name)
 r['unchanged_electronics']={'objects_compared':len(electronics),'changed':changed,'method':'Exact BREP serialization and object placement equality'}
 check(len(electronics)>2900 and not changed,'Assigned PCB/component geometry changed')
 for name in ['ReferencePCB','ReferenceBatteryEnvelope','ReferenceHeltecEnvelope','ReferenceOLEDGlass','ReferencePTTSwitch']:
  o=old.getObject(name);q=doc.getObject(name)
  if o is not None and q is not None and hasattr(o,'Shape'):
   result=compare(o.Shape,q.Shape);r['retained_comparisons'][name]=result;check(result['matches'],'Retained reference '+name)
 params=doc.getObject('Parameters');oldparams=old.getObject('Parameters')
 r['datum_cells']={c:{'R6':str(oldparams.get(c)),'R7':str(params.get(c))}for c in ['B1','B2','B3','B7','B8','B44','B59','B78','B79']}
 check(all(x['R6']==x['R7']for x in r['datum_cells'].values()),'PCB/OLED/PTT datums changed')
 doc.recompute();r['recompute']={n:compare(s,doc.getObject(n).Shape)for n,s in shapes.items()}
 check(all(x['matches']for x in r['recompute'].values()),'Recompute changed printed geometry')
 imported=Part.read(str(step)).Solids;check(len(imported)==len(shapes),'STEP printable solid count')
 if len(imported)==len(shapes):
  nb={n:bounds(s)for n,s in shapes.items()};sb=[bounds(s)for s in imported]
  cost={(n,i):sum(abs(a-b)for a,b in zip(nb[n],sb[i]))+abs(s.Volume-imported[i].Volume)/max(s.Volume,1)for n,s in shapes.items()for i in range(len(imported))}
  assignment=min(itertools.permutations(range(len(imported))),key=lambda order:sum(cost[n,i]for n,i in zip(shapes,order)))
  for n,i in zip(shapes,assignment):
   result=compare(shapes[n],imported[i]);r['step'][n]=result;check(result['matches'],'STEP '+n)
 installed=[p['object']for p in plan['parts']if not p.get('optional')]
 r['installed_pair_intersections_mm3']={}
 for a,b in itertools.combinations(installed,2):
  v=abs(shapes[a].common(shapes[b]).Volume);r['installed_pair_intersections_mm3'][a+'__'+b]=v;check(v<1e-6,'Printed intersection '+a+'/'+b)
finally:
 A.closeDocument(doc.Name);A.closeDocument(old.Name)
r['sources_unchanged']={k:sha(p)==before[k]for k,p in files.items()};check(all(r['sources_unchanged'].values()),'Sources modified')
r['ok']=not r['failures']
(ROOT/'audit/saved-r7-validation.json').write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps({'ok':r['ok'],'failures':r['failures'],'electronics':r.get('unchanged_electronics')}))
if not r['ok']:raise SystemExit(1)
