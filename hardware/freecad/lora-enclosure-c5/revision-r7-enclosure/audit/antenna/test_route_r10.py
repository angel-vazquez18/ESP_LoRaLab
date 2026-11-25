from pathlib import Path
import FreeCAD as A,Part,json,math
from route_geometry import route
OUT=Path(__file__).resolve().parent;ENC=OUT.parents[2]
def load(p):s=Part.Shape();s.read(str(p));return s
def bb(s):
 b=s.BoundBox;return[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def lower(a,b):return math.sqrt(sum(max(a[i]-b[i+3],b[i]-a[i+3],0)**2 for i in range(3)))
def pair(a,b):
 c=a.common(b);return {'volume':c.Volume,'distance':a.distToShape(b)[0],'intersection_bounds':bb(c)if not c.isNull()else None}
points=[[47,82,14],[47,80,14],[44,62,19.3],[66,62,19.3],[66,85.3,19.3],[37,85.3,19.3],[37,39.14914,16.8],[23.00004,39.14914,16.8]]
coax,data=route(points,10)
r={'route':data,'pairs':{n:pair(coax,load(OUT/(n+'.brep')))for n in ['EnclosureBase','EnclosureLid','SMAKey','ReferenceSMARearBodyR7','ReferenceCoaxTie']}}
print(json.dumps(r['pairs']),flush=True)
ref=A.newDocument('R7RouteRef');Part.insert(str(ENC/'detailed-import/C5-detailed-assembly.step'),ref.Name);comps=[]
for i,o in enumerate(o for o in ref.Objects if hasattr(o,'Shape')and not o.Shape.isNull()):
 s=o.Shape.copy();s.translate(A.Vector(0,0,6.4814));comps.append((i,s,bb(s)))
hits=[];n=0;sb=bb(coax)
for i,s,b in comps:
 if lower(sb,b)>1e-7:continue
 v=coax.common(s).Volume;n+=1
 if v>1e-6:hits.append({'index':i,'volume':v})
best=1e9;nearest=None;cnt=0
for lb,i,s in sorted((lower(sb,b),i,s)for i,s,b in comps):
 if lb>best+1e-7:break
 dist=coax.distToShape(s)[0];cnt+=1
 if dist<best:best=dist;nearest=i
r['components']={'hits':hits,'count':len(comps),'exact_booleans':n,'minimum_mm':best,'nearest':nearest,'exact_distance_checks':cnt}
r['ok']=not hits and all(x['volume']<1e-6 for x in r['pairs'].values())
(OUT/'route-r10-audit.json').write_text(json.dumps(r,indent=2));coax.exportBrep(str(OUT/'CoaxR10Final.brep'))
print(json.dumps({'ok':r['ok'],'components':r['components'],'length':data['length_mm']}),flush=True)
