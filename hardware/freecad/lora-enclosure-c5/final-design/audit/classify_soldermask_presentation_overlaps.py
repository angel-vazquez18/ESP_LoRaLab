"""Prove the STEP's flat mask faces span physical NPTH holes; retain evidence."""
from pathlib import Path
import json,hashlib
import FreeCAD as App,Part
out=Path(__file__).resolve().parent
path=out/'final-actual-clearance.json';report=json.loads(path.read_text())
step=Path(report['reference_step']);assert hashlib.sha256(step.read_bytes()).hexdigest()==report['reference_sha256']
doc=App.newDocument('MaskArtifactCheck');Part.insert(str(step),doc.Name)
def source(i):
 s=doc.getObject('C5_detailed_assembly'+f'{i:03d}').Shape.copy();s.translate(App.Vector(0,0,6.4814));return s
substrate=source(1067);masks={i:source(i) for i in (2947,2948)}
classified=[]
for name,part in report['parts'].items():
 if not name.startswith('M3ScrewEnvelope'):continue
 x,y=map(float,name.removeprefix('M3ScrewEnvelope').split('_'))
 screw=Part.makeCylinder(1.5,22,App.Vector(x,y,2.6)).fuse(Part.makeCylinder(2.75,3,App.Vector(x,y,24.6)))
 npth=Part.makeCylinder(1.6,5,App.Vector(x,y,4))
 holesub=substrate.common(npth)
 distance=substrate.distToShape(screw)[0]
 real_overlap=substrate.common(screw).Volume
 remaining=[];artifacts=[]
 for rec in part['penetrations']+part.get('presentation_artifacts',[]):
  if rec['index'] not in masks:remaining.append(rec);continue
  crossing=masks[rec['index']].common(screw)
  outside=crossing.cut(npth)
  evidence=dict(actual_substrate_to_screw_clearance_mm=distance,actual_substrate_screw_common_volume_mm3=real_overlap,npth_clearance_cylinder_diameter_mm=3.2,npth_cylinder_substrate_common_volume_mm3=holesub.Volume,mask_intersection_outside_np_th_hole_area_mm2=outside.Area,mask_intersection_volume_mm3=crossing.Volume,mask_intersection_area_mm2=crossing.Area)
  assert distance>.09999 and real_overlap<1e-7 and holesub.Volume<1e-7 and outside.Area<1e-7 and abs(crossing.Volume)<1e-7,evidence
  artifacts.append({**rec,'classification':'Planar STEP soldermask presentation surface crossing an actual empty NPTH hole; not a physical material interference.','proof':evidence})
 part['penetrations']=remaining;part['presentation_artifacts']=artifacts
 classified.extend(dict(part=name,**a) for a in artifacts)
report['soldermask_artifact_classification']=dict(count=len(classified),method='Exact OCC: screw clears drilled substrate by 0.1 mm; mask/screw intersection lies entirely in the actual empty diameter 3.2 mm NPTH cylinder; positive mask intersection has zero volume.',records=classified)
report['ok']=not report['errors'] and all(v['valid'] and v['closed'] and v['solids']==1 and not v['penetrations'] for v in report['parts'].values()) and report['source_file_unchanged']
path.write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(dict(ok=report['ok'],presentation_artifacts=len(classified),remaining_penetrations=sum(len(p['penetrations']) for p in report['parts'].values()))))
App.closeDocument(doc.Name)
