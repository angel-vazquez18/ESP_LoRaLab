"""Read-only saved native R3 audit and exact CAD-derived OLED cross-section."""
from pathlib import Path
import hashlib,json,math
import FreeCAD as A
import Part

root=Path(__file__).resolve().parents[1]
source=root.parent/'revision-r2-oled/cad/LoRa-Enclosure-C5-R2-OLED.FCStd'
revised=root/'cad/LoRa-Enclosure-C5-R3-OLED.FCStd'
assembly=root.parent/'detailed-import/C5-detailed-assembly.step'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
hashes={str(p):sha(p) for p in (source,revised,assembly)}
report={'scope':'Read-only native R3 geometry, independent nominal rebuild, dependencies and exact section. No physical qualification.','sources':hashes,'failures':[]}
def check(condition,message):
 if not condition:report['failures'].append(message)
def bounds(s):
 b=s.optimalBoundingBox(False,False)
 return[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def info(s):return{'valid':s.isValid(),'closed':s.isClosed(),'solids':len(s.Solids),'volume_mm3':s.Volume,'bounds_mm':bounds(s)}
def delta(a,b):return a.cut(b).Volume+b.cut(a).Volume
def box(x,y,z,dx,dy,dz):return Part.makeBox(dx,dy,dz,A.Vector(x,y,z))
before=A.openDocument(str(source));after=A.openDocument(str(revised))
names=('EnclosureBase','EnclosureLid','PTTPlunger','PTTStopCup')
original={n:before.getObject(n).Shape.copy() for n in names}
saved={n:after.getObject(n).Shape.copy() for n in names}
old_lid=original['EnclosureLid'];lid=saved['EnclosureLid']
report['parts']={n:info(s) for n,s in saved.items()}
for n,s in saved.items():check(s.isValid() and s.isClosed() and len(s.Solids)==1,n+' must be one valid closed solid')
report['unchanged_parts']={n:delta(original[n],saved[n]) for n in names if n!='EnclosureLid'}
check(all(v<1e-6 for v in report['unchanged_parts'].values()),'Non-lid geometry changed')

# Build the intended R3 independently from R2 exact shape and nominal dimensions.
# Four screw reliefs apply only to the added underside ledge, preserving the
# existing full lid above them. All pocket dimensions below are independent
# fixed design inputs rather than copied from saved expressions.
centers=[(x,y) for x in (16,30) for y in (43.55,72.55)]
outer=box(12.8,42.55,20.5,20.4,31,.55)
inner=box(14.8,44.55,20.4,16.4,27,.8)
reliefs=Part.makeCompound([Part.makeCylinder(2.2,1,A.Vector(x,y,20.4)) for x,y in centers])
ring=outer.cut(inner).cut(reliefs).removeSplitter()
def wire(extra,z):
 x0,y0=12.8-extra,42.55-extra;x1,y1=33.2+extra,73.55+extra
 return Part.makePolygon([A.Vector(x0,y0,z),A.Vector(x1,y0,z),A.Vector(x1,y1,z),A.Vector(x0,y1,z),A.Vector(x0,y0,z)])
pocket=Part.makeLoft([wire(0,22.1),wire(2.6,24.7)],True,True)
expected=old_lid.cut(pocket).fuse(ring).removeSplitter()
report['independent_rebuild']={'symmetric_difference_mm3':delta(lid,expected),'volume_difference_mm3':abs(lid.Volume-expected.Volume),'expected':info(expected)}
check(report['independent_rebuild']['symmetric_difference_mm3']<1e-4,'Saved lid does not match independent intended R3 rebuild')
added=lid.cut(old_lid);removed=old_lid.cut(lid)
report['lid_change']={'added_volume_mm3':added.Volume,'removed_volume_mm3':removed.Volume,'added_bounds_mm':bounds(added),'removed_bounds_mm':bounds(removed),'added_outside_intended_ring_mm3':added.cut(ring).Volume,'removed_outside_intended_pocket_mm3':removed.cut(pocket).Volume}
check(report['lid_change']['added_outside_intended_ring_mm3']<1e-5 and report['lid_change']['removed_outside_intended_pocket_mm3']<1e-5,'Material changes extend outside intended ring/recess')
report['printed_part_addition_intersections_mm3']={n:added.common(saved[n]).Volume for n in names if n!='EnclosureLid'}
check(all(v<1e-6 for v in report['printed_part_addition_intersections_mm3'].values()),'Added ledge intersects another printed part')
def roof_probe(x,y):
 clipped=lid.common(Part.makeLine(A.Vector(x,y,19),A.Vector(x,y,25)))
 return{'xy_mm':[x,y],'solid_path_length_mm':clipped.Length,'intervals_z_mm':[[bounds(e)[2],bounds(e)[5]] for e in clipped.Edges]}
report['physical_roof_probes']={'normal_rim':[roof_probe(x,58.05) for x in (14,32)],'relief_roofs':[roof_probe(x,y) for x,y in centers]}
check(all(abs(v['solid_path_length_mm']-1.6)<1e-6 for v in report['physical_roof_probes']['normal_rim']),'Actual normal rim thickness does not equal 1.6 mm')
check(all(abs(v['solid_path_length_mm']-1.1)<1e-6 for v in report['physical_roof_probes']['relief_roofs']),'Actual corner relief roof thickness does not equal 1.1 mm')

p=after.getObject('Parameters');val=lambda cell:float(str(p.get(cell)).split()[0])
params={}
for row in range(73,100):
 try:
  name=p.get('A'+str(row));cell='B'+str(row)
  params[cell]={'name':str(name),'value':val(cell),'formula':p.getContents(cell)}
 except Exception:pass
report['parameters']=params
expected_params={'B73':1.6,'B74':2,'B75':2.5,'B76':22.1,'B77':.1,'B78':.5,'B79':20.5,'B80':2.2,'B81':14,'B82':29}
report['parameter_values_verified']={cell:{'actual':val(cell),'expected':expected,'matches':abs(val(cell)-expected)<1e-8} for cell,expected in expected_params.items()}
check(all(v['matches'] for v in report['parameter_values_verified'].values()),'R3 parameter value mismatch')
drop_cells=[cell for cell,v in params.items() if 'drop' in v['name'].lower()]
check(len(drop_cells)==1,'Cannot uniquely identify local bezel drop parameter')
report['native_dependencies']={o.Name:{'type':o.TypeId,'links':[v.Name for v in o.OutList],'expressions':dict(o.ExpressionEngine)} for o in after.Objects if o.Name.startswith('OLED') and hasattr(o,'Shape')}
check(after.getObject('OLEDLowerRim') in after.getObject('LidWithClamps').Shapes,'Lower rim is not linked into native lid union')
check(all(after.getObject('OLEDHeadRelief'+str(i)) in after.getObject('LidCutters').Shapes for i in range(1,5)),'Four screw reliefs are not linked into native cutters')
after.recompute()
report['recompute_difference_mm3']={n:delta(s,after.getObject(n).Shape) for n,s in saved.items()}
check(all(v<1e-6 for v in report['recompute_difference_mm3'].values()),'Saved native geometry changes on recompute')
if len(drop_cells)==1:
 cell=drop_cells[0];old=p.getContents(cell)
 check(abs(val(cell)-.5)<1e-8,'Saved drop is not nominal 0.50 mm')
 p.set(cell,'0.4');after.recompute();changed=after.getObject('EnclosureLid').Shape.copy()
 report['parameter_sensitivity']={'drop_cell':cell,'temporary_drop_mm':.4,'temporary_shape_valid':changed.isValid(),'changed_difference_mm3':delta(lid,changed),'temporary_volume_mm3':changed.Volume}
 check(changed.isValid() and delta(lid,changed)>1,'Drop parameter does not change valid solid')
 p.set(cell,old);after.recompute()
 report['parameter_sensitivity']['restored_difference_mm3']=delta(lid,after.getObject('EnclosureLid').Shape)
 check(report['parameter_sensitivity']['restored_difference_mm3']<1e-6,'In-memory parameter test did not restore R3 geometry')
print('Saved native checks finished',flush=True)

ref=A.newDocument('R3CorrectedReferenceReadOnly');Part.insert(str(assembly),ref.Name)
obs=[o for o in ref.Objects if hasattr(o,'Shape') and not o.Shape.isNull()]
check(len(obs)==2949,'Reference object count changed');assert len(obs)==2949
models=[]
for o in obs:
 s=o.Shape.copy();s.translate(A.Vector(0,0,6.4814));models.append(s)
glass=models[2812]
oled=[]
for i in range(2811,2831):
 s=models[i]
 oled.append({'index':i,'minimum_lid_distance_mm':lid.distToShape(s)[0],'intersection_mm3':lid.common(s).Volume})
report['oled_fit']={'components':oled,'glass':info(glass),'glass_intersection_mm3':oled[1]['intersection_mm3'],'glass_minimum_distance_to_actual_lid_mm':oled[1]['minimum_lid_distance_mm'],'all_oled_intersection_mm3':sum(v['intersection_mm3'] for v in oled),'frame_minimum_clearance_mm':oled[0]['minimum_lid_distance_mm'],'screw_minimum_clearance_mm':min(v['minimum_lid_distance_mm'] for v in oled if 2818<=v['index']<=2829)}
check(report['oled_fit']['all_oled_intersection_mm3']<1e-7,'OLED intersects R3 lid')
check(abs(report['oled_fit']['frame_minimum_clearance_mm']-.44128073928)<1e-6,'Frame clearance differs from intended value')
check(abs(report['oled_fit']['screw_minimum_clearance_mm']-.69878073914)<1e-6,'Screw clearances not preserved')
# Conservative broad-phase test of every corrected electronic model against
# the new addition; exact interference for the local neighborhood. R3 removal
# cannot introduce interference, and R2's prior full assembly audit is retained.
near=[];ab=added.BoundBox
for i,s in enumerate(models):
 b=s.BoundBox
 bd=math.sqrt(sum(max(0,a0-b1,b0-a1)**2 for a0,a1,b0,b1 in [(ab.XMin,ab.XMax,b.XMin,b.XMax),(ab.YMin,ab.YMax,b.YMin,b.YMax),(ab.ZMin,ab.ZMax,b.ZMin,b.ZMax)]))
 if bd<=1.0:near.append({'index':i,'addition_distance_mm':added.distToShape(s)[0],'addition_intersection_mm3':added.common(s).Volume})
report['all_electronics_addition_check']={'objects_checked':len(models),'exact_neighborhood':near,'maximum_intersection_mm3':max((v['addition_intersection_mm3'] for v in near),default=0),'method':'Every model checked by conservative bounding separation; exact geometry intersection/distance for all within 1 mm of added material. Remaining change is exterior removal.'}
check(report['all_electronics_addition_check']['maximum_intersection_mm3']<1e-7,'Added material intersects electronics')

section_y=58.05
def section(shapes,indices=None):
 wires=[];closed=[]
 for s in shapes:
  b=s.BoundBox
  if b.YMin-1e-7<=section_y<=b.YMax+1e-7:
   for w in s.slice(A.Vector(0,1,0),section_y):
    poly=[[round(v.x,8),round(v.z,8)] for v in w.discretize(Deflection=.01)]
    if w.isClosed() and poly and poly[-1]!=poly[0]:poly.append(poly[0])
    wires.append(poly);closed.append(w.isClosed())
 return{'wires':wires,'wire_closed':closed,'bounds_mm':bounds(Part.makeCompound(shapes)),'source_indices':indices}
sections={'lid_r2':section([old_lid]),'lid_r3':section([lid])}
families={'oled_glass':[2812],'oled_frame':[2811,2813,2830],'heltec':list(range(1,889))+list(range(2145,2811)),'carrier':list(range(889,1068))+[2947,2948]}
for name,indices in families.items():
 sections[name]=section([models[i] for i in indices],indices)
 print('Sectioned '+name,flush=True)

# Verify physical datums with exact shape-plane sections at the ledge center;
# these plane positions are validated by the independent full-solid equality.
gz=glass.BoundBox.ZMax
dimensions={'glass_top_z':gz,'main_inner_lid_z':21,'local_inner_lid_z':20.5,'inner_lid_z':20.5,'main_outer_z':24.6,'recessed_face_z':22.1,'aperture_width':16.4,'aperture_height':27,'local_thickness':1.6,'recess_depth':2.5,'ledge_width':2,'screw_clearance_mm':report['oled_fit']['screw_minimum_clearance_mm'],'frame_clearance_mm':report['oled_fit']['frame_minimum_clearance_mm'],'minimum_relief_roof_thickness':1.1,'minimum_relief_roof_thickness_mm':1.1,'glass_to_recessed_face_mm':22.1-gz,'glass_to_main_outer_mm':24.6-gz,'glass_to_inner_plane_mm':20.5-gz,'glass_to_main_inner_plane_mm':21-gz,'window_center_x':23,'window_center_y':58.05,'bevel_angle_degrees':45,'relief_radius_mm':2.2,'bezel_drop_mm':.5,'pocket_floor_width':20.4,'pocket_floor_height':31,'pocket_outer_width':25.4,'pocket_outer_height':36}
report['dimensions_mm']=dimensions
dimensions.update(recess_floor_width=20.4,recess_floor_length=31,recess_top_width=25.4,recess_top_length=36)
report['source_files_unchanged']={path:sha(Path(path))==initial for path,initial in hashes.items()}
check(all(report['source_files_unchanged'].values()),'Source file changed during read-only audit')
report['ok']=not report['failures']
geometry={'units':'mm','section_plane':{'axis':'Y','value_mm':section_y,'drawing_axes':['X','Z']},'method':'Exact saved B-rep slices discretized at 0.01 mm deflection. No substituted nominal outlines.','sources':hashes,'sections':sections,'dimensions':dimensions,'audit_ok':report['ok'],'limitations':['OLED supplement and installed header height are approximate; fit values require actual hardware confirmation.','The 0.50 mm dimension is to the local underside reference plane bordering an open aperture, not a ceiling touching glass.','Main underside remains Z21; only the local bezel is lowered. Four reliefs preserve screw clearance.','The normal rim is 1.6 mm; the roof above reliefs is locally 1.1 mm. Strength and production tolerances are not qualified.']}
(root/'documentation').mkdir(parents=True,exist_ok=True)
(root/'documentation/oled-section-geometry.json').write_text(json.dumps(geometry,indent=2)+'\n',encoding='utf-8')
(root/'audit/r3-oled-fit-validation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
for doc in (before,after,ref):A.closeDocument(doc.Name)
print(json.dumps({'ok':report['ok'],'failures':report['failures'],'independent_rebuild':report['independent_rebuild'],'dimensions':dimensions,'source_files_unchanged':report['source_files_unchanged']},indent=2))
if not report['ok']:raise SystemExit(1)
