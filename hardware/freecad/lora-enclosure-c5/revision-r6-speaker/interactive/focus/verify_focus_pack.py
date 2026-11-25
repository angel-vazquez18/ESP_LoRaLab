"""Independent decode of focus mesh transport and checked CAD provenance."""
from pathlib import Path
import base64,gzip,hashlib,json,math,struct
root=Path(__file__).resolve().parent
data=json.loads((root/'focus-mesh-data.json').read_text())
blob=gzip.decompress(base64.b64decode((root/'focus-mesh-data.b64').read_bytes()))
header_length=struct.unpack_from('<I',blob)[0];payload_start=4+header_length
packed=json.loads(blob[4:payload_start]);assert packed['schema']==2
assert len(packed['parts'])==len(data['parts'])
for item,part in zip(packed['parts'],data['parts']):
 cursor=payload_start+item['byteOffset']
 def integer():
  global cursor
  value=0;shift=0
  while True:
   b=blob[cursor];cursor+=1;value+=(b&127)<<shift;shift+=7
   if not b&128:break
  return -(value+1)//2 if value%2 else value//2
 previous=[0,0,0];positions=[]
 for i in range(item['vertices']*3):
  axis=i%3;previous[axis]+=integer();positions.append(previous[axis]/1000)
 previous=0;indices=[]
 for i in range(item['indexCount']):previous+=integer();indices.append(previous)
 assert positions==part['positions'] and indices==part['indices']
 assert cursor==payload_start+item['byteOffset']+item['byteLength']
 assert all(math.isfinite(x)for x in positions)
 assert all(0<=i<item['vertices']for i in indices)
 assert part['variant']=='focus'and part['focusId']in{v['id']for v in data['metadata']['views']}
report=json.loads((root/'FOCUS-MESH-VALIDATION.json').read_text())
assert report['ok']and all(report['source_files_unchanged'].values())
assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in report['source_hashes'].items())
assert all(v['valid_shapes']and v['cap_triangles']>0 and all(w['ok']for w in v['witness_checks'])for v in report['view_audit'])
report['packed_round_trip_exact']=True
report['retained_surface_witness_checks']=sum(len(v['witness_checks'])for v in report['view_audit'])
report['all_focus_meshes_have_caps']=True
(root/'FOCUS-MESH-VALIDATION.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(dict(ok=True,views=report['views'],parts=report['parts'],triangles=report['triangles'],base64_bytes=report['base64_bytes'],packed_round_trip_exact=True,witness_checks=report['retained_surface_witness_checks'])))
