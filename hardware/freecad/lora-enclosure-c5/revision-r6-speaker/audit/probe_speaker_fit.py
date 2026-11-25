from pathlib import Path
import FreeCAD as A,Part,json,hashlib
OUT=Path(__file__).resolve().parent; ENC=OUT.parents[1]
NATIVE=ENC/'revision-r5-sma/cad/LoRa-Enclosure-C5-R5-SMA.FCStd'
STEP=ENC/'detailed-import/C5-detailed-assembly.step'
def bb(s):
 b=s.BoundBox;return[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
d=A.openDocument(str(NATIVE));r={}
for o in d.Objects:
 if hasattr(o,'Shape')and not o.Shape.isNull() and any(x in o.Name.lower()for x in ['speaker','ptt','lid','support','boss','microphone','rim','body','base','battery','post','nut','screw']):
  r[o.Name]={'label':o.Label,'bounds':bb(o.Shape),'volume':o.Shape.Volume}
ref=A.newDocument('ProbeSpeaker');Part.insert(str(STEP),ref.Name)
objects=[o for o in ref.Objects if hasattr(o,'Shape')and not o.Shape.isNull()]
comps=[]
for i,o in enumerate(objects):
 s=o.Shape.copy();s.translate(A.Vector(0,0,6.4814));comps.append({'i':i,'label':o.Label,'bounds':bb(s)})
groups={'amplifier':range(1715,2138),'mic':range(1068,1715),'oled':range(2811,2831),'pcb':[1067,2947,2948]}
for n,inds in groups.items():
 bs=[comps[i]['bounds']for i in inds];r[n]={'bounds':[min(b[j]for b in bs)for j in range(3)]+[max(b[j+3]for b in bs)for j in range(3)]}
(OUT/'probe-native-bounds.json').write_text(json.dumps(r,indent=2));(OUT/'probe-component-bounds.json').write_text(json.dumps(comps))
print(json.dumps({n:r[n]for n in ['amplifier','mic','oled','pcb','EnclosureLid','EnclosureBase','PTTStopCup']},indent=2))
print('Amplitude large objects',json.dumps([c for c in comps[1715:2138] if (c['bounds'][3]-c['bounds'][0])*(c['bounds'][4]-c['bounds'][1])*(c['bounds'][5]-c['bounds'][2])>30],indent=2))
