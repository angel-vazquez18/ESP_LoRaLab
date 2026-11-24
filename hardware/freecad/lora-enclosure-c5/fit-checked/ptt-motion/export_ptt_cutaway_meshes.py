import json,pathlib,time,hashlib,math
import FreeCAD as App
import Part
import MeshPart
OUT=pathlib.Path(__file__).resolve().parent
SOURCE=OUT.parent/'cutaway-view'/'LoRa-Enclosure-C5-Assembled-Cutaway.FCStd'
START=time.time();DEFLECTION=.02;CUT_Y=9.0
def log(s):print(f'[{time.time()-START:.1f}s] {s}',flush=True)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def bbox(s):
 b=s.BoundBox;return[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def shifted(s,z):
 n=s.copy();n.translate(App.Vector(0,0,z));return n
def common_diff(a,b):return a.cut(b).Volume+b.cut(a).Volume
def contact_area(a,b,z):
 fs=lambda s:[f for f in s.Faces if abs(f.BoundBox.ZMin-z)<1e-6 and abs(f.BoundBox.ZMax-z)<1e-6]
 return sum(f.common(g).Area for f in fs(a) for g in fs(b))
def pair(a,b,z=None):
 r={'distance_mm':a.distToShape(b)[0],'common_volume_mm3':a.common(b).Volume}
 if z is not None:r['contact_area_mm2']=contact_area(a,b,z)
 return r
log('Opening saved cutaway read-only')
source_hash=sha(SOURCE);doc=App.openDocument(str(SOURCE))
frontbox=Part.makeBox(200,109,200,App.Vector(-50,-100,-50))
def cutfront(s):return s.cut(frontbox).removeSplitter()
def original(name):return doc.getObject(name).Shape.copy()
sw=original('PTTDetailSwitchSource');nominal=original('PTTPlunger');cup=original('PTTStopCup')
splitbox=Part.makeBox(100,100,100,App.Vector(0,-40,12.5))
upperbox=Part.makeBox(100,100,100,App.Vector(0,-40,12.25))
fixed=sw.cut(splitbox).removeSplitter();upper=sw.common(upperbox).removeSplitter()
upper_exact=sw.common(splitbox)
released_switch=fixed.fuse(upper).removeSplitter()
pressed_switch=fixed.fuse(shifted(upper,-.25)).removeSplitter()
reference_pressed=fixed.fuse(shifted(upper_exact,-.25)).removeSplitter()
pcb=original('PTTDetailPCB');pcbsolids=pcb.Solids
assert len(pcbsolids)==10
substrate=max(pcbsolids,key=lambda x:x.Volume)
assert abs(substrate.BoundBox.XMin-38)<1e-7 and abs(substrate.BoundBox.XMax-64)<1e-7 and abs(substrate.BoundBox.ZMin-6.4814)<1e-7 and abs(substrate.BoundBox.ZMax-7.9068)<1e-7
copper=Part.makeCompound([s for s in pcbsolids if s.Volume<100])
specs=[
 ('plunger','PTT plunger','plunger',shifted(nominal,-.20),[.20,.53,.87],[.43,.72,.98],None,None,'PTTPlunger'),
 ('stop_cup','Printed stop cup','fixed',cup,[.88,.50,.14],[1,.73,.32],None,None,'PTTStopCup'),
 ('lid','Enclosure lid section','fixed',original('PTTLidSection'),[.67,.72,.78],[.83,.87,.92],None,None,'PTTLidSection'),
 ('left_screw','Left M2 screw','fixed',original('PTTFastenerLeftScrew'),[.47,.52,.59],[.75,.79,.84],None,None,'PTTFastenerLeftScrew'),
 ('right_screw','Right M2 screw','fixed',original('PTTFastenerRightScrew'),[.47,.52,.59],[.75,.79,.84],None,None,'PTTFastenerRightScrew'),
 ('left_nut','Left M2 nut','fixed',original('PTTFastenerLeftNut'),[.47,.52,.59],[.75,.79,.84],None,None,'PTTFastenerLeftNut'),
 ('right_nut','Right M2 nut','fixed',original('PTTFastenerRightNut'),[.47,.52,.59],[.75,.79,.84],None,None,'PTTFastenerRightNut'),
 ('pcb_substrate','Actual carrier substrate','fixed',substrate,[.10,.40,.27],[.34,.65,.40],None,None,'PTTDetailPCB solid 9 (actual carrier substrate)'),
 ('pcb_copper','Actual carrier copper pads and plating','fixed',copper,[.74,.51,.20],[.95,.76,.40],None,None,'PTTDetailPCB other nine actual solids'),
 ('floor','Enclosure floor section','fixed',original('PTTDetailFloor'),[.54,.60,.67],[.75,.81,.87],None,None,'PTTDetailFloor'),
 ('switch_fixed','Actual SW1 fixed housing and leads','fixed',fixed,[.21,.25,.31],[.41,.47,.54],12.5,None,'PTTDetailSwitchSource below Z12.5'),
 ('switch_stem','Actual SW1 moving actuator','switch_stem',upper,[.15,.19,.25],[.37,.44,.53],12.25,12.5,'PTTDetailSwitchSource above Z12.25')]

audit=[]
def mesh_for(spec):
 ident,label,motion,source,ext,cap,omit_z,clip_z,origin=spec
 s=cutfront(source);positions=[];normals=[];groups=[];indices=[];omitted=0;projection_errors=[]
 faces={0:[],1:[]}
 for f in s.Faces:
  b=f.BoundBox
  if omit_z is not None and abs(b.ZMin-omit_z)<1e-6 and abs(b.ZMax-omit_z)<1e-6:
   omitted+=1;continue
  material=1 if abs(b.YMin-CUT_Y)<1e-6 and abs(b.YMax-CUT_Y)<1e-6 else 0
  faces[material].append(f)
 for material in [0,1]:
  start=len(indices)
  for face in faces[material]:
   mesh=MeshPart.meshFromShape(Shape=face.cleaned(),LinearDeflection=DEFLECTION,AngularDeflection=.3,Relative=False)
   vs,ts=mesh.Topology
   offset=len(positions)//3
   sums=[App.Vector() for _ in vs]
   for a,b,c in ts:
    normal=(vs[b]-vs[a]).cross(vs[c]-vs[a])
    for i in [a,b,c]:sums[i]+=normal
   for i,v in enumerate(vs):
    n=sums[i]
    try:
     u,vv=face.Surface.parameter(v);analytic=face.normalAt(u,vv)
     if analytic.dot(n)<0:analytic=-analytic
     n=analytic
     projection_errors.append(v.distanceToPoint(face.Surface.value(u,vv)))
    except Exception:pass
    if n.Length>0:n.normalize()
    if material==1:n=App.Vector(0,-1,0)
    positions.extend([round(v.x,5),round(v.y,5),round(v.z,5)])
    normals.extend([round(n.x,5),round(n.y,5),round(n.z,5)])
   for tri in ts:indices.extend(offset+i for i in tri)
  if len(indices)>start:groups.append({'start':start,'count':len(indices)-start,'material':material})
 assert indices and positions
 bb=[min(positions[i::3]) for i in range(3)]+[max(positions[i::3]) for i in range(3)]
 assert bb[1]>=8.99999
 assert all(i>=0 and i<len(positions)//3 for i in indices)
 bounds=bbox(s)
 contained=all(bb[i]>=bounds[i]-2e-5 and bb[i+3]<=bounds[i+3]+2e-5 for i in range(3))
 assert contained,(ident,bb,bounds)
 item={'id':ident,'label':label,'motion':motion,'positions':positions,'normals':normals,'indices':indices,'groups':groups,'materials':[{'name':'exterior','color':ext,'opacity':1},{'name':'section','color':cap,'opacity':1}],'bounds':bb}
 if clip_z is not None:item['clipMinZ']=clip_z
 audit.append({'id':ident,'source_object':origin,'source_valid':source.isValid(),'cut_shape_valid':s.isValid(),'source_solids':len(source.Solids),'cut_solids':len(s.Solids),'mesh_vertices':len(positions)//3,'mesh_triangles':len(indices)//3,'opaque_front_cut_triangles':sum(g['count']//3 for g in groups if g['material']==1),'omitted_artificial_horizontal_cap_faces':omitted,'cad_conservative_bbox_mm':bounds,'mesh_bbox_mm':bb,'mesh_bbox_contained_in_cad_bbox':contained,'max_tessellation_vertex_surface_projection_error_mm':max(projection_errors,default=0)})
 log(ident+': '+str(len(indices)//3)+' triangles')
 return item

parts=[mesh_for(spec) for spec in specs]
checks={'released_switch_union_vs_original_volume_difference_mm3':common_diff(released_switch,sw),'pressed_overlap_union_vs_original_split_method_volume_difference_mm3':common_diff(pressed_switch,reference_pressed),'released':{'plunger_offset_z_mm':-.20,'actuator_offset_z_mm':0,'foot_switch':pair(shifted(nominal,-.20),released_switch,16),'stop':pair(shifted(nominal,-.20),cup)},'pressed':{'plunger_offset_z_mm':-.45,'actuator_offset_z_mm':-.25,'foot_switch':pair(shifted(nominal,-.45),pressed_switch,15.75),'stop':pair(shifted(nominal,-.45),cup,22.15)},'extra_0_01mm':pair(shifted(nominal,-.46),cup)}
assert checks['released_switch_union_vs_original_volume_difference_mm3']<1e-7
assert checks['pressed_overlap_union_vs_original_split_method_volume_difference_mm3']<1e-7
assert checks['released']['foot_switch']['common_volume_mm3']<1e-7 and checks['pressed']['foot_switch']['common_volume_mm3']<1e-7
assert checks['pressed']['stop']['common_volume_mm3']<1e-7 and checks['pressed']['stop']['contact_area_mm2']>90
assert checks['extra_0_01mm']['common_volume_mm3']>.9
assert all(a['source_valid'] and a['cut_shape_valid'] for a in audit)
contract={'progress_min':0,'progress_max':1,'stroke_mm':.25,'dynamic_translation':'For motion plunger or switch_stem: worldZ = exportedZ - 0.25*progress. Fixed parts do not move.','released_plunger_already_shifted_from_nominal_mm':-.20,'pressed_total_plunger_shift_from_nominal_mm':-.45,'nominal_CAD_free_gap_is_not_released_pose_mm':.20,'released_stop_clearance_mm':.25,'pressed_stop_clearance_mm':0,'actuator_clip':'For part switch_stem only, fragment shader MUST discard if transformed worldZ < part.clipMinZ (12.5). Apply after motion translation.','actuator_overlap':'Fixed lower ends at12.5. Moving upper begins at12.25, extends to12.0 after fullpress. Internal horizontal split caps omitted on both meshes. Clip prevents overlap z-fighting and an exposed artificial split plane.','cut_direction':'Removed all material Y<9. View from negativeY toward positiveY to see opaque section faces. Z is up.','groups':'start and count index the flat indices array; group.material selects materials[0] exterior or materials[1] opaque front-cut surface.'}
geometry={'schema_version':1,'units':'mm','source_file':str(SOURCE),'source_sha256':source_hash,'section_plane_y_mm':9,'coordinate_axes':{'x':'left/right','y':'front/back; retainedpositiveY','z':'up'},'linear_deflection_mm':DEFLECTION,'rounding_decimal_places':5,'animation':contract,'parts':parts,'limits':['External reference-stroke motion only; switch springs, internal electrical contacts, tolerances and force are not modeled.','PCB uses ten actual solids: one substrate and nine copper/pad/plating pieces. Detached zero-thickness soldermask surfaces are omitted.','Opaque front faces are real boolean cut surfaces. Artificial actuator split caps are omitted and moving actuator is clipped as documented.']}
mesh_path=OUT/'ptt-cutaway-meshes.json';mesh_path.write_text(json.dumps(geometry,separators=(',',':')),encoding='utf-8')
provenance={'ok':True,'source_file':str(SOURCE),'source_sha256':source_hash,'source_unchanged':sha(SOURCE)==source_hash,'mesh_file':str(mesh_path),'mesh_sha256':sha(mesh_path),'mesh_bytes':mesh_path.stat().st_size,'target_bytes':500000,'within_target':mesh_path.stat().st_size<500000,'total_vertices':sum(len(p['positions'])//3 for p in parts),'total_triangles':sum(len(p['indices'])//3 for p in parts),'parts':audit,'endpoint_checks':checks,'renderer_contract':contract,'elapsed_seconds':time.time()-START}
assert provenance['source_unchanged']
(OUT/'ptt-cutaway-mesh-provenance.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
log('Wrote '+str(mesh_path.stat().st_size)+' bytes; '+str(provenance['total_triangles'])+' triangles')
print(json.dumps({'ok':True,'bytes':provenance['mesh_bytes'],'triangles':provenance['total_triangles'],'vertices':provenance['total_vertices'],'endpoint_checks':checks},indent=2))
