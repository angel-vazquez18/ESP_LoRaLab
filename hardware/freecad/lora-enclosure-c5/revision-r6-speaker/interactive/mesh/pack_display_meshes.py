"""Lossless delta/varint transport of the original 0.001 mm display mesh vertices."""
from pathlib import Path
import base64,gzip,hashlib,json,struct
root=Path(__file__).resolve().parent
source=root/'mesh-data-full.json';data=json.loads(source.read_bytes())
out=bytearray();headers=[]
def varint(n):
    n=n*2 if n>=0 else -n*2-1
    while n>=128:out.append((n&127)|128);n>>=7
    out.append(n)
for part in data['parts']:
    header={k:v for k,v in part.items()if k not in('positions','indices')}
    header['vertices']=len(part['positions'])//3;header['indexCount']=len(part['indices'])
    header['byteOffset']=len(out)
    prev=[0,0,0]
    for i,x in enumerate(part['positions']):
        q=round(x*1000);axis=i%3;varint(q-prev[axis]);prev[axis]=q
    previous=0
    for i in part['indices']:varint(i-previous);previous=i
    header['byteLength']=len(out)-header['byteOffset'];headers.append(header)
header=json.dumps(dict(schema=2,codec='xyz-millimetre-1000-axis-delta-zigzag-varint;index-delta-zigzag-varint',units='mm',parts=headers,metadata=data['metadata']),separators=(',',':')).encode()
raw=struct.pack('<I',len(header))+header+out
compressed=gzip.compress(raw,compresslevel=9,mtime=0)
encoded=base64.b64encode(compressed)
(root/'mesh-data.packed').write_bytes(raw)
(root/'mesh-data.packed.gz').write_bytes(compressed)
(root/'mesh-data.b64').write_bytes(encoded)
(root/'mesh-data.json').write_bytes(source.read_bytes())
print(json.dumps(dict(raw_bytes=len(raw),gzip_bytes=len(compressed),base64_bytes=len(encoded))))
