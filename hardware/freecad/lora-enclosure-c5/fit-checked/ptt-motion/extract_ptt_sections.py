import json,math,time,pathlib,hashlib
import FreeCAD as App
import Part
OUT=pathlib.Path(__file__).resolve().parent
SOURCE=OUT.parent/'cutaway-view'/'LoRa-Enclosure-C5-Assembled-Cutaway.FCStd'
START=time.time();Y=9.0;DEFLECTION=.005;SPLIT=12.5;STROKE=.25
def log(s):print(f'[{time.time()-START:.1f}s] {s}',flush=True)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def bbox(s):
 b=s.BoundBox;return[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def shifted(s,z):
 n=s.copy();n.translate(App.Vector(0,0,z));return n
def contact_area(a,b,z):
 fa=[f for f in a.Faces if abs(f.BoundBox.ZMin-z)<1e-6 and abs(f.BoundBox.ZMax-z)<1e-6]
 fb=[f for f in b.Faces if abs(f.BoundBox.ZMin-z)<1e-6 and abs(f.BoundBox.ZMax-z)<1e-6]
 return sum(f.common(g).Area for f in fa for g in fb)
def pair(a,b,z=None):
 d,pts,_=a.distToShape(b);c=a.common(b)
 r={'distance_mm':d,'common_volume_mm3':c.Volume,'nearest_points':[[[p.x,p.y,p.z],[q.x,q.y,q.z]] for p,q in pts[:2]]}
 if z is not None:r['contact_area_mm2']=contact_area(a,b,z)
 return r
def path_for(polys,closed):
 paths=[]
 for p in polys:
  q=p[:-1] if closed and p[0]==p[-1] else p
  if not q:continue
  paths.append('M '+' L '.join(f'{x:.8f} {z:.8f}' for x,z in q)+(' Z' if closed else ''))
 return ' '.join(paths)
def sections(s,y=Y):return s.slice(App.Vector(0,1,0),y)
def section_data(s,source_object=None):
 closed=[];opened=[]
 extras={};wires=sections(s);used_y=Y
 if source_object=='PTTDetailPCB':
  # OCC slice() omits the trimmed substrate here even when applied per solid.
  # Explicit world-plane section preserves the actual substrate and pad step.
  used_y=Y+.0001
  plane=Part.makePlane(100,40,App.Vector(0,used_y,40),App.Vector(0,1,0),App.Vector(1,0,0))
  fs=[]
  for so in s.Solids:
   sec=so.section(plane)
   if not sec.Edges:continue
   for es in Part.sortEdges(sec.Edges):
    w=Part.Wire(es)
    if w.isClosed():fs.append(Part.Face(w))
  assert fs
  combined=fs[0]
  for f in fs[1:]:combined=combined.fuse(f)
  combined=combined.removeSplitter();wires=combined.Wires
  assert combined.Area>30 and combined.BoundBox.XLength>25.9
  extras={'section_area_mm2':combined.Area,'section_bbox_mm':bbox(combined),'extraction_method':'Slice every solid of actual cropped PCB separately, convert closed wires to planar faces, then fuse their actual sections. No substituted primitive geometry.'}
 elif not wires and source_object=='PTTDetailFloor':
  used_y=Y+.0001;wires=sections(s,used_y)
 for w in wires:
  ps=w.discretize(Deflection=DEFLECTION)
  points=[[round(p.x,9),round(p.z,9)] for p in ps]
  isclosed=w.isClosed()
  if isclosed and points and points[0]!=points[-1]:points.append(points[0])
  if points:(closed if isclosed else opened).append(points)
 return {'source_object':source_object,'section_y_mm':used_y,'shape_bbox_mm':bbox(s),'shape_valid':s.isValid(),'solid_count':len(s.Solids),'closed_loops_xz':closed,'open_polylines_xz':opened,'svg_path_xz':path_for(closed,True),'svg_open_path_xz':path_for(opened,False),'svg_fill_rule':'evenodd','closed_loop_count':len(closed),'open_polyline_count':len(opened),'point_count':sum(map(len,closed+opened)),**extras}

log('Reading saved cutaway and extracting actual source shapes')
source_hash=sha(SOURCE);doc=App.openDocument(str(SOURCE))
names=['PTTPlunger','PTTStopCup','PTTLidSection','PTTFastenerLeftScrew','PTTFastenerRightScrew','PTTFastenerLeftNut','PTTFastenerRightNut','PTTDetailPCB','PTTDetailFloor','PTTDetailSwitchSource']
shapes={n:doc.getObject(n).Shape.copy() for n in names}
sw=shapes['PTTDetailSwitchSource'];cup=shapes['PTTStopCup'];nominal=shapes['PTTPlunger']
upperbox=Part.makeBox(40,40,40,App.Vector(30,-10,SPLIT));upper=sw.common(upperbox);fixed=sw.cut(upperbox)
pressed_switch=fixed.fuse(shifted(upper,-STROKE)).removeSplitter()
released=shifted(nominal,-.2);pressed=shifted(nominal,-.45);past=shifted(nominal,-.46)
variants={'PTTPlungerReleased':released,'PTTPlungerPressed':pressed,'PTTSwitchReleased':sw,'PTTSwitchPressed':pressed_switch,'PTTSwitchFixedLower':fixed,'PTTSwitchMovingUpperReleased':upper,'PTTSwitchMovingUpperPressed':shifted(upper,-STROKE)}
log('Slicing at Y9 and discretizing closed contours')
parts={n:section_data(s,n) for n,s in shapes.items()}
parts.update({n:section_data(s,'PTTPlunger' if n.startswith('PTTPlunger') else 'PTTDetailSwitchSource') for n,s in variants.items()})

# Independent exact contour proof: move each top edge and shorten only the
# vertical stem edges crossing the split level, keeping every lower edge fixed.
warped=[];crossing=[]
for w in sections(sw):
 es=[]
 for e in w.Edges:
  b=e.BoundBox
  if b.ZMin>=SPLIT-1e-7:es.append(shifted(e,-STROKE))
  elif b.ZMax<=SPLIT+1e-7:es.append(e.copy())
  else:
   ps=[v.Point for v in e.Vertexes]
   crossing.append({'curve_type':str(type(e.Curve)),'bbox_mm':bbox(e),'constant_x':b.XLength<1e-7,'constant_y':b.YLength<1e-7})
   assert len(ps)==2 and b.XLength<1e-7 and b.YLength<1e-7
   ps=[App.Vector(p.x,p.y,p.z-STROKE if p.z>SPLIT else p.z) for p in ps]
   es.append(Part.makeLine(ps[0],ps[1]))
 warped.append(Part.Face(Part.Wire(es)))
expected=Part.makeCompound(warped);actual=Part.makeCompound([Part.Face(w) for w in sections(pressed_switch)])
sym_area=expected.cut(actual).Area+actual.cut(expected).Area

checks={'nominal_free_gap_is_not_released_pose':{'nominal_plunger_offset_z_mm':0,'nominal_foot_to_switch_gap_mm':pair(nominal,sw)['distance_mm']},'released':{'plunger_offset_z_mm':-.2,'switch_actuator_offset_z_mm':0,'foot_switch':pair(released,sw,16),'plunger_cup':pair(released,cup),'plunger_lid':pair(released,shapes['PTTLidSection'])},'fully_pressed':{'plunger_offset_z_mm':-.45,'switch_actuator_offset_z_mm':-.25,'foot_switch':pair(pressed,pressed_switch,15.75),'plunger_cup':pair(pressed,cup,22.15),'plunger_lid':pair(pressed,shapes['PTTLidSection'])},'extra_0_01mm_blocked':{'plunger_offset_z_mm':-.46,'plunger_cup':pair(past,cup)},'switch_model':{'original_valid':sw.isValid(),'upper_valid':upper.isValid(),'upper_solids':len(upper.Solids),'upper_bbox_mm':bbox(upper),'pressed_valid':pressed_switch.isValid(),'pressed_solids':len(pressed_switch.Solids),'fixed_lower_unchanged':True,'stem_axis_x_mm':50.9,'stem_axis_y_mm':9,'stem_radius_mm':1.75,'top_flat_radius_mm':1.65,'split_z_mm':SPLIT,'crossing_profile_edges':crossing,'exact_vertex_warp_vs_split_union_symmetric_section_area_mm2':sym_area,'upper_profile_translation_is_faithful':sym_area<1e-8}}
geometry={'schema_version':1,'source_file':str(SOURCE),'source_sha256':source_hash,'units':'mm','section_plane':{'normal':[0,1,0],'y_mm':Y,'reason':'Exact central section through PTT and fastener axes.'},'coordinates':'Every polyline point is [world X, world Z]. SVG path uses X,Z directly; reverse screen Y when rendering so positive Z is upward.','discretization':{'maximum_chord_deflection_mm':DEFLECTION,'closed_loops_repeat_first_point':True,'open_polylines_are_unfilled_reference_surface_intersections':True},'parts':parts,'animation':{'progress_range':[0,1],'plunger_offset_z_mm':'-0.20 - 0.25 * progress','upper_switch_stem_offset_z_mm':'-0.25 * progress','switch_fixed_profile_below_z_mm':12.5,'nominal_free_gap_mm':.2,'released_is_switch_supported_contact':True,'pressed_total_displacement_from_nominal_mm':.45,'stroke_between_shown_endpoints_mm':.25,'profile_motion_method':'For actual switch section vertices above Z12.5, subtract 0.25*progress from Z; keep lower vertices fixed. Exact contour equivalence checked against upper-solid translation and union with fixed lower switch.'},'checks_file':'ptt-motion-contact-checks.json','limits':['This is an external-geometry animation using provisional reference stroke, not a switch mechanism simulation.','Internal switch contacts, springs, force, elastic deformation, print tolerance, and measured purchased-switch travel are not modeled.','All CAD/project files were read only; only JSON and this extraction script were written.']}
checks.update(source_file=str(SOURCE),source_sha256=source_hash,source_file_unchanged=sha(SOURCE)==source_hash,section_y_mm=Y,elapsed_seconds=time.time()-START)
checks['ok']=checks['source_file_unchanged'] and checks['released']['foot_switch']['distance_mm']<1e-7 and checks['released']['foot_switch']['common_volume_mm3']<1e-7 and abs(checks['released']['plunger_cup']['distance_mm']-.25)<1e-7 and checks['fully_pressed']['foot_switch']['distance_mm']<1e-7 and checks['fully_pressed']['foot_switch']['common_volume_mm3']<1e-7 and checks['fully_pressed']['plunger_cup']['common_volume_mm3']<1e-7 and checks['fully_pressed']['plunger_cup']['contact_area_mm2']>1 and checks['extra_0_01mm_blocked']['plunger_cup']['common_volume_mm3']>.1 and sym_area<1e-8
(OUT/'ptt-section-geometry.json').write_text(json.dumps(geometry,indent=2),encoding='utf-8')
(OUT/'ptt-motion-contact-checks.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
log('Wrote geometry and contact checks; ok='+str(checks['ok']))
print(json.dumps({'ok':checks['ok'],'parts':{n:{'loops':p['closed_loop_count'],'open':p['open_polyline_count'],'points':p['point_count']} for n,p in parts.items()},'released':checks['released'],'pressed':checks['fully_pressed'],'extra':checks['extra_0_01mm_blocked'],'exact_section_warp_area_difference_mm2':sym_area},indent=2))
