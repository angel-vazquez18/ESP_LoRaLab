from pathlib import Path
import FreeCAD as A, Part, json, time
ROOT=Path(__file__).resolve().parents[2]; OUT=Path(__file__).resolve().parent
d=A.openDocument(str(ROOT/'cad/LoRa-Enclosure-C5-R5-SMA.FCStd'))
ref=A.newDocument('CoaxReference');Part.insert(str(ROOT.parent/'detailed-import/C5-detailed-assembly.step'),ref.Name)
objs=[o for o in ref.Objects if hasattr(o,'Shape') and not o.Shape.isNull()]
comp=[]
for i,o in enumerate(objs):
 s=o.Shape.copy();s.translate(A.Vector(0,0,6.4814));s.exportBrep(str(OUT/f'component-{i}.brep'))
 b=s.BoundBox;comp.append({'i':i,'label':o.Label,'bb':[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]})
(OUT/'component-bounds.json').write_text(json.dumps(comp))
for n in ['EnclosureBase','EnclosureLid','PTTPlunger','PTTStopCup','BatteryCover','ReferenceBatteryEnvelope','ReferenceSMARearBody']:
 d.getObject(n).Shape.exportBrep(str(OUT/f'{n}.brep'))
print('Exported read-only route audit cache',len(comp),flush=True)
A.closeDocument(ref.Name);A.closeDocument(d.Name)
