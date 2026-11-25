"""Prepare immutable R6 viewer inputs from the audited candidate or saved native.

Run with FreeCAD Python. Generated reference BREPs are presentation only.
"""
from pathlib import Path
import argparse,hashlib,json,math
import FreeCAD as A,Part
ROOT=Path(__file__).resolve().parent;R6=ROOT.parent;ENC=R6.parent
P=argparse.ArgumentParser();P.add_argument('--preflight',action='store_true');args=P.parse_args()
AUDIT=R6/'audit';REF=ROOT/'reference';REF.mkdir(exist_ok=True)
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
plan=json.loads((AUDIT/'speaker-geometry-plan.json').read_text())
check=json.loads((AUDIT/'speaker-candidate-audit.json').read_text());assert check['ok']
native_path=R6/'cad/LoRa-Enclosure-C5-R6-Speaker.FCStd'
shapes={};sources={str(Path(__file__).resolve()):sha(__file__),str(AUDIT/'speaker-geometry-plan.json'):sha(AUDIT/'speaker-geometry-plan.json'),str(AUDIT/'speaker-candidate-audit.json'):sha(AUDIT/'speaker-candidate-audit.json')}
def record(ident,name,kind='reference',part=None):
 path=AUDIT/(name+'.brep')
 if not args.preflight and ident in ('base','lid','speaker_retainer'):
  assert native_path.is_file(),native_path
  result={'native':str(native_path),'object':name,'kind':kind};sources[str(native_path)]=sha(native_path)
 else:
  assert path.is_file(),path
  result={'brep':str(path),'kind':kind};sources[str(path)]=sha(path)
 if part:result['part']=part
 shapes[ident]=result
for ident,name in [('base','EnclosureBase'),('lid','EnclosureLid'),('speaker_retainer','SpeakerRetainer')]:record(ident,name,'printed-cad')
for ident,name in [('speaker_gasket','ReferenceSpeakerFrontGasket'),('speaker_pad','ReferenceSpeakerBackPad'),('speaker_screw_shafts','ReferenceSpeakerScrewShafts'),('speaker_nuts','ReferenceSpeakerNuts')]:record(ident,name,part='speaker_screws' if ident=='speaker_screw_shafts' else None)

def box(b):x,y,z,X,Y,Z=b;return Part.makeBox(X-x,Y-y,Z-z,A.Vector(x,y,z))
def stadium(x,y,z,length,width,height):
 r=width/2;mid=Part.makeBox(length-width,width,height,A.Vector(x+r,y,z))
 return mid.fuse(Part.makeCylinder(r,height,A.Vector(x+r,y+r,z))).fuse(Part.makeCylinder(r,height,A.Vector(x+length-r,y+r,z))).removeSplitter()
def reference(ident,part,shape):
 assert shape.isValid(),ident
 path=REF/(ident+'.brep');shape.exportBrep(str(path));sources[str(path)]=sha(path)
 shapes[ident]={'brep':str(path),'part':part,'kind':'reference'}
x,y,z,X,Y,Z=plan['speaker']['bounds'];length=X-x;width=Y-y
reference('speaker_body','speaker',stadium(x,y,z,length,width,3.2))
reference('speaker_rim','speaker',stadium(x,y,Z-.3,length,width,.3).cut(stadium(x+1,y+1,Z-.4,length-2,width-2,.6)))
reference('speaker_diaphragm','speaker',stadium(x+1,y+1,Z-.3,length-2,width-2,.1))
# Hardware envelope dimensions follow the candidate's measured lid top.
top=check['shaft_top_mm'];heads=[];washers=[]
for cx,cy in check['fasteners_xy']:
 heads.append(Part.makeCylinder(1.9,1.6,A.Vector(cx,cy,top)))
 washers.append(Part.makeCylinder(2.5,.3,A.Vector(cx,cy,top-.3)).cut(Part.makeCylinder(1.1,.5,A.Vector(cx,cy,top-.4))))
reference('speaker_screw_heads','speaker_screws',Part.makeCompound(heads))
reference('speaker_screw_washers','speaker_screws',Part.makeCompound(washers))

for ident,name in [('speaker_lead_a','ReferenceSpeakerLeadA'),('speaker_lead_b','ReferenceSpeakerLeadB')]:
 path=AUDIT/(name+'.brep')
 if path.is_file():record(ident,name)
sources[str(ENC/'revision-r5-sma/cad/LoRa-Enclosure-C5-R5-SMA.FCStd')]=sha(ENC/'revision-r5-sma/cad/LoRa-Enclosure-C5-R5-SMA.FCStd')
sources[str(ENC/'detailed-import/C5-detailed-assembly.step')]=sha(ENC/'detailed-import/C5-detailed-assembly.step')
if not args.preflight:
 current=A.openDocument(str(native_path));prior=A.openDocument(str(ENC/'revision-r5-sma/cad/LoRa-Enclosure-C5-R5-SMA.FCStd'))
 comparisons=[]
 for name in ['EnclosureBase','EnclosureLid','SpeakerRetainer','ReferenceSpeakerEnvelope']:
  expected=Part.Shape();expected.read(str(AUDIT/(name+'.brep')))
  actual=current.getObject(name).Shape
  difference=actual.cut(expected).Volume+expected.cut(actual).Volume
  assert abs(difference)<1e-5,(name,difference)
  assert actual.isValid() and actual.isClosed()
  comparisons.append({'object':name,'candidate_symmetric_difference_mm3':difference})
 retained=[]
 for name in ['PTTPlunger','PTTStopCup','BatteryCover','ReferenceBatteryEnvelope','ReferenceSMARearBody','ReferenceSMAStud','ReferenceSMAWasher','ReferenceSMANut','ReferenceAntennaCoupler','ReferenceAntenna50mm']:
  a=current.getObject(name).Shape;b=prior.getObject(name).Shape
  difference=a.cut(b).Volume+b.cut(a).Volume;assert abs(difference)<1e-6,(name,difference)
  retained.append({'object':name,'R5_symmetric_difference_mm3':difference})
 A.closeDocument(current.Name);A.closeDocument(prior.Name)
 proof={'ok':True,'printed_and_speaker_envelope_comparisons':comparisons,'retained_native_parts':retained,'native_cad_modified':False}
 (ROOT/'NATIVE-INPUT-VALIDATION.json').write_text(json.dumps(proof,indent=2)+'\n')
 sources[str(ROOT/'NATIVE-INPUT-VALIDATION.json')]=sha(ROOT/'NATIVE-INPUT-VALIDATION.json')
config=dict(source_status='audited preflight geometry; saved-native verification pending' if args.preflight else 'saved R6 native printed geometry plus audited fit references',
 shapes=shapes,source_hashes=sources,
 limitations=['Illustrative oval speaker from the photo within the conservative 15 x 10 x 3.5 mm rectangular fit envelope. All engineering collision checks use the full box, not this visual approximation.',
 'Gasket and rear pad rectangles indicate allowance only; trim support to the actual speaker frame and keep the diaphragm clear.',
 'Screw/washer/nut and wire envelopes are references. Actual terminal left/right polarity and wire entry shape require checking on hardware.'])
(ROOT/'SOURCE-INPUTS.json').write_text(json.dumps(config,indent=2)+'\n')
print(json.dumps({'source_status':config['source_status'],'shapes':list(shapes)}))
