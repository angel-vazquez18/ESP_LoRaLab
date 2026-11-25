"""Read-only native/fit/export audit after the R5 files have been approved.

Run with FreeCAD's bundled Python. Use --native-only before exports exist.
No native documents or manufacturing files are saved or exported by this audit.
"""
from pathlib import Path
from collections import Counter
import argparse,hashlib,importlib.util,itertools,json,math,sys,time
import FreeCAD as A,Part

ROOT=Path(__file__).resolve().parents[1];ENC=ROOT.parent;OUT=ROOT/'audit'
P=argparse.ArgumentParser();P.add_argument('--native-only',action='store_true');P.add_argument('--native',default=str(ROOT/'cad/LoRa-Enclosure-C5-R5-SMA.FCStd'));ARGS=P.parse_args()
NATIVE=Path(ARGS.native);OLD=ENC/'revision-r4-battery/cad/LoRa-Enclosure-C5-R4-Battery.FCStd';ASSEMBLY=ENC/'detailed-import/C5-detailed-assembly.step'
STEMS={'EnclosureBase':'enclosure-base','EnclosureLid':'enclosure-lid','PTTPlunger':'ptt-plunger','PTTStopCup':'ptt-stop-cup','BatteryCover':'battery-cover'}
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();start=time.time()
def log(s):print(f'[{time.time()-start:.1f}s] {s}',flush=True)
def load_module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def bb(s):
 b=s.optimalBoundingBox(False,False);return[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def broad_bb(s):
 b=s.BoundBox;return[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def overlaps(a,b):return all(a[i]<=b[i+3]+1e-7 and a[i+3]+1e-7>=b[i]for i in range(3))
def lower_bound(a,b):return math.sqrt(sum(max(a[i]-b[i+3],b[i]-a[i+3],0)**2 for i in range(3)))
def info(s):return {'valid':s.isValid(),'closed':s.isClosed(),'solids':len(s.Solids),'volume_mm3':s.Volume,'bounds_mm':bb(s)}
def compare(a,b):
 sym=a.cut(b).Volume+b.cut(a).Volume;bd=max(abs(x-y)for x,y in zip(bb(a),bb(b)))
 return {'symmetric_difference_mm3':sym,'bounds_difference_mm':bd,'volume_difference_mm3':abs(a.Volume-b.Volume),'matches':sym<1e-5 and bd<1e-6}
def box(x0,y0,z0,x1,y1,z1):return Part.makeBox(x1-x0,y1-y0,z1-z0,A.Vector(x0,y0,z0))
def cyl(r,y,h):return Part.makeCylinder(r,h,A.Vector(47,y,14),A.Vector(0,1,0))
def pair(a,b):return {'intersection_mm3':a.common(b).Volume,'distance_mm':a.distToShape(b)[0]}
def minimum(shape,components):
 sb=broad_bb(shape);ordered=sorted((lower_bound(sb,b),i,s)for i,s,b in components)
 best=float('inf');records=[];closest=None
 for lower,i,s in ordered:
  if lower>best+1e-7:break
  actual=shape.distToShape(s)[0];records.append({'index':i,'aabb_lower_bound_mm':lower,'exact_distance_mm':actual})
  if actual<best:best=actual;closest=i
 return {'minimum_mm':best,'component_index':closest,'aabb_lower_bounds_evaluated':len(components),'exact_distance_checks':records,'method':'All conservative AABB distance lower bounds sorted; exact distance evaluated until remaining lower bounds exceed best distance.'}
def no_interference(shape,components):
 sb=broad_bb(shape);hits=[];exact=[]
 for i,s,b in components:
  if not overlaps(sb,b):continue
  volume=shape.common(s).Volume;exact.append({'index':i,'intersection_mm3':volume})
  if volume>1e-6:hits.append({'index':i,'intersection_mm3':volume})
 return {'source_objects_scanned':len(components),'aabb_disjoint_count':len(components)-len(exact),'exact_boolean_count':len(exact),'exact_boolean_checks':exact,'hits':hits,'ok':not hits,'method':'Conservative bounding boxes reject disjoint shapes; all overlapping candidates use exact Boolean intersection.'}

files={'native':NATIVE,'r4_native':OLD,'actual_component_step':ASSEMBLY,'preflight_report':OUT/'final-plan-validation.json'}
if not ARGS.native_only:
 files['step']=ROOT/'cad/LoRa-Enclosure-C5-R5-SMA.step'
 for n,stem in STEMS.items():
  for ext in('stl','3mf'):files[n+'.'+ext]=ROOT/f'printing/C5-R5-{stem}-mm.{ext}'
missing=[str(p)for p in files.values()if not p.is_file()]
if missing:raise SystemExit('Wait for approved files before audit: '+', '.join(missing))
initial={k:sha(v)for k,v in files.items()};report={'scope':'Saved R5 native/fit comparison'+(' only'if ARGS.native_only else' plus STEP and five STL/3MF pairs'),'files':{k:{'path':str(v),'sha256':initial[k],'bytes':v.stat().st_size}for k,v in files.items()},'failures':[]};docs=[]
def check(ok,why):
 if not ok:report['failures'].append(why)
try:
 before=A.openDocument(str(OLD));docs.append(before);after=A.openDocument(str(NATIVE));docs.append(after)
 old={n:before.getObject(n).Shape.copy()for n in STEMS};saved={n:after.getObject(n).Shape.copy()for n in STEMS}
 # Independent exact construction of the reviewed plan from the released R4.
 for name in('BaseCutters','LidCutters'):
  o=before.getObject(name);o.Shapes=[v for v in o.Shapes if v.Name!='AntennaPassage']
 before.recompute()
 blank=box(38,89,9.2,56,92.2,19);backing=blank.makeFillet(.6,blank.Edges)
 blank=box(55,84,14,61.5,92.2,18);anchor=blank.makeFillet(.6,blank.Edges)
 blank=box(54.9,85.8,15.2,61.6,88.8,16.7);slot=blank.makeFillet(.4,blank.Edges)
 relief=cyl(5.6,88.8,3.2);bore=cyl(3.3,88.5,7)
 expected_base=before.getObject('EnclosureBase').Shape.fuse(backing).fuse(anchor).cut(Part.makeCompound([relief,bore,slot])).removeSplitter()
 expected_lid=before.getObject('EnclosureLid').Shape.copy()
 report['native_parts']={n:info(s)for n,s in saved.items()}
 check(all(r['valid']and r['closed']and r['solids']==1 for r in report['native_parts'].values()),'One or more native printables are invalid/nonclosed/not one solid')
 report['independent_plan_comparison']={'EnclosureBase':compare(saved['EnclosureBase'],expected_base),'EnclosureLid':compare(saved['EnclosureLid'],expected_lid)}
 check(all(v['matches']for v in report['independent_plan_comparison'].values()),'Saved geometry differs from the independently reconstructed plan')
 report['unchanged_parts']={n:compare(old[n],saved[n])for n in('PTTPlunger','PTTStopCup','BatteryCover')}
 check(all(v['matches']for v in report['unchanged_parts'].values()),'A retained R4 part changed')
 battery=before.getObject('ReferenceBatteryEnvelope').Shape.copy();saved_battery=after.getObject('ReferenceBatteryEnvelope').Shape.copy()
 report['battery_reference_comparison']=compare(battery,saved_battery);check(report['battery_reference_comparison']['matches'],'Battery reference changed')
 report['assembly_pairs']={a+'__'+b:pair(saved[a],saved[b])for a,b in itertools.combinations(STEMS,2)}
 check(all(v['intersection_mm3']<1e-6 for v in report['assembly_pairs'].values()),'Printed parts interfere')
 report['battery_fit']={'base':pair(saved['EnclosureBase'],battery),'cover':pair(saved['BatteryCover'],battery),'partition_difference_mm3':compare(old['EnclosureBase'].common(box(17,11,0,53,79,2.4)),saved['EnclosureBase'].common(box(17,11,0,53,79,2.4)))['symmetric_difference_mm3']}
 check(abs(report['battery_fit']['base']['distance_mm']-3)<1e-6 and abs(report['battery_fit']['cover']['distance_mm']-1)<1e-6 and report['battery_fit']['partition_difference_mm3']<1e-6,'Battery clearances or separator changed')
 region=box(8,38,16,39,76,26)
 report['oled_fit']={'lid_roi_comparison':compare(old['EnclosureLid'].common(region),saved['EnclosureLid'].common(region)),'glass_top_z_mm':19.9987192588,'rim_underside_z_mm':20.5,'vertical_datum_gap_mm':.5012807412,'meaning':'Vertical datum offset across open aperture; not minimum glass-to-solid distance.'}
 check(report['oled_fit']['lid_roi_comparison']['matches'],'OLED lid region changed')
 report['native_links']={name:[o.Name for o in after.getObject(name).Shapes]for name in('BaseWithSupports','BaseCutters','LidCutters')}
 check(all('AntennaPassage'not in report['native_links'][n]for n in('BaseCutters','LidCutters')),'Old split coax cutter remains linked')
 after.recompute();report['recompute']={n:compare(s,after.getObject(n).Shape)for n,s in saved.items()};check(all(v['matches']for v in report['recompute'].values()),'Saved native changes on recompute')
 log('Saved native matches reviewed construction; importing component reference')
 ref=A.newDocument('R5SavedElectronicsAudit');docs.append(ref);Part.insert(str(ASSEMBLY),ref.Name)
 objects=[o for o in ref.Objects if hasattr(o,'Shape')and not o.Shape.isNull()];check(len(objects)==2949,'Actual component mapping changed')
 components=[]
 for i,o in enumerate(objects):
  s=o.Shape.copy();s.translate(A.Vector(0,0,6.4814));components.append((i,s,broad_bb(s)))
 added=saved['EnclosureBase'].cut(old['EnclosureBase']);lid_added=saved['EnclosureLid'].cut(old['EnclosureLid']);rear=cyl(5,82,10)
 report['actual_electronics']={'source_objects':len(objects),'new_base_material':no_interference(added,components),'healed_lid_material':no_interference(lid_added,components),'new_base_material_clearance':minimum(added,components),'reference_connector_rear_clearance':minimum(rear,components),'reference_rear_to_lid':pair(rear,saved['EnclosureLid'])}
 check(report['actual_electronics']['new_base_material']['ok']and report['actual_electronics']['healed_lid_material']['ok'],'New material intersects actual components')
 log('Electronics broad-phase and exact minimum-distance checks complete')
 if not ARGS.native_only:
  helpers=load_module('r4_mesh_export_helpers',ENC/'revision-r4-battery/audit/validate_r4_exports.py')
  validator=load_module('fit_mesh_validator',ENC/'fit-checked/verify_exports.py')
  helpers.FILES={n:files[n]for n in files if n.endswith(('.stl','.3mf'))}
  solids=Part.read(str(files['step'])).Solids;report['step_solid_count']=len(solids);check(len(solids)==5,'STEP must have five printed solids')
  report['step_parts']={}
  if len(solids)==5:
   bounds={n:bb(s)for n,s in saved.items()};sb=[bb(s)for s in solids]
   pairing=min(itertools.permutations(range(5)),key=lambda order:sum(sum(abs(a-b)for a,b in zip(bounds[n],sb[i]))+abs(saved[n].Volume-solids[i].Volume)/saved[n].Volume for n,i in zip(STEMS,order)))
   for n,i in zip(STEMS,pairing):report['step_parts'][n]={'index':i,'info':info(solids[i]),'comparison':compare(saved[n],solids[i])}
   check(all(r['comparison']['matches']and r['info']['valid']and r['info']['closed']and r['info']['solids']==1 for r in report['step_parts'].values()),'STEP differs from native')
  r4_report=json.loads((ENC/'revision-r4-battery/audit/r4-export-validation.json').read_text());report['mesh_pairs']={};report['reused_file_provenance']={}
  for n,stem in STEMS.items():
   translation=r4_report['meshes'][n]['translation_from_print_to_assembly_mm']if n in('PTTPlunger','PTTStopCup')else[0,0,0]
   report['mesh_pairs'][n]=helpers.check_mesh_pair(n,saved[n],validator,translation);check(report['mesh_pairs'][n]['ok'],'STL/3MF validation failed: '+n)
   if n in('PTTPlunger','PTTStopCup','BatteryCover'):
    report['reused_file_provenance'][n]={ext:{'source':str(ENC/f'revision-r4-battery/printing/C5-R4-{stem}-mm.{ext}'),'same_hash':sha(files[n+'.'+ext])==sha(ENC/f'revision-r4-battery/printing/C5-R4-{stem}-mm.{ext}')}for ext in('stl','3mf')}
    check(all(r['same_hash']for r in report['reused_file_provenance'][n].values()),'Retained export not exact R4 copy: '+n)
  log('STEP and STL/3MF validation complete')
except Exception as exc:
 report['failures'].append(type(exc).__name__+': '+str(exc));raise
finally:
 for doc in reversed(docs):A.closeDocument(doc.Name)
 report['source_files_unchanged']={k:sha(p)==initial[k]for k,p in files.items()};check(all(report['source_files_unchanged'].values()),'An input file changed during audit')
 report['hardware_fit_qualified']=False;report['ok']=not report['failures'];report['limitations']=['Owned bulkhead mounting dimensions/panel nut torque remain unmeasured.','Connector rear volume is an explicit provisional Ø10×10mm envelope.','169mm coax routing and electrical/RF performance are not qualified.','Mesh topology/bounds/volume checks do not prove physical print strength or self-intersection absence.']
 destination=OUT/('r5-native-fit-validation.json'if ARGS.native_only else'r5-export-validation.json');destination.write_text(json.dumps(report,indent=2))
 print(json.dumps({'ok':report['ok'],'failures':report['failures'],'report':str(destination),'clearances':report.get('actual_electronics',{})},indent=2),flush=True)
if not report['ok']:raise SystemExit(1)
