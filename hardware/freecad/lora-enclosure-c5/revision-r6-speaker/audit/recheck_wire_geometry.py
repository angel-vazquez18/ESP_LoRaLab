"""Recheck unchanged speaker leads against an updated printable candidate.

Electronics checks may be reused only after exact wire BREP and STEP hash
equality with the preceding completed fit audit. All candidate native-shape
intersection/distance pairs are evaluated again.
"""
from pathlib import Path
import FreeCAD,Part,json,hashlib
OUT=Path(__file__).resolve().parent;ENC=OUT.parents[1]
fit=json.loads((OUT/'speaker-fit-audit.json').read_text())
r=json.loads((OUT/'speaker-wire-audit.json').read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
sources={p:sha(Path(p))==v for p,v in fit['source_hashes'].items()}
for name in ['ReferenceSpeakerLeadA','ReferenceSpeakerLeadB']:
 p=OUT/(name+'.brep');sources[str(p)]=sha(p)==fit['derived_brep_hashes'][p.name]
assert all(sources.values()),'Source change prevents reuse of actual-electronics checks'
def load(p):s=Part.Shape();s.read(str(p));return s
def pair(a,b):return {'intersection_mm3':a.common(b).Volume,'distance_mm':a.distToShape(b)[0]}
others={n:load(OUT/(n+'.brep'))for n in ['EnclosureBase','EnclosureLid','SpeakerRetainer','ReferenceSpeakerEnvelope','ReferenceSpeakerScrewShafts']}
others['Coax']=load(ENC/'revision-r5-sma/interactive/routing/coax.brep')
for name in ['ReferenceSpeakerLeadA','ReferenceSpeakerLeadB']:
 s=load(OUT/(name+'.brep'));r['native_pairs'][name]={n:pair(s,t)for n,t in others.items()}
r['source_hash_verification']=sources
r['candidate_lid_sha256']=sha(OUT/'EnclosureLid.brep')
r['candidate_native_brep_hashes']={n:sha(OUT/(n+'.brep'))for n in others if n!='Coax'}
r['recheck']='Updated3mm-pitch grille. Exact wireBREP and originalSTEP hashes unchanged; existing2949source electronics audit reused; all nativeBRep distance/intersection pairs re-evaluated.'
r['ok']=all(sources.values())and all(not a['hits']for a in r['actual_electronics'].values())and all(a['intersection_mm3']<1e-6 for p in r['native_pairs'].values()for a in p.values())
assert r['ok']
(OUT/'speaker-wire-audit.json').write_text(json.dumps(r,indent=2))
print(json.dumps({'ok':r['ok'],'unchanged_sources':sources,'lid_sha256':r['candidate_lid_sha256']}))
