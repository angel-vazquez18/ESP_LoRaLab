"""Read-only integrity guard for PCB/fabrication/firmware during R7 work.

Capture exactly once with --capture. Subsequent calls verify both membership
and byte hashes. Only reports under this script's audit directory are written.
Transient KiCad locks/preferences and build caches are intentionally excluded.
"""
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import argparse, hashlib, json

OUT=Path(__file__).resolve().parent
WORK=OUT.parents[3]
LOCAL=Path('C:/Users/Homar/Documents/Arduino/ESP_LoRaLab/local-node-homar')
SCOPES={
    'workspace_c5_design':WORK/'output/heltec-v4-carrier-c5/design',
    'c5_fabrication_handoff':WORK/'output/enclosure-c5/revision-r4-battery/pcb-fabrication',
    'assigned_component_step':WORK/'output/enclosure-c5/detailed-import/C5-detailed-assembly.step',
    'local_hardware':LOCAL/'hardware',
    'local_exports':LOCAL/'exports',
}
for group,root in [('current_heltec_firmware',LOCAL),('workspace_legacy_firmware',WORK/'esp32-audio-chunker-test')]:
    for sub in ['include','src','lib','test','tools','platformio.ini']:
        SCOPES[group+'/'+sub]=root/sub

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def included(p,root):
    rel=p.relative_to(root) if root.is_dir() else Path(p.name)
    if any(part in {'.git','.pio','__pycache__','node_modules'} for part in rel.parts):return False
    return not (p.name.endswith('.lck') or p.suffix.lower() in {'.pyc','.pyo','.kicad_prl'} or p.name.startswith('~'))

def snapshot():
    files={};counts={}
    for scope,root in SCOPES.items():
        if not root.exists():raise FileNotFoundError('Required guard scope missing: '+str(root))
        candidates=[root] if root.is_file() else sorted(p for p in root.rglob('*') if p.is_file())
        selected=[p for p in candidates if included(p,root)]
        counts[scope]=len(selected)
        for p in selected:
            key=scope+'/'+(p.name if root.is_file() else p.relative_to(root).as_posix())
            files[key]={'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
    return {'scope_counts':counts,'files':files}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--capture',action='store_true');args=parser.parse_args()
    baseline=OUT/'pcb-guard-baseline.json';current=snapshot()
    if args.capture:
        if baseline.exists():raise FileExistsError('Baseline already exists; do not replace it during the revision')
        current.update({'date':'2026-11-25','captured_utc':datetime.now(timezone.utc).isoformat(),
            'scope':'Existing C5 PCB and fabrication handoff, assigned detailed component STEP, local hardware/exports, and both relevant firmware source trees. No writes to protected sources.',
            'exclusions':['KiCad .lck/.kicad_prl','~ temporary files','build/cache folders .git/.pio/__pycache__/node_modules','Python bytecode'],
            'scope_roots':{k:str(v) for k,v in SCOPES.items()}})
        baseline.write_text(json.dumps(current,indent=2)+'\n')
        print(json.dumps({'captured':True,'files':len(current['files']),'scope_counts':current['scope_counts'],'baseline_sha256':sha(baseline)}))
        return
    before=json.loads(baseline.read_text());old=before['files'];now=current['files']
    added=sorted(set(now)-set(old));missing=sorted(set(old)-set(now))
    changed=[k for k in sorted(set(old)&set(now)) if old[k]['sha256']!=now[k]['sha256'] or old[k]['bytes']!=now[k]['bytes']]
    report={'ok':not(added or missing or changed),'verified_utc':datetime.now(timezone.utc).isoformat(),
        'baseline_sha256':sha(baseline),'files_checked':len(now),'scope_counts':current['scope_counts'],
        'added':added,'missing':missing,'changed':changed,'statement':'PCB, manufacturing handoff and firmware bytes/membership unchanged within the recorded scopes.'}
    (OUT/'pcb-guard-verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
    if not report['ok']:raise SystemExit(1)

if __name__=='__main__':main()
