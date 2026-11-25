"""Read-only exact Boolean local sections for R7 dimension focus views.

View-only meshes: released manufacturing geometry is never modified or saved.
"""
from pathlib import Path
from collections import defaultdict
import base64,gzip,hashlib,json,math,struct,time
import FreeCAD as App,Part,MeshPart

OUT=Path(__file__).resolve().parent;R7=OUT.parents[1];ENC=R7.parent
R6=ENC/'revision-r6-speaker'
NATIVE=R6/'cad/LoRa-Enclosure-C5-R6-Speaker.FCStd'
ELECTRONICS=ENC/'detailed-import/C5-detailed-assembly.step'
DIMENSIONS=OUT.parent/'dimensions/dimensions.json'
DEFLECTION=.04;DECIMALS=3;START=time.time()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
source_hashes={str(p):sha(p)for p in(NATIVE,ELECTRONICS,DIMENSIONS)}
config=json.loads((OUT.parent/'SOURCE-INPUTS.json').read_text())
source_hashes.update(config['source_hashes'])
source_hashes[str(OUT.parent/'SOURCE-INPUTS.json')]=sha(OUT.parent/'SOURCE-INPUTS.json')
assert all(sha(Path(p))==h for p,h in source_hashes.items())
documents={}
def load_extra(record):
 if 'brep' in record:
  shape=Part.Shape();shape.read(record['brep']);return shape
 path=record['native']
 if path not in documents:documents[path]=App.openDocument(path)
 return documents[path].getObject(record['object']).Shape.copy()
def log(s):print(f'[{time.time()-START:.1f}s] {s}',flush=True)
def box(bb):
 x,y,z,X,Y,Z=bb;return Part.makeBox(X-x,Y-y,Z-z,App.Vector(x,y,z))
def bounds(s):
 b=s.BoundBox;return[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def overlaps(b,c):return all(b[k+3]>c[k]+1e-8 and b[k]<c[k+3]-1e-8 for k in range(3))
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

definitions=[
 ('battery_top',[43,30,-17,65,42,7],[55,30,-1.5],0,10,[45,30,-9.5,65,30,6.5]),
 ('battery_pad',[43,35,-17,65,47,1],[55,35,-13.5],0,12,[45,35,-19.5,65,35,-7.5]),
 ('battery_left',[9.5,30,-17,23.5,42,-4],[16.5,30,-12],0,22,[9.5,30,-18,23.5,30,-6]),
 ('battery_right',[46.5,60,-17,60.5,72,-4],[53.5,60,-12],0,22,[46.5,60,-18,60.5,60,-6]),
 ('battery_front',[35,3.5,-17,47,17.5,-4],[35,10.5,-12],-90,22,[35,3.5,-18,35,17.5,-6]),
 ('battery_rear',[35,72.5,-17,47,86.5,-4],[35,79.5,-12],-90,22,[35,72.5,-18,35,86.5,-6]),
 ('pcb_main',[47,50,4,76,63,26],[66,50,14.4825],0,8,[53,50,3,79,50,26]),
 ('pcb_local',[23,58.05,4,42,68,26],[34.1,58.05,14.2325],0,8,[23,58.05,3,45.2,58.05,25.465]),
 ('oled_gap',[22,58.05,14,39,68,26],[30.45,58.05,20.24936],0,5,[24.45,58.05,15.74936,36.45,58.05,24.74936]),
]
views=[dict(id=i,roi_mm=roi,target_mm=target,yaw=yaw,pitch=pitch,frame_mm=frame,
 section_axis='X'if i in('battery_front','battery_rear')else'Y',section_mm=roi[0]if i in('battery_front','battery_rear')else roi[1],
 section_description='Exact capped Boolean intersection of released shapes with local inspection volume; clipped context only.')
 for i,roi,target,yaw,pitch,frame in definitions]

log('Loading R7 changes and immutable retained R6 parts')
native=App.openDocument(str(NATIVE));records=[];native_shapes={}
mapping={'base':'EnclosureBase','lid':'EnclosureLid','plunger':'PTTPlunger','cup':'PTTStopCup','cover':'BatteryCover','battery':'ReferenceBatteryEnvelope'}
for ident,name in mapping.items():
 s=load_extra(config['shapes'][ident]) if ident in ('base','lid') else native.getObject(name).Shape.copy();assert s.isValid();native_shapes[ident]=s
 records.append(dict(id=ident,part=ident,shape=s,bb=bounds(s),source_kind='reference'if ident=='battery'else'printed-cad',source_index=name))
for ident,record in config['shapes'].items():
 if ident in ('base','lid'):continue
 s=load_extra(record);assert s.isValid()
 records.append(dict(id=ident,part=record.get('part',ident),shape=s,bb=bounds(s),source_kind=record.get('kind','reference'),source_index=record.get('object',record.get('brep'))))
pad=box([17,11,-14,53,79,-13])
records.append(dict(id='pad',part='pad',shape=pad,bb=bounds(pad),source_kind='reference',source_index='1 mm padding envelope'))
log('Importing assigned component assembly')
reference=App.newDocument('R7ClearanceFocusReadOnly');Part.insert(str(ELECTRONICS),reference.Name)
objects=[o for o in reference.Objects if hasattr(o,'Shape')and not o.Shape.isNull()];assert len(objects)==2949
for i,obj in enumerate(objects):
 s=obj.Shape.copy();s.translate(App.Vector(0,0,6.4814));bucket,semantic=classify(i,s)
 records.append(dict(id=bucket,part=semantic,shape=s,bb=bounds(s),source_kind='assigned-component',source_index=i))
dimensions={d['id']:d for d in json.loads(DIMENSIONS.read_text())['dimensions']}
parts=[];view_audit=[];dropped=0

def export_faces(view,bucket,semantic,faces,is_cap,kind,indices):
 global dropped
 if not faces:return
 lookup={};positions=[];triangles=[];omitted=0
 for shape in faces:
  mesh=MeshPart.meshFromShape(Shape=shape,LinearDeflection=DEFLECTION,AngularDeflection=.35,Relative=False)
  vs,ts=mesh.Topology;mapped=[]
  for v in vs:
   point=tuple(round(float(c),DECIMALS)for c in(v.x,v.y,v.z))
   if point not in lookup:lookup[point]=len(positions)//3;positions.extend(point)
   mapped.append(lookup[point])
  for tri in ts:
   a,b,c=[mapped[i]for i in tri]
   if len({a,b,c})!=3:omitted+=1;continue
   A=positions[3*a:3*a+3];B=positions[3*b:3*b+3];C=positions[3*c:3*c+3]
   u=[B[i]-A[i]for i in range(3)];v=[C[i]-A[i]for i in range(3)]
   cross=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
   if sum(x*x for x in cross)<1e-14:omitted+=1;continue
   triangles.extend((a,b,c))
 if not triangles:return
 used=sorted(set(triangles));compact={old:i for i,old in enumerate(used)}
 positions=[v for old in used for v in positions[3*old:3*old+3]];triangles=[compact[i]for i in triangles]
 bb=[min(positions[j::3])for j in range(3)]+[max(positions[j::3])for j in range(3)]
 parts.append(dict(id=view['id']+'_'+bucket+('_section'if is_cap else''),part=semantic,variant='focus',focusId=view['id'],
  group='enclosure'if kind=='printed-cad'else'reference'if kind=='reference'else'electronics',
  positions=positions,indices=triangles,bounds=bb,sourceKind=kind,explodeZ=0,isSection=is_cap))
 dropped+=omitted

for view in views:
 roi=view['roi_mm'];clip=box(roi);groups=defaultdict(list);record_groups=defaultdict(list);selected=[];kept_shapes=defaultdict(list);valid=True
 for record in records:
  if not overlaps(record['bb'],roi):continue
  s=record['shape'].common(clip)
  if s.isNull()or s.Area<1e-9:continue
  assert s.isValid(),(view['id'],record['source_index'])
  kept_shapes[record['part']].append(s);selected.append(record['source_index'])
  for face in s.Faces:
   bb=bounds(face)
   cap=any(abs(bb[k]-p)<1e-6 and abs(bb[k+3]-p)<1e-6 for k in range(3)for p in(roi[k],roi[k+3]))
   key=(record['id'],record['part'],cap,record['source_kind'])
   groups[key].append(face);record_groups[key].append(record['source_index'])
 for (bucket,semantic,cap,kind),faces in groups.items():export_faces(view,bucket,semantic,faces,cap,kind,record_groups[(bucket,semantic,cap,kind)])
 witness_checks=[];dimension=dimensions[view['id']]
 for part,point in zip(dimension['anchor_parts'],(dimension['witness_start_mm'],dimension['witness_end_mm'])):
  part='pcb'if part=='pcb_mask'else part
  surface=Part.makeCompound([f for s in kept_shapes[part]for f in s.Faces])
  distance=surface.distToShape(Part.Vertex(App.Vector(*point)))[0]
  witness_checks.append(dict(part=part,point_mm=point,distance_to_retained_surface_mm=distance,ok=distance<1e-6))
  assert distance<1e-6,(view['id'],part,point,distance)
 vp=[p for p in parts if p['focusId']==view['id']]
 view_audit.append(dict(id=view['id'],roi_mm=roi,valid_shapes=True,source_indices=selected,parts=len(vp),
  triangles=sum(len(p['indices'])//3 for p in vp),cap_triangles=sum(len(p['indices'])//3 for p in vp if p['isSection']),witness_checks=witness_checks))
 log(f"{view['id']}: {len(vp)} meshes / {view_audit[-1]['triangles']} triangles; witnesses passed")

metadata=dict(source_revision='R7',source_hashes=source_hashes,views=views,
 section='All focus geometry is exact Boolean intersection with the listed inspection ROI; section caps are tessellated native faces.',
 source_component_object_count=2949,linear_deflection_mm=DEFLECTION,coordinate_rounding_max_mm=.0005,
 limitations=['Cutaways remove neighboring context for inspection only; original CAD remains unchanged.',
 'Battery and pad are conservative fit envelopes, not manufacturer-qualified models.',
 'OLED 0.50 mm value is a Z datum offset between separated surfaces, not minimum glass-to-lid distance.'])
data=dict(schema=1,units='mm',parts=parts,metadata=metadata)
(OUT/'focus-mesh-data.json').write_text(json.dumps(data,separators=(',',':')))
(OUT/'focus-views.json').write_text(json.dumps(views,indent=2)+'\n')
out=bytearray();headers=[]
def varint(n):
 n=n*2 if n>=0 else -n*2-1
 while n>=128:out.append((n&127)|128);n>>=7
 out.append(n)
for part in parts:
 header={k:v for k,v in part.items()if k not in('positions','indices')};header['vertices']=len(part['positions'])//3;header['indexCount']=len(part['indices']);header['byteOffset']=len(out)
 prev=[0,0,0]
 for i,x in enumerate(part['positions']):
  q=round(x*1000);axis=i%3;varint(q-prev[axis]);prev[axis]=q
 previous=0
 for i in part['indices']:varint(i-previous);previous=i
 header['byteLength']=len(out)-header['byteOffset'];headers.append(header)
header=json.dumps(dict(schema=2,codec='xyz-millimetre-1000-axis-delta-zigzag-varint;index-delta-zigzag-varint',units='mm',parts=headers,metadata=metadata),separators=(',',':')).encode()
packed=struct.pack('<I',len(header))+header+out
compressed=gzip.compress(packed,compresslevel=9,mtime=0);encoded=base64.b64encode(compressed)
(OUT/'focus-mesh-data.packed.gz').write_bytes(compressed);(OUT/'focus-mesh-data.b64').write_bytes(encoded)
assert gzip.decompress(base64.b64decode(encoded))==packed
unchanged={p:sha(Path(p))==h for p,h in source_hashes.items()};assert all(unchanged.values())
report=dict(ok=True,views=len(views),parts=len(parts),triangles=sum(len(p['indices'])//3 for p in parts),
 base64_bytes=len(encoded),target_base64_bytes=300000,within_target=len(encoded)<300000,
 source_hashes=source_hashes,source_files_unchanged=unchanged,view_audit=view_audit,
 packed_sha256=sha(OUT/'focus-mesh-data.packed.gz'),mesh_data_sha256=sha(OUT/'focus-mesh-data.json'),
 views_sha256=sha(OUT/'focus-views.json'),coordinate_rounding_max_mm=.0005,omitted_quantization_degenerates=dropped,
 elapsed_seconds=time.time()-START)
(OUT/'FOCUS-MESH-VALIDATION.json').write_text(json.dumps(report,indent=2)+'\n')
dimension_report=dict(ok=True,source_revision='R7',source_hashes=source_hashes,source_files_unchanged=unchanged,
 dimensions_sha256=sha(DIMENSIONS),witness_checks=[dict(dimension=v['id'],**w)for v in view_audit for w in v['witness_checks']],
 source_component_object_count=2949,component_translation_mm=[0,0,6.4814],
 evidence='All nine local sections regenerated from current R7 input shapes and actual component geometry; both endpoints of each dimension remain on retained surfaces.',native_cad_modified=False)
(OUT.parent/'dimensions/DIMENSION-VALIDATION.json').write_text(json.dumps(dimension_report,indent=2)+'\n')
App.closeDocument(reference.Name);App.closeDocument(native.Name)
for doc in documents.values():App.closeDocument(doc.Name)
print(json.dumps({k:v for k,v in report.items()if k not in('view_audit','source_hashes')},indent=2))
