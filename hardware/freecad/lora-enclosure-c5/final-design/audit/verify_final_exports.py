"""Read-only final native CAD, STEP, mesh and recompute verification."""
from pathlib import Path
import json,hashlib,itertools,sys,importlib.util,zipfile,xml.etree.ElementTree as ET
import FreeCAD as App
import Part,Mesh

root=Path(__file__).resolve().parents[1]
cad=Path(sys.argv[1]) if len(sys.argv)>1 else root/'cad/LoRa-Enclosure-C5-R1.FCStd'
step=Path(sys.argv[2]) if len(sys.argv)>2 else root/'cad/LoRa-Enclosure-C5-R1.step'
meshdir=Path(sys.argv[3]) if len(sys.argv)>3 else root/'printing'
out=Path(__file__).resolve().parent
names={'EnclosureBase':'enclosure-base.stl','EnclosureLid':'enclosure-lid.stl','PTTPlunger':'ptt-plunger.stl','PTTStopCup':'ptt-stop-cup.stl'}
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def bbox(s):
 b=s.BoundBox
 return [b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def info(s):return dict(valid=s.isValid(),closed=s.isClosed(),solids=len(s.Solids),volume_mm3=s.Volume,bounds_mm=bbox(s))
def compare(a,b):
 d=max(abs(x-y) for x,y in zip(bbox(a),bbox(b)));v=abs(a.Volume-b.Volume)
 sym=a.cut(b).Volume+b.cut(a).Volume
 return dict(max_bounds_difference_mm=d,absolute_volume_difference_mm3=v,symmetric_difference_volume_mm3=sym,matches=d<1e-6 and v<1e-5 and sym<1e-5)
spec=importlib.util.spec_from_file_location('mesh_validation',str(root.parent/'fit-checked/verify_exports.py'))
mv=importlib.util.module_from_spec(spec);spec.loader.exec_module(mv)
report=dict(native_file=str(cad),native_sha256=sha(cad),step_file=str(step),step_sha256=sha(step),scope='Read-only saved file validation. No native document saved or exported by this checker.',parts={},parameters={},failures=[])
doc=App.openDocument(str(cad));saved={n:doc.getObject(n).Shape.copy() for n in names}
for cell,expected in {'B8':13,'B12':4.4,'B13':5,'B17':.4,'B24':1.6,'B29':.4,'B37':9.5,'B44':21,'B47':24.6,'B59':.25,'B67':19.15,'B68':17.15,'B71':4,'B72':22}.items():
 p=doc.getObject('Parameters');value=float(str(p.get(cell)).split()[0]);ok=abs(value-expected)<1e-7
 report['parameters'][cell]=dict(value=value,expected=expected,stored=p.getContents(cell),matches=ok)
 if not ok:report['failures'].append('Parameter mismatch '+cell)
assembly=Part.read(str(step));solids=assembly.Solids
report['step_solid_count']=len(solids)
if len(solids)!=4:report['failures'].append('STEP must contain exactly four printable solids')
pairing=min(itertools.permutations(range(4)),key=lambda order:sum(sum(abs(x-y) for x,y in zip(bbox(saved[n]),bbox(solids[i])))+abs(saved[n].Volume-solids[i].Volume)/max(1,saved[n].Volume) for n,i in zip(names,order))) if len(solids)==4 else []
for n,i in zip(names,pairing):
 s=saved[n];p=meshdir/names[n];mesh=Mesh.Mesh(str(p));b=mesh.BoundBox;mb=[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
 shapeinfo=info(s);comparison=compare(s,solids[i]);topology=mv.validate_mesh(p)
 # Print-oriented meshes may be rigidly rotated and translated; volume and sorted spans
 # compare geometry independently of origin. Surface equivalence is not asserted here.
 spans=sorted([mb[j+3]-mb[j] for j in range(3)]);cb=bbox(s);cspans=sorted([cb[j+3]-cb[j] for j in range(3)])
 span_delta=max(abs(a-b) for a,b in zip(spans,cspans));volume_error=abs(abs(mesh.Volume)-s.Volume)/s.Volume
 report['parts'][n]=dict(native=shapeinfo,step_comparison=comparison,mesh_file=str(p),mesh_sha256=sha(p),mesh_topology=topology,mesh_sorted_span_difference_mm=span_delta,mesh_relative_volume_error=volume_error)
 if not (shapeinfo['valid'] and shapeinfo['closed'] and shapeinfo['solids']==1 and comparison['matches'] and topology['ok'] and span_delta<.1 and volume_error<.005):report['failures'].append('Geometry or mesh validation failed '+n)
doc.recompute();report['recompute']={n:compare(s,doc.getObject(n).Shape) for n,s in saved.items()}
if not all(x['matches'] for x in report['recompute'].values()):report['failures'].append('Recompute changed saved geometry')
baseline=App.openDocument(str(root.parent/'fit-checked/LoRa-Enclosure-C5-Fit-Checked.FCStd'))
bp=baseline.getObject('Parameters')
for cell,value in {'B8':13,'B12':4.4,'B13':5,'B17':.4,'B24':1.6,'B29':.4,'B37':9.5}.items():bp.set(cell,str(value))
baseline.recompute()
expected={n:baseline.getObject(n).Shape.copy() for n in names}
import math
vents=[Part.makeCylinder(.8,3.8,App.Vector(54.5+2.6*math.cos(i*math.pi/3),30.5+2.6*math.sin(i*math.pi/3),20.9)) for i in range(6)]
expected['EnclosureLid']=expected['EnclosureLid'].cut(Part.makeCompound(vents)).removeSplitter()
report['independent_final_parameter_rebuild']={n:compare(saved[n],expected[n]) for n in names}
if not all(x['matches'] for x in report['independent_final_parameter_rebuild'].values()):report['failures'].append('Final saved geometry differs from independently rebuilt intended parameter revision')
App.closeDocument(baseline.Name)
report['source_unchanged']=sha(cad)==report['native_sha256'] and sha(step)==report['step_sha256']
if not report['source_unchanged']:report['failures'].append('Source file changed during check')
report['normalized_upload_meshes']=[]
report['individual_cnc_step']=[]
for n,filename in names.items():
 single=root/'cnc'/('C5-R1-'+Path(filename).stem+'.step')
 if not single.exists():continue
 candidate=Part.read(str(single));test=compare(saved[n],candidate)
 entry=dict(file=str(single),sha256=sha(single),solid_count=len(candidate.Solids),valid=candidate.isValid(),comparison=test)
 report['individual_cnc_step'].append(entry)
 if len(candidate.Solids)!=1 or not candidate.isValid() or not test['matches']:report['failures'].append('Individual CNC STEP mismatch '+single.name)
upload=root/'craftcloud/upload'
for n,filename in names.items():
 target=upload/('C5-R1-'+Path(filename).stem+'-mm.stl')
 if not target.exists():continue
 check=mv.validate_mesh(target);_,original=mv.read_stl(meshdir/filename);_,normalized=mv.read_stl(target)
 mins=[min(p[j] for t in original for p in t) for j in range(3)]
 delta=max(abs((a[j]-mins[j])-b[j]) for ot,nt in zip(original,normalized) for a,b in zip(ot,nt) for j in range(3)) if len(original)==len(normalized) else float('inf')
 ok=check['ok'] and delta<1e-4
 report['normalized_upload_meshes'].append(dict(file=str(target),sha256=sha(target),topology=check,maximum_translation_round_trip_error_mm=delta,ok=ok))
 if not ok:report['failures'].append('Normalized upload mesh failed '+target.name)
report['three_mf']=[]
for path in list(meshdir.glob('*.3mf'))+list(upload.glob('*.3mf')):
 try:
  with zipfile.ZipFile(path) as z:
   assert z.testzip() is None
   m=ET.fromstring(z.read('3D/3dmodel.model'));ns={'m':'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'}
   entry=dict(path=str(path),sha256=sha(path),unit=m.get('unit','millimeter'),mesh_objects=len(m.findall('.//m:mesh',ns)),build_items=len(m.findall('.//m:build/m:item',ns)),vertices=len(m.findall('.//m:vertex',ns)),triangles=len(m.findall('.//m:triangle',ns)))
   assert entry['unit']=='millimeter' and entry['mesh_objects'] and entry['build_items'] and entry['triangles']
   report['three_mf'].append(entry)
 except Exception as e:report['failures'].append('3MF invalid '+str(path)+': '+repr(e))
report['limitations']=['Mesh equivalence uses bounding spans and volume plus manifold topology, not a pointwise distance proof.','Electronics interference is checked by the separate final-clearance audit.','Geometric validity does not establish printer calibration, material strength or physical fit.']
report['ok']=not report['failures']
(out/'final-export-validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(dict(ok=report['ok'],failures=report['failures'],parts={n:{'native':v['native'],'mesh_ok':v['mesh_topology']['ok'],'step_matches':v['step_comparison']['matches'],'mesh_span_delta':v['mesh_sorted_span_difference_mm'],'mesh_volume_error':v['mesh_relative_volume_error']} for n,v in report['parts'].items()},normalized_uploads=[{'file':v['file'],'ok':v['ok'],'delta_mm':v['maximum_translation_round_trip_error_mm']} for v in report['normalized_upload_meshes']],three_mf=report['three_mf']),indent=2))
App.closeDocument(doc.Name)
