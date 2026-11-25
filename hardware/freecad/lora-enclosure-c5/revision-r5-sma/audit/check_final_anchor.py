from pathlib import Path
import json,hashlib
import FreeCAD as A,Part
O=Path(__file__).resolve().parent;P=O.parents[1]/'revision-r4-battery/cad/LoRa-Enclosure-C5-R4-Battery.FCStd'
h=hashlib.sha256(P.read_bytes()).hexdigest();d=A.openDocument(str(P))
def box(x0,y0,z0,x1,y1,z1):return Part.makeBox(x1-x0,y1-y0,z1-z0,A.Vector(x0,y0,z0))
blank=box(55,84,14,61.5,92.2,18)
slot=box(54.9,85.8,15.2,61.6,88.8,16.7)
# Fillet every edge of each simple box before the subtraction.
rounded=blank.makeFillet(.6,blank.Edges)
rounded_slot=slot.makeFillet(.4,slot.Edges)
anchor=rounded.cut(rounded_slot)
rows={}
for n in('EnclosureBase','EnclosureLid','ReferenceBatteryEnvelope','BatteryCover','PTTStopCup'):
 s=d.getObject(n).Shape
 rows[n]={'anchor_intersection_mm3':anchor.common(s).Volume,'anchor_distance_mm':anchor.distToShape(s)[0],'slot_intersection_mm3':rounded_slot.common(s).Volume}
report={'dimensions':{'blank':[55,84,14,61.5,92.2,18],'slot':[54.9,85.8,15.2,61.6,88.8,16.7]},'outer_fillet_mm':.6,'slot_fillet_mm':.4,'valid':anchor.isValid(),'solids':len(anchor.Solids),'pairs':rows,'source_unchanged':hashlib.sha256(P.read_bytes()).hexdigest()==h}
(O/'final-anchor-audit.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
A.closeDocument(d.Name)
