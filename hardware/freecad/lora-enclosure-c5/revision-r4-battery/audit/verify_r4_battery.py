"""Read-only saved R4 battery-compartment validation; no CAD writes/exports."""
from pathlib import Path
import argparse,hashlib,json,math
import FreeCAD as A,Part

ap=argparse.ArgumentParser();ap.add_argument('--native',required=True);a=ap.parse_args()
out=Path(__file__).resolve().parent
native=Path(a.native).resolve()
source=out.parents[1]/'revision-r3-oled-gap/cad/LoRa-Enclosure-C5-R3-OLED.FCStd'
assembly=out.parents[1]/'detailed-import/C5-detailed-assembly.step'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
hashes={str(p):sha(p)for p in(native,source,assembly)}
report=dict(scope='Saved native mechanical verification, not physical battery/connector/USB fit qualification.',sources=hashes,failures=[])
def check(ok,msg):
 if not ok:report['failures'].append(msg)
def box(x0,x1,y0,y1,z0,z1):return Part.makeBox(x1-x0,y1-y0,z1-z0,A.Vector(x0,y0,z0))
def rounded(x0,x1,y0,y1,z0,z1,r):
 s=box(x0,x1,y0,y1,z0,z1)
 return s.makeFillet(r,[e for e in s.Edges if e.BoundBox.ZLength>z1-z0-1e-6])
def bb(s):
 b=s.optimalBoundingBox(False,False);return[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def info(s):return dict(valid=s.isValid(),closed=s.isClosed(),solids=len(s.Solids),volume_mm3=s.Volume,bounds_mm=bb(s))
def delta(s,t):return s.cut(t).Volume+t.cut(s).Volume
def capsule(x,y,w,l,z0,z1):
 r=w/2
 return box(x-r,x+r,y-l/2+r,y+l/2-r,z0,z1).fuse(Part.makeCylinder(r,z1-z0,A.Vector(x,y-l/2+r,z0))).fuse(Part.makeCylinder(r,z1-z0,A.Vector(x,y+l/2-r,z0)))
before=A.openDocument(str(source));after=A.openDocument(str(native))
names=('EnclosureBase','EnclosureLid','PTTPlunger','PTTStopCup','BatteryCover')
saved={n:after.getObject(n).Shape.copy()for n in names}
report['parts']={n:info(s)for n,s in saved.items()}
for n,s in saved.items():check(s.isValid()and s.isClosed()and len(s.Solids)==1,n+' invalid or not one closed solid')
old=before.getObject('EnclosureBase').Shape.copy()
report['unchanged_r3_parts']={n:delta(saved[n],before.getObject(n).Shape)for n in names if n not in('EnclosureBase','BatteryCover')}
check(all(v<1e-6 for v in report['unchanged_r3_parts'].values()),'R3 upper lid or PTT part changed')
centers=[(4,4),(66,4),(4,86),(66,86)]
tube=rounded(-4.4,74.4,-4.4,94.4,-14,.2,4.5).cut(rounded(-2,72,-2,92,-14.1,.3,2.1))
posts=[Part.makeCylinder(4,14.2,A.Vector(x,y,-14))for x,y in centers]
webs=[box(-2,4,y-1.2,y+1.2,-11,.2)if x==4 else box(66,72,y-1.2,y+1.2,-11,.2)for x,y in centers]
pilots=[Part.makeCylinder(2.2,4.6,A.Vector(x,y,-14.1))for x,y in centers]
hood=box(21,35,92,99.6,-14,11.1);chase=box(23.4,32.6,91.9,97.2,-14.1,13.2)
expect_body=old.fuse(Part.makeCompound([tube,hood]+posts+webs)).cut(Part.makeCompound(pilots+[chase])).removeSplitter()
plate=rounded(-4.4,74.4,-4.4,94.4,-16.4,-14,4.5)
lip=rounded(-1.6,71.6,-1.6,91.6,-14.2,-12.4,1.7).cut(rounded(-.4,70.4,-.4,90.4,-14.3,-12.3,.5))
guides=[rounded(x,x+2,y,y+14,-14.1,-11,.8)for x in(14,54)for y in(23,53)]
ends=[rounded(26,44,y,y+2,-14.1,-11,.8)for y in(8,80)]
slots=[capsule(x,y,2.4,12,-16.5,-13.8)for x in(12.2,57.8)for y in(30,60)]
channels=[box(12.2,57.8,y-6,y+6,-16.5,-15.4)for y in(30,60)]
holes=[Part.makeCylinder(1.7,3,A.Vector(x,y,-16.6))for x,y in centers]
tab=box(21,35,92,99.6,-16.4,-14);lip_route=box(23.4,32.6,90.3,94.5,-14,-12.3)
expect_cover=plate.fuse(Part.makeCompound([lip,tab]+guides+ends)).cut(Part.makeCompound(slots+channels+holes+[lip_route])).removeSplitter()
report['independent_rebuild']={'EnclosureBase':delta(saved['EnclosureBase'],expect_body),'BatteryCover':delta(saved['BatteryCover'],expect_cover)}
check(all(v<1e-5 for v in report['independent_rebuild'].values()),'Saved native differs from independently constructed battery revision')
removed_original=old.cut(saved['EnclosureBase'])
report['original_base_change']=dict(removed_volume_mm3=removed_original.Volume,removed_bounds_mm=bb(removed_original),removed_outside_intended_harness_chase_mm3=removed_original.cut(chase).Volume)
check(report['original_base_change']['removed_outside_intended_harness_chase_mm3']<1e-6,'Original base material removed outside local rear harness chase')
after.recompute();report['recompute']={n:delta(s,after.getObject(n).Shape)for n,s in saved.items()}
check(all(v<1e-6 for v in report['recompute'].values()),'Saved geometry changes on recompute')
p=after.getObject('Parameters');expected=[14,2.4,8,4.5,11.1,99.6,97.2,36,68,10,1,10,2.4]
report['parameters']={f'B{i}':dict(value=float(str(p.get(f'B{i}')).split()[0]),expected=v)for i,v in enumerate(expected,83)}
check(all(abs(x['value']-x['expected'])<1e-8 for x in report['parameters'].values()),'R4 parameter mismatch')
p.set('B83','15');after.recompute()
report['parameter_sensitivity']=dict(temporary_depth_mm=15,temporary_body_bounds_mm=bb(after.getObject('EnclosureBase').Shape),temporary_cover_bounds_mm=bb(after.getObject('BatteryCover').Shape),temporary_cell_bounds_mm=bb(after.getObject('ReferenceBatteryEnvelope').Shape))
check(abs(report['parameter_sensitivity']['temporary_body_bounds_mm'][2]+15)<1e-7 and abs(report['parameter_sensitivity']['temporary_cover_bounds_mm'][2]+17.4)<1e-7 and abs(report['parameter_sensitivity']['temporary_cell_bounds_mm'][2]+14)<1e-7,'Bay depth does not drive body/cover/cell geometry')
p.set('B83','14');after.recompute()
report['parameter_sensitivity']['restored_differences_mm3']={n:delta(s,after.getObject(n).Shape)for n,s in saved.items()}
check(all(v<1e-6 for v in report['parameter_sensitivity']['restored_differences_mm3'].values()),'Parameter sensitivity test failed to restore saved geometry')
body,cover=saved['EnclosureBase'],saved['BatteryCover'];cell=after.getObject('ReferenceBatteryEnvelope').Shape.copy()
check(delta(cell,box(17,53,11,79,-13,-3))<1e-6,'Reference battery envelope mismatch')
barrier_region=box(17,53,11,79,0,2.4);partition=body.common(barrier_region)
report['battery_fit']=dict(envelope=info(cell),body_distance_mm=body.distToShape(cell)[0],cover_distance_mm=cover.distToShape(cell)[0],body_intersection_mm3=body.common(cell).Volume,cover_intersection_mm3=cover.common(cell).Volume,body_cover_intersection_mm3=body.common(cover).Volume,partition_volume_mm3=partition.Volume,expected_partition_volume_mm3=barrier_region.Volume,partition_thickness_mm=2.4)
check(all(report['battery_fit'][k]<1e-6 for k in('body_intersection_mm3','cover_intersection_mm3','body_cover_intersection_mm3')),'Battery or cover interference')
check(abs(partition.Volume-barrier_region.Volume)<1e-5,'Battery separator is not continuous beneath pouch footprint')
report['rear_fasteners']=dict(centers_xy_mm=centers,screw='M3x6 buttonhead',nominal_engagement_mm=3.6,blind_pilot_depth_mm=4.5,screw_tip_z_mm=-10.4,pilot_top_z_mm=-9.5,tip_clearance_mm=.9,insert='M3 OD5 x length4',insert_unused_engagement_mm=.4)
shaft=Part.makeCompound([Part.makeCylinder(1.5,6,A.Vector(x,y,-16.4))for x,y in centers])
report['rear_fasteners']['shaft_battery_intersection_mm3']=shaft.common(cell).Volume
check(report['rear_fasteners']['shaft_battery_intersection_mm3']<1e-8,'Rear screw enters pouch volume')
route=json.loads((out/'rear-harness-predictive-report.json').read_text())
plug=box(*[route['plug_assumed_bounds_mm'][i]for i in(0,3,1,4,2,5)])
points=route['lead_centerline_mm'];wire_shapes=[]
for aa,bbp in zip(points,points[1:]):
 av,bv=A.Vector(*aa),A.Vector(*bbp);v=bv-av;wire_shapes.append(Part.makeCylinder(.8,v.Length,av,v))
for pt in points[1:-1]:wire_shapes.append(Part.makeSphere(.8,A.Vector(*pt)))
wire=Part.makeCompound(wire_shapes)
report['provisional_harness']={k:route[k]for k in('plug_assumed_bounds_mm','lead_centerline_mm','lead_radius_mm','lead_nominal_polyline_length_mm','lead_assumptions','usb_limitation','plug_usb_access_envelope_overlap_mm3','wire_usb_access_envelope_overlap_mm3')}
report['provisional_harness'].update(plug_body_intersection_mm3=body.common(plug).Volume,wire_body_intersection_mm3=body.common(wire).Volume,plug_cover_intersection_mm3=cover.common(plug).Volume,wire_cover_intersection_mm3=cover.common(wire).Volume)
check(all(report['provisional_harness'][k]<1e-6 for k in('plug_body_intersection_mm3','wire_body_intersection_mm3','plug_cover_intersection_mm3','wire_cover_intersection_mm3')),'Provisional plug/wire intersects printed parts')
ref=A.newDocument('SavedR4ReferenceReadOnly');Part.insert(str(assembly),ref.Name)
objs=[o for o in ref.Objects if hasattr(o,'Shape')and not o.Shape.isNull()]
check(len(objs)==2949,'Corrected electronic source mapping changed')
added=body.cut(old);checks=[];min_z=100
for i,o in enumerate(objs):
 s=o.Shape.copy();s.translate(A.Vector(0,0,6.4814));b=s.BoundBox;min_z=min(min_z,b.ZMin)
 if b.YMax<90 or b.YMin>100 or b.XMin>36 or b.XMax<20 or b.ZMin>14 or b.ZMax<0:continue
 checks.append(dict(index=i,added_material_intersection_mm3=added.common(s).Volume,plug_intersection_mm3=plug.common(s).Volume,wire_intersection_mm3=wire.common(s).Volume,added_minimum_distance_mm=added.distToShape(s)[0]))
report['actual_electronics']=dict(nearby_checks=checks,lowest_component_z_mm=min_z,pouch_top_to_lowest_component_mm=min_z+3,new_material_basis='All new material aboveZ0.2 is confined to local rear chimney; all other addition below unchanged original floor. Bounding candidates checked exactly.',new_interference_mm3=sum(x['added_material_intersection_mm3']for x in checks),plug_interference_mm3=sum(x['plug_intersection_mm3']for x in checks),wire_interference_mm3=sum(x['wire_intersection_mm3']for x in checks))
check(all(report['actual_electronics'][k]<1e-6 for k in('new_interference_mm3','plug_interference_mm3','wire_interference_mm3')),'New geometry or provisional harness intersects actual component models')
report['source_files_unchanged']={path:sha(Path(path))==h for path,h in hashes.items()}
check(all(report['source_files_unchanged'].values()),'Read-only audit modified a source')
report['limitations']=['Pouch dimensions from user photo with conservative36mm width; actual maximum packaging thickness and seal/cable details unmeasured.','Provisional plug/harness geometry is not vendor mating CAD. Connector polarity, family, cablebend and USB-overmould simultaneous fit remain unqualified.','Battery storage and Heltec connection only; no claim that carrier5V amplifier rail works frombattery.','No thermal, abuse, impact or physical qualification is established by CAD checks.']
report['ok']=not report['failures'];report['native_geometry_ok']=report['ok'];report['hardware_fit_qualified']=False;report['release_fit_qualified']=False
(out/'r4-battery-fit-validation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
for doc in(before,after,ref):A.closeDocument(doc.Name)
print(json.dumps({k:v for k,v in report.items()if k not in('actual_electronics','provisional_harness','sources','parts')},indent=2))
if not report['ok']:raise SystemExit(1)
