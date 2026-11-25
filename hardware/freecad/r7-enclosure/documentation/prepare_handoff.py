"""Verify current R7 documents and handoff without obsolete enclosure folders.

No CAD/PCB export, CAM generation or BOM rewriting. Original reviewed reports
stay immutable; HANDOFF-VALIDATION binds their artifacts to current locations.
"""
from pathlib import Path
from datetime import datetime,timezone
import argparse,hashlib,json,zipfile,subprocess,sys

DOC=Path(__file__).resolve().parent;ROOT=DOC.parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
load=lambda p:json.loads(Path(p).read_text(encoding='utf-8-sig'))
def verify(path,expected):
 p=ROOT/path
 assert p.is_file() and sha(p)==expected,path
 return {'path':path,'bytes':p.stat().st_size,'sha256':expected}

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--bind-approved',action='store_true',help='Compatibility flag: verify only; never copy or export geometry.')
 parser.add_argument('--verify-pcb',action='store_true',help='Rerun all367 protected-source checks; requires complete local project/external trees and preserved full PCB baseline.')
 args=parser.parse_args();files=[];pcb_files=[]
 plan=load(ROOT/'release-plan.json');native=ROOT/plan['native_file'];step=ROOT/plan['step_file']
 audit=load(ROOT/'audit/saved-r7-validation.json')
 assert audit['ok'] and sha(native)==audit['native_sha256'] and sha(step)==audit['source_hashes']['step']
 guard_path=ROOT/'audit/pcb-relocation-verification.json'
 if args.verify_pcb:
  subprocess.run([sys.executable,str(ROOT/'audit/verify_pcb_guard.py')],check=True,stdout=subprocess.PIPE,text=True)
 guard=load(guard_path if guard_path.exists() else ROOT/'audit/pcb-guard-verification.json')
 assert guard['ok'] and guard['files_checked']==367 and not(guard['changed']or guard['added']or guard['missing'])
 assert sha(ROOT/'audit/pcb-guard-baseline.json')==guard['baseline_sha256']
 retained={
  'documentation/references/BATTERY-CONNECTION-REVIEW.txt':'3a4f50edcac6e813a6ccce38e1e4330ae4b0ed164297e812f36649f951efcc6c',
  'documentation/references/HARDWARE-ADDENDUM.txt':'1efd8a4eda610d49912a8a8ef0f912e59858167d825f08b5662f0809a1f0c3a2',
  'documentation/references/complete-bom-provenance.json':'7e1d099d4a0681c861a9522c4fbf14ff9ca4255f7987887ac664a6476a4f3964'}
 files.extend(verify(p,h) for p,h in retained.items())
 pcb_manifest=ROOT/'pcb-fabrication/R7-PRESERVED-PCB-MANIFEST.json'
 if (ROOT/'pcb-fabrication').exists():
  pcb=load(pcb_manifest);assert pcb['ok']
  for record in pcb['files']:
   pcb_files.append(verify(record['path'],record['sha256']))
   if args.verify_pcb:
    source_suffix=record['source'].replace('\\','/').split('/pcb-fabrication/',1)[1]
    assert sha(ROOT/'references/pcb-fabrication-baseline'/source_suffix)==record['sha256']
  archive=ROOT/'pcb-fabrication/C5-PCB-Gerbers-and-Drills.zip'
  with zipfile.ZipFile(archive) as z:
   assert z.testzip() is None
   assert all(z.read(n)==(ROOT/'pcb-fabrication/gerbers'/Path(n).name).read_bytes() for n in z.namelist() if not n.endswith('/'))
  assert sha(archive)==pcb['archive_sha256']
 bom=load(DOC/'bom/BOM-VALIDATION.json');assert bom['ok'] and not bom['visual_review_pending']
 assert bom['reviewed_xlsx_sha256']==bom['files']['xlsx']
 for ext,h in bom['files'].items():files.append(verify('documentation/bom/LoRa-C5-R7-Complete-BOM.'+ext,h))
 data=DOC/'bom/R7-complete-bom.json';assert sha(data)==next(iter(bom['source_hashes'].values()))
 rows=load(data);old={r['Reference']:r for r in load(DOC/'references/complete-bom-provenance.json')};now={r['Reference']:r for r in rows}
 assert len(rows)==len(now)==37
 for ref in ['PCB','U1','U2','U3','R8','SW1','HDR_U1','HDR_U2','JAMP1']:
  for field in ['Reference','Item','Specification','Qty per unit','Unit']:assert now[ref][field]==old[ref][field]
 drawing=load(DOC/'manufacturing/MANUFACTURING-DRAWING-VALIDATION.json')
 assert drawing['ok'] and drawing['release_ready'] and not drawing['visual_review_pending']
 assert drawing['pdf_sha256']==drawing['reviewed_pdf_sha256']
 files.append(verify('documentation/manufacturing/'+drawing['pdf'],drawing['pdf_sha256']))
 for p,h in drawing['source_hashes'].items():files.append(verify(p,h))
 assert drawing['global_placement_correction']['ok'] and drawing['global_placement_correction']['component_count']==2949
 changed=load(DOC/'DOCUMENT-VALIDATION.json');assert changed['ok'] and not changed['visual_review_pending']
 files.append(verify('documentation/LoRa-C5-R7-Enclosure-Improvements.pdf',changed['reviewed_pdf_sha256']))
 shop=load(ROOT/'cnc-shop/CNC-SHOP-GEOMETRY-MANIFEST.json')
 assert shop['ok'] and shop['native_sha256']==sha(native) and shop['step_sha256']==sha(step)
 assert shop['native_validation_sha256']==sha(ROOT/'audit/saved-r7-validation.json')
 files.append(verify(shop['geometry_copy']['path'],sha(step)))
 proofs=['audit/pcb-guard-baseline.json','audit/pcb-guard-verification.json','audit/saved-r7-validation.json','documentation/DOCUMENT-VALIDATION.json','documentation/bom/BOM-SOURCE-MANIFEST.json','documentation/bom/BOM-VALIDATION.json','documentation/manufacturing/provenance/MANUFACTURING-DRAWING-VALIDATION.json','documentation/manufacturing/provenance/manufacturing-geometry.json','cnc-shop/CNC-SHOP-GEOMETRY-MANIFEST.json']
 report={'ok':True,'verified_utc':datetime.now(timezone.utc).isoformat(),'portable':not args.verify_pcb,'scope':'Current R7 documents, reviewed BOM, corrected drawing and exact CNC STEP; PCB payload checked only when supplied.','native_sha256':sha(native),'step_sha256':sha(step),'pcb_files_checked':len(pcb_files),'pcb_copy_status':'present copies verified against original manifest and ZIP contents' if pcb_files else 'not supplied; PCB source checks not performed','protected_files_checked':367 if args.verify_pcb else 0,'historical_guard_file_count':367,'protected_source_recheck_performed':args.verify_pcb,'bom_rows':37,'pcb_component_rows_unchanged':9,'actual_components_global_placement':2949,'pcb_cam_regenerated':False,'machine_gcode_generated':False,'historical_comparisons_rerun':False,'files':files,'optional_pcb_copy_files':pcb_files,'preserved_evidence_sha256':{p:sha(ROOT/p) for p in proofs},'current_geometry_sha256':drawing['geometry_sha256'],'current_drawing_sha256':drawing['pdf_sha256'],'guard_evidence_sha256':sha(guard_path if guard_path.exists() else ROOT/'audit/pcb-guard-verification.json')}
 (DOC/'HANDOFF-VALIDATION.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'ok':True,'protected_files_checked':report['protected_files_checked'],'historical_guard_file_count':367,'bom_rows':37,'pcb_files_checked':len(pcb_files),'drawing_pages':drawing['pages'],'output':'documentation/HANDOFF-VALIDATION.json'}))

if __name__=='__main__':main()
