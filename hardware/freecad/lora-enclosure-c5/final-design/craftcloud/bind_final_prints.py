"""Bind the four final manufacturing STLs into the quote manifest, without uploading."""
from pathlib import Path
import argparse, hashlib, json, struct

root=Path(__file__).resolve().parent
p=argparse.ArgumentParser()
for key in ['base','lid','ptt-plunger','ptt-stop-cup']:
 p.add_argument('--'+key,required=True,type=Path)
args=p.parse_args()
result=json.loads((root/'order-manifest.json').read_text())
final_root=root.parent.resolve()
upload=json.loads((root/'upload-manifest.json').read_text())
upload_lookup={r['part']:r for r in upload['files']}
part_names={'base':'enclosure-base','lid':'enclosure-lid','ptt_plunger':'ptt-plunger','ptt_stop_cup':'ptt-stop-cup'}
for entry in result['parts']:
 path=getattr(args,entry['part']).resolve()
 if not path.is_relative_to(final_root):raise ValueError('Use final-design manufacturing STLs')
 if path.suffix.lower()!='.stl':raise ValueError('Expected individual STL')
 raw=path.read_bytes()
 n=struct.unpack_from('<I',raw,80)[0] if len(raw)>=84 else -1
 if len(raw)==84+50*n:
  vertices=[struct.unpack_from('<3f',raw,84+50*i+12+12*j) for i in range(n) for j in range(3)]
 else:
  vertices=[tuple(map(float,line.split()[1:])) for line in raw.decode('ascii').splitlines() if line.strip().startswith('vertex ')]
  n=len(vertices)//3
 if not vertices:raise ValueError('Empty STL')
 low=[min(v[a] for v in vertices) for a in range(3)]
 high=[max(v[a] for v in vertices) for a in range(3)]
 size=[round(high[a]-low[a],6) for a in range(3)]
 if not all(0<x<500 for x in size):raise ValueError('Unexpected bounds')
 digest=hashlib.sha256(raw).hexdigest()
 reference=upload_lookup[part_names[entry['part']]]
 assert digest==reference['stl_sha256'] and all(abs(a-b)<1e-5 for a,b in zip(size,reference['dimensions_mm']))
 alternate=Path(reference['3mf']).resolve()
 assert alternate.is_relative_to(final_root)
 assert hashlib.sha256(alternate.read_bytes()).hexdigest()==reference['3mf_sha256']
 entry.update(file=path.relative_to(final_root).as_posix(),size_mm=size,sha256=digest,bytes=len(raw),triangles=n,alternative_3mf=dict(file=alternate.relative_to(final_root).as_posix(),sha256=reference['3mf_sha256']))
result['files_bound']=True
result['status']='Final manufacturing STL files bound; manufacturer critical-fit review and quote selection pending'
result['upload_instruction']='Upload four STL files OR four alternative 3MF files, never both; one per part, quantity one, units mm, scale 1:1. Neutral 3MF contains no machine-specific print settings.'
result['upload_manifest_sha256']=hashlib.sha256((root/'upload-manifest.json').read_bytes()).hexdigest()
(root/'order-manifest.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result['parts'],indent=2))
