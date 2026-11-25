"""Independent in-memory R5 preflight. Never saves or exports native CAD."""
from pathlib import Path
import json,hashlib,time
import FreeCAD as A,Part
OUT=Path(__file__).resolve().parent;ENC=OUT.parents[1]
NATIVE=ENC/'revision-r4-battery/cad/LoRa-Enclosure-C5-R4-Battery.FCStd'
STEP=ENC/'detailed-import/C5-detailed-assembly.step'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
sources={str(p):sha(p)for p in(NATIVE,STEP)};start=time.time()
def log(s):print(f'[{time.time()-start:.1f}s] {s}',flush=True)
def bb(s):
 b=s.optimalBoundingBox(False,False);return[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def info(s):return {'valid':s.isValid(),'closed':s.isClosed(),'solids':len(s.Solids),'volume_mm3':s.Volume,'bounds_mm':bb(s)}
def box(x0,y0,z0,x1,y1,z1):return Part.makeBox(x1-x0,y1-y0,z1-z0,A.Vector(x0,y0,z0))
def cyl(r,y,h):return Part.makeCylinder(r,h,A.Vector(47,y,14),A.Vector(0,1,0))
def pair(a,b):return {'intersection_mm3':a.common(b).Volume,'distance_mm':a.distToShape(b)[0]}
def delta(a,b):return a.cut(b).Volume+b.cut(a).Volume
d=A.openDocument(str(NATIVE));log('Opened R4 native read-only')
original={n:d.getObject(n).Shape.copy()for n in('EnclosureBase','EnclosureLid','PTTPlunger','PTTStopCup','BatteryCover','ReferenceBatteryEnvelope')}
changes=[]
for name in('BaseCutters','LidCutters'):
 o=d.getObject(name);before=list(o.Shapes);after=[x for x in before if x.Name!='AntennaPassage'];assert len(after)==len(before)-1,(name,[x.Name for x in before])
 o.Shapes=after;changes.append({'name':name,'before':[x.Name for x in before],'after':[x.Name for x in after]})
d.recompute();healed_base=d.getObject('EnclosureBase').Shape.copy();lid=d.getObject('EnclosureLid').Shape.copy()
blank=box(38,89,9.2,56,92.2,19.0);backing=blank.makeFillet(.6,blank.Edges)
blank=box(55,84,14,61.5,92.2,18);anchor=blank.makeFillet(.6,blank.Edges)
blank=box(54.9,85.8,15.2,61.6,88.8,16.7);slot=blank.makeFillet(.4,blank.Edges)
relief=cyl(5.6,88.8,3.2);bore=cyl(3.3,88.5,7)
base=healed_base.fuse(backing).fuse(anchor).cut(Part.makeCompound([relief,bore,slot])).removeSplitter()
log('Built in-memory revised base and healed lid')
cover=original['BatteryCover'];battery=original['ReferenceBatteryEnvelope']
new_material=base.cut(original['EnclosureBase']);new_lid_material=lid.cut(original['EnclosureLid'])
oled_roi=box(8,38,16,39,76,26)
report={'sources':sources,'source_modified_in_memory_only':True,'cutter_changes':changes,'parts':{'EnclosureBase':info(base),'EnclosureLid':info(lid)},'failures':[],
 'local_features':{'backing':info(backing),'anchor':info(anchor),'slot':info(slot),'relief':info(relief),'bore':info(bore)},
 'pairs':{'base_lid':pair(base,lid),'base_cover':pair(base,cover),'base_battery':pair(base,battery),'lid_battery':pair(lid,battery),'base_ptt_cup':pair(base,original['PTTStopCup']),'base_plunger':pair(base,original['PTTPlunger'])},
 'original_pairs':{'base_battery':pair(original['EnclosureBase'],battery),'cover_battery':pair(cover,battery)},
 'unchanged_region':{'oled_lid_roi_difference_mm3':delta(lid.common(oled_roi),original['EnclosureLid'].common(oled_roi))},
 'material_changes':{'base_added_volume_mm3':new_material.Volume,'base_removed_volume_mm3':original['EnclosureBase'].cut(base).Volume,'lid_added_volume_mm3':new_lid_material.Volume,'lid_removed_volume_mm3':original['EnclosureLid'].cut(lid).Volume},
 'battery_dimensions_mm':{'envelope':[68,36,10],'above':3.0,'pad_allowance':1.0},'oled_vertical_datum_gap_mm':.5012807412}
for n,s in [('base',base),('lid',lid)]:
 if not(s.isValid()and s.isClosed()and len(s.Solids)==1):report['failures'].append(n+' invalid/nonclosed/multiple solids')
for n,p in report['pairs'].items():
 if p['intersection_mm3']>1e-6:report['failures'].append(n+' intersects')
if report['unchanged_region']['oled_lid_roi_difference_mm3']>1e-7:report['failures'].append('OLED region changed')
if abs(report['pairs']['base_battery']['distance_mm']-report['original_pairs']['base_battery']['distance_mm'])>1e-7:report['failures'].append('Battery base clearance changed')
# The body/shaft envelopes are conservative reference checks, not kit CAD.
rear=cyl(5,82,10);stud=cyl(3.175,92,10)
report['reference_connector']={'rear_bounds_mm':bb(rear),'rear_to_lid':pair(rear,lid),'rear_to_base':pair(rear,base),'stud_to_base':pair(stud,base),'radial_bore_clearance_mm':.125}
ref=A.newDocument('SMAFinalPlanReadOnly');Part.insert(str(STEP),ref.Name)
objs=[o for o in ref.Objects if hasattr(o,'Shape')and not o.Shape.isNull()];assert len(objs)==2949
hits=[];nearest_added=[];nearest_rear=[];glass_candidates=[]
basebb=base.BoundBox
for i,o in enumerate(objs):
 s=o.Shape.copy();s.translate(A.Vector(0,0,6.4814));b=s.BoundBox
 # No new material is outside these two localized rear-end regions.
 if b.XMax<36 or b.XMin>64 or b.YMax<81 or b.YMin>96 or b.ZMax<8 or b.ZMin>25:continue
 va=new_material.common(s).Volume;vl=new_lid_material.common(s).Volume;vb=base.common(s).Volume;vll=lid.common(s).Volume
 nearest_added.append((new_material.distToShape(s)[0],i));nearest_rear.append((rear.distToShape(s)[0],i))
 if va+vl+vb+vll>1e-6:hits.append({'i':i,'new_base_added_intersection_mm3':va,'healed_lid_added_intersection_mm3':vl,'final_base_intersection_mm3':vb,'final_lid_intersection_mm3':vll,'bounds':bb(s)})
report['electronics_rear_region']={'assigned_source_objects':len(objs),'checked_candidates':len(nearest_added),'hits':hits,'nearest_new_material':sorted(nearest_added)[:8],'nearest_rear_envelope':sorted(nearest_rear)[:8]}
if hits:report['failures'].append('Rear geometry intersects actual electronic models')
log('Exact actual-component rear-region checks complete')
# Export display-only tessellation JSON for parent documentation; not manufacturing output.
display=[]
for name,shape in [('base',base),('lid',lid),('cover',cover),('battery',battery),('mount_backing',backing.cut(relief)),('tie_anchor',anchor.cut(slot))]:
 vs,fs=shape.tessellate(.1);display.append({'id':name,'positions':[[round(v.x,5),round(v.y,5),round(v.z,5)]for v in vs],'triangles':fs,'bounds_mm':bb(shape)})
(OUT/'final-plan-display-meshes.json').write_text(json.dumps({'units':'mm','scope':'display-only derived preflight geometry; native CAD untouched','parts':display},separators=(',',':')))
report['source_files_unchanged']={p:sha(Path(p))==h for p,h in sources.items()}
if not all(report['source_files_unchanged'].values()):report['failures'].append('Source file changed')
report['ok']=not report['failures'];report['hardware_fit_qualified']=False
report['limitations']=['Connector dimensions are provisional; kit mounting geometry is unmeasured.','Rear-region exact checks cover all newly added material; untouched original regions inherit R4 validation.','The 169mm cable route and bending/slack are not physically validated.']
(OUT/'final-plan-validation.json').write_text(json.dumps(report,indent=2))
A.closeDocument(ref.Name);A.closeDocument(d.Name)
print(json.dumps({k:v for k,v in report.items()if k not in('cutter_changes','sources','local_features')},indent=2),flush=True)
if not report['ok']:raise SystemExit(1)
