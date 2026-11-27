import json,pathlib,hashlib,math,time
import FreeCAD as App
import Part
import MeshPart
OUT=pathlib.Path(__file__).resolve().parent
SOURCE=OUT.parent/'cutaway-view'/'LoRa-Enclosure-C5-Assembled-Cutaway.FCStd'
START=time.time()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def bbox(s):
 b=s.BoundBox;return[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
source_hash=sha(SOURCE);doc=App.openDocument(str(SOURCE))
cup=doc.getObject('PTTStopCup').Shape.copy();nominal=doc.getObject('PTTPlunger').Shape.copy()
released=nominal.copy();released.translate(App.Vector(0,0,-.20))
pressed=nominal.copy();pressed.translate(App.Vector(0,0,-.45))
Z=22.15
flat=lambda s:[f for f in s.Faces if abs(f.BoundBox.ZMin-Z)<1e-6 and abs(f.BoundBox.ZMax-Z)<1e-6]
common_faces=[]
for f in flat(cup):
 for g in flat(pressed):
  c=f.common(g)
  if c.Area>1e-7:common_faces.extend(c.Faces)
assert len(common_faces)==1
patch=common_faces[0]
front=Part.makeBox(200,109,100,App.Vector(-50,-100,-20))
retained=patch.cut(front)
assert len(retained.Faces)==1
retained=retained.Faces[0]
annulus=Part.Face(Part.Wire(Part.makeCircle(6,App.Vector(51,9,Z)))).cut(Part.Face(Part.Wire(Part.makeCircle(2.6,App.Vector(51,9,Z)))))
annular_difference=patch.cut(annulus).Area+annulus.cut(patch).Area
assert annular_difference<1e-7
assert abs(patch.Area-math.pi*(36-2.6**2))<1e-7
assert abs(retained.Area-patch.Area/2)<1e-7
mesh=MeshPart.meshFromShape(Shape=retained.cleaned(),LinearDeflection=.005,AngularDeflection=.12,Relative=False)
vs,ts=mesh.Topology
positions=[round(q,7) for v in vs for q in [v.x,v.y,v.z]]
indices=[]
for a,b,c in ts:
 if (vs[b]-vs[a]).cross(vs[c]-vs[a]).z<0:b,c=c,b
 indices.extend([a,b,c])
boundaries=[]
for w in retained.Wires:
 points=[[round(p.x,7),round(p.y,7),round(p.z,7)] for p in w.discretize(Deflection=.005)]
 if points[0]!=points[-1]:points.append(points[0])
 boundaries.append(points)
anchor=App.Vector(46.5,9,Z)
anchor_shelf_distance=patch.distToShape(Part.Vertex(anchor))[0]
assert anchor_shelf_distance<1e-7
anchor_upper=App.Vector(46.5,9,22.4)
assert released.distToShape(Part.Vertex(anchor_upper))[0]<1e-7
interior=[]
for f in [.1,.25,.5,.75,.9]:
 p=App.Vector(46.5,9,22.15+.25*f)
 interior.append({'z_mm':p.z,'inside_cup':any(s.isInside(p,1e-7,False) for s in cup.Solids),'inside_released_plunger':any(s.isInside(p,1e-7,False) for s in released.Solids)})
assert not any(q['inside_cup'] or q['inside_released_plunger'] for q in interior)
report={'schema_version':1,'source_file':str(SOURCE),'source_sha256':source_hash,'source_unchanged':sha(SOURCE)==source_hash,'units':'mm','extraction':'Exact planar common of actual cup shelf and fully pressed plunger flange, then removed Y<9.','plane_z_mm':Z,'center_xyz':[51,9,Z],'verified_annulus_inner_radius_mm':2.6,'verified_annulus_outer_radius_mm':6,'actual_patch_vs_analytic_annulus_symmetric_area_difference_mm2':annular_difference,'full_area_mm2':patch.Area,'retained_area_mm2':retained.Area,'retained_bounds_mm':bbox(retained),'positions':positions,'indices':indices,'normal':[0,0,1],'boundary_polylines':boundaries,'linear_deflection_mm':.005,'boundary_chord_deflection_mm':.005,'arrow':{'anchor_xy_mm':[46.5,9],'lower_z_mm':22.15,'released_upper_z_mm':22.4,'pressed_upper_z_mm':22.15,'upper_z_formula':'22.4 - 0.25 * progress','gap_formula':'0.25 * (1 - progress)','anchor_on_actual_contact_surface_distance_mm':anchor_shelf_distance,'released_upper_anchor_on_flange':True,'sampled_gap_interior':interior,'rendering_note':'Coordinates are exact on the retained cut face. If needed, offset only the visual overlay slightly toward negative Y to avoid z-fighting; measurements remain at Y9.'},'state_proof':{'released_stop_clearance_mm':released.distToShape(cup)[0],'pressed_stop_distance_mm':pressed.distToShape(cup)[0],'pressed_solid_overlap_volume_mm3':pressed.common(cup).Volume},'mesh_vertices':len(vs),'mesh_triangles':len(ts),'elapsed_seconds':time.time()-START}
assert report['source_unchanged']
path=OUT/'ptt-contact-patch.json';path.write_text(json.dumps(report,separators=(',',':')),encoding='utf-8')
print(json.dumps({'file':str(path),'bytes':path.stat().st_size,'full_area':patch.Area,'retained_area':retained.Area,'triangles':len(ts),'vertices':len(vs),'annulus_area_difference':annular_difference,'bounds':bbox(retained),'state_proof':report['state_proof']},indent=2))
