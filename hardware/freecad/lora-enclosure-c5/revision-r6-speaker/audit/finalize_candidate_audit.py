from pathlib import Path
import FreeCAD,Part,json,hashlib
OUT=Path(__file__).resolve().parent
r=json.loads((OUT/'speaker-candidate-audit.json').read_text())
def load(n):s=Part.Shape();s.read(str(OUT/(n+'.brep')));return s
a=load('EnclosureBase');b=load('EnclosureLid')
r['pairs']['EnclosureBase__EnclosureLid']={'intersection_mm3':a.common(b).Volume,'distance_mm':a.distToShape(b)[0]}
r['source_files_unchanged']={p:hashlib.sha256(Path(p).read_bytes()).hexdigest()==v for p,v in r['source_hashes'].items()}
r['plan_sha256']=hashlib.sha256((OUT/'speaker-geometry-plan.json').read_bytes()).hexdigest()
r['derived_brep_hashes']={p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in OUT.glob('*.brep')}
r['ok']=r['ok']and all(r['source_files_unchanged'].values())and r['pairs']['EnclosureBase__EnclosureLid']['intersection_mm3']<1e-6
r['limits']=['Approximate speaker dimensions; no exact manufacturer model or rim geometry.','Gasket and pad allowances must support the verified frame, not diaphragm or lead terminals.','No strength/acoustic/drop qualification; shim retention by physical fit.','Reference terminal entry positions and wire slack need physical confirmation.']
assert r['ok']
(OUT/'speaker-fit-audit.json').write_text(json.dumps(r,indent=2))
print(json.dumps({'ok':r['ok'],'base_lid':r['pairs']['EnclosureBase__EnclosureLid'],'unchanged':r['source_files_unchanged']}))
