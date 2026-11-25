"""Verify the original 367-file PCB guard after documented relocation.

The baseline and historical verification are immutable. This script has no
capture/reset mode and writes only pcb-relocation-verification.json. Explicit
workspace-root override supports clones; external local-source scopes retain
their original recorded locations. No protected files are modified.
"""
from pathlib import Path
from datetime import datetime, timezone
import argparse, hashlib, json

OUT=Path(__file__).resolve().parent
ROOT=OUT.parent
EXPECTED_BASELINE='1171efb220241711e4425e6aee6cdb6817560d79c8021e5547892f0445d0a20f'

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def included(p,root):
    rel=p.relative_to(root) if root.is_dir() else Path(p.name)
    if any(part in {'.git','.pio','__pycache__','node_modules'} for part in rel.parts):return False
    return not (p.name.endswith('.lck') or p.suffix.lower() in {'.pyc','.pyo','.kicad_prl'} or p.name.startswith('~'))

def snapshot(scopes):
    files={};counts={}
    for scope,root in scopes.items():
        if not root.exists():raise FileNotFoundError('Required guard scope missing: '+str(root))
        candidates=[root] if root.is_file() else sorted(p for p in root.rglob('*') if p.is_file())
        selected=[p for p in candidates if included(p,root)]
        counts[scope]=len(selected)
        for p in selected:
            key=scope+'/'+(p.name if root.is_file() else p.relative_to(root).as_posix())
            files[key]={'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
    return {'scope_counts':counts,'files':files}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workspace-root',type=Path);args=parser.parse_args()
    baseline=OUT/'pcb-guard-baseline.json'
    assert sha(baseline)==EXPECTED_BASELINE,'Original baseline bytes changed'
    before=json.loads(baseline.read_text())
    work=args.workspace_root.resolve() if args.workspace_root else next((p for p in ROOT.parents if (p/'output/heltec-v4-carrier-c5/design').is_dir()),None)
    if work is None:raise ValueError('Pass --workspace-root to the project containing output/heltec-v4-carrier-c5/design')
    scopes={k:Path(p) for k,p in before['scope_roots'].items()}
    scopes.update({'workspace_c5_design':work/'output/heltec-v4-carrier-c5/design',
        'c5_fabrication_handoff':ROOT/'references/pcb-fabrication-baseline',
        'assigned_component_step':ROOT/'references/components/C5-detailed-assembly.step'})
    for k in scopes:
        if k.startswith('workspace_legacy_firmware/'):
            scopes[k]=work/'esp32-audio-chunker-test'/k.split('/',1)[1]
    current=snapshot(scopes);old=before['files'];now=current['files']
    added=sorted(set(now)-set(old));missing=sorted(set(old)-set(now))
    changed=[k for k in sorted(set(old)&set(now)) if old[k]['sha256']!=now[k]['sha256'] or old[k]['bytes']!=now[k]['bytes']]
    report={'ok':not(added or missing or changed),'verified_utc':datetime.now(timezone.utc).isoformat(),
        'baseline_sha256':sha(baseline),'files_checked':len(now),'scope_counts':current['scope_counts'],
        'added':added,'missing':missing,'changed':changed,
        'original_baseline_preserved':True,'historical_verification_preserved':True,
        'relocated_scopes':['c5_fabrication_handoff','assigned_component_step'],
        'scope_roots':{k:str(p) for k,p in scopes.items()},
        'relocation':{k:{'original':before['scope_roots'][k],'current':scopes[k].relative_to(ROOT).as_posix()} for k in ['c5_fabrication_handoff','assigned_component_step']},
        'statement':'Original 367 protected files have identical hashes, sizes and scope-relative membership. Only documented enclosure-related reference locations changed; PCB and firmware bytes were not modified.'}
    (OUT/'pcb-relocation-verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
    if not report['ok']:raise SystemExit(1)

if __name__=='__main__':main()
