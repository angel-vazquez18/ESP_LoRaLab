"""Read-only R5 display tessellation, retaining unchanged R4 assigned geometry.

Run with FreeCAD's bundled Python. Never writes a manufacturing document.
"""
from pathlib import Path
import hashlib,json,runpy,time
import FreeCAD as App,Part,MeshPart

OUT=Path(__file__).resolve().parent
R5=OUT.parents[1];ENCLOSURE=R5.parent;R4=ENCLOSURE/'revision-r4-battery'
NATIVE=R5/'cad/LoRa-Enclosure-C5-R5-SMA.FCStd'
R4_NATIVE=R4/'cad/LoRa-Enclosure-C5-R4-Battery.FCStd'
ELECTRONICS=ENCLOSURE/'detailed-import/C5-detailed-assembly.step'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(NATIVE)=='b2c616f78a5f2515217f5c06ec199f38b0106067289fdab60a29e0879d1d9678'
assert sha(R4_NATIVE)=='2ce40bd7f99df5cf6a079d0178c988ab2c42ab040630e65c8de78022cdb164aa'
assert sha(ELECTRONICS)=='65143fecb376c40ac75cf7b3b2ffdf477c9ff656706a80c1fda63717d1041a19'
previous=json.loads((R4/'interactive/mesh/mesh-data-full.json').read_bytes())
old_audit=json.loads((R4/'interactive/mesh/MESH-VALIDATION.json').read_bytes())
assert old_audit['complete_source_index_coverage'] and old_audit['actual_source_object_count']==2949
assert all(sha(Path(p))==v for p,v in old_audit['source_hashes'].items())
assert sha(R4/'interactive/mesh/mesh-data-full.json')==old_audit['mesh_sha256']

# Reuse the established quantized tessellator, not the old script's execution.
helper_source=(R4/'interactive/mesh/export_viewer_meshes.py').read_text()
helper_source=helper_source[:helper_source.index("log('Open R4 native CAD read-only')")]
context={'__file__':str(R4/'interactive/mesh/export_viewer_meshes.py')}
exec(compile(helper_source,'R4 tessellation helper','exec'),context)
export_shapes=context['export_shapes'];parts=context['parts'];audit=context['audit']
box=context['box'];bounds=context['bounds']
context['labels'].update(base='R5 enclosure base with SMA mount',lid='R5 enclosure lid',
 sma_body='Provisional SMA bulkhead body',sma_washer='Provisional SMA lock washer',
 sma_nut='Provisional SMA retaining nut',antenna='Provisional 50 x 8 mm antenna')
context['colors'].update(sma_body=[.77,.59,.23],sma_washer=[.81,.67,.31],
 sma_nut=[.76,.61,.23],antenna=[.12,.13,.14])
context['offsets'].update(sma_body=-30,sma_washer=-30,sma_nut=-30,antenna=-30)

native=App.openDocument(str(NATIVE))
prior=App.openDocument(str(R4_NATIVE))
retained_checks=[]
for ident,name in {'plunger':'PTTPlunger','cup':'PTTStopCup','cover':'BatteryCover','battery':'ReferenceBatteryEnvelope'}.items():
 a=native.getObject(name).Shape;b=prior.getObject(name).Shape
 difference=a.cut(b).Volume+b.cut(a).Volume
 assert difference<1e-7,(ident,difference)
 retained_checks.append(dict(part=ident,native_symmetric_difference_mm3=difference))

for part in previous['parts']:
 if part['part'] not in ('base','lid'):
  parts.append(part)
for entry in old_audit['part_audit']:
 if entry['part'] not in ('base','lid'):
  audit.append(dict(entry,reused_identically_from_R4=True))

cut_bounds=[[-20,-20,-25,85,30,40],[70,-20,-25,85,84,40]]
rear_roof=[18,30,19,66,96,40]
for ident,name in [('base','EnclosureBase'),('lid','EnclosureLid')]:
 shape=native.getObject(name).Shape.copy();assert shape.isValid()
 export_shapes(ident,ident,[shape],source_kind='printed-cad')
 cutters=cut_bounds+([rear_roof] if ident=='lid' else [])
 cut=shape
 for b in cutters:cut=cut.cut(box(b))
 cut=cut.removeSplitter();assert cut.isValid()
 caps=[];surfaces=[]
 for face in cut.Faces:
  fb=bounds(face)
  # A planar new cut face lies on a cutter boundary and was not a source face.
  plane=any(any(abs(fb[axis]-b[axis+side])<1e-6 and abs(fb[axis+3]-b[axis+side])<1e-6 for side in (0,3)) for b in cutters for axis in range(3))
  new_face=plane and face.common(shape).Area>1e-8 and not any(face.common(original).Area>=face.Area-1e-7 for original in shape.Faces)
  (caps if new_face else surfaces).append(face)
 export_shapes(ident+'_cut',ident,surfaces,variant='cut',source_kind='printed-cad')
 export_shapes(ident+'_cut_section',ident,caps,variant='cut',color=[.88,.64,.31],source_kind='printed-cad')

axis=App.Vector(0,1,0)
def tube_cut(shape,r,y0,y1):return shape.cut(Part.makeCylinder(r,y1-y0,App.Vector(47,y0,14),axis))
hardware={
 'sma_rear':('sma_body','ReferenceSMARearBody',None),
 'sma_stud':('sma_body','ReferenceSMAStud',None),
 'sma_washer':('sma_washer','ReferenceSMAWasher',(3.3,94.3,95.0)),
 'sma_nut':('sma_nut','ReferenceSMANut',(3.175,94.8,96.7)),
 'antenna_coupler':('antenna','ReferenceAntennaCoupler',(3.175,99.3,103.4)),
 'antenna_body':('antenna','ReferenceAntenna50mm',None)}
for ident,(semantic,name,hole) in hardware.items():
 shape=native.getObject(name).Shape.copy()
 if hole:shape=tube_cut(shape,*hole)
 assert shape.isValid()
 export_shapes(ident,semantic,[shape],source_kind='reference')

route_path=OUT.parent/'routing/route-mesh-data.json'
route_data=json.loads(route_path.read_bytes())
assert route_data['schema']==1 and route_data['units']=='mm'
for part in route_data['parts']:
 assert part['id'] in ('coax','coax_plug') and part['variant']=='full'
 assert len(part['positions'])%3==0 and len(part['indices'])%3==0
 assert min(part['indices'])>=0 and max(part['indices'])<len(part['positions'])//3
 shape=Part.Shape();shape.read(str(OUT.parent/'routing'/(part['id']+'.brep')))
 bb=part['bounds'];original=bounds(shape)
 inside=all(bb[i]>=original[i]-.001 and bb[i+3]<=original[i+3]+.001 for i in range(3))
 assert inside,(part['id'],bb,original)
 parts.append(part)
 audit.append(dict(id=part['id'],part=part['part'],variant='full',source_kind='reference',
  source_shapes=1,mesh_vertices=len(part['positions'])//3,mesh_triangles=len(part['indices'])//3,
  source_bounds_mm=original,mesh_bounds_mm=bb,within_source_bounds_plus_quantization=True,
  source_brep=str(OUT.parent/'routing'/(part['id']+'.brep')),
  quantization_degenerate_triangles_omitted=0))

# Local inspection volumes used by retained R4 close-ups are unchanged in R5.
focus_checks=[]
for view in json.loads((R4/'interactive/focus/focus-views.json').read_bytes()):
 roi=box(view['roi_mm']);checks={}
 for name in ('EnclosureBase','EnclosureLid','BatteryCover','PTTPlunger','PTTStopCup','ReferenceBatteryEnvelope'):
  a=native.getObject(name).Shape.common(roi);b=prior.getObject(name).Shape.common(roi)
  difference=a.cut(b).Volume+b.cut(a).Volume
  assert difference<1e-7,(view['id'],name,difference)
  checks[name]=difference
 focus_checks.append(dict(id=view['id'],symmetric_difference_mm3=checks))

metadata=dict(previous['metadata'])
sources={str(p):sha(p) for p in (NATIVE,R4_NATIVE,ELECTRONICS,route_path,OUT.parent/'routing/coax.brep',OUT.parent/'routing/coax_plug.brep')}
metadata.update(source_revision='R5',sources=sources,
 section='Capped Boolean housing cut: Y<30 plus X>70/Y<84; lid also opens roof X18..66,Y30..96,Z19..40 to expose LoRa port, coax route, SMA backing and coax anchor. Electronics remain complete.',
 cut_boxes_mm={'base':cut_bounds,'lid':cut_bounds+[rear_roof],'cover':cut_bounds},
 exploded_offsets_mm=context['offsets'],sma_axis_mm=[47,92,14],sma_direction=[0,1,0],
 sma_hardware='Provisional native R5 connector and 50x8 mm antenna envelopes. Washer/nut/coupler inner voids derived for display, no dimensional claim about the owned kit.',
 coax_geometry='Provisional 1.32 mm diameter swept service route to the actual top LoRa IPEX location. 4.8 mm centerline bends, 4.14 mm inner radius; actual cable dimensions and usable length unverified. Coax and plug translate rigidly with base in exploded view, disconnected from board.',
 retained_R4_geometry='Unchanged electronics and other part mesh arrays retained exactly after source hash and native retained-part Boolean checks.',
 limitations=previous['metadata']['limitations']+['SMA hardware is a fit reference based on analogue dimensions; actual connector dimensions remain unverified.'])
data=dict(schema=1,units='mm',parts=parts,metadata=metadata)
(OUT/'mesh-data-full.json').write_text(json.dumps(data,separators=(',',':')))
report=dict(ok=True,parts=len(parts),source_hashes=sources,source_files_unchanged={p:sha(Path(p))==v for p,v in sources.items()},
 actual_source_object_count=2949,complete_source_index_coverage=True,retained_native_checks=retained_checks,
 retained_focus_ROI_checks=focus_checks,part_audit=audit,total_triangles=sum(len(p['indices'])//3 for p in parts),
 omitted_quantization_degenerates=sum(a.get('quantization_degenerate_triangles_omitted',0) for a in audit),
 target_base64_bytes=750000,geometric_decimation_applied=False)
(OUT/'FULL-MESH-VALIDATION.json').write_text(json.dumps(report,indent=2)+'\n')
for filename in ('pack_display_meshes.py','verify_packed_mesh.py'):
 (OUT/filename).write_text((R4/'interactive/mesh'/filename).read_text())
App.closeDocument(native.Name);App.closeDocument(prior.Name)
runpy.run_path(str(OUT/'pack_display_meshes.py'),run_name='__main__')
runpy.run_path(str(OUT/'verify_packed_mesh.py'),run_name='__main__')
