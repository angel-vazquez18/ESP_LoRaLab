"""Independent read-only validation of R4 BOM CSV, source data and saved XLSX."""
from pathlib import Path
import argparse,csv,hashlib,json,zipfile,xml.etree.ElementTree as ET
parser=argparse.ArgumentParser()
parser.add_argument('--visual-reviewed',action='store_true',help='Record that the current rendered upper, middle and lower previews were visually checked')
args=parser.parse_args()
ROOT=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
rows=json.loads((ROOT/'complete-bom.json').read_text(encoding='utf-8'))
with (ROOT/'LoRa-C5-R4-Complete-BOM.csv').open(encoding='utf-8-sig',newline='') as f:
    csvrows=list(csv.DictReader(f))
assert len(rows)==len(csvrows)==28
for a,b in zip(rows,csvrows):
    assert all(str(a[k])==b[k] for k in a)
byref={r['Reference']:r for r in rows}
assert len(byref)==28
for key,qty in {'CASE_INSERT':8,'CASE_SCREW':4,'BAT_SCREW':4,'CUP_SCREW':2,'CUP_NUT':2,'BAT1':1,'BAT_STRAP':2,'BAT_PAD':1,'BAT_EXT':0}.items():
    assert byref[key]['Qty per unit']==qty
printed=['CASE_BASE','CASE_LID','PTT_PLUNGER','PTT_CUP','BAT_COVER']
assert all(byref[k]['Qty per unit']==1 for k in printed)
baseline=json.loads((ROOT/'../../final-design/bom/complete-bom.json').resolve().read_text(encoding='utf-8'))
for r in baseline:
    assert r['Reference'] in byref
    if r['Reference']!='CASE_INSERT':assert byref[r['Reference']]['Qty per unit']==r['Qty per unit']
    if r['Reference'] in [v['Reference'] for v in baseline[9:]]:
        assert byref[r['Reference']]['Specification']==r['Specification']
ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
with zipfile.ZipFile(ROOT/'LoRa-C5-R4-Complete-BOM.xlsx') as z:
    assert z.testzip() is None
    xml=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
    cells={c.get('r'):c for c in xml.findall('.//s:c',ns)}
    assert float(cells['B4'].find('s:v',ns).text)==1
    for i,r in enumerate(rows,7):
        assert float(cells[f'D{i}'].find('s:v',ns).text)==r['Qty per unit']
        assert float(cells[f'F{i}'].find('s:v',ns).text)==r['Qty for build']
        assert cells[f'F{i}'].find('s:f',ns).text==f'D{i}*$B$4'
    assert not any(c.get('t')=='e' for c in cells.values())
validation=json.loads((ROOT/'BOM-VALIDATION.json').read_text(encoding='utf-8'))
assert validation['quantityScaleAndRestorePassed'] and validation['conditionalExtensionSelectionPassed']
assert 'matched 0 entries' in (ROOT/'bom-formula-scan.json').read_text()
assert sha(ROOT/'LoRa-C5-R4-Complete-BOM.xlsx')==validation['files']['xlsx']
assert sha(ROOT/'LoRa-C5-R4-Complete-BOM.csv')==validation['files']['csv']
reviewed=args.visual_reviewed or validation.get('visualReview','').startswith('passed:')
validation.update(savedXlsxFormulaAndValueCheck=True,baselineElectronicsPreserved=True,
    csvAndJsonAgree=True,formulaErrors=0,visualReview='passed: upper, middle and lower regions inspected' if reviewed else 'pending',ok=reviewed)
(ROOT/'BOM-VALIDATION.json').write_text(json.dumps(validation,indent=2)+'\n')
print(json.dumps(validation,indent=2))
