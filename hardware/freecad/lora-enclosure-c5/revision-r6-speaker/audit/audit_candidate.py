from pathlib import Path
import FreeCAD as A,Part,json,math,hashlib,time
OUT=Path(__file__).resolve().parent;ENC=OUT.parents[1];start=time.time()
NATIVE=ENC/'revision-r5-sma/cad/LoRa-Enclosure-C5-R5-SMA.FCStd';STEP=ENC/'detailed-import/C5-detailed-assembly.step'
def box(x0,y0,z0,x1,y1,z1):return Part.makeBox(x1-x0,y1-y0,z1-z0,A.Vector(x0,y0,z0))
def cyl(r,h,x,y,z):return Part.makeCylinder(r,h,A.Vector(x,y,z))
def bb(s):
 b=s.BoundBox;return[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def overlap(a,b):return all(a[i]<=b[i+3]+1e-7 and a[i+3]+1e-7>=b[i]for i in range(3))
def lower(a,b):return math.sqrt(sum(max(a[i]-b[i+3],b[i]-a[i+3],0)**2 for i in range(3)))
def hexagon(x,y,z,af,height):
 r=af/math.sqrt(3);pts=[A.Vector(x+r*math.cos(i*math.pi/3),y+r*math.sin(i*math.pi/3),z)for i in range(6)];return Part.Face(Part.makePolygon(pts+[pts[0]])).extrude(A.Vector(0,0,height))
def info(s):return {'valid':s.isValid(),'closed':s.isClosed(),'solids':len(s.Solids),'volume_mm3':s.Volume,'bounds_mm':bb(s)}
def compare(a,b):return {'intersection_mm3':a.common(b).Volume,'distance_mm':a.distToShape(b)[0]}
def audit(s,comps):
 hits=[];n=0;sb=bb(s)
 for i,t,tb in comps:
  if overlap(sb,tb):
   n+=1;v=s.common(t).Volume
   if v>1e-6:hits.append({'index':i,'volume_mm3':v})
 ordered=sorted((lower(sb,tb),i,t)for i,t,tb in comps);best=1e9;nearest=None;k=0
 for lb,i,t in ordered:
  if lb>best+1e-7:break
  dist=s.distToShape(t)[0];k+=1
  if dist<best:best=dist;nearest=i
 return {'objects_scanned':len(comps),'exact_booleans':n,'hits':hits,'minimum_mm':best,'nearest_source_index':nearest,'exact_distances':k}
d=A.openDocument(str(NATIVE));original={n:d.getObject(n).Shape.copy()for n in ['EnclosureBase','EnclosureLid','PTTPlunger','PTTStopCup','BatteryCover','ReferenceBatteryEnvelope']}
healed={}
for n in ['BaseCutters','LidCutters']:
 o=d.getObject(n);o.Shapes=[x for x in o.Shapes if x.Name not in ['SpeakerPassage','SpeakerTieSlot1','SpeakerTieSlot2']]
d.recompute();base=d.EnclosureBase.Shape.copy();lid=d.EnclosureLid.Shape.copy()
outer=box(45.5,40.5,16.4,63.5,53.5,21.2)
outer=outer.makeFillet(.4,outer.Edges)
inner=box(46.7,41.7,16.3,62.3,52.3,21.1)
cradle=outer.cut(inner)
fasteners=[(43.5,47),(65.5,42)]
bosses=Part.makeCompound([cyl(4.0,4.8,x,y,16.4)for x,y in fasteners])
holes=Part.makeCompound([cyl(1.2,12,x,y,13.6)for x,y in fasteners])
grille=Part.makeCompound([cyl(.9,5,x,y,20.8)for x in [51.5,54.5,57.5]for y in [44,47,50]])
wire_notch=box(61.8,45.5,17.1,63.6,48.5,20.3)
mount=cradle.fuse(bosses).cut(inner).removeSplitter()
newlid=lid.fuse(mount).cut(holes).cut(grille).cut(wire_notch).removeSplitter()
retainer=box(39.5,38.0,13.8,69.5,53.5,16.4)
retainer=retainer.makeFillet(.4,retainer.Edges)
backwindow=box(48,43,13.7,61,51,16.5)
nutpockets=Part.makeCompound([hexagon(x,y,13.7,4.3,1.9)for x,y in fasteners])
retainer=retainer.cut(holes).cut(backwindow).cut(nutpockets).removeSplitter()
speaker=box(47,42,16.9,62,52,20.4)
frontpad=box(47,42,20.4,62,52,21).cut(box(48,43,20.3,61,51,21.1))
backpad=box(47,42,16.4,62,52,16.9).cut(box(48,43,16.3,61,51,17.0))
local_top={str((x,y)):sorted(set(round(v.Point.z,6)for v in lid.common(Part.makeLine(A.Vector(x,y,0),A.Vector(x,y,30))).Vertexes))for x,y in fasteners}
top=max(max(v)for v in local_top.values())
shafts=Part.makeCompound([cyl(1,12,x,y,top+.3-12)for x,y in fasteners])
nuts=Part.makeCompound([hexagon(x,y,14.0,4.0,1.6).cut(cyl(.8,2,x,y,13.8))for x,y in fasteners])
shapes={'EnclosureBase':base,'EnclosureLid':newlid,'SpeakerRetainer':retainer,'ReferenceSpeakerEnvelope':speaker,'ReferenceSpeakerFrontGasket':frontpad,'ReferenceSpeakerBackPad':backpad,'ReferenceSpeakerScrewShafts':shafts,'ReferenceSpeakerNuts':nuts,'AddedLidMaterial':newlid.cut(original['EnclosureLid']),'HealedBaseMaterial':base.cut(original['EnclosureBase'])}
ref=A.newDocument('R6SpeakerAudit');Part.insert(str(STEP),ref.Name);objects=[o for o in ref.Objects if hasattr(o,'Shape')and not o.Shape.isNull()];comps=[]
for i,o in enumerate(objects):
 s=o.Shape.copy();s.translate(A.Vector(0,0,6.4814));comps.append((i,s,bb(s)))
report={'source_hashes':{str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in [NATIVE,STEP]},'geometry':{n:info(s)for n,s in shapes.items()},'actual_electronics':{},'pairs':{},'local_lid_face_z_mm':local_top,'fasteners_xy':fasteners,'shaft_bottom_mm':top+.3-12,'shaft_top_mm':top+.3}
for n in ['SpeakerRetainer','ReferenceSpeakerEnvelope','ReferenceSpeakerScrewShafts','AddedLidMaterial','HealedBaseMaterial']:
 report['actual_electronics'][n]=audit(shapes[n],comps);print(n,report['actual_electronics'][n],flush=True)
for a,b in [('EnclosureLid','SpeakerRetainer'),('EnclosureLid','ReferenceSpeakerEnvelope'),('SpeakerRetainer','ReferenceSpeakerEnvelope'),('SpeakerRetainer','EnclosureBase'),('SpeakerRetainer','ReferenceSpeakerNuts'),('EnclosureBase','EnclosureLid')]:report['pairs'][a+'__'+b]=compare(shapes[a],shapes[b])
coax=Part.Shape();coax.read(str(ENC/'revision-r5-sma/interactive/routing/coax.brep'))
report['coax']={n:compare(s,coax)for n,s in shapes.items()if n in ['SpeakerRetainer','ReferenceSpeakerEnvelope','AddedLidMaterial']}
report['terminal_cavities']={}
t=comps[2133][1]
for y in [69.71,75.29]:
 report['terminal_cavities'][str(y)]={str(x):[z for z in [13,13.5,14,14.5,15,15.5,16,16.5,17,17.5,18]if not t.isInside(A.Vector(x,y,z),1e-6,True)]for x in [52.75,56.25]}
report['ok']=all(not r['hits']for r in report['actual_electronics'].values())and all(r['valid']and r['closed']for r in report['geometry'].values())and all(r['intersection_mm3']<1e-6 for r in report['pairs'].values())and all(r['intersection_mm3']<1e-6 for r in report['coax'].values())
report['source_files_unchanged']={p:hashlib.sha256(Path(p).read_bytes()).hexdigest()==v for p,v in report['source_hashes'].items()}
report['ok']=report['ok']and all(report['source_files_unchanged'].values())
(OUT/'speaker-candidate-audit.json').write_text(json.dumps(report,indent=2))
for n,s in shapes.items():s.exportBrep(str(OUT/(n+'.brep')))
print(json.dumps({'ok':report['ok'],'pairs':report['pairs'],'coax':report['coax'],'terminal_cavities':report['terminal_cavities']}),flush=True)
