"""Hash and package the reviewed CNC-shop handoff. Run after visual QA."""
from pathlib import Path
import argparse,hashlib,json,zipfile
from pypdf import PdfReader
ap=argparse.ArgumentParser();ap.add_argument('--visual-reviewed',action='store_true');args=ap.parse_args()
if not args.visual_reviewed:raise SystemExit('Review all six rendered sheets before finalizing')
root=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
g=json.loads((root/'manufacturing-geometry.json').read_text())
native=root.parent/'cad/LoRa-Enclosure-C5-R4-Battery.FCStd'
assert sha(native)==g['source_sha256']
assert len(g['parts'])==5 and all(r['step_symmetric_difference_mm3']<1e-5 for r in g['parts'].values())
for r in g['parts'].values():assert sha(root/r['step_file'])==r['step_sha256']
dx=json.loads((root/'cnc-reference/DXF-READBACK-VALIDATION.json').read_text());assert dx['ok']
dxm=json.loads((root/'cnc-reference/DXF-REFERENCE-MANIFEST.json').read_text())
for r in dxm['records']:assert sha(root/'cnc-reference'/Path(r['file']).name)==r['sha256']
pdf=root/'C5-R4-Manufacturing-Drawings.pdf';reader=PdfReader(pdf);assert len(reader.pages)==6
assert all(abs(float(p.mediabox.width)-1190.551)<.01 and abs(float(p.mediabox.height)-841.8898)<.01 for p in reader.pages)
text='\n'.join(p.extract_text()for p in reader.pages)
assert all(s in text for s in ['BATTERY COVER','0.50','M3 x 6','0.45','CNC SHOP','AMP_SD LOW'])
outputs=[pdf,root/'CNC-SHOP-HANDOFF.txt',root/'manufacturing-geometry.json']+sorted((root/'cnc-step').glob('*.step'))+sorted((root/'cnc-reference').glob('*'))+sorted((root/'drawing-previews').glob('C5-R4-Manufacturing-Sheet-*.png'))
guard={'ok':True,'scope':'R4 CNC-shop CAD handoff and engineering drawings, not executable CNC code or physical qualification',
       'source_native_sha256':sha(native),'native_source_unchanged':True,'single_solid_step_count':5,
       'step_native_symmetric_differences_mm3':{n:r['step_symmetric_difference_mm3']for n,r in g['parts'].items()},
       'dxf_readback_ok':True,'dxf_max_bound_deviation_mm':max(r['max_bound_deviation_mm']for r in dx['records']),
       'pdf_pages':6,'pdf_text_checks':True,'visual_review':'All six final A3 sheets visually inspected. No clipping, overlap or blank views; sheet2 title also inspected at enlarged pixel scale.',
       'physical_fit_qualified':False,'cnc_cam_qualified':False,'machine_gcode_included':False,
       'outputs':[{'path':p.relative_to(root).as_posix(),'sha256':sha(p),'bytes':p.stat().st_size}for p in outputs]}
(root/'MANUFACTURING-VALIDATION.json').write_text(json.dumps(guard,indent=2)+'\n')
archive=root/'C5-R4-CNC-Shop-Handoff.zip'
payload=[p for p in outputs if 'drawing-previews'not in p.parts]+[root/'MANUFACTURING-VALIDATION.json']
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED)as z:
 for p in payload:z.write(p,p.relative_to(root).as_posix())
 integration=root.parent/'documentation/C5-R4-Battery-Integration.pdf'
 z.write(integration,'C5-R4-Battery-Integration.pdf')
with zipfile.ZipFile(archive)as z:assert z.testzip()is None
print(json.dumps({'ok':True,'archive':str(archive),'archive_sha256':sha(archive),'files':len(payload)+1,'pdf':str(pdf)}))
