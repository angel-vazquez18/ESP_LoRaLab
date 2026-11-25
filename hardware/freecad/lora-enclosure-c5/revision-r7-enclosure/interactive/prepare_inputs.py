"""Bind R7 view inputs to audited candidates or an approved saved native model.

Reads immutable project/R6/R7 files. Never saves a FreeCAD document.
"""
from pathlib import Path
import argparse,hashlib,json
import FreeCAD as A,Part
ROOT=Path(__file__).resolve().parent;R7=ROOT.parent;ENC=R7.parent;R6=ENC/'revision-r6-speaker'
P=argparse.ArgumentParser();P.add_argument('--preflight',action='store_true');args=P.parse_args()
ANT=R7/'audit/antenna';LID=R7/'audit/lid';REF=ROOT/'reference';REF.mkdir(exist_ok=True)
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
native_path=R7/'cad/LoRa-Enclosure-C5-R7-Reinforced.FCStd'
sources={str(Path(__file__).resolve()):sha(__file__)}
for p in [ANT/'antenna-final-audit.json',ANT/'route-r10-audit.json',LID/'lid-candidate-audit.json',LID/'oled-roof-witnesses.json',LID/'larger-speaker-tie-audit.json']:
 d=json.loads(p.read_text());assert d['ok'],p;sources[str(p)]=sha(p)
 for checked_path,expected_hash in d.get('source_hashes',{}).items():assert sha(checked_path)==expected_hash,(p,checked_path)
prior_config_path=R6/'interactive/SOURCE-INPUTS.json';prior_config=json.loads(prior_config_path.read_text());sources[str(prior_config_path)]=sha(prior_config_path)
for p,h in prior_config['source_hashes'].items():assert sha(p)==h,p
shapes={k:dict(v,reuse_mesh=True)for k,v in prior_config['shapes'].items()}
changed={'base','lid','speaker_retainer','speaker_nuts','sma_body','coax','coax_tie','speaker_tie','sma_key'}
candidates={}
def record(ident,folder,name,kind='reference',native=None,part=None):
 path=folder/(name+'.brep');assert path.is_file();sources[str(path)]=sha(path)
 candidates[ident]=(path,native)
 if native and not args.preflight:
  assert native_path.is_file(),native_path
  result={'native':str(native_path),'object':native,'kind':kind};sources[str(native_path)]=sha(native_path)
 else:result={'brep':str(path),'kind':kind}
 if part:result['part']=part
 shapes[ident]=result
for ident,name,folder in [('base','EnclosureBase',ANT),('lid','EnclosureLid',ANT),('sma_key','SMAKey',ANT),('speaker_retainer','SpeakerRetainer',LID)]:record(ident,folder,name,'printed-cad',native=name)
record('speaker_nuts',LID,'ReferenceSpeakerNuts')
record('speaker_tie',LID,'ReferenceSpeakerTie',native='ReferenceSpeakerTie')
record('coax',ANT,'CoaxR10Final')
record('coax_tie',ANT,'ReferenceCoaxTie')
def load(p):s=Part.Shape();s.read(str(p));return s
r6native=R6/'cad/LoRa-Enclosure-C5-R6-Speaker.FCStd';sources[str(r6native)]=sha(r6native)
prior=A.openDocument(str(r6native))
body=Part.makeCompound([load(ANT/'ReferenceSMARearBodyR7.brep'),prior.ReferenceSMAStud.Shape.copy()]);body_path=REF/'sma_body.brep';body.exportBrep(str(body_path));sources[str(body_path)]=sha(body_path)
sources[str(ANT/'ReferenceSMARearBodyR7.brep')]=sha(ANT/'ReferenceSMARearBodyR7.brep')
shapes['sma_body']={'brep':str(body_path),'kind':'reference'}
for record_ in shapes.values():
 p=Path(record_.get('brep',record_.get('native')));sources[str(p)]=sha(p)
step=ENC/'detailed-import/C5-detailed-assembly.step';sources[str(step)]=sha(step)
def delta(a,b):return a.cut(b).Volume+b.cut(a).Volume
if not args.preflight:
 current=A.openDocument(str(native_path));comparisons=[]
 for ident,(path,name)in candidates.items():
  if not name:continue
  actual=current.getObject(name).Shape;expected=load(path);difference=delta(actual,expected)
  assert difference<1e-5,(name,difference)
  assert actual.isValid() and actual.isClosed(),name
  comparisons.append({'object':name,'candidate_symmetric_difference_mm3':difference,'volume_integration_difference_mm3':abs(actual.Volume-expected.Volume)})
 retained=[]
 for name in ['PTTPlunger','PTTStopCup','BatteryCover','ReferenceBatteryEnvelope','ReferenceSMAStud','ReferenceSMAWasher','ReferenceSMANut','ReferenceAntennaCoupler','ReferenceAntenna50mm','ReferenceSpeakerEnvelope']:
  a=current.getObject(name).Shape;b=prior.getObject(name).Shape;difference=delta(a,b);assert difference<1e-6,(name,difference)
  retained.append({'object':name,'R6_symmetric_difference_mm3':difference})
 proof={'ok':True,'native_sha256':sha(native_path),'candidate_comparisons':comparisons,'retained_native_parts':retained,'native_cad_modified':False}
 rear_difference=delta(current.ReferenceSMARearBodyR7.Shape,load(ANT/'ReferenceSMARearBodyR7.brep'));assert rear_difference<1e-6
 proof['SMA_rear_body_symmetric_difference_mm3']=rear_difference
 native_nuts=Part.makeCompound([current.ReferenceSpeakerNut1.Shape,current.ReferenceSpeakerNut2.Shape]);nut_difference=delta(native_nuts,load(LID/'ReferenceSpeakerNuts.brep'));assert nut_difference<1e-6
 proof['speaker_nuts_symmetric_difference_mm3']=nut_difference
 proof['derived_references_not_native']=['R10 coax route','coax tie installation envelope']
 p=ROOT/'NATIVE-INPUT-VALIDATION.json';p.write_text(json.dumps(proof,indent=2)+'\n');sources[str(p)]=sha(p)
 A.closeDocument(current.Name)
A.closeDocument(prior.Name)
config={'source_status':'audited preflight geometry; saved-native verification pending' if args.preflight else 'saved R7 native printed geometry plus audited fit references',
 'shapes':shapes,'changed_semantics':sorted(changed),'source_hashes':sources,
 'limitations':prior_config['limitations']+['SMA body is an illustrative 8 mm AF hex; connector flats and key fit require measurement. R10 coax is a routing envelope, not a cable qualification.',
 'Two loose 2.5 mm ties are installation envelopes. Actual strap/head geometry and service access require fit checking. Microphone shroud does not contact or clamp the capsule.',
 'OLED 0.50 mm nominal datum gap and actual electronics placements are retained. No PCB manufacturing geometry is changed.']}
(ROOT/'SOURCE-INPUTS.json').write_text(json.dumps(config,indent=2)+'\n')
print(json.dumps({'source_status':config['source_status'],'shapes':list(shapes)}))
