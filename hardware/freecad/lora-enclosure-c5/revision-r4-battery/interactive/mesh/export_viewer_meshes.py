"""Read-only tessellation of released R4 solids and all assigned C5 components.

These display meshes are not replacement manufacturing exports.
"""
from pathlib import Path
from collections import defaultdict
import base64,gzip,hashlib,json,math,time
import FreeCAD as App,Part,MeshPart

OUT=Path(__file__).resolve().parent
R4=OUT.parents[1];ENCLOSURE=R4.parent
NATIVE=R4/'cad/LoRa-Enclosure-C5-R4-Battery.FCStd'
ELECTRONICS=ENCLOSURE/'detailed-import/C5-detailed-assembly.step'
DEFLECTION=.08;DECIMALS=3;START=time.time()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
sources={str(p):sha(p)for p in(NATIVE,ELECTRONICS)}
def log(text):print(f'[{time.time()-START:.1f}s] {text}',flush=True)
def bounds(s):
 b=s.optimalBoundingBox(False,False)
 return[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def box(bb):
 x0,y0,z0,x1,y1,z1=bb;return Part.makeBox(x1-x0,y1-y0,z1-z0,App.Vector(x0,y0,z0))
colors={'base':[.12,.20,.27],'lid':[.72,.79,.82],'plunger':[.98,.26,.035],
 'cup':[.16,.65,.40],'cover':[.30,.48,.62],'battery':[.13,.63,.39],
 'pad':[.34,.38,.40],'plug':[.82,.83,.79],'lead_positive':[.82,.06,.025],'lead_negative':[.08,.08,.08],
 'pcb_substrate':[.26,.08,.40],'pcb_pads':[.80,.64,.22],'pcb_markings':[.85,.85,.85],
 'heltec_board':[.08,.11,.13],'heltec_chips':[.16,.17,.18],'heltec_metal':[.65,.68,.70],
 'heltec_pins':[.82,.65,.20],'oled':[.035,.045,.05],'microphone':[.34,.27,.08],
 'amplifier':[.34,.12,.44],'switch':[.20,.22,.23],'resistor':[.70,.56,.34]}
labels={'base':'R4 enclosure base','lid':'R3-fit enclosure lid','plunger':'PTT plunger','cup':'PTT stop cup',
 'cover':'Removable battery cover','battery':'68 x 36 x 10 mm battery envelope','pad':'1 mm padding allowance',
 'plug':'Provisional battery plug','lead_positive':'Provisional positive lead','lead_negative':'Provisional negative lead',
 'pcb':'C5 carrier PCB','heltec':'Heltec V4 assembly','oled':'OLED / bracket supplement','microphone':'Round INMP441 module',
 'amplifier':'MAX98357A module','switch':'SW1 tactile switch','resistor':'R8 axial resistor'}
offsets={'base':-30,'lid':80,'plunger':55,'cup':35,'cover':-90,'battery':-60,'pad':-60}
parts=[];audit=[];dropped=0

def export_shapes(ident,semantic,shape_list,variant='full',color=None,source_kind='assigned-component',source_records=None):
 global dropped
 lookup={};positions=[];indices=[];raw_triangles=0;local_dropped=0
 bbs=[]
 for shape in shape_list:
  if shape.isNull():continue
  bbs.append(bounds(shape))
  mesh=MeshPart.meshFromShape(Shape=shape.cleaned(),LinearDeflection=DEFLECTION,AngularDeflection=.5,Relative=False)
  vs,ts=mesh.Topology
  mapped=[]
  for v in vs:
   point=tuple(round(float(c),DECIMALS)for c in(v.x,v.y,v.z))
   if point not in lookup:
    lookup[point]=len(positions)//3;positions.extend(point)
   mapped.append(lookup[point])
  for tri in ts:
   raw_triangles+=1
   a,b,c=[mapped[i]for i in tri]
   if a==b or a==c or b==c:local_dropped+=1;continue
   A=positions[3*a:3*a+3];B=positions[3*b:3*b+3];C=positions[3*c:3*c+3]
   u=[B[i]-A[i]for i in range(3)];v=[C[i]-A[i]for i in range(3)]
   cross=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
   if sum(x*x for x in cross)<1e-14:local_dropped+=1;continue
   indices.extend((a,b,c))
 if not indices:return
 # Remove unused quantized vertices caused by microscopic degenerate faces.
 used=sorted(set(indices));compact={old:i for i,old in enumerate(used)}
 positions=[v for old in used for v in positions[3*old:3*old+3]]
 indices=[compact[i]for i in indices]
 bb=[min(positions[j::3])for j in range(3)]+[max(positions[j::3])for j in range(3)]
 original=[min(b[j]for b in bbs)for j in range(3)]+[max(b[j+3]for b in bbs)for j in range(3)]
 inside=all(bb[i]>=original[i]-.001 and bb[i+3]<=original[i+3]+.001 for i in range(3))
 assert inside,(ident,bb,original)
 group='enclosure'if semantic in('base','lid','cover','plunger','cup')else'reference'if source_kind=='reference'else'electronics'
 parts.append(dict(id=ident,part=semantic,group=group,variant=variant,label=labels[semantic],positions=positions,indices=indices,
                   color=color or colors.get(ident,colors.get(semantic)),bounds=bb,sourceKind=source_kind,
                   explodeZ=offsets.get(semantic,0)if variant=='full'else 0))
 audit.append(dict(id=ident,part=semantic,variant=variant,source_indices=source_records,source_kind=source_kind,
                   source_shapes=len(shape_list),mesh_vertices=len(positions)//3,mesh_triangles=len(indices)//3,
                   source_bounds_mm=original,mesh_bounds_mm=bb,within_source_bounds_plus_quantization=inside,
                   quantization_degenerate_triangles_omitted=local_dropped))
 dropped+=local_dropped
 log(f'{ident}: {len(indices)//3} triangles / {len(positions)//3} vertices')

log('Open R4 native CAD read-only')
native=App.openDocument(str(NATIVE))
mapping={'base':'EnclosureBase','lid':'EnclosureLid','plunger':'PTTPlunger','cup':'PTTStopCup','cover':'BatteryCover','battery':'ReferenceBatteryEnvelope'}
cut_boxes=[box([-20,-20,-25,85,30,40]),box([70,-20,-25,85,84,40])]
for ident,name in mapping.items():
 shape=native.getObject(name).Shape.copy()
 assert shape.isValid()
 source_kind='reference'if ident=='battery'else'printed-cad'
 export_shapes(ident,ident,[shape],source_kind=source_kind)
 if ident in('base','lid','cover'):
  cut=shape.cut(cut_boxes[0]).cut(cut_boxes[1]).removeSplitter();assert cut.isValid()
  caps=[];surfaces=[]
  for face in cut.Faces:
   b=face.BoundBox
   is_cap=(abs(b.YMin-30)<1e-6 and abs(b.YMax-30)<1e-6)or(abs(b.XMin-70)<1e-6 and abs(b.XMax-70)<1e-6)or(abs(b.YMin-84)<1e-6 and abs(b.YMax-84)<1e-6)
   (caps if is_cap else surfaces).append(face)
  export_shapes(ident+'_cut',ident,surfaces,variant='cut',source_kind='printed-cad')
  export_shapes(ident+'_cut_section',ident,caps,variant='cut',color=[.88,.64,.31],source_kind='printed-cad')
export_shapes('pad','pad',[box([17,11,-14,53,79,-13])],source_kind='reference')
route=json.loads((R4/'audit/rear-harness-predictive-report.json').read_text())
export_shapes('plug','plug',[box(route['plug_assumed_bounds_mm'])],source_kind='reference')
for ident,dx in(('lead_positive',-.4),('lead_negative',.4)):
 points=[App.Vector(x+dx,y,z)for x,y,z in route['lead_centerline_mm']];shapes=[]
 for a,b in zip(points,points[1:]):
  d=b-a
  if d.Length>1e-8:shapes.append(Part.makeCylinder(.35,d.Length,a,d))
 shapes.extend(Part.makeSphere(.35,p)for p in points[1:-1])
 export_shapes(ident,ident,shapes,source_kind='reference')

log('Import corrected assigned-model assembly')
reference=App.newDocument('InteractiveR4ReferenceReadOnly');Part.insert(str(ELECTRONICS),reference.Name)
objects=[o for o in reference.Objects if hasattr(o,'Shape')and not o.Shape.isNull()]
assert len(objects)==2949
buckets=defaultdict(list);bucket_indices=defaultdict(list);semantics={}
def classify(i,s):
 if i==0:return'switch','switch'
 if 889<=i<=1066:return'pcb_pads','pcb'
 if i==1067 or i in(2947,2948):return'pcb_substrate','pcb'
 if 1068<=i<=1714:return'microphone','microphone'
 if 1715<=i<=2137:return'amplifier','amplifier'
 if 2138<=i<=2144:return'resistor','resistor'
 if 2811<=i<=2830:return'oled','oled'
 if i>=2831:return'pcb_markings','pcb'
 b=s.BoundBox;spans=sorted((b.XLength,b.YLength,b.ZLength))
 if i==1:return'heltec_board','heltec'
 if spans[0]<.9 and spans[1]<1.8 and spans[2]>1:return'heltec_pins','heltec'
 if b.ZMin>13.8 and b.ZLength>1.4 and b.YMax>80:return'heltec_metal','heltec'
 return'heltec_chips','heltec'
for i,obj in enumerate(objects):
 shape=obj.Shape.copy();shape.translate(App.Vector(0,0,6.4814))
 bucket,semantic=classify(i,shape);buckets[bucket].append(shape);bucket_indices[bucket].append(i);semantics[bucket]=semantic
for bucket,shapes in buckets.items():
 export_shapes(bucket,semantics[bucket],shapes,source_records=bucket_indices[bucket])

data=dict(schema=1,units='mm',parts=parts,metadata=dict(
 source_revision='R4',axes='X left/right, Y front/back, Z up; carrier nominal top Z8',
 sources=sources,linear_deflection_mm=DEFLECTION,coordinate_decimal_places=DECIMALS,
 coordinate_rounding_max_mm=.0005,color_source='Semantic illustration palette, not exact original STEP face colors.',
 section='Real Boolean cut surfaces; housing material removed for Y<30 and X>70/Y<84. Electronics retained complete.',
 exploded_offsets_mm=offsets,battery_envelope_mm=[68,36,10],battery_is_reference=True,
 original_component_objects=2949,component_geometry='All assigned component and carrier shapes from corrected KiCad STEP; no component proxy blocks.',
 limitations=['Battery/pad/plug/wires are provisional fit envelopes.','Small triangles collapsed by 0.001 mm display rounding are omitted; original CAD is unchanged.','Display tessellation is for inspection, not metrology or manufacturing.','Exploded gaps are presentation offsets, not assembly clearances.']))
raw=json.dumps(data,separators=(',',':')).encode()
compressed=gzip.compress(raw,compresslevel=9,mtime=0);encoded=base64.b64encode(compressed)
(OUT/'mesh-data.json').write_bytes(raw)
(OUT/'mesh-data.json.gz').write_bytes(compressed)
(OUT/'mesh-data.b64').write_bytes(encoded)
assert gzip.decompress(base64.b64decode(encoded))==raw
unchanged={p:sha(Path(p))==value for p,value in sources.items()}
assert all(unchanged.values())
report=dict(ok=True,parts=len(parts),source_files_unchanged=unchanged,source_hashes=sources,actual_source_object_count=len(objects),
 complete_source_index_coverage=sorted(i for a in bucket_indices.values()for i in a)==list(range(2949)),
 raw_bytes=len(raw),gzip_bytes=len(compressed),base64_bytes=len(encoded),target_base64_bytes=750000,
 within_target=len(encoded)<750000,total_triangles=sum(len(p['indices'])//3 for p in parts),
 omitted_quantization_degenerates=dropped,part_audit=audit,mesh_sha256=sha(OUT/'mesh-data.json'),
 compressed_sha256=sha(OUT/'mesh-data.json.gz'),elapsed_seconds=time.time()-START)
(OUT/'MESH-VALIDATION.json').write_text(json.dumps(report,indent=2)+'\n')
App.closeDocument(reference.Name);App.closeDocument(native.Name)
print(json.dumps({k:v for k,v in report.items()if k!='part_audit'},indent=2))
