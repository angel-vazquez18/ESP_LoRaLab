"""Prove R4 clearance-view geometry and dimensions are unchanged in saved R5.

Reads native CAD only. Reuses audited tessellation bytes after exact local CAD
comparison; only packed metadata is updated to identify the R5 evidence.
"""
from pathlib import Path
import base64,gzip,hashlib,json,struct,time
import FreeCAD as A,Part

OUT=Path(__file__).resolve().parent
R5=OUT.parents[1];ENC=R5.parent;R4=ENC/'revision-r4-battery'
OLD=R4/'cad/LoRa-Enclosure-C5-R4-Battery.FCStd'
NEW=R5/'cad/LoRa-Enclosure-C5-R5-SMA.FCStd'
STEP=ENC/'detailed-import/C5-detailed-assembly.step'
OLDI=R4/'interactive';DOUT=OUT.parent/'dimensions'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
load=lambda p:json.loads(p.read_text(encoding='utf-8'))
write=lambda p,x:p.write_text(json.dumps(x,indent=2)+'\n',encoding='utf-8')
OUT.mkdir(parents=True,exist_ok=True);DOUT.mkdir(parents=True,exist_ok=True)
started=time.time()
previous_focus=load(OLDI/'focus/FOCUS-MESH-VALIDATION.json')
previous_dimension=load(OLDI/'dimensions/DIMENSION-VALIDATION.json')
assert previous_focus['ok'] and previous_focus['packed_round_trip_exact']
assert previous_dimension['ok']
for report in (previous_focus,previous_dimension):
 for path,value in report['source_hashes'].items():assert sha(Path(path))==value,path
assert sha(NEW)=='b2c616f78a5f2515217f5c06ec199f38b0106067289fdab60a29e0879d1d9678'
sources={str(p):sha(p) for p in (OLD,NEW,STEP,OLDI/'focus/focus-mesh-data.b64',OLDI/'focus/focus-views.json',OLDI/'dimensions/dimensions.json')}
views=load(OLDI/'focus/focus-views.json')
mapping={'base':'EnclosureBase','lid':'EnclosureLid','plunger':'PTTPlunger','cup':'PTTStopCup','cover':'BatteryCover','battery':'ReferenceBatteryEnvelope'}
old=A.openDocument(str(OLD));new=A.openDocument(str(NEW))
oldshapes={k:old.getObject(v).Shape.copy()for k,v in mapping.items()}
newshapes={k:new.getObject(v).Shape.copy()for k,v in mapping.items()}
for shape in [*oldshapes.values(),*newshapes.values()]:assert shape.isValid()

def box(b):
 x,y,z,X,Y,Z=b;return Part.makeBox(X-x,Y-y,Z-z,A.Vector(x,y,z))

def compare_roi(before,after,clip):
 a=before.common(clip);b=after.common(clip)
 # Null/empty regions have no mesh contribution. Solid symmetry is an exact
 # BRep Boolean calculation (numerical acceptance 1e-8 mm^3).
 if a.isNull() and b.isNull():return dict(empty=True,symmetric_difference_mm3=0.0,ok=True)
 assert a.isValid() and b.isValid()
 if not a.Solids and not b.Solids and a.Area<1e-8 and b.Area<1e-8:
  return dict(empty=True,symmetric_difference_mm3=0.0,ok=True)
 difference=a.cut(b).Volume+b.cut(a).Volume
 return dict(empty=False,symmetric_difference_mm3=difference,before_volume_mm3=a.Volume,after_volume_mm3=b.Volume,ok=abs(difference)<1e-8)

comparisons=[]
for view in views:
 clip=box(view['roi_mm']);checks={k:compare_roi(oldshapes[k],newshapes[k],clip)for k in mapping}
 assert all(v['ok']for v in checks.values()),(view['id'],checks)
 comparisons.append(dict(id=view['id'],roi_mm=view['roi_mm'],shape_checks=checks,ok=True))
 print('Exact local comparison passed: '+view['id'],flush=True)

dimensions=load(OLDI/'dimensions/dimensions.json')
new_witnesses=[]
for dim in dimensions['dimensions']:
 for k,point in zip(dim['anchor_parts'],(dim['witness_start_mm'],dim['witness_end_mm'])):
  if k not in newshapes:continue
  distance=newshapes[k].distToShape(Part.Vertex(A.Vector(*point)))[0]
  assert distance<1e-6,(dim['id'],k,distance)
  new_witnesses.append(dict(dimension=dim['id'],part=k,point_mm=point,surface_distance_mm=distance,ok=True))

dimensions['revision']='R5'
dimensions['reuse_evidence']='Exact R4/R5 Boolean ROI comparisons in ../focus/R5-FOCUS-REUSE-VALIDATION.json; identical assigned STEP and placement.'
write(DOUT/'dimensions.json',dimensions)
write(OUT/'focus-views.json',views)
packed=gzip.decompress(base64.b64decode((OLDI/'focus/focus-mesh-data.b64').read_bytes()))
n=struct.unpack_from('<I',packed)[0];header=json.loads(packed[4:4+n]);payload=packed[4+n:]
assert header['schema']==2 and len(header['parts'])==previous_focus['parts']
header['metadata']['source_revision']='R5'
header['metadata']['source_hashes']={str(NEW):sha(NEW),str(STEP):sha(STEP),str(DOUT/'dimensions.json'):sha(DOUT/'dimensions.json')}
header['metadata']['reuse_provenance']={'revision':'R4','reason':'All six native source shapes are unchanged inside all nine exact Boolean inspection ROIs; corrected STEP and +6.4814 mm placement retained.','source_geometry_payload_sha256':hashlib.sha256(payload).hexdigest()}
newheader=json.dumps(header,separators=(',',':')).encode()
newpacked=struct.pack('<I',len(newheader))+newheader+payload
compressed=gzip.compress(newpacked,compresslevel=9,mtime=0);encoded=base64.b64encode(compressed)
(OUT/'focus-mesh-data.packed.gz').write_bytes(compressed)
(OUT/'focus-mesh-data.b64').write_bytes(encoded)
decoded=gzip.decompress(base64.b64decode(encoded));newn=struct.unpack_from('<I',decoded)[0]
assert decoded[4+newn:]==payload
unchanged={p:sha(Path(p))==h for p,h in sources.items()};assert all(unchanged.values())
reuse=dict(ok=True,source_hashes=sources,source_files_unchanged=unchanged,roi_comparisons=comparisons,native_witness_checks=new_witnesses,
 unchanged_component_source_count=2949,component_translation_mm=[0,0,6.4814],component_source_sha256=sha(STEP),
 source_geometry_payload_sha256=hashlib.sha256(payload).hexdigest(),geometry_payload_byte_identical=True,native_cad_modified=False,
 note='Battery/pad remain fit references. OLED is a vertical glass-top to inner-rim datum offset, not minimum solid distance.',elapsed_seconds=time.time()-started)
write(OUT/'R5-FOCUS-REUSE-VALIDATION.json',reuse)
focus=dict(previous_focus)
focus.update(source_revision='R5',source_hashes=sources,source_files_unchanged=unchanged,base64_bytes=len(encoded),
 packed_sha256=sha(OUT/'focus-mesh-data.packed.gz'),views_sha256=sha(OUT/'focus-views.json'),reuse_validation_sha256=sha(OUT/'R5-FOCUS-REUSE-VALIDATION.json'),
 original_R4_mesh_data_sha256=focus.pop('mesh_data_sha256'),geometry_payload_byte_identical=True)
write(OUT/'FOCUS-MESH-VALIDATION.json',focus)
dim_report=dict(previous_dimension)
dim_report.update(source_revision='R5',source_hashes=sources,source_files_unchanged=unchanged,native_R5_witness_checks=new_witnesses,
 dimensions_sha256=sha(DOUT/'dimensions.json'),reuse_validation_sha256=sha(OUT/'R5-FOCUS-REUSE-VALIDATION.json'))
write(DOUT/'DIMENSION-VALIDATION.json',dim_report)
A.closeDocument(old.Name);A.closeDocument(new.Name)
print(json.dumps(dict(ok=True,roi_checks=len(comparisons)*len(mapping),native_witnesses=len(new_witnesses),focus_meshes=focus['parts'],triangles=focus['triangles'],base64_bytes=len(encoded))))
