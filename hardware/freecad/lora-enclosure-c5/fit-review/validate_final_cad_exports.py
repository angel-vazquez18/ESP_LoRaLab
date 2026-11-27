import json,math,pathlib,time,hashlib,itertools
import FreeCAD as App
import Part
ROOT=pathlib.Path(r'C:\Users\Homar\Documents\ChatGPT\LoRa-Walkie-Talkies\output\enclosure-c5')
OUT=ROOT/'fit-checked'
CAD=OUT/'LoRa-Enclosure-C5-Fit-Checked.FCStd'
STEP=OUT/'LoRa-Enclosure-C5-Fit-Checked.step'
START=time.time()
def log(s):print(f'[{time.time()-START:.1f}s] {s}',flush=True)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def bbox(s):
 b=s.BoundBox
 return [b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def shape_info(s):return {'valid':s.isValid(),'closed':s.isClosed(),'solid_count':len(s.Solids),'solids_closed':[so.isClosed() for so in s.Solids],'bbox_mm':bbox(s),'volume_mm3':s.Volume,'faces':len(s.Faces)}
def cyl(r,z0,z1,x=51,y=9):return Part.makeCylinder(r,z1-z0,App.Vector(x,y,z0))
def cup_reference():
 s=cyl(8.3,20.15,24)
 for x in [42,60]:s=s.fuse(cyl(3,20.15,24,x=x))
 s=s.cut(cyl(6.6,22.15,24.1)).cut(cyl(2.6,19,25))
 for x in [42,60]:s=s.cut(cyl(1.2,19,31,x=x))
 return s.removeSplitter()
def compare(a,b):
 bd=max(abs(x-y) for x,y in zip(bbox(a),bbox(b)))
 vd=abs(a.Volume-b.Volume)
 ab=a.cut(b).Volume;ba=b.cut(a).Volume
 return {'max_absolute_bbox_difference_mm':bd,'absolute_volume_difference_mm3':vd,'a_minus_b_volume_mm3':ab,'b_minus_a_volume_mm3':ba,'symmetric_difference_volume_mm3':ab+ba,'matches':bd<1e-6 and vd<1e-5 and ab+ba<1e-5}
def placement_info(p):return {'base_mm':[p.Base.x,p.Base.y,p.Base.z],'rotation_xyzw':list(p.Rotation.Q)}
log('Reading saved final FCStd')
cad_hash=sha(CAD);step_hash=sha(STEP)
doc=App.openDocument(str(CAD))
names=['EnclosureBase','EnclosureLid','PTTPlunger','PTTStopCup']
saved={n:doc.getObject(n).Shape.copy() for n in names}
native={n:{**shape_info(s),'object_type':doc.getObject(n).TypeId,'placement':placement_info(doc.getObject(n).Placement),'global_placement':placement_info(doc.getObject(n).getGlobalPlacement()),'state':list(doc.getObject(n).State)} for n,s in saved.items()}
expected_params={'B59':.25,'B67':22.15,'B68':20.15,'B69':3.85}
params={}
for cell,expected in expected_params.items():
 raw=doc.getObject('Parameters').get(cell);val=float(str(raw).split()[0])
 params[cell]={'computed_value':val,'expected':expected,'matches':abs(val-expected)<1e-8,'stored_contents':doc.getObject('Parameters').getContents(cell)}
log('Comparing native saved geometry against independent audited construction')
old=App.openDocument(str(ROOT/'LoRa-Enclosure-C5.FCStd'))
reference={n:old.getObject(n).Shape.copy() for n in names[:3]}
for x in [42,60]:reference['EnclosureLid']=reference['EnclosureLid'].cut(cyl(1.2,19,31,x=x))
reference['EnclosureLid']=reference['EnclosureLid'].removeSplitter();reference['PTTStopCup']=cup_reference()
audited={n:{'reference':shape_info(reference[n]),'saved_vs_reference':compare(saved[n],reference[n])} for n in names}
log('Reading saved STEP and pairing its solids with native final parts')
step=Part.read(str(STEP));solids=step.Solids
stepmatches=[]
if len(solids)==4:
 def score(order):return sum(sum(abs(x-y) for x,y in zip(bbox(saved[n]),bbox(solids[i])))+abs(saved[n].Volume-solids[i].Volume)/saved[n].Volume for n,i in zip(names,order))
 best=min(itertools.permutations(range(4)),key=score)
 for n,i in zip(names,best):stepmatches.append({'native_part':n,'step_solid_index':i,'step_geometry':shape_info(solids[i]),'native_vs_step':compare(saved[n],solids[i])})
log('Checking in-memory recompute preserves saved final geometry')
recompute_result=doc.recompute()
recomputed={n:compare(saved[n],doc.getObject(n).Shape) for n in names}
passed=all(x['valid'] and x['closed'] and x['solid_count']==1 and all(x['solids_closed']) for x in native.values()) and all(x['matches'] for x in params.values()) and all(x['saved_vs_reference']['matches'] for x in audited.values()) and len(solids)==4 and all(x['step_geometry']['valid'] and x['step_geometry']['closed'] and x['native_vs_step']['matches'] for x in stepmatches) and all(x['matches'] for x in recomputed.values())
report={'ok':passed,'case_file':str(CAD),'case_sha256':cad_hash,'step_file':str(STEP),'step_sha256':step_hash,'reference_original_case_sha256':sha(ROOT/'LoRa-Enclosure-C5.FCStd'),'verification_scope':'Headless read-only disk verification of four saved assembled printable parts, independent audited geometry, computed parameters, STEP solids, and in-memory recompute stability.','tolerances':{'bbox_mm':1e-6,'volume_mm3':1e-5,'parameter_absolute':1e-8},'native_parts':native,'parameters':params,'audited_geometry_comparisons':audited,'step_container':shape_info(step),'step_matches':stepmatches,'in_memory_recompute_result':recompute_result,'in_memory_recompute_comparisons':recomputed,'source_files_unchanged':{'fcstd':sha(CAD)==cad_hash,'step':sha(STEP)==step_hash},'limits':['This verifies printable CAD exports. The earlier actual-electronics interference audit is reused because no geometric discrepancy was detected.','Hardware models are references, not printable STEP solids. Physical switch actuation and print strength are not established by export validation.'],'elapsed_seconds':time.time()-START}
report['ok']=report['ok'] and all(report['source_files_unchanged'].values())
path=OUT/'final-cad-export-validation.json';path.write_text(json.dumps(report,indent=2),encoding='utf-8')
log('Validation '+('PASSED' if report['ok'] else 'FAILED')+'; wrote '+str(path))
print(json.dumps({'ok':report['ok'],'native':{n:shape_info(s) for n,s in saved.items()},'parameters':params,'step_solids':len(solids),'step_comparisons':[{k:v for k,v in x.items() if k!='step_geometry'} for x in stepmatches]},indent=2))
