from pathlib import Path
import FreeCAD as A,Part,json,math,hashlib
OUT=Path(__file__).resolve().parent;ENC=OUT.parents[2]
def box(a,b):return Part.makeBox(b[0]-a[0],b[1]-a[1],b[2]-a[2],A.Vector(*a))
def yzrect(y0,z0,y1,z1,r):
 s=box([56.75,y0,z0],[59.25,y1,z1]);edges=[e for e in s.Edges if abs((e.Vertexes[-1].Point-e.Vertexes[0].Point).x)>2.49]
 return s.makeFillet(r,edges)
loop=yzrect(83,15.6,90.7,20.6,.9).cut(yzrect(83.5,16.1,90.2,20.1,.4))
head=box([55.75,79,16],[60.25,83.5,18.7]);head=head.makeFillet(.4,head.Edges)
tie=loop.fuse(head).removeSplitter();assert tie.isValid()and len(tie.Solids)==1
tie.exportBrep(str(OUT/'ReferenceCoaxTie.brep'))
# All assigned component AABBs exclude the entire updated tie bounding box.
boundfile=ENC/'revision-r5-sma/interactive/routing/component-bounds.json'
data=json.loads(boundfile.read_text());b=tie.BoundBox;bb=[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def lower(a,b):return math.sqrt(sum(max(a[i]-b[i+3],b[i]-a[i+3],0)**2 for i in range(3)))
distances=[(lower(bb,c['bb']),c['i'])for c in data];best=min(distances)
assert len(data)==2949 and best[0]>0
r={'ok':True,'reference':'ReferenceCoaxTie.brep','sha256':hashlib.sha256((OUT/'ReferenceCoaxTie.brep').read_bytes()).hexdigest(),'head_bounds_mm':[55.75,79,16,60.25,83.5,18.7],'strap_bounds_mm':bb,
 'component_bounds_source':str(boundfile),'component_bounds_sha256':hashlib.sha256(boundfile.read_bytes()).hexdigest(),'component_count':len(data),'aabb_intersections':0,'minimum_conservative_component_clearance_mm':best[0],'nearest_index':best[1],
 'note':'Head moved0.4mm up; complete tie boundingboxexcludesall2949assigned componentbounds. Exact wire/lid/nativeintersections checkedbyfinalize_audit.py.'}
(OUT/'tie-reference-audit.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
