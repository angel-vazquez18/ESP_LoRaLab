import json, math, time, pathlib, sys, hashlib
import FreeCAD as App
import Part
import Mesh
from itertools import combinations

ROOT=pathlib.Path(r'C:\Users\Homar\Documents\ChatGPT\LoRa-Walkie-Talkies\output\enclosure-c5')
OUT=ROOT/'fit-review'
OUT.mkdir(exist_ok=True)
START=time.time()
def log(s): print(f'[{time.time()-START:.1f}s] {s}',flush=True)
def bbox(s):
 b=s.BoundBox
 return [b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def bdist(a,b):
 return math.sqrt(sum(max(a[i]-b[i+3],b[i]-a[i+3],0)**2 for i in range(3)))
def component(i):
 if i==0:return 'SW1 PTT switch'
 if i<=888:return 'U1 Heltec manufacturer model'
 if i<=1066:return 'Carrier pads and plating'
 if i==1067:return 'Carrier substrate'
 if i<=1714:return 'U2 INMP441'
 if i<=2137:return 'JAMP1 MAX98357A'
 if i<=2144:return 'R8 resistor'
 if i<=2810:return 'U1 Heltec manufacturer model'
 if i<=2830:return 'U1 OLED supplement'
 if i<=2930:return 'Carrier top silkscreen'
 if i<=2946:return 'Carrier bottom silkscreen'
 if i==2947:return 'Carrier top soldermask'
 return 'Carrier bottom soldermask'
def vec(v):return [v.x,v.y,v.z]
case_path=pathlib.Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'LoRa-Enclosure-C5.FCStd'
step_path=ROOT/'detailed-import'/'C5-detailed-assembly.step'
report_name=sys.argv[2] if len(sys.argv)>2 else 'baseline-actual-clearance.json'
log('Loading assembled enclosure '+str(case_path))
case_sha256=hashlib.sha256(case_path.read_bytes()).hexdigest()
case=App.openDocument(str(case_path))
cases={n:case.getObject(n).Shape.copy() for n in ('EnclosureBase','EnclosureLid','PTTPlunger')}
log('Importing corrected detailed STEP')
doc=App.newDocument('ActualClearanceAssembly')
Part.insert(str(step_path),doc.Name)
objs=[o for o in doc.Objects if hasattr(o,'Shape') and not o.Shape.isNull()]
log('Imported '+str(len(objs))+' objects')
assert len(objs)==2949, len(objs)
sources=[]
for i,o in enumerate(objs):
 s=o.Shape.copy();s.translate(App.Vector(0,0,6.4814))
 sources.append((i,o.Name,component(i),s,bbox(s)))
report={'case_file':str(case_path),'case_sha256':case_sha256,'step_file':str(step_path),'step_sha256':hashlib.sha256(step_path.read_bytes()).hexdigest(),'component_top_datum_raw':1.5186,'mounted_translation_mm':[0,0,6.4814],'source_objects':len(sources),'threshold_mm':5.0,'parts':{},'limits':['Distances and intersections apply to assigned project CAD, not measured hardware.','Converted VRML components are open presentation surfaces; positive common area with strict interior points indicates surface penetration, not solid intersection volume.','Intended PCB mounting contacts are reported, not automatically classified as defects.']}
for pname,ps in cases.items():
 log('Checking '+pname)
 pfaces=[bbox(f) for f in ps.Faces]
 psolids=ps.Solids
 assert len(psolids)==1,(pname,len(psolids))
 exact=0;records=[];mins={};penetrations=[];zeroes=[]
 candidates=sorted([(min(bdist(bb,fbb) for fbb in pfaces),i,oname,comp,shape,bb) for i,oname,comp,shape,bb in sources],key=lambda r:r[0])
 for lower,i,oname,comp,shape,bb in candidates:
  if lower>max(5.0001,mins.get(comp,{}).get('distance_mm',float('inf'))):continue
  exact+=1
  try:
   dist,pts,info=ps.distToShape(shape)
   rec={'index':i,'object':oname,'component':comp,'bbox_mm':bb,'distance_mm':dist,'solids':len(shape.Solids),'faces':len(shape.Faces),'nearest_points':[[vec(a),vec(b)] for a,b in pts[:2]],'nearest_pair_count':len(pts)}
   if dist<=1e-6:
    common=ps.common(shape)
    rec['common_volume_mm3']=common.Volume
    rec['common_area_mm2']=common.Area
    inside=[]
    for face in common.Faces:
     p=face.CenterOfMass
     if psolids[0].isInside(p,1e-7,False):
      inside.append(vec(p))
      if len(inside)>=3:break
    rec['strict_inside_common_face_samples']=inside
    rec['classification']='solid_interference' if common.Volume>1e-7 and len(shape.Solids)>0 else ('surface_penetration' if inside else 'contact_or_boundary_intersection')
    zeroes.append(rec)
    if rec['classification'] in ('solid_interference','surface_penetration'):penetrations.append(rec)
   if comp not in mins or dist<mins[comp]['distance_mm']:mins[comp]=rec
   if dist<0.5001 or rec.get('classification'):records.append(rec)
  except Exception as e:
   records.append({'index':i,'object':oname,'component':comp,'error':repr(e),'bbox_mm':bb})
  if exact%100==0:log(pname+' checked '+str(exact)+' candidate parts')
 data={'shape_valid':ps.isValid(),'bounds_mm':bbox(ps),'volume_mm3':ps.Volume,'faces':len(ps.Faces),'exact_distance_evaluations':exact,'minimum_by_component':mins,'within_0_5mm_or_contacts':records,'penetrations':penetrations,'zero_distance_count':len(zeroes)}
 report['parts'][pname]=data
 (OUT/report_name).write_text(json.dumps(report,indent=2),encoding='utf-8')
 log(pname+' finished; '+str(len(penetrations))+' penetration records; mins '+str({k:round(v['distance_mm'],5) for k,v in mins.items()}))
log('Checking housing joints, representative PTT motion, and mesh correspondence')
housing={}
for a,b in combinations(cases,2):
 d,pts,info=cases[a].distToShape(cases[b]);common=cases[a].common(cases[b])
 housing[a+'__'+b]={'distance_mm':d,'common_volume_mm3':common.Volume,'common_area_mm2':common.Area,'nearest_points':[[vec(x),vec(y)] for x,y in pts[:2]]}
report['housing_pairs']=housing
section_checks={}
for title,a,b,z in [('locating_lip_horizontal_clearance','EnclosureBase','EnclosureLid',23.0),('plunger_guide_radial_clearance','EnclosureLid','PTTPlunger',26.6)]:
 sa=Part.makeCompound(cases[a].slice(App.Vector(0,0,1),z));sb=Part.makeCompound(cases[b].slice(App.Vector(0,0,1),z));d,pts,info=sa.distToShape(sb)
 section_checks[title]={'z_mm':z,'distance_mm':d,'nearest_points':[[vec(x),vec(y)] for x,y in pts[:2]],'method':'Exact OCC distance between horizontal cross-section wires of final native printable shapes.'}
report['housing_section_clearances']=section_checks
travel=[]
switch=sources[0][3]
for down in [0.0,0.2,0.4]:
 p=cases['PTTPlunger'].copy();p.translate(App.Vector(0,0,-down))
 rec={'downward_displacement_mm':down,'switch_representation':'Static representative switch model; geometric overlap models depression only, not verified permissible physical travel.'}
 for label,obstacle in [('switch',switch),('lid',cases['EnclosureLid']),('base',cases['EnclosureBase'])]:
  d,pts,info=p.distToShape(obstacle);common=p.common(obstacle)
  rec[label]={'distance_mm':d,'common_volume_mm3':common.Volume,'common_area_mm2':common.Area,'nearest_points':[[vec(x),vec(y)] for x,y in pts[:2]]}
 travel.append(rec)
report['representative_ptt_travel']=travel
meshes={}
for pname,fname in [('EnclosureBase','enclosure-base.stl'),('EnclosureLid','enclosure-lid.stl'),('PTTPlunger','ptt-plunger.stl')]:
 mesh_path=case_path.parent/fname
 if not mesh_path.exists():continue
 m=Mesh.Mesh(str(mesh_path));mb=m.BoundBox;mbounds=[mb.XMin,mb.YMin,mb.ZMin,mb.XMax,mb.YMax,mb.ZMax];s=cases[pname];cbounds=bbox(s)
 meshes[pname]={'file':str(mesh_path),'sha256':hashlib.sha256(mesh_path.read_bytes()).hexdigest(),'mesh_solid':m.isSolid(),'facets':m.CountFacets,'mesh_bounds_mm':mbounds,'cad_bounds_mm':cbounds,'max_absolute_bbox_difference_mm':max(abs(a-b) for a,b in zip(mbounds,cbounds)),'mesh_volume_mm3':m.Volume,'cad_volume_mm3':s.Volume,'relative_volume_difference':(m.Volume-s.Volume)/s.Volume,'limitation':'Bounds and volume compare geometry coarsely; not a surface-to-surface equivalence proof.'}
report['stl_cad_comparison']=meshes
report['elapsed_seconds']=time.time()-START
(OUT/report_name).write_text(json.dumps(report,indent=2),encoding='utf-8')
log('Wrote '+str(OUT/report_name))
