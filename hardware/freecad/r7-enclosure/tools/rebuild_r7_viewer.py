"""Verify/reconstruct the R7 viewer fragment from its compact archived inputs.

Default operation is read-only. --output writes a new file only, never replaces
the published fragment. This needs ordinary Python 3.10+, not CAD/browser tools.
"""
from pathlib import Path
from html.parser import HTMLParser
import argparse,base64,gzip,hashlib,json,math,struct

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def check(condition,message):
    if not condition:raise ValueError(message)

def decode(path):
    raw=gzip.decompress(base64.b64decode(path.read_bytes(),validate=True))
    check(len(raw)<100_000_000,'Packed viewer exceeds size bound')
    length=struct.unpack_from('<I',raw)[0];header=json.loads(raw[4:4+length]);start=4+length
    check(header['schema']==2 and header['units']=='mm','Unexpected display transport')
    triangles=0
    for part in header['parts']:
        cursor=start+part['byteOffset'];end=cursor+part['byteLength']
        check(start<=cursor<=end<=len(raw),'Packed segment out of bounds')
        def integer():
            nonlocal cursor
            value=0;shift=0
            while True:
                check(cursor<end and shift<35,'Invalid varint')
                b=raw[cursor];cursor+=1;value|=(b&127)<<shift;shift+=7
                if not b&128:return -(value+1)//2 if value&1 else value//2
        previous=[0,0,0]
        for i in range(part['vertices']*3):
            previous[i%3]+=integer();check(math.isfinite(previous[i%3]/1000),'Nonfinite position')
        index=0
        for _ in range(part['indexCount']):
            index+=integer();check(0<=index<part['vertices'],'Invalid triangle index')
        check(cursor==end and part['indexCount']%3==0,'Packed segment size/count mismatch')
        triangles+=part['indexCount']//3
    return {'parts':len(header['parts']),'triangles':triangles,'sha256':sha(path)}

def reconstruct(root,require_final=True):
    root=Path(root)
    config=json.loads((root/'SOURCE-INPUTS.json').read_text(encoding='utf-8'))
    if require_final:check('pending' not in config['source_status'].lower() and 'preflight' not in config['source_status'].lower(),'Viewer is still a draft')
    dimensions=json.loads((root/'dimensions/dimensions.json').read_text(encoding='utf-8'))
    focus={'views':json.loads((root/'focus/focus-views.json').read_text(encoding='utf-8'))}
    for d in dimensions['dimensions']:
        check(abs(math.dist(d['start_mm'],d['end_mm'])-d['value_mm'])<1e-6,'Dimension mismatch '+d['id'])
    check({v['id']for v in focus['views']}=={d['id']for d in dimensions['dimensions']},'Focus/dimension IDs differ')
    overview=decode(root/'mesh/mesh-data.b64');closeups=decode(root/'focus/focus-mesh-data.b64')
    text=(root/'r7-enclosure-viewer.template.html').read_text(encoding='utf-8')
    fields={
        '__R7_SOURCE_LABEL__':'Draft R7 design' if 'preflight' in config['source_status'] else 'R7 design',
        '__R7_MESH_BASE64__':(root/'mesh/mesh-data.b64').read_text().strip(),
        '__R7_DIMENSIONS_JSON__':json.dumps(dimensions,separators=(',',':')).replace('</','<\\/'),
        '__R7_FOCUS_MESH_BASE64__':(root/'focus/focus-mesh-data.b64').read_text().strip(),
        '__R7_FOCUS_JSON__':json.dumps(focus,separators=(',',':')).replace('</','<\\/'),
    }
    for key,value in fields.items():
        check(text.count(key)==1,'Template substitution count: '+key);text=text.replace(key,value)
    published_path=root/'r7-enclosure-viewer.html'
    published=published_path.read_text(encoding='utf-8');published_bytes=published_path.read_bytes()
    check(text==published,'Reconstructed fragment differs from published source')
    check(len(text.encode('utf-8'))<1_000_000,'Fragment exceeds size bound')
    # Preserve the source newline convention as well as all generated content.
    encoded=text.replace('\n','\r\n').encode('utf-8')if b'\r\n'in published_bytes else text.encode('utf-8')
    check(encoded==published_bytes,'Reconstructed fragment byte sequence differs')
    class Frames(HTMLParser):
        def __init__(self):super().__init__(convert_charrefs=True);self.frames=[]
        def handle_starttag(self,tag,attrs):
            if tag=='iframe':self.frames.append(dict(attrs))
    preview=root/'qa/r7-preview.html';parser=Frames();parser.feed(preview.read_text(encoding='utf-8'))
    check(len(parser.frames)==1,'Expected one standalone viewer frame')
    embedded=parser.frames[0].get('data-srcdoc','').replace('\r\n','\n')
    check(embedded.count(text)==1,'Standalone preview does not embed the exact current fragment')
    return encoded,{'ok':True,'overview':overview,'focus':closeups,'dimensions':len(dimensions['dimensions']),'fragment_sha256':sha(published_path),'preview_sha256':sha(preview),'preview_fragment_matches':True,'exact_text_reconstruction':True,'exact_byte_reconstruction':True,'writes':False}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]/'interactive')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    try:
        encoded,report=reconstruct(args.root)
        if args.output:
            with args.output.open('xb')as f:f.write(encoded)
            report.update(writes=True,output=str(args.output))
        print(json.dumps(report,indent=2));return 0
    except (ValueError,OSError,KeyError,IndexError,struct.error)as error:
        print(json.dumps({'ok':False,'error':str(error)}));return 1

if __name__=='__main__':raise SystemExit(main())
