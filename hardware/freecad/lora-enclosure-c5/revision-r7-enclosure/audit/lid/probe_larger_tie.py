from pathlib import Path
import FreeCAD as A, Part, json
OUT=Path(__file__).resolve().parent;ENC=OUT.parents[2];R6=ENC/'revision-r6-speaker';ANT=OUT.parent/'antenna'
scope={'__file__':str(R6/'audit/audit_candidate.py')};src=(R6/'audit/audit_candidate.py').read_text();exec(src[:src.index('d=A.openDocument')],scope)
box,bb,compare,audit=[scope[n]for n in ['box','bb','compare','audit']]
def load(p):s=Part.Shape();s.read(str(p));return s
def yr(b,r):
 s=box(*b);return s.makeFillet(r,[e for e in s.Edges if len(e.Vertexes)==2 and abs(e.Vertexes[1].Point.y-e.Vertexes[0].Point.y)>b[4]-b[1]-1e-7])
loop=yr([65.2,55.05,16,71.3,57.55,19.35],.8).cut(yr([65.65,54.95,16.45,70.85,57.65,18.9],.35))
head=box(66.8,54.05,13.6,71.3,58.55,16.3);head=head.makeFillet(.3,head.Edges)
tie=loop.fuse(head).removeSplitter();assert tie.isValid() and len(tie.Solids)==1
refs={}
for folder,names in [(ANT,['EnclosureBase','EnclosureLid','SMAKey','CoaxR10Final','ReferenceCoaxTie']), (OUT,['SpeakerTieAnchor','SpeakerRetainer','ReferenceSpeakerLeadA','ReferenceSpeakerLeadB','MicrophoneShroud'])]:
 for name in names:refs[name]=load(folder/(name+'.brep'))
relief=box(70.1,54.55,19.25,72.2,58.05,19.8)
refs['EnclosureLid']=refs['EnclosureLid'].cut(relief).removeSplitter()
src=A.openDocument(str(R6/'cad/LoRa-Enclosure-C5-R6-Speaker.FCStd'))
refs['RelievedLocatingLip']=src.LocatingLip.Shape.cut(relief).removeSplitter()
relief.exportBrep(str(OUT/'SpeakerTieLipRelief.brep'))
d=A.newDocument('TieAudit');Part.insert(str(ENC/'detailed-import/C5-detailed-assembly.step'),d.Name);comps=[]
for i,o in enumerate(o for o in d.Objects if hasattr(o,'Shape')and not o.Shape.isNull()):
 s=o.Shape.copy();s.translate(A.Vector(0,0,6.4814));comps.append((i,s,bb(s)))
report={'head_bounds':[66.8,54.05,13.6,71.3,58.55,16.3],'actual_electronics':audit(tie,comps),'pairs':{n:compare(tie,s)for n,s in refs.items()}}
report['ok']=not report['actual_electronics']['hits'] and all(v['intersection_mm3']<1e-6 for v in report['pairs'].values())
assert report['ok'],report
tie.exportBrep(str(OUT/'ReferenceSpeakerTieLargeHead.brep'))
(OUT/'larger-speaker-tie-audit.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
A.closeDocument(d.Name)
A.closeDocument(src.Name)
