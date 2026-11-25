from pathlib import Path
import json,hashlib,time
import FreeCAD as A, Part
OUT=Path(__file__).resolve().parent
ENC=OUT.parents[1]
NATIVE=ENC/'revision-r4-battery/cad/LoRa-Enclosure-C5-R4-Battery.FCStd'
ASSEMBLY=ENC/'detailed-import/C5-detailed-assembly.step'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
sources={str(p):sha(p) for p in (NATIVE,ASSEMBLY)}
def bb(s):
 b=s.optimalBoundingBox(False,False);return[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def box(x0,y0,z0,x1,y1,z1):return Part.makeBox(x1-x0,y1-y0,z1-z0,A.Vector(x0,y0,z0))
doc=A.openDocument(str(NATIVE))
p=doc.getObject('Parameters')
params=[]
for i in range(1,96):
 try:params.append([i,p.get('A'+str(i)),p.get('B'+str(i)),p.get('C'+str(i))])
 except:pass
parts={}
for o in doc.Objects:
 if hasattr(o,'Shape') and not o.Shape.isNull() and (any(x.lower() in (o.Name+' '+o.Label).lower()for x in('antenna','coax','USB','TieSlot','ReferenceBattery','EnclosureBase','EnclosureLid','Cable'))):
  parts[o.Name]={'label':o.Label,'bounds':bb(o.Shape),'expressions':dict(o.ExpressionEngine)}
print(json.dumps({'parameters':params,'parts':parts}),flush=True)
ref=A.newDocument('SMAReadOnlyComponents');Part.insert(str(ASSEMBLY),ref.Name)
objs=[o for o in ref.Objects if hasattr(o,'Shape')and not o.Shape.isNull()]
assert len(objs)==2949
shapes=[]
for i,o in enumerate(objs):
 s=o.Shape.copy();s.translate(A.Vector(0,0,6.4814));shapes.append((i,o.Label,s,bb(s)))
near=[{'index':i,'label':label,'bounds':b}for i,label,s,b in shapes if b[4]>79 and b[3]>34 and b[0]<66 and b[2]>7]
report={'sources':sources,'parameters':params,'parts':parts,'rear_components':near,'candidates':[]}
# A connector projects in +Y from the top/USB end. Loose conservative envelopes:
# rear hardware body 10mm diameter/depth10, external antenna 8mm diameter/50mm.
for x in (43,47,51,55,59):
 for z in (9,12,15,18):
  rear=Part.makeCylinder(5,10,A.Vector(x,92,z),A.Vector(0,-1,0))
  outer=Part.makeCylinder(5.5,4,A.Vector(x,94.4,z),A.Vector(0,1,0))
  antenna=Part.makeCylinder(4,50,A.Vector(x,98.4,z),A.Vector(0,1,0))
  collisions=[];nearest=[]
  for i,label,s,b in shapes:
   if b[3]<x-8 or b[0]>x+8 or b[4]<79 or b[1]>94 or b[5]<z-8 or b[2]>z+8:continue
   vol=rear.common(s).Volume
   dist=rear.distToShape(s)[0]
   if vol>1e-6:collisions.append({'index':i,'label':label,'volume':vol,'bounds':b})
   nearest.append((dist,i,label))
  hardware=[(n,doc.getObject(n).Shape)for n in('PTTPlunger','PTTStopCup','BatteryCover','ReferenceBatteryEnvelope','EnclosureLid')]
  clashes={n:rear.common(s).Volume for n,s in hardware}
  report['candidates'].append({'x':x,'z':z,'rear_body_bounds':bb(rear),'component_collision_count':len(collisions),'component_collision_volume':sum(c['volume']for c in collisions),'collisions':collisions,'closest_components':sorted(nearest)[:4],'retained_part_collisions':clashes,'external_antenna_bounds':bb(antenna)})
  print('candidate',x,z,len(collisions),sum(c['volume']for c in collisions),flush=True)
report['source_files_unchanged']={p:sha(Path(p))==v for p,v in sources.items()}
(OUT/'sma-candidate-audit.json').write_text(json.dumps(report,indent=2))
A.closeDocument(ref.Name);A.closeDocument(doc.Name)
print(json.dumps({'saved':str(OUT/'sma-candidate-audit.json'),'sources_unchanged':report['source_files_unchanged']}),flush=True)
