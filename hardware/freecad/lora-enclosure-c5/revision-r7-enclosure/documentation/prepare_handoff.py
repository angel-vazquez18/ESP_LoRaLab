"""Prepare unchanged PCB copies and R7 BOM data; bind shop files only after approval.

No native CAD saves, STEP exports, PCB regeneration, CAM or machine code.
"""
from pathlib import Path
import argparse,csv,hashlib,json,shutil,zipfile
from datetime import datetime,timezone

DOC=Path(__file__).resolve().parent;REV=DOC.parent;ENC=REV.parent
R4=ENC/'revision-r4-battery';BASE=R4/'pcb-fabrication'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,x):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2)+'\n',encoding='utf-8')
def copy_exact(src,dst):
 dst.parent.mkdir(parents=True,exist_ok=True)
 if dst.exists() and sha(dst)!=sha(src):raise ValueError('Different existing copy: '+str(dst))
 if not dst.exists():shutil.copyfile(src,dst)
 assert sha(src)==sha(dst)
 return {'source':str(src),'path':dst.relative_to(REV).as_posix(),'bytes':dst.stat().st_size,'sha256':sha(dst)}

parser=argparse.ArgumentParser();parser.add_argument('--bind-approved',action='store_true');args=parser.parse_args()
plan=json.loads((REV/'release-plan.json').read_text())
pcb=REV/'pcb-fabrication';copied=[]
for src in sorted((BASE/'gerbers').iterdir()):
 if src.is_file():copied.append(copy_exact(src,pcb/'gerbers'/src.name))
for n in ['C5-PCB-Gerbers-and-Drills.zip','bom/C5-Electronics-BOM.csv','bom/C5-Electronics-BOM.xlsx']:
 copied.append(copy_exact(BASE/n,pcb/n))
copied.append(copy_exact(BASE/'FABRICATION-VALIDATION.json',pcb/'BASELINE-R4-FABRICATION-VALIDATION.json'))
archive=pcb/'C5-PCB-Gerbers-and-Drills.zip'
with zipfile.ZipFile(archive)as z:
 assert z.testzip()is None
 names=z.namelist()
 archive_equal=all(z.read(n)==(BASE/'gerbers'/Path(n).name).read_bytes()for n in names if not n.endswith('/'))
assert archive_equal
board=ENC.parent/'heltec-v4-carrier-c5/design/heltec_v4_audio_carrier.kicad_pcb'
schematic=board.with_suffix('.kicad_sch')
assert sha(board)=='9ef59b8ef6a1937503a51312633e34348a537de5761d74d0506117e61386f553'
assert sha(schematic)=='221021ce94e51d4ce6a826606c6a65f4d4664fdf0d2b3e172846919db74757e6'
pcb_manifest={'ok':True,'prepared_utc':datetime.now(timezone.utc).isoformat(),'scope':'Exact copies of previously released C5 PCB manufacturing files; no regenerated or modified PCB files.','source_revision':'R4 enclosure / unchanged C5 board','board_sha256':sha(board),'schematic_sha256':sha(schematic),'archive_sha256':sha(archive),'archive_crc_ok':True,'archive_members_equal_baseline_gerbers':archive_equal,'prior_erc_drc_cam_rerun':False,'files':copied}
write(pcb/'R7-PRESERVED-PCB-MANIFEST.json',pcb_manifest)

# Complete assembly BOM: derive from the prior assembly list, retaining all
# PCB-mounted components; replace only enclosure/off-board configuration rows.
prior=R4/'bom/complete-bom.json';rows=json.loads(prior.read_text(encoding='utf-8'));by={r['Reference']:dict(r)for r in rows}
for r in by.values():r['Group']='Purchased hardware'
def update(ref,**kw):by[ref].update(kw)
def add(ref,item,spec,qty,unit,note,source,group='Purchased hardware'):
 by[ref]={'Reference':ref,'Item':item,'Specification':spec,'Qty per unit':qty,'Unit':unit,'Qty for build':qty,'Assembly note':note,'Source':source,'Group':group}
printed={'CASE_BASE':'enclosure-base','CASE_LID':'enclosure-lid','PTT_PLUNGER':'ptt-plunger','PTT_CUP':'ptt-stop-cup','BAT_COVER':'battery-cover'}
for ref,stem in printed.items():
 update(ref,Group='Printed part',Specification='Unfilled MJF PA12; exact R7 geometry',**{'Assembly note':f'C5-R7-{stem}-mm.stl / .3mf. Quantity one per enclosure.','Source':'R7 release-plan.json and approved master geometry'})
add('SPEAKER_RETAINER','Speaker retainer','3.2 thick; 4.3 AF pockets; 1.4 bearing roof',1,'part','Seat on original hard stops; use M2x12 screws.','R7 lid audit and drawing','Printed part')
add('SMA_KEY','Replaceable SMA key','14 x 2 x 9.9; 8.4 jaw gap; provisional 8 AF rear hex',1,'part','Measure owned rear fixed hex; adjust key if required.','R7 antenna final audit','Printed part')
add('FIT_COUPON','Optional fit coupon','50 x 32; insert/nut/plunger fit trials',0,'part','Not installed. Set quantity to 1 only if ordering a process sample.','R7 fit-coupon-plan.json','Optional print')
by.pop('WIRE_TIE')
add('COAX_TIE','Coax retaining tie','2.5 wide; 0.50 strap; head envelope 4.5 x 4.5 x 2.7',1,'piece','Loose fit; measure purchased tie; do not crush coax.','R7 antenna tie-reference audit')
add('SPEAKER_TIE','Speaker lead retaining tie','2.5 wide; 0.45 strap; head envelope 4.5 x 4.5 x 2.7',1,'piece','Measure actual tie and locking-tail access.','R7 larger-speaker-tie audit')
add('SPK_SCREW','Speaker-retainer screws','M2 x 12; actual head must fit modeled envelope',2,'piece','Use with 0.3 mm washer and captive M2 nut.','R6 speaker hardware basis; R7 retained screw stack')
add('SPK_NUT','Speaker-retainer nuts','M2 x 0.4; 4 AF x 1.6 high',2,'piece','4.3 AF x 1.8 deep pockets in R7 retainer.','R7 drawing and lid audit')
add('SPK_WASHER','Speaker screw washers','5 OD x 2.2 ID x 0.3 thick reference',2,'piece','Measure owned washers.','R6 speaker assembly and R7 retained stack')
add('SPK_FRONT_PAD','Speaker front-frame gasket','Soft nonconductive; 0.6 installed allowance',1,'piece','Trim to stationary rim only; keep diaphragm clear.','R6 speaker assembly; retained R7 fit')
add('SPK_REAR_PAD','Speaker rear-frame pad','Soft nonconductive; 0.5 installed allowance',1,'piece','Keep vents and lead joints clear; do not crush speaker.','R6 speaker assembly; retained R7 fit')
for ref in ['PCB','U1','U2','U3','R8','SW1','HDR_U1','HDR_U2','JAMP1']:by[ref]['Group']='PCB assembly unchanged'
update('LS1',Item='Alrhso miniature speaker',Specification='ASIN B0GX6GZFJ2; seller 15 x 10 x 3.5 mm; 8 ohm / 1 W',Group='Off-board component',**{'Assembly note':'One speaker, enclosure mounted. Remove connector; leads to SPK+ and SPK-. Confirm actual frame and audio power limit.','Source':'R6 speaker assembly record; https://www.amazon.com/dp/B0GX6GZFJ2'})
wire_ref=next(k for k in by if k.startswith('LS1') and k!='LS1')
update(wire_ref,Item='Speaker supplied lead pair',Specification='Nominal 80 mm; included with LS1 speaker',Group='Included subcomponent',**{'Assembly note':'Do not purchase twice. Remove plug, retain service slack; neither conductor is GND.','Source':'R6 speaker assembly record'})
update('RF_ASSEMBLY',Item='915 MHz SMA antenna and U.FL pigtail kit',Specification='User-selected ASIN B0FRRZGCTQ; owned rear body must be measured',Group='Off-board component',**{'Assembly note':'Includes bulkhead mounting nut/washer. R7 assumes 8 AF rear body, 1.32 cable OD and R10 route; verify actual kit.','Source':'User-selected antenna kit; R5/R7 mounting records'})
by['BAT1']['Group']='Off-board component';by['USB_LEAD']['Group']='External service item';by['BAT_EXT']['Group']='Conditional hardware'
ordered=['CASE_BASE','CASE_LID','BAT_COVER','PTT_PLUNGER','PTT_CUP','SPEAKER_RETAINER','SMA_KEY','FIT_COUPON','CASE_SCREW','BAT_SCREW','CASE_INSERT','CUP_SCREW','CUP_NUT','SPK_SCREW','SPK_NUT','SPK_WASHER','COAX_TIE','SPEAKER_TIE','BAT_STRAP','BAT_PAD','SPK_FRONT_PAD','SPK_REAR_PAD','BAT1','BAT_EXT','RF_ASSEMBLY','LS1',wire_ref,'PCB','U1','U2','U3','R8','SW1','HDR_U1','HDR_U2','JAMP1','USB_LEAD']
assert set(ordered)==set(by) and len(ordered)==len(set(ordered))
rows=[by[k]for k in ordered]
for r in rows:r['Qty for build']=r['Qty per unit']
prior_by={r['Reference']:r for r in json.loads(prior.read_text(encoding='utf-8'))}
for ref in ['PCB','U1','U2','U3','R8','SW1','HDR_U1','HDR_U2','JAMP1']:
 for field in ['Reference','Item','Specification','Qty per unit','Unit']:
  assert by[ref][field]==prior_by[ref][field],(ref,field)
write(DOC/'bom/R7-complete-bom.json',rows)
write(DOC/'bom/BOM-SOURCE-MANIFEST.json',{'ok':True,'source_hashes':{str(prior):sha(prior),str(BASE/'bom/C5-Electronics-BOM.csv'):sha(BASE/'bom/C5-Electronics-BOM.csv'),str(DOC/'R7-ASSEMBLY-AND-INSPECTION.txt'):sha(DOC/'R7-ASSEMBLY-AND-INSPECTION.txt')},'rows':len(rows),'pcb_component_rows_unchanged':9,'offboard_speaker_and_antenna_configuration_updated':True,'default_installed_printed_quantity':7,'default_optional_coupon_quantity':0})

shop=REV/'cnc-shop';shop.mkdir(exist_ok=True)
binding={'ok':False,'status':'Awaiting approved native/STEP files and saved-native validation','geometry_basis':plan['step_file'],'machine_program_supplied':False,'installed_parts':7,'optional_coupon_parts':1,'units':'mm'}
if args.bind_approved:
 native=REV/plan['native_file'];step=REV/plan['step_file'];validation=REV/'audit/saved-r7-validation.json'
 v=json.loads(validation.read_text());assert v['ok'] and v['native_sha256']==sha(native)
 assert v['source_hashes']['step']==sha(step)
 rec=copy_exact(step,shop/'geometry'/step.name)
 binding.update(ok=True,status='Exact approved master STEP copied; shop DFM/CAM and first article required',native_sha256=sha(native),step_sha256=sha(step),geometry_copy=rec,native_validation_sha256=sha(validation),parts=[{'name':p['object'],'quantity':p['quantity'],'optional':p['optional'],'bounds_mm':v['parts'][p['object']]['bounds_mm']}for p in plan['parts']])
write(shop/'CNC-SHOP-GEOMETRY-MANIFEST.json',binding)
print(json.dumps({'pcb_copy_ok':True,'pcb_files':len(copied),'bom_rows':len(rows),'cnc_bound':binding['ok']}))
