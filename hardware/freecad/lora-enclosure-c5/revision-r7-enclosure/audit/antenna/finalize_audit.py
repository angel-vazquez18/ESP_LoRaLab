from pathlib import Path
import FreeCAD as A,Part,json,hashlib,itertools
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[1];ENC=OUT.parents[2]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):s=Part.Shape();s.read(str(p));return s
def pair(a,b):return {'intersection_mm3':a.common(b).Volume,'distance_mm':a.distToShape(b)[0]}
lidfile=ROOT/'audit/lid/EnclosureLid.brep'
sources={str(p):sha(p)for p in [lidfile,OUT/'EnclosureBase.brep',OUT/'SMAKey.brep',OUT/'CoaxR10Final.brep',OUT/'ReferenceCoaxTie.brep',OUT/'ReferenceSMARearBodyR7.brep',OUT/'antenna-native-plan.json']}
lid=load(lidfile)
for name in ['SMAKeyLipRelief','SMATieLipRelief']:lid=lid.cut(load(OUT/(name+'.brep')))
lid=lid.removeSplitter();lid.exportBrep(str(OUT/'EnclosureLid.brep'))
shapes={n:load(OUT/(n+'.brep'))for n in ['EnclosureBase','SMAKey','CoaxR10Final','ReferenceCoaxTie','ReferenceSMARearBodyR7']}
shapes['EnclosureLid']=lid
shapes['SpeakerRetainer']=load(ROOT/'audit/lid/SpeakerRetainer.brep')
shapes['SpeakerTie']=load(ROOT/'audit/lid/ReferenceSpeakerTie.brep')
for n in ['ReferenceSpeakerLeadA','ReferenceSpeakerLeadB']:shapes[n]=load(ENC/'revision-r6-speaker/audit'/(n+'.brep'))
pairs={}
for n in ['SMAKey','CoaxR10Final','ReferenceCoaxTie','ReferenceSMARearBodyR7']:
 for m in ['EnclosureBase','EnclosureLid','SpeakerRetainer','SpeakerTie','ReferenceSpeakerLeadA','ReferenceSpeakerLeadB']:
  pairs[n+'__'+m]=pair(shapes[n],shapes[m])
pairs['Coax__tie']=pair(shapes['CoaxR10Final'],shapes['ReferenceCoaxTie'])
pairs['Key__body']=pair(shapes['SMAKey'],shapes['ReferenceSMARearBodyR7'])
pairs['base__lid']=pair(shapes['EnclosureBase'],lid)
# Geometric stop demonstration at extreme nominal guide/roof clearances.
stops=[]
for x,y,z in itertools.product([-.3,.3],[-.3,.3],[0,.7]):
 key=shapes['SMAKey'].copy();key.translate(A.Vector(x,y,z))
 for angle in [-8,8]:
  body=shapes['ReferenceSMARearBodyR7'].copy();body.rotate(A.Vector(47,0,14),A.Vector(0,1,0),angle)
  stops.append({'key_offset_mm':[x,y,z],'body_rotation_deg':angle,'interference_mm3':body.common(key).Volume})
# Verify the proposed native prism placement builds the exact illustrative hex.
d=A.newDocument('R7NativeKeyProof');p=d.addObject('Part::Prism','P');p.Polygon=6;p.Circumradius=8/(3**.5);p.Height=2.6
p.Placement=A.Placement(A.Vector(47,89.4,14),A.Rotation(0,30,-90));d.recompute()
native=p.Shape.fuse(Part.makeCylinder(3,7.4,A.Vector(47,82,14),A.Vector(0,1,0))).removeSplitter()
target=shapes['ReferenceSMARearBodyR7'];native_delta=abs(native.cut(target).Volume)+abs(target.cut(native).Volume)
report={'ok':all(v['intersection_mm3']<1e-6 for v in pairs.values())and all(v['interference_mm3']>1e-6 for v in stops)and native_delta<1e-6,
 'source_hashes':sources,'source_files_unchanged':{p:sha(Path(p))==v for p,v in sources.items()},'final_lid_sha256':sha(OUT/'EnclosureLid.brep'),
 'geometry':{n:{'valid':s.isValid(),'closed':s.isClosed(),'solids':len(s.Solids),'volume_mm3':s.Volume}for n,s in shapes.items()},
 'pairs':pairs,'key_stop_checks':stops,'native_reference_prism_symmetric_difference_mm3':native_delta,
 'route':'route-r10-audit.json','component_check':'candidate-audit.json; added material and key/tie source unchanged; R10 components independently checked',
 'limits':['Key8.4mm jaw assumes measured-equivalent8mmAF rearhex; actualhardware must be gauged.','Geometricrotationstopproof is not a torque/drop rating.','R10route uses1.32mmOD reference; actualusablelength,flexibility,head dimensions remain to verify.','Finallid was rebased to latestcorner-return lid before these checks.']}
report['ok']=report['ok']and all(report['source_files_unchanged'].values())
(OUT/'antenna-final-audit.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'ok':report['ok'],'lid_hash':report['final_lid_sha256'],'lid_volume':lid.Volume,'pairs':pairs,'minimum_key_stop_interference':min(s['interference_mm3']for s in stops),'native_ref_delta':native_delta}),flush=True)
