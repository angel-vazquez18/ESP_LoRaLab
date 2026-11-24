import json,math,time,pathlib,hashlib
import FreeCAD as App
import Part

ROOT=pathlib.Path(r'C:\Users\Homar\Documents\ChatGPT\LoRa-Walkie-Talkies\output\enclosure-c5')
OUT=ROOT/'fit-review'
START=time.time()
def log(s):print(f'[{time.time()-START:.1f}s] {s}',flush=True)
def vec(v):return [v.x,v.y,v.z]
def bbox(s):
 b=s.BoundBox
 return [b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def bdist(a,b):return math.sqrt(sum(max(a[i]-b[i+3],b[i]-a[i+3],0)**2 for i in range(3)))
def component(i):
 if i==0:return 'SW1 PTT switch'
 if i<=888 or 2145<=i<=2810:return 'U1 Heltec manufacturer model'
 if i<=1066:return 'Carrier pads and plating'
 if i==1067:return 'Carrier substrate'
 if i<=1714:return 'U2 INMP441'
 if i<=2137:return 'JAMP1 MAX98357A'
 if i<=2144:return 'R8 resistor'
 if i<=2830:return 'U1 OLED supplement'
 if i<=2930:return 'Carrier top silkscreen'
 if i<=2946:return 'Carrier bottom silkscreen'
 if i==2947:return 'Carrier top soldermask'
 return 'Carrier bottom soldermask'
def cylinder(r,z0,z1,x=51,y=9):return Part.makeCylinder(r,z1-z0,App.Vector(x,y,z0))
def stop_cup(zshift=0):
 # Bottom and stop shelf move together; lid mating face stays at Z24.
 s=cylinder(8.3,20.15+zshift,24)
 for x in [42,60]:s=s.fuse(cylinder(3,20.15+zshift,24,x=x))
 s=s.cut(cylinder(6.6,22.15+zshift,24.1)).cut(cylinder(2.6,19,25))
 for x in [42,60]:s=s.cut(cylinder(1.2,19,31,x=x))
 return s.removeSplitter()
def contact_area(a,b,z):
 fa=[f for f in a.Faces if abs(f.BoundBox.ZMin-z)<1e-6 and abs(f.BoundBox.ZMax-z)<1e-6]
 fb=[f for f in b.Faces if abs(f.BoundBox.ZMin-z)<1e-6 and abs(f.BoundBox.ZMax-z)<1e-6]
 return sum(f.common(g).Area for f in fa for g in fb)
def pair(a,b,plane=None):
 d,pts,info=a.distToShape(b);c=a.common(b)
 r={'distance_mm':d,'common_volume_mm3':c.Volume,'common_area_mm2':c.Area,'nearest_points':[[vec(x),vec(y)] for x,y in pts[:2]]}
 if plane is not None:r['face_contact_area_at_z_mm2']=contact_area(a,b,plane)
 return r
def audit_against_actual(name,s,sources):
 log('Auditing '+name)
 faceboxes=[bbox(f) for f in s.Faces]
 candidates=sorted([(min(bdist(bb,f) for f in faceboxes),i,oname,comp,shape,bb) for i,oname,comp,shape,bb in sources],key=lambda r:r[0])
 mins={};near=[];errors=[];count=0
 for lower,i,oname,comp,shape,bb in candidates:
  if lower>max(5.0001,mins.get(comp,{}).get('distance_mm',float('inf'))):continue
  count+=1
  try:
   d,pts,info=s.distToShape(shape)
   rec={'index':i,'object':oname,'component':comp,'bbox_mm':bb,'distance_mm':d,'nearest_points':[[vec(x),vec(y)] for x,y in pts[:2]],'source_solids':len(shape.Solids)}
   if d<=1e-6:
    common=s.common(shape);rec.update(common_volume_mm3=common.Volume,common_area_mm2=common.Area)
    rec['strict_inside_common_face_samples']=[vec(f.CenterOfMass) for f in common.Faces if any(so.isInside(f.CenterOfMass,1e-7,False) for so in s.Solids)][:3]
   if comp not in mins or d<mins[comp]['distance_mm']:mins[comp]=rec
   if d<.5001:near.append(rec)
  except Exception as e:errors.append({'index':i,'component':comp,'error':repr(e)})
 return {'valid':s.isValid(),'solids':len(s.Solids),'bbox_mm':bbox(s),'volume_mm3':s.Volume,'exact_evaluations':count,'minimum_by_component':mins,'within_0_5mm':near,'errors':errors}

case_path=ROOT/'LoRa-Enclosure-C5.FCStd';step_path=ROOT/'detailed-import'/'C5-detailed-assembly.step'
log('Loading original enclosure and constructing provisional stop cup in memory')
doc=App.openDocument(str(case_path))
base=doc.getObject('EnclosureBase').Shape.copy();lid=doc.getObject('EnclosureLid').Shape.copy();plunger=doc.getObject('PTTPlunger').Shape.copy()
for x in [42,60]:lid=lid.cut(cylinder(1.2,19,31,x=x))
lid=lid.removeSplitter();cup=stop_cup()
hardware={}
for n,x in [('left',42),('right',60)]:
 shaft=cylinder(1,17.6,27.6,x=x);head=cylinder(2,27.6,29.32,x=x)
 radius=4/math.sqrt(3)
 poly=[App.Vector(x+radius*math.cos(a*math.pi/3),9+radius*math.sin(a*math.pi/3),18.55) for a in range(6)]
 poly.append(poly[0]);nut=Part.Face(Part.makePolygon(poly)).extrude(App.Vector(0,0,1.6)).cut(cylinder(1,18.4,20.3,x=x))
 hardware[n+'_screw']=shaft.fuse(head).removeSplitter();hardware[n+'_nut']=nut.removeSplitter()
log('Importing corrected actual KiCad assembly')
actual=App.newDocument('StopCupReference');Part.insert(str(step_path),actual.Name)
objs=[o for o in actual.Objects if hasattr(o,'Shape') and not o.Shape.isNull()]
assert len(objs)==2949
sources=[]
for i,o in enumerate(objs):
 s=o.Shape.copy();s.translate(App.Vector(0,0,6.4814));sources.append((i,o.Name,component(i),s,bbox(s)))
switch=sources[0][3]
report={'case_file':str(case_path),'case_sha256':hashlib.sha256(case_path.read_bytes()).hexdigest(),'step_file':str(step_path),'step_sha256':hashlib.sha256(step_path.read_bytes()).hexdigest(),'geometry_scope':'All proposed geometry constructed in memory only; original CAD and STEP untouched.','parameters':{'cup_od':16.6,'cavity_id':13.2,'foot_bore':5.2,'cup_bottom_z':20.15,'stop_shelf_z':22.15,'mating_top_z':24,'lug_centres':[[42,9],[60,9]],'lug_od':6,'fastener_holes_diameter':2.4,'shaft_diameter':2,'shaft_z':[17.6,27.6],'head_diameter':4,'head_z':[27.6,29.32],'nut_AF':4,'nut_z':[18.55,20.15]},'actual_model_audits':{},'limits':['Switch travel is provisional and inferred from comparable parts, not verified for purchased switch.','Hardware envelopes omit thread and socket details and represent conservative M2 pan-head screw geometry.','VRML-derived models contain open presentation surfaces; zero distance requires surface-penetration interpretation.','Zshift variants change cup floor and shelf elevations while preserving its lid contact face at Z24; corresponding nuts follow the cup underside.','Pan-head tops are only 0.08 mm below the resting plunger top, and stand 0.37 mm above it at full provisional depression; finger access is not represented by CAD.']}
for name,s in [('cup',cup),*hardware.items()]:report['actual_model_audits'][name]=audit_against_actual(name,s,sources)
report['modified_lid_valid']=lid.isValid();report['modified_lid_solids']=len(lid.Solids)
report['cup_housing']={'base':pair(cup,base),'lid':pair(cup,lid,24),'plunger_rest':pair(cup,plunger)}
report['hardware_housing']={n:{'base':pair(s,base),'lid':pair(s,lid,27.6),'cup':pair(s,cup,20.15),'plunger':pair(s,plunger)} for n,s in hardware.items()}
report['hardware_pairs']={a+'__'+b:pair(sa,sb) for ia,(a,sa) in enumerate(hardware.items()) for ib,(b,sb) in enumerate(hardware.items()) if ib>ia}
travel=[]
for down in [0,.2,.45,.46]:
 p=plunger.copy();p.translate(App.Vector(0,0,-down))
 travel.append({'downward_mm':down,'implied_switch_depression_mm':max(0,down-.2),'cup':pair(p,cup,22.15),'switch':pair(p,switch),'lid':pair(p,lid),'base':pair(p,base),'hardware':{n:pair(p,s) for n,s in hardware.items()}})
report['nominal_travel_sweep']=travel
variants=[]
for zshift,stroke in [(.1,.15),(-.1,.35)]:
 c=stop_cup(zshift);down=.2+stroke;p=plunger.copy();p.translate(App.Vector(0,0,-down));past=plunger.copy();past.translate(App.Vector(0,0,-down-.01))
 hw={n:s.copy() for n,s in hardware.items()}
 for n,s in hw.items():
  if n.endswith('_nut'):s.translate(App.Vector(0,0,zshift))
 variants.append({'shelf_zshift_mm':zshift,'stop_shelf_z':22.15+zshift,'provisional_switch_stroke_mm':stroke,'total_plunger_travel_mm':down,'cup_valid':c.isValid(),'cup_solids':len(c.Solids),'at_stop':pair(p,c,22.15+zshift),'0_01mm_beyond_stop':pair(past,c),'cup_lid':pair(c,lid,24),'cup_base':pair(c,base),'cup_switch':pair(c,switch),'switch_at_stop':pair(p,switch),'hardware_housing':{n:pair(s,c,20.15+zshift) for n,s in hw.items()}})
report['stroke_variants']=variants
sections=cup.slice(App.Vector(0,0,1),23.0)
cavity_wire=next(w for w in sections if abs(w.BoundBox.XLength-13.2)<1e-6)
hole_wires=[w for w in sections if abs(w.BoundBox.XLength-2.4)<1e-6]
report['lug_material_webs']={'method':'Exact distance between final cup section wires at Z23, flange cavity and M2 clearance holes.','hole_to_cavity_mm':[pair(w,cavity_wire)['distance_mm'] for w in hole_wires],'nominal_hole_to_outer_lug_mm':3-1.2,'nominal_cup_sidewall_mm':8.3-6.6,'nominal_cup_floor_mm':2,'minimum_required_feature_here':'1.2 mm web between each M2 clearance bore and flange cavity; printing strength is not proven by geometric distance.'}
fullstop=plunger.copy();fullstop.translate(App.Vector(0,0,-.45))
report['screw_head_access_at_stop']={'plunger_top_z_mm':fullstop.BoundBox.ZMax,'head_top_z_mm':29.32,'head_top_above_depressed_plunger_mm':29.32-fullstop.BoundBox.ZMax,'head_to_plunger':[pair(cylinder(2,27.6,29.32,x=x),fullstop) for x in [42,60]],'axis_to_plunger_shaft_radial_distance_mm':5,'coaxial_cylindrical_tool_max_diameter_without_clearance_at_shaft_height_mm':10,'limits':'No particular screwdriver or finger is specified. Theoretical tool diameter is radial geometric access only; use a smaller tool for working clearance. Pan-head envelopes do not directly conflict with the depressed plunger.'}
report['elapsed_seconds']=time.time()-START
path=OUT/'provisional-ptt-stop-cup-audit.json';path.write_text(json.dumps(report,indent=2),encoding='utf-8')
log('Wrote '+str(path))
