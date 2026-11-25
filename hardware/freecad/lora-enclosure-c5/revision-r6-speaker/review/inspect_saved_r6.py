"""Read-only saved-model inventory for the R6 engineering review."""
from pathlib import Path
from collections import Counter
import hashlib, json, math
import FreeCAD as App

ROOT=Path(__file__).resolve().parents[1]
native=ROOT/'cad/LoRa-Enclosure-C5-R6-Speaker.FCStd'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
initial=sha(native)
prior=json.loads((ROOT/'manufacturing-validation.json').read_text())
assert prior['ok'] and initial==prior['files']['native']['sha256']
doc=App.openDocument(str(native))
try:
    names=['EnclosureBase','EnclosureLid','PTTPlunger','PTTStopCup','BatteryCover','SpeakerRetainer']
    parts={}
    for name in names:
        o=doc.getObject(name);s=o.Shape;b=s.optimalBoundingBox(False,False)
        parts[name]={'type':o.TypeId,'valid':s.isValid(),'closed':s.isClosed(),'solids':len(s.Solids),
            'volume_mm3':s.Volume,'bounds_mm':[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax],
            'size_mm':[b.XLength,b.YLength,b.ZLength]}
    tables={}
    for name in ['Parameters','SpeakerParameters']:
        o=doc.getObject(name);rows=[]
        for row in range(1,121):
            try:
                label=o.getContents('A'+str(row));value=o.get('B'+str(row));expr=o.getContents('B'+str(row))
            except Exception:continue
            if label:rows.append({'row':row,'label':label,'value':str(value),'expression':expr})
        tables[name]=rows
    obsolete=['SpeakerMountUntrimmed','SpeakerRetainerCutters','SpeakerPassage','SpeakerTieSlot1','SpeakerTieSlot2','AntennaPassage']
    history={n:{'type':doc.getObject(n).TypeId,'used_by':[o.Name for o in doc.getObject(n).InList]}for n in obsolete if doc.getObject(n)}
    report={'date':'2026-11-25','scope':'Read-only geometry/parameter inventory; existing detailed fit audits reviewed separately; no load simulation or physical testing.',
        'native_sha256':initial,'matches_existing_export_audit':True,'document_label':doc.Label,
        'object_count':len(doc.Objects),'object_types':dict(Counter(o.TypeId for o in doc.Objects)),
        'parts':parts,'parameters':tables,'retained_construction_history':history,
        'speaker_grille_open_area_mm2':9*math.pi*.9**2,
        'speaker_grille_open_fraction_of_13_by_8_window':9*math.pi*.9**2/(13*8),
        'all_printed_parts_valid_closed_single_solids':all(p['valid'] and p['closed'] and p['solids']==1 for p in parts.values())}
finally:App.closeDocument(doc.Name)
report['native_file_unchanged']=sha(native)==initial
assert report['native_file_unchanged'] and report['all_printed_parts_valid_closed_single_solids']
(ROOT/'review/native-review-evidence.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'native_unchanged':report['native_file_unchanged'],'objects':report['object_count'],'parts':parts,'grille_area_mm2':report['speaker_grille_open_area_mm2']}))
