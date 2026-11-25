"""Verify translation-only supplier meshes against approved/reused raw meshes."""
from pathlib import Path
import hashlib, importlib.util, json, zipfile, xml.etree.ElementTree as ET
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('meshcheck',root.parent/'fit-checked/verify_exports.py')
mv=importlib.util.module_from_spec(spec);spec.loader.exec_module(mv)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
data=json.loads((root/'craftcloud/upload-manifest.json').read_text())
report={'scope':'Translation-only normalized supplier meshes; physical fit remains unqualified.', 'parts':[], 'failures':[]}
ns={'m':'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'}
for entry in data['files']:
    source,stl,mf=map(Path,(entry['source'],entry['stl'],entry['3mf']))
    _,a=mv.read_stl(source);_,b=mv.read_stl(stl)
    shift=entry['translation_from_source_mm']
    error=max(abs(x[k]+shift[k]-y[k]) for ta,tb in zip(a,b) for x,y in zip(ta,tb) for k in range(3)) if len(a)==len(b) else float('inf')
    topology=mv.validate_mesh(stl)
    with zipfile.ZipFile(mf) as z:
        assert z.testzip() is None
        model=ET.fromstring(z.read('3D/3dmodel.model'))
    vertices=[tuple(float(v.get(k)) for k in ('x','y','z')) for v in model.findall('.//m:vertex',ns)]
    triangles=[tuple(int(t.get(k)) for k in ('v1','v2','v3')) for t in model.findall('.//m:triangle',ns)]
    mf_error=max(abs(vertices[face[j]][k]-tri[j][k]) for face,tri in zip(triangles,b) for j in range(3) for k in range(3)) if len(triangles)==len(b) else float('inf')
    ok=(error<1e-5 and mf_error<1e-5 and topology['ok'] and model.get('unit')=='millimeter'
        and sha(source)==entry['source_sha256'] and sha(stl)==entry['stl_sha256'] and sha(mf)==entry['3mf_sha256'])
    record=dict(part=entry['part'],source_sha256=sha(source),stl_sha256=sha(stl),three_mf_sha256=sha(mf),
                translation_error_mm=error,three_mf_to_stl_error_mm=mf_error,topology=topology,ok=ok)
    report['parts'].append(record)
    if not ok:report['failures'].append(entry['part'])
if len(report['parts'])!=5:report['failures'].append('Expected five parts')
report['ok']=not report['failures']
(root/'craftcloud/UPLOAD-VALIDATION.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'ok':report['ok'],'failures':report['failures'],'parts':[{'part':p['part'],'ok':p['ok'],'translation_error_mm':p['translation_error_mm'],'3mf_error_mm':p['three_mf_to_stl_error_mm']}for p in report['parts']]}))
if not report['ok']:raise SystemExit(1)
