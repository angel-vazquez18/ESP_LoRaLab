"""Validate newly exported individual CNC STEP inputs without changing CAD."""
from pathlib import Path
import FreeCAD as App,Part,json,hashlib
root=Path(__file__).resolve().parents[1];path=root/'audit/final-export-validation.json'
report=json.loads(path.read_text());cad=root/'cad/LoRa-Enclosure-C5-R1.FCStd'
assert hashlib.sha256(cad.read_bytes()).hexdigest()==report['native_sha256']
doc=App.openDocument(str(cad));items=[]
for name,file in [('EnclosureBase','enclosure-base'),('EnclosureLid','enclosure-lid'),('PTTPlunger','ptt-plunger'),('PTTStopCup','ptt-stop-cup')]:
 p=root/'cnc'/('C5-R1-'+file+'.step');a=doc.getObject(name).Shape;b=Part.read(str(p))
 sym=a.cut(b).Volume+b.cut(a).Volume;v=abs(a.Volume-b.Volume)
 ok=b.isValid() and b.isClosed() and len(b.Solids)==1 and sym<1e-5 and v<1e-5
 items.append(dict(native_part=name,file=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),valid=b.isValid(),closed=b.isClosed(),solid_count=len(b.Solids),volume_difference_mm3=v,symmetric_difference_volume_mm3=sym,matches=ok))
 if not ok:report['failures'].append('Individual CNC STEP mismatch '+p.name)
report['individual_cnc_step']=items;report['ok']=not report['failures']
path.write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(dict(ok=report['ok'],individual_cnc_step=items),indent=2));App.closeDocument(doc.Name)
