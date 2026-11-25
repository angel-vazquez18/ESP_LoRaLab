"""Independently decode the browser transport and compare every coordinate/index."""
from pathlib import Path
import base64,gzip,hashlib,json,struct
root=Path(__file__).resolve().parent
raw=gzip.decompress(base64.b64decode((root/'mesh-data.b64').read_bytes()))
length=struct.unpack_from('<I',raw,0)[0]
header=json.loads(raw[4:4+length]);start=4+length
original=json.loads((root/'mesh-data-full.json').read_bytes())
comparisons=[]
for actual,expected in zip(header['parts'],original['parts']):
    cursor=start+actual['byteOffset'];end=cursor+actual['byteLength']
    def integer():
        global cursor
        value=0;shift=0
        while True:
            byte=raw[cursor];cursor+=1
            value|=(byte&127)<<shift
            if not byte&128:break
            shift+=7
            assert shift<35
        return -(value+1)//2 if value&1 else value//2
    positions=[];previous=[0,0,0]
    for i in range(actual['vertices']*3):
        previous[i%3]+=integer();positions.append(previous[i%3]/1000)
    indices=[];last=0
    for _ in range(actual['indexCount']):last+=integer();indices.append(last)
    assert cursor==end
    assert actual['id']==expected['id'] and positions==expected['positions'] and indices==expected['indices']
    comparisons.append(dict(id=actual['id'],vertices=actual['vertices'],triangles=actual['indexCount']//3,coordinates_exact=True,indices_exact=True))
assert len(header['parts'])==len(original['parts'])
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
audit=json.loads((root/'FULL-MESH-VALIDATION.json').read_bytes())
assert all(sha(Path(p))==v for p,v in audit['source_hashes'].items())
audit.update(ok=True,codec_schema=2,codec=header['codec'],packed_bytes=len(raw),
             gzip_bytes=(root/'mesh-data.packed.gz').stat().st_size,
             base64_bytes=(root/'mesh-data.b64').stat().st_size,within_target=(root/'mesh-data.b64').stat().st_size<750000,
             packed_round_trip_exact=True,geometric_decimation_applied=False,
             max_coordinate_quantization_error_per_axis_mm=.0005,
             max_coordinate_quantization_error_3d_mm=(3*.0005**2)**.5,
             mesh_sha256=sha(root/'mesh-data.json'),compressed_sha256=sha(root/'mesh-data.packed.gz'),
             decoded_comparison=comparisons)
(root/'MESH-VALIDATION.json').write_text(json.dumps(audit,indent=2)+'\n')
(root/'mesh-data.json.gz').write_bytes(gzip.compress((root/'mesh-data.json').read_bytes(),compresslevel=9,mtime=0))
print(json.dumps(dict(ok=True,parts=len(comparisons),triangles=audit['total_triangles'],base64_bytes=audit['base64_bytes'],packed_round_trip_exact=True,source_files_unchanged=True)))
