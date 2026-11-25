"""Vertical thickness witnesses over the four OLED head-relief regions."""
from pathlib import Path
import FreeCAD as A, Part, json, hashlib
OUT=Path(__file__).resolve().parent;ENC=OUT.parents[2]
native=ENC/'revision-r6-speaker/cad/LoRa-Enclosure-C5-R6-Speaker.FCStd'
d=A.openDocument(str(native));old=d.EnclosureLid.Shape.copy();new=Part.Shape();new.read(str(OUT/'EnclosureLid.brep'))
def spans(s,x,y):
 c=s.common(Part.makeLine(A.Vector(x,y,20.4),A.Vector(x,y,24.7)))
 raw=sorted([e.BoundBox.ZMin,e.BoundBox.ZMax]for e in c.Edges if e.Length>1e-5)
 merged=[]
 for a,b in raw:
  if merged and a<=merged[-1][1]+1e-7:merged[-1][1]=max(merged[-1][1],b)
  else:merged.append([a,b])
 return [[a,b,b-a]for a,b in merged]
values=[]
for cx,cy in [(16,43.55),(30,43.55),(16,72.55),(30,72.55)]:
 for dx in [-2.15,-1.5,-.5,0,.5,1.5,2.15]:
  for dy in [-2.15,-2,-1.5,-1.01,-1,-.99,-.95,-.5,0,.5,.95,.99,1,1.01,1.5,2,2.15]:
   if dx*dx+dy*dy>2.2**2:continue
   x,y=cx+dx,cy+dy
   a,b=spans(old,x,y),spans(new,x,y)
   if not a:continue
   if len(a)!=1 or len(b)!=1:raise RuntimeError((x,y,a,b))
   values.append({'center':[cx,cy],'xy':[x,y],'R6':a[0],'R7':b[0]})
thin=[v for v in values if abs(v['R6'][2]-1.1)<1e-6]
assert thin and all(v['R7'][2]>=v['R6'][2]-1e-6 for v in values)
report={'scope':'Exact vertical line-section witnesses, not a global minimum-wall solver.',
 'source_sha256':hashlib.sha256(native.read_bytes()).hexdigest(),'candidate_lid_sha256':hashlib.sha256((OUT/'EnclosureLid.brep').read_bytes()).hexdigest(),
 'sampled_positions':len(values),'sampled_R6_1_1mm_roof_positions':len(thin),
 'minimum_R6_sampled_roof_mm':min(v['R6'][2]for v in values),
 'minimum_R7_sampled_roof_mm':min(v['R7'][2]for v in values),
 'minimum_R7_where_R6_was_1_1_mm':min(v['R7'][2]for v in thin),
 'maximum_R7_where_R6_was_1_1_mm':max(v['R7'][2]for v in thin),
 'witnesses':values,'ok':True}
(OUT/'oled-roof-witnesses.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items()if k!='witnesses'}));A.closeDocument(d.Name)
