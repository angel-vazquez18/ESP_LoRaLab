from pathlib import Path
import json, hashlib
import FreeCAD as A
import Part, Import

root=Path(__file__).resolve().parent
source=root.parents[1]/'revision-r3-oled-gap/cad/LoRa-Enclosure-C5-R3-OLED.FCStd'
heltec=root.parents[2]/'heltec-v4-carrier/design/models/reference/heltec-v4_3_1-reference.step'
def bb(s):
 b=s.optimalBoundingBox(False,False)
 return[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def info(s):return dict(valid=s.isValid(),closed=s.isClosed(),solids=len(s.Solids),volume=s.Volume,bounds=bb(s))
doc=A.openDocument(str(source))
base=doc.getObject('EnclosureBase').Shape
metadata={n:dict(type=doc.getObject(n).TypeId,bounds=bb(doc.getObject(n).Shape),expressions=dict(doc.getObject(n).ExpressionEngine)) for n in ('EnclosureBase','BaseWithBosses','BaseCutters') if doc.getObject(n)}
ref=A.newDocument('BatteryConnectorReadOnly')
Import.insert(str(heltec),ref.Name)
jp=ref.getObject('JP2').Group[0]
s=jp.Shape
v,f=s.tessellate(.04)
connector=dict(label=jp.Label,bounds=bb(s),solids=[info(q) for q in s.Solids],vertices=[[a.x,a.y,a.z] for a in v],triangles=f)
(root/'jp2-connector-geometry.json').write_text(json.dumps(connector),encoding='utf-8')
print(json.dumps({'base':info(base),'objects':metadata,'jp2':{k:v for k,v in connector.items() if k not in ('vertices','triangles')}},indent=2))
A.closeDocument(doc.Name);A.closeDocument(ref.Name)
