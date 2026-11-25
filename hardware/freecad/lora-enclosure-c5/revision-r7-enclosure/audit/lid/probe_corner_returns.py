"""Candidate supplemental corner returns; source/current plan untouched."""
from pathlib import Path
import FreeCAD as A,Part,json
OUT=Path(__file__).resolve().parent
lid=Part.Shape();lid.read(str(OUT/'EnclosureLid.brep'))
returns=[];spec=[]
for x,X in [(12.5,14.8),(31.2,33.5)]:
 for y,Y in[(44.4,45.6),(70.5,71.7)]:
  s=Part.makeBox(X-x,Y-y,.7,A.Vector(x,y,22))
  edges=[e for e in s.Edges if all(abs(v.Point.z-22.7)<1e-7 for v in e.Vertexes)]
  s=s.makeFillet(.2,edges);returns.append(s);spec.append([x,y,22,X,Y,22.7])
new=lid
for s in returns:new=new.fuse(s)
new=new.removeSplitter()
old_report=json.loads((OUT/'oled-roof-witnesses.json').read_text())
values=[]
for v in old_report['witnesses']:
 x,y=v['xy'];s=new.common(Part.makeLine(A.Vector(x,y,20.4),A.Vector(x,y,24.7)))
 raw=sorted([e.BoundBox.ZMin,e.BoundBox.ZMax]for e in s.Edges if e.Length>1e-5);merged=[]
 for a,b in raw:
  if merged and a<=merged[-1][1]+1e-7:merged[-1][1]=max(b,merged[-1][1])
  else:merged.append([a,b])
 assert len(merged)==1,(x,y,merged)
 a,b=merged[0];values.append(dict(v,R7_with_returns=[a,b,b-a]))
thin=[v for v in values if abs(v['R6'][2]-1.1)<1e-6]
r={'valid':new.isValid(),'single_solid':len(new.Solids)==1,'return_bounds':spec,
 'minimum_witnessed_roof_mm':min(v['R7_with_returns'][2]for v in values),
 'old_1_1mm_roof_minimum_with_returns':min(v['R7_with_returns'][2]for v in thin),
 'witnesses':values}
(OUT/'corner-return-probe.json').write_text(json.dumps(r,indent=2)+'\n')
new.exportBrep(str(OUT/'EnclosureLidWithCornerReturns.brep'))
print(json.dumps({k:v for k,v in r.items()if k!='witnesses'}))
