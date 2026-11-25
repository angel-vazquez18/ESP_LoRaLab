from pathlib import Path
import json,hashlib,math
import FreeCAD as A,Part
OUT=Path(__file__).resolve().parent;ENC=OUT.parents[1]
native=ENC/'revision-r4-battery/cad/LoRa-Enclosure-C5-R4-Battery.FCStd';assembly=ENC/'detailed-import/C5-detailed-assembly.step'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
hashes={str(p):sha(p)for p in(native,assembly)}
d=A.openDocument(str(native));r=A.newDocument('SMABlockReadOnly');Part.insert(str(assembly),r.Name)
parts={n:d.getObject(n).Shape.copy()for n in('EnclosureBase','EnclosureLid','ReferenceBatteryEnvelope','BatteryCover','PTTStopCup')}
shapes=[]
for i,o in enumerate([o for o in r.Objects if hasattr(o,'Shape')and not o.Shape.isNull()]):
 s=o.Shape.copy();s.translate(A.Vector(0,0,6.4814));shapes.append((i,s))
def bb(s):
 b=s.optimalBoundingBox(False,False);return[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def box(x0,y0,z0,x1,y1,z1):return Part.makeBox(x1-x0,y1-y0,z1-z0,A.Vector(x0,y0,z0))
def overlaps(a,b):return all(a[i]<b[i+3]and a[i+3]>b[i]for i in range(3))
out=[]
for x in (43,47):
 hexr=8.4/math.sqrt(3)
 points=[A.Vector(x+hexr*math.cos(t*math.pi/3),88.9,14+hexr*math.sin(t*math.pi/3))for t in range(6)]
 pocket=Part.Face(Part.makePolygon(points+[points[0]])).extrude(A.Vector(0,3.1,0))
 block=box(x-9,89,9.2,x+9,92.1,19.0).cut(pocket)
 rear=Part.makeCylinder(5,10,A.Vector(x,92,14),A.Vector(0,-1,0))
 for kind,s in [('block',block),('rear_body',rear)]:
  candidates=[];nearest=[]
  for i,c in shapes:
   b=c.BoundBox
   if b.XMax<x-11 or b.XMin>x+11 or b.YMax<79 or b.YMin>95 or b.ZMax<7 or b.ZMin>22:continue
   v=s.common(c).Volume;dist=s.distToShape(c)[0]
   if v>1e-7:candidates.append({'i':i,'volume_mm3':v,'bounds':bb(c)})
   nearest.append((dist,i))
  item={'x':x,'z':14,'kind':kind,'bounds':bb(s),'valid':s.isValid(),'collisions':candidates,'nearest':sorted(nearest)[:6],
        'retained_parts':{n:{'intersection_mm3':s.common(c).Volume,'distance_mm':s.distToShape(c)[0]}for n,c in parts.items()}}
  out.append(item);print(json.dumps(item),flush=True)
extra=[]
relief=Part.makeCylinder(5.6,3.1,A.Vector(47,88.9,14),A.Vector(0,1,0))
backing=box(38,89,9.2,56,92.2,19.1).cut(relief)
original_slot=box(56.9,87,15.2,64.1,90,16.7)
safe_slot=box(54.9,85,15.2,61.1,88,16.7)
original_anchor=box(57,85,14,64,92.2,18).cut(original_slot)
safe_anchor=box(55,82,14,61,92.2,18).cut(safe_slot)
for name,s in [('backing_relief',backing),('original_anchor',original_anchor),('safe_anchor',safe_anchor)]:
 hits=[];near=[]
 for i,c in shapes:
  b=c.BoundBox
  if b.XMax<30 or b.XMin>70 or b.YMax<79 or b.YMin>95 or b.ZMax<7 or b.ZMin>22:continue
  v=s.common(c).Volume;dist=s.distToShape(c)[0]
  if v>1e-7:hits.append({'i':i,'volume':v})
  near.append((dist,i))
 item={'name':name,'bounds':bb(s),'valid':s.isValid(),'solids':len(s.Solids),'hits':hits,'near':sorted(near)[:5],'part_gaps':{n:{'volume':s.common(c).Volume,'distance':s.distToShape(c)[0]}for n,c in parts.items()}}
 extra.append(item);print(json.dumps(item),flush=True)
for name,s in [('original_slot',original_slot),('safe_slot',safe_slot)]:
 cut=parts['EnclosureBase'].common(s);item={'name':name,'original_base_removed_mm3':cut.Volume,'removed_bounds':bb(cut)if cut.Volume else None};extra.append(item);print(json.dumps(item),flush=True)
report={'candidates':out,'revision_proposal':extra,'source_files_unchanged':{p:sha(Path(p))==h for p,h in hashes.items()},'sources':hashes}
(OUT/'sma-block-fit-audit.json').write_text(json.dumps(report,indent=2))
A.closeDocument(r.Name);A.closeDocument(d.Name)
