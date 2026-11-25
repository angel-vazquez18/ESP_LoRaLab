from pathlib import Path
import FreeCAD as A, Part, json, hashlib, math, time
from route_geometry import route
OUT=Path(__file__).resolve().parent;ENC=OUT.parents[2];ROOT=OUT.parents[1]
NATIVE=ENC/'revision-r6-speaker/cad/LoRa-Enclosure-C5-R6-Speaker.FCStd'
STEP=ENC/'detailed-import/C5-detailed-assembly.step'
V=lambda p:A.Vector(*p)
def box(a,b):return Part.makeBox(b[0]-a[0],b[1]-a[1],b[2]-a[2],V(a))
def rounded(a,b,r):
 s=box(a,b);return s.makeFillet(r,s.Edges)
def load(p):s=Part.Shape();s.read(str(p));return s
def bb(s):
 b=s.BoundBox;return[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def lower(a,b):return math.sqrt(sum(max(a[i]-b[i+3],b[i]-a[i+3],0)**2 for i in range(3)))
def info(s):return dict(valid=s.isValid(),closed=s.isClosed(),solids=len(s.Solids),volume=s.Volume,bounds=bb(s))
def pair(a,b):return dict(intersection_mm3=a.common(b).Volume,distance_mm=a.distToShape(b)[0])
def inspect(s,comps):
 sb=bb(s);hits=[];checks=0
 for i,t,tb in comps:
  if lower(sb,tb)>1e-7:continue
  v=s.common(t).Volume;checks+=1
  if v>1e-6:hits.append({'i':i,'volume':v})
 best=1e9;nearest=None;distchecks=0
 for lb,i,t in sorted((lower(sb,b),i,t)for i,t,b in comps):
  if lb>best+1e-7:break
  dist=s.distToShape(t)[0];distchecks+=1
  if dist<best:best=dist;nearest=i
 return dict(objects=len(comps),hits=hits,exact_booleans=checks,minimum_mm=best,nearest=nearest,exact_distances=distchecks)

sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
sources={str(p):sha(p)for p in [NATIVE,STEP]}
d=A.openDocument(str(NATIVE));oldbase=d.EnclosureBase.Shape.copy()
d.Parameters.set('B99','4.2')
d.BaseWithSupports.Shapes=[o for o in d.BaseWithSupports.Shapes if o.Name!='SMACoaxAnchor']
d.BaseCutters.Shapes=[o for o in d.BaseCutters.Shapes if o.Name!='SMACoaxTieSlot']
d.recompute()

# Captive, replaceable two-flat key; nominal rear hex is explicitly provisional.
carrier=rounded([38.5,87.8,9.2],[55.5,92.2,20.6],.4)
pocket=box([39.7,89.3,10.4],[54.3,91.9,21.2])
keyblank=rounded([40,89.6,10.4],[54,91.6,20.3],.3)
jaw=box([42.8,89.5,10.3],[51.2,91.7,19.2])
key=keyblank.cut(jaw).removeSplitter()
liprelief=box([38.1,87.4,18.8],[55.9,92.0,21.0])
tierelief=box([55.35,89.8,19.0],[60.65,91.1,21.0])

# A front pad joined to the wall at one side leaves both Y tunnel mouths clear.
anchorbody=rounded([55,84,14],[61.5,89.8,18],.4)
anchorneck=rounded([60,89.2,14],[61.5,92.2,18],.4)
anchor=anchorbody.fuse(anchorneck).removeSplitter()
slot=rounded([56.5,83.9,15.2],[59.5,89.9,16.7],.35)
base=d.BaseWithSupports.Shape.fuse(carrier).fuse(anchor).cut(d.BaseCutters.Shape).cut(pocket).cut(slot).removeSplitter()
lidfile=ROOT/'audit/lid/EnclosureLid.brep'
lid=(load(lidfile)if lidfile.exists()else d.EnclosureLid.Shape).cut(liprelief).cut(tierelief).removeSplitter()
retfile=ROOT/'audit/lid/SpeakerRetainer.brep'
ret=load(retfile)if retfile.exists()else d.SpeakerRetainer.Shape.copy()

# Provisional connector body:8mmAF fixed rear hex, not a measured owned model.
pts=[A.Vector(47+8/math.sqrt(3)*math.cos(math.pi/6+i*math.pi/3),89.4,14+8/math.sqrt(3)*math.sin(math.pi/6+i*math.pi/3))for i in range(6)]
hexbody=Part.Face(Part.makePolygon(pts+[pts[0]])).extrude(A.Vector(0,2.6,0))
body=hexbody.fuse(Part.makeCylinder(3,7.4,A.Vector(47,82,14),A.Vector(0,1,0))).removeSplitter()

# Loose reference tie in a YZ plane across the X-directed cable.
outer=Part.makePlane(7.7,5.3,A.Vector(56.75,83,15.3),A.Vector(1,0,0))
# Explicit polygon avoids plane-axis conventions.
def yzrect(y0,z0,y1,z1,r):
 s=box([56.75,y0,z0],[59.25,y1,z1]);vertical=[e for e in s.Edges if abs((e.Vertexes[-1].Point-e.Vertexes[0].Point).x)>2.49]
 return s.makeFillet(r,vertical)
tie=yzrect(83,15.6,90.7,20.6,.9).cut(yzrect(83.5,16.1,90.2,20.1,.4)).removeSplitter()
head=rounded([55.75,79,16.0],[60.25,83.5,18.7],.4)
tie=tie.fuse(head).removeSplitter()
coax,route48=route([[47,82,14],[47,76.3,14],[62,76.3,20],[62,86.3,19.2],[37.5,86.3,20],[37.5,31,17.8],[23.00004,31,16.8],[23.00004,39.14914,16.8]],4.8)
coax10,route10=route([[47,82,14],[47,80,14],[47,62,19.5],[68,62,19.5],[68,86.3,19.5],[37,86.3,19.5],[37,39.14914,16.8],[23.00004,39.14914,16.8]],10)

shapes={'EnclosureBase':base,'EnclosureLid':lid,'SMAKey':key,'SMAKeyCarrier':carrier,'SMAKeyPocket':pocket,'SMAKeyLipRelief':liprelief,'SMATieLipRelief':tierelief,'SMAAnchor':anchor,'SMAAnchorSlot':slot,'ReferenceSMARearBodyR7':body,'ReferenceCoaxTie':tie,'Coax':coax,'CoaxR10Trial':coax10,'AddedBaseMaterial':base.cut(oldbase)}
print('Candidate solids built; loading assigned components',flush=True)
ref=A.newDocument('R7AntennaReference');Part.insert(str(STEP),ref.Name)
objs=[o for o in ref.Objects if hasattr(o,'Shape')and not o.Shape.isNull()];comps=[]
for i,o in enumerate(objs):
 s=o.Shape.copy();s.translate(A.Vector(0,0,6.4814));comps.append((i,s,bb(s)))
report={'source_hashes':sources,'geometry':{n:info(s)for n,s in shapes.items()},'components':{},'pairs':{},'notes':['SMA key8.4mm paralleljaw gap is provisional for illustrative8mm rearhex, not measuredkit.','Tie is nominal2.5mmwide/0.5mmthick; actualhead and bendingneedphysicalcheck.','Coax retainsR5illustrative route pendingnewroute study.']}
for n in ['SMAKey','ReferenceSMARearBodyR7','ReferenceCoaxTie','AddedBaseMaterial','Coax','CoaxR10Trial']:
 report['components'][n]=inspect(shapes[n],comps);print(n,report['components'][n],flush=True)
for n,s in {'key':key,'body':body,'tie':tie,'coax':coax}.items():
 report['pairs'][n]={m:pair(s,t)for m,t in {'base':base,'lid':lid,'key':key,'body':body,'retainer':ret}.items()if not(n==m)}
report['pairs']['base_lid']=pair(base,lid);report['pairs']['tie_coax']=pair(tie,coax)
report['r10_trial']={'components':report['components']['CoaxR10Trial'],'pairs':{n:pair(coax10,s)for n,s in {'base':base,'lid':lid,'key':key,'body':body,'retainer':ret,'tie':tie}.items()}}
report['routes']={'current_r4_8':route48,'trial_r10':route10}
report['source_unchanged']={p:sha(Path(p))==v for p,v in sources.items()}
for n,s in shapes.items():s.exportBrep(str(OUT/(n+'.brep')))
(OUT/'candidate-audit.json').write_text(json.dumps(report,indent=2))
print(json.dumps({'pairs':report['pairs'],'geometry':report['geometry']}),flush=True)
A.closeDocument(ref.Name);A.closeDocument(d.Name)
