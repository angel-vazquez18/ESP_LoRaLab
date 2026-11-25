"""Read-only predictive rear battery bay. No CAD save/export is performed."""
from pathlib import Path
import json, hashlib
import FreeCAD as A
import Part

out=Path(__file__).resolve().parent
src=out.parents[1]/'revision-r3-oled-gap/cad/LoRa-Enclosure-C5-R3-OLED.FCStd'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
before=sha(src)
d=A.openDocument(str(src))
old=d.getObject('EnclosureBase').Shape
def box(x0,x1,y0,y1,z0,z1):return Part.makeBox(x1-x0,y1-y0,z1-z0,A.Vector(x0,y0,z0))
def rounded(x0,x1,y0,y1,z0,z1,r):
 s=box(x0,x1,y0,y1,z0,z1)
 edges=[e for e in s.Edges if e.BoundBox.ZLength>z1-z0-1e-6]
 return s.makeFillet(r,edges)
def bb(s):
 b=s.optimalBoundingBox(False,False)
 return[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def info(s):return dict(valid=s.isValid(),closed=s.isClosed(),solids=len(s.Solids),volume_mm3=s.Volume,bounds_mm=bb(s))
def capsule(x,y,w,l,z0,z1):
 r=w/2
 return box(x-r,x+r,y-l/2+r,y+l/2-r,z0,z1).fuse(Part.makeCylinder(r,z1-z0,A.Vector(x,y-l/2+r,z0))).fuse(Part.makeCylinder(r,z1-z0,A.Vector(x,y+l/2-r,z0)))
outer=rounded(-4.4,74.4,-4.4,94.4,-14,.2,4.5)
cavity=rounded(-2,72,-2,92,-14.1,.3,2.1)
tube=outer.cut(cavity)
centers=[(4,4),(66,4),(4,86),(66,86)]
posts=[Part.makeCylinder(4,14.2,A.Vector(x,y,-14))for x,y in centers]
webs=[box(-2,4,y-1.2,y+1.2,-11,.2)if x==4 else box(66,72,y-1.2,y+1.2,-11,.2)for x,y in centers]
pilot=[Part.makeCylinder(2.2,4.6,A.Vector(x,y,-14.1))for x,y in centers]
body=old.fuse(Part.makeCompound([tube]+posts+webs)).cut(Part.makeCompound(pilot)).removeSplitter()
cover=rounded(-4.4,74.4,-4.4,94.4,-16.4,-14,4.5)
lip=rounded(-1.6,71.6,-1.6,91.6,-14.2,-12.4,1.7).cut(rounded(-.4,70.4,-.4,90.4,-14.3,-12.3,.5))
guides=[rounded(x,x+2,y,y+14,-14.1,-11,.8)for x in(14,54)for y in(23,53)]
endstops=[rounded(26,44,y,y+2,-14.1,-11,.8)for y in(8,80)]
slots=[capsule(x,y,2.4,12,-16.5,-13.8)for x in(12.2,57.8)for y in(30,60)]
channels=[box(12.2,57.8,y-6,y+6,-16.5,-15.4)for y in(30,60)]
holes=[Part.makeCylinder(1.7,3,A.Vector(x,y,-16.6))for x,y in centers]
cover=cover.fuse(Part.makeCompound([lip]+guides+endstops)).cut(Part.makeCompound(slots+channels+holes)).removeSplitter()
cell=box(17,53,11,79,-13,-3)
report={'scope':'Predictive enclosure-only bay; does not claim verified connector or cable route.',
 'source':str(src),'source_sha256':before,'new_base':info(body),'rear_cover':info(cover),
 'battery_envelope':info(cell),'body_to_battery_mm':body.distToShape(cell)[0],
 'cover_to_battery_mm':cover.distToShape(cell)[0],
 'body_battery_intersection_mm3':body.common(cell).Volume,'cover_battery_intersection_mm3':cover.common(cell).Volume,
 'body_cover_intersection_mm3':body.common(cover).Volume,
 'existing_base_lost_mm3':old.cut(body).Volume,
 'original_electronics_partition_mm':2.4,'bay_ceiling_z':0,'cover_inner_face_z':-14,
 'pouch_nominal_lower_air_mm':1,'pouch_nominal_upper_air_mm':3,
 'case_outer_height_mm':41,'rear_fastener_centers_mm':centers,
 'rear_insert_pilot':{'diameter_mm':4.4,'depth_mm':4.5,'blind_top_z':-9.5,'nominal_insert':'M3 OD5 x length4, same RX-M3x5x4 family as original'},
 'rear_screw':'Four M3x6 buttonhead;3.6mm nominal engagement after2.4mm cover; tipZ-10.4 stays0.9mm below blind-pilot topZ-9.5, outside pouch footprint.',
 'strap_slot_centers_mm':[(x,y)for x in(12.2,57.8)for y in(30,60)],
 'strap_slot_size_mm':[2.4,12],'strap_channels_depth_mm':1,'cover_min_channel_floor_mm':1.4,
 'retention':'Two soft nonconductive nominal10mm straps around pouch, through rear-cover slots; not supplied/manufactured with print. Round guide corners, no clamp preload.',
 'source_unchanged':sha(src)==before}
report['ok']=all([body.isValid(),cover.isValid(),len(body.Solids)==1,len(cover.Solids)==1,report['body_battery_intersection_mm3']<1e-6,report['cover_battery_intersection_mm3']<1e-6,report['body_cover_intersection_mm3']<1e-6,report['existing_base_lost_mm3']<1e-6,report['source_unchanged']])
(out/'rear-bay-predictive-report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,indent=2))
A.closeDocument(d.Name)
