import json,pathlib,hashlib,time
import FreeCAD as App
import Part
OUT=pathlib.Path(__file__).resolve().parent
SOURCE=OUT.parent/'cutaway-view'/'LoRa-Enclosure-C5-Assembled-Cutaway.FCStd'
START=time.time();source_hash=hashlib.sha256(SOURCE.read_bytes()).hexdigest()
doc=App.openDocument(str(SOURCE))
shape=lambda name:doc.getObject(name).Shape.copy()
cup=shape('PTTStopCup');lid=shape('PTTLidSection');plunger=shape('PTTPlunger');plunger.translate(App.Vector(0,0,-.45))
def point_checks(pos,a,b):
 v=Part.Vertex(App.Vector(*pos));da=a.distToShape(v)[0];db=b.distToShape(v)[0]
 assert da<1e-7 and db<1e-7,(pos,da,db)
 return {'point_xyz_mm':pos,'distance_to_first_part_mm':da,'distance_to_second_part_mm':db}
def contact_area(a,b,z):
 fs=lambda s:[f for f in s.Faces if abs(f.BoundBox.ZMin-z)<1e-6 and abs(f.BoundBox.ZMax-z)<1e-6]
 return sum(f.common(g).Area for f in fs(a) for g in fs(b))
arrows=[];interfaces=[];routes=[]
for side,axis,x,flange in [('left',42,40.4,46.5),('right',60,61.6,55.5)]:
 nut=shape('PTTFastener'+side.title()+'Nut');screw=shape('PTTFastener'+side.title()+'Screw')
 shelf=[flange,9,22.15];bearing=[x,9,20.15];head=[x,9,27.6];thread=[axis,9,19.35]
 checks={'flange_shelf':point_checks(shelf,plunger,cup),'cup_nut':point_checks(bearing,cup,nut),'head_lid':point_checks(head,screw,lid)}
 interfaces.append({'side':side,'screw_axis_xy_mm':[axis,9],'cup_underside_and_nut_top_z_mm':20.15,'lid_top_and_head_bearing_z_mm':27.6,'cup_nut_contact_area_mm2':contact_area(cup,nut,20.15),'head_lid_contact_area_mm2':contact_area(screw,lid,27.6),'bearing_point_verification':checks})
 definitions=[
  ('flange_on_cup','Flange on stop cup','plunger','stop_cup',shelf,[0,0,-1],'Actual flange/shelf interface.'),
  ('cup_on_nut','Cup on nut','stop_cup',side+'_nut',bearing,[0,0,-1],'Actual cup underside/nut top bearing interface.'),
  ('nut_on_screw','Nut on screw','nut threads',side+'_screw',thread,[0,0,-1],'Schematic axial resultant at thread region; detailed thread contact geometry is not modeled.'),
  ('head_on_lid','Screw head on lid',side+'_screw','lid',head,[0,0,-1],'Actual screw head/lid top bearing interface.'),
  ('lid_on_screw','Lid reaction on screw','lid',side+'_screw',head,[0,0,1],'Equal-and-opposite reaction at the same head/lid interface.')]
 for suffix,label,source,target,anchor,direction,note in definitions:
  arrows.append({'id':side+'_'+suffix,'label':label,'force_exerted_by':source,'force_on':target,'anchor_xyz_mm':anchor,'unit_direction_world':direction,'magnitude':'unspecified','visibility':'when stop engaged; qualitative incremental load transfer only','note':note})
 routes.append({'side':side,'polyline_xyz_mm':[shelf,bearing,thread,[axis,9,27.6],head],'rendering':'Use a distinct dashed connector or other routing style; its upward segment along the screw is load-path location, not an upward force vector.','screw_internal_load':'tension','equal_load_sharing_assumed':False})
report={'schema_version':1,'source_file':str(SOURCE),'source_sha256':source_hash,'source_unchanged':hashlib.sha256(SOURCE.read_bytes()).hexdigest()==source_hash,'units':'mm','scope':'Qualitative stop-engagement free-body interpretation; CAD bearing interfaces verified read-only.','stop_contact_z_mm':22.15,'pressed_plunger_offset_from_nominal_mm':-.45,'full_flange_shelf_contact_area_mm2':contact_area(plunger,cup,22.15),'interfaces':interfaces,'arrows':arrows,'load_path_routes':routes,'notes':['Downward force on the flange transfers downward onto the cup, onto the nuts, through the screw threads, and from screw heads down into the lid.','Nut forces pull the screw lower ends downward while lid reactions push screw heads upward, so screws carry tension. The route from nuts to heads runs upward spatially; this is not an upward applied load.','Head-on-lid and lid-on-head are an action/reaction pair acting on different bodies, not two forces to add on one free-body diagram.','Cup-on-nut arrows have corresponding nut-on-cup upward reactions; flange-on-cup has cup-on-flange upward reaction. These counterparts may be shown in a dedicated free-body view, not added as extra transferred load.','No force magnitude, tightening preload, stiffness, deflection, load sharing, or stress is calculated. Equal drawn arrow lengths do not imply equal force division between fasteners.','The touching cup top/lid underside at Z24 can carry initial clamp compression; its remaining contact pressure under pressing depends on unknown preload/compliance. Do not assign an extra bearing load there in this qualitative stop-load diagram.','Arrow coordinates at40.4/61.6 are actual bearing material,1.6mm outboard of each screw axis. Axes42/60 at the bearing planes are clearance holes. Thread-resultant anchors are schematic because thread engagement detail is absent.','Coordinates lie on the retained front cut face Y9. A small negative-Y visual overlay offset may improve visibility without changing measured anchors or CAD.'],'elapsed_seconds':time.time()-START}
assert report['source_unchanged']
path=OUT/'ptt-load-path.json';path.write_text(json.dumps(report,separators=(',',':')),encoding='utf-8')
print(json.dumps({'file':str(path),'bytes':path.stat().st_size,'interfaces':interfaces,'source_unchanged':report['source_unchanged']},indent=2))
