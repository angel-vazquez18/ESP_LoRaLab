"""R7 lid candidate: read-only source, derived BREP/audit output only."""
from pathlib import Path
import FreeCAD as A, Part, json, math, hashlib, time
OUT=Path(__file__).resolve().parent
ENC=OUT.parents[2]
R6=ENC/'revision-r6-speaker'
NATIVE=R6/'cad/LoRa-Enclosure-C5-R6-Speaker.FCStd'
STEP=ENC/'detailed-import/C5-detailed-assembly.step'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
sources={str(p):sha(p)for p in[NATIVE,STEP]}
src=(R6/'audit/audit_candidate.py').read_text();helpers=src[:src.index('d=A.openDocument')]
scope={'__file__':str(R6/'audit/audit_candidate.py')};exec(compile(helpers,'helpers','exec'),scope)
box,cyl,bb,info,compare,audit,hexagon=[scope[n]for n in['box','cyl','bb','info','compare','audit','hexagon']]
def rounded(s,r):return s.makeFillet(r,s.Edges)
def top_round(s,r):
 top=s.BoundBox.ZMax
 return s.makeFillet(r,[e for e in s.Edges if all(abs(v.Point.z-top)<1e-7 for v in e.Vertexes)])
def yround(x0,y0,z0,x1,y1,z1,r):
 s=box(x0,y0,z0,x1,y1,z1)
 edges=[e for e in s.Edges if len(e.Vertexes)==2 and abs(e.Vertexes[1].Point.y-e.Vertexes[0].Point.y)>y1-y0-1e-7]
 return s.makeFillet(r,edges)
def load(p):s=Part.Shape();s.read(str(p));return s
d=A.openDocument(str(NATIVE))
original={n:d.getObject(n).Shape.copy()for n in['EnclosureBase','EnclosureLid','SpeakerRetainer','PTTPlunger','PTTStopCup','BatteryCover','ReferenceBatteryEnvelope']}
fasteners=[(43.5,47),(65.5,42)]
retainer=rounded(box(39.5,38,13.2,69.5,53.5,16.4),.4)
window=box(48,43,13.1,61,51,16.5)
holes=Part.makeCompound([cyl(1.2,13,x,y,12.8)for x,y in fasteners])
pockets=Part.makeCompound([hexagon(x,y,13.1,4.3,1.9)for x,y in fasteners])
retainer=retainer.cut(window).cut(holes).cut(pockets).removeSplitter()
nuts=Part.makeCompound([hexagon(x,y,13.4,4,1.6).cut(cyl(.8,2,x,y,13.2))for x,y in fasteners])
mic_blank=rounded(cyl(5.5,8.2,54.5,30.5,13),.4)
mic_bore=cyl(4,8.5,54.5,30.5,12.9)
mic=mic_blank.cut(mic_bore).removeSplitter()
bands=[top_round(box(12.5,y,22.0,33.5,y+2.35,22.7),.2)for y in[42.2,71.55]]
for x,X in[(12.5,14.8),(31.2,33.5)]:
 for y,Y in[(44.4,45.6),(70.5,71.7)]:bands.append(top_round(box(x,y,22,X,Y,22.7),.2))
band=bands[0].multiFuse(bands[1:]).removeSplitter()
anchor_blank=rounded(box(68.3,53.6,16.8,70.0,59.0,21.2),.4)
slot=box(68.2,54.8,18.7,70.1,57.8,19.5)
anchor=anchor_blank.cut(slot).removeSplitter()
loop=yround(65.2,55.05,16.0,71.3,57.55,19.35,.8).cut(yround(65.65,54.95,16.45,70.85,57.65,18.9,.35)).removeSplitter()
tie_head=rounded(box(66.8,54.05,13.6,71.3,58.55,16.3),.3)
tie=loop.fuse(tie_head).removeSplitter()
tie_lip_relief=box(70.1,54.55,19.25,72.2,58.05,19.8)
lid=original['EnclosureLid'].fuse(mic).fuse(band).fuse(anchor).cut(tie_lip_relief).removeSplitter()
shapes={'EnclosureLid':lid,'SpeakerRetainer':retainer,'MicrophoneShroud':mic,'OLEDReinforcement':band,
 'SpeakerTieAnchor':anchor,'ReferenceSpeakerTie':tie,'ReferenceSpeakerNuts':nuts,
 'AddedLidMaterial':lid.cut(original['EnclosureLid']).removeSplitter(),'SpeakerTieLipRelief':tie_lip_relief}
for n in ['ReferenceSpeakerEnvelope','ReferenceSpeakerLeadA','ReferenceSpeakerLeadB','ReferenceSpeakerScrewShafts']:
 shapes[n]=load(R6/'audit'/(n+'.brep'))
coax=load(ENC/'revision-r5-sma/interactive/routing/coax.brep')
ref=A.newDocument('R7LidAudit');Part.insert(str(STEP),ref.Name)
comps=[]
for i,o in enumerate(o for o in ref.Objects if hasattr(o,'Shape')and not o.Shape.isNull()):
 s=o.Shape.copy();s.translate(A.Vector(0,0,6.4814));comps.append((i,s,bb(s)))
report={'source_hashes':sources,'geometry':{n:info(s)for n,s in shapes.items()},'actual_electronics':{},'pairs':{},'native_property_basis':{}}
for n in ['SpeakerRetainer','ReferenceSpeakerNuts','AddedLidMaterial','ReferenceSpeakerTie']:
 report['actual_electronics'][n]=audit(shapes[n],comps);print(n,report['actual_electronics'][n],flush=True)
for a in ['SpeakerRetainer','MicrophoneShroud','SpeakerTieAnchor','ReferenceSpeakerTie']:
 for b,t in list(original.items())+[('Coax',coax)]+[(n,shapes[n])for n in['ReferenceSpeakerLeadA','ReferenceSpeakerLeadB','ReferenceSpeakerEnvelope','ReferenceSpeakerScrewShafts']]:
  if b in ['EnclosureLid','SpeakerRetainer']:continue
  report['pairs'][a+'__'+b]=compare(shapes[a],t)
report['pairs']['EnclosureLid__SpeakerRetainer']=compare(lid,retainer)
report['pairs']['SpeakerRetainer__ReferenceSpeakerNuts']=compare(retainer,nuts)
report['pairs']['SpeakerTieAnchor__ReferenceSpeakerTie']=compare(anchor,tie)
for n in ['SpeakerRetainerBlank','SpeakerRetainerWindow','SpeakerNutPocket1','SpeakerNutPocket2','ReferenceSpeakerNutBlank1','ReferenceSpeakerNutBore1','SpeakerScrewHole1','LidWithClamps']:
 o=d.getObject(n);report['native_property_basis'][n]={'type':o.TypeId,'placement':str(o.Placement),'expressions':[(a,str(b))for a,b in o.ExpressionEngine]}
 if hasattr(o,'Shapes'):report['native_property_basis'][n]['Shapes']=[q.Name for q in o.Shapes]
report['ok']=all(not r['hits']for r in report['actual_electronics'].values())and all(p['intersection_mm3']<1e-6 for p in report['pairs'].values())and all(g['valid'] and g['closed']for g in report['geometry'].values())
report['source_files_unchanged']={p:sha(Path(p))==h for p,h in sources.items()};report['ok']&=all(report['source_files_unchanged'].values())
for n,s in shapes.items():s.exportBrep(str(OUT/(n+'.brep')))
(OUT/'lid-candidate-audit.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'ok':report['ok'],'problem_pairs':{k:v for k,v in report['pairs'].items()if v['intersection_mm3']>1e-6},'native':report['native_property_basis']}),flush=True)
A.closeDocument(ref.Name);A.closeDocument(d.Name)
