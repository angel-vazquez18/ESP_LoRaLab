"""R7 changed-feature schematic drawing and first-article inspection sheet.

Rendered PDF is visually checked before DOCUMENT-VALIDATION is released.
No CAD, PCB or manufacturing input is edited by this document generator.
"""
from pathlib import Path
import hashlib,json,math,subprocess,sys
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A3,landscape
from pypdf import PdfReader
from drawing_helpers import Drawing,INK,MUTED,ACCENT,PALE,METAL,GASKET,WARN,WHITE,SPEAKER

ROOT=Path(__file__).resolve().parent;REV=ROOT.parent
SOURCES={
 'lid':REV/'audit/lid/lid-candidate-audit.json',
 'antenna':REV/'audit/antenna/antenna-final-audit.json',
 'coax_route':REV/'audit/antenna/route-r10-audit.json',
 'coax_tie':REV/'audit/antenna/tie-reference-audit.json',
 'speaker_tie':REV/'audit/lid/larger-speaker-tie-audit.json',
 'coupon':REV/'audit/fit-coupon-audit.json',
 'coupon_plan':REV/'audit/fit-coupon-plan.json',
 'oled_roofs':REV/'audit/lid/oled-roof-witnesses.json',
 'pcb_guard_baseline':REV/'audit/pcb-guard-baseline.json',
}
sources={k:json.loads(p.read_text())for k,p in SOURCES.items()}
guard=json.loads((REV/'audit/pcb-guard-verification.json').read_text())
assert all(sources[k]['ok'] for k in ['lid','antenna','coax_route','coax_tie','speaker_tie','coupon']) and guard['ok']
assert sources['oled_roofs']['sampled_positions']==252
assert sources['oled_roofs']['minimum_R7_where_R6_was_1_1_mm']==1.5
assert sources['coupon']['dimensions']['nut_bearing_roof']==1.4
assert sources['lid']['geometry']['SpeakerRetainer']['bounds_mm']==[39.5,38.,13.2,69.5,53.5,16.4]
PDF=ROOT/'LoRa-C5-R7-Enclosure-Improvements.pdf'
W,H=landscape(A3);c=canvas.Canvas(str(PDF),pagesize=(W,H),pageCompression=1)
c.setTitle('LoRa C5 R7 enclosure-only improvements and first-article checks');c.setAuthor('LoRa enclosure project');d=Drawing(c)

def header(page,title,subtitle):
 d.text(34,H-43,'R7  |  '+title,22,True)
 d.text(W-34,H-40,'LoRa walkie-talkie / C5 carrier',11,True,align='right')
 d.text(W-34,H-57,f'2026-11-25  -  Nominal millimetres  -  Sheet {page} of 2',9,color=MUTED,align='right')
 d.text(34,H-67,subtitle,10,True,ACCENT);d.line((34,H-82),(W-34,H-82),ACCENT,1.1)

def footer(page):
 d.line((34,103),(W-34,103),ACCENT,.9)
 d.text(40,85,'SCOPE',9,True,ACCENT)
 d.text(100,85,'Enclosure-only revision. PCB, Gerbers, drills, firmware and component mounting positions remain unchanged.',9)
 d.wrap(40,66,'Dimensioned schematic details: the saved R7 CAD controls full contours and unshown dimensions. Nominal digital fit is not a physical strength, acoustic or ingress qualification. Measure the owned SMA, speaker and switch before production.',W-80,8.4,11,MUTED)
 d.text(40,27,'Sources: R7 candidate geometry/audits and preserved C5 assembly; unfilled MJF PA12 prototype basis.',8,color=MUTED)
 d.text(W-40,27,f'R7-ENC-0{page}  /  FIT PROTOTYPE',9,True,WARN,align='right')

header(1,'Enclosure mechanical improvements','Replaceable SMA key, thicker speaker retainer, microphone shroud and local OLED reinforcement')

# A. Viewed toward the antenna axis: X horizontal and Z vertical.
d.title(40,729,'A  Replaceable SMA key - front X-Z view')
d.text(40,713,'Parallel jaws capture the fixed rear hex; slide key from above before closing lid.',8.5,color=MUTED)
s=14;ox=110;oy=482
X=lambda x:ox+(x-39.7)*s
Z=lambda z:oy+(z-10.4)*s
c.setDash([4,3]);d.rect(X(39.7),Z(10.4),14.6*s,10.8*s,None,MUTED,.65);c.setDash([])
pts=[(X(47+8/math.sqrt(3)*math.cos(math.pi/6+i*math.pi/3)),Z(14+8/math.sqrt(3)*math.sin(math.pi/6+i*math.pi/3)))for i in range(6)]
d.poly(pts,METAL,MUTED,.7);d.circle(X(47),Z(14),3.175*s,None,MUTED,.55)
d.poly([(X(x),Z(z))for x,z in[(40,10.4),(42.8,10.4),(42.8,19.2),(51.2,19.2),(51.2,10.4),(54,10.4),(54,20.3),(40,20.3)]],PALE,INK,.8)
d.line((X(46.4),Z(14)),(X(47.6),Z(14)),MUTED,.5)
d.line((X(47),Z(13.4)),(X(47),Z(14.6)),MUTED,.5)
d.dim_h(X(42.8),X(51.2),Z(21.7),'8.40 jaw gap',Z(19.2))
d.dim_h(X(40),X(54),Z(8.2),'14.00 key width',Z(10.4))
d.dim_v(Z(10.4),Z(20.3),X(56),'9.90',X(54))
d.leader([(X(53),Z(19.8)),(X(58.5),Z(22.0))],'1.10 bridge; 2.00 axial thickness',X(58.2),Z(23.0),150)
d.text(40,426,'Nominal rear-hex reference: 8.00 AF; key gap 8.40, 0.20 per side.',9,True)
d.text(40,410,'Pocket gives 0.30 per side/axially; key top Z20.30 below lid Z21.00.',8.7)
d.wrap(40,394,'Rear hex is unmeasured: trial-fit the replaceable key and adjust its jaw gap. Match the fixed rear body, not the mounting nut.',525,8.5,11,WARN)
d.text(40,365,'Coax route uses nominal R10 bends and assumed DIA 1.32; verify the actual cable.',8.3,color=MUTED)

# B. Retainer section at first screw: support plane retained while nut moves down.
d.title(628,729,'B  Speaker retainer - reinforced nut-bearing section')
d.text(628,713,'X-Z section through screw at X43.5, Y47; other screw remains X65.5, Y42.',8.5,color=MUTED)
s=13;ox=645;oy=474
X=lambda x:ox+(x-39.5)*s
Z=lambda z:oy+(z-12)*s
# Small local patch of lid and boss shows the existing fixed stop plane.
for x0,x1 in [(39.5,42.3),(44.7,48.0)]:d.hatch_rect(X(x0),Z(21),(x1-x0)*s,3.6*s)
for x0,x1 in [(39.5,42.3),(44.7,46.7)]:d.hatch_rect(X(x0),Z(16.4),(x1-x0)*s,4.6*s)
pocket_r=4.3/math.sqrt(3)
for x0,x1 in [(39.5,43.5-pocket_r),(43.5+pocket_r,48),(61,69.5)]:d.hatch_rect(X(x0),Z(13.2),(x1-x0)*s,3.2*s)
for x0,x1 in [(43.5-pocket_r,42.3),(44.7,43.5+pocket_r)]:d.hatch_rect(X(x0),Z(15),(x1-x0)*s,1.4*s)
d.rect(X(47),Z(16.9),15*s,3.5*s,SPEAKER)
for x0,x1 in [(47,48),(61,62)]:d.rect(X(x0),Z(16.4),(x1-x0)*s,.5*s,GASKET,MUTED,.5)
d.rect(X(42.5),Z(12.9),2*s,12*s,METAL,MUTED,.5)
d.rect(X(41),Z(24.6),5*s,.3*s,METAL,MUTED,.5)
c.setFillColor(METAL);c.setStrokeColor(MUTED);c.roundRect(X(41.5),Z(24.9),4*s,1.5*s,.5*s,fill=1,stroke=1)
nr=4/math.sqrt(3);d.rect(X(43.5-nr),Z(13.4),2*nr*s,1.6*s,METAL,MUTED,.5)
d.dim_v(Z(13.2),Z(16.4),X(71),'3.20 retainer',X(69.5))
d.leader([(X(45),Z(15.7)),(X(52),Z(13.2)),(X(58),Z(13.2))],'1.40 bearing roof (was 0.80)',X(54),Z(12.2),225)
d.text(X(54.5),Z(18.4),'Speaker reference',9,True,align='center')
d.text(628,426,'Hard stop Z16.40 retained; underside lowered to Z13.20.',9,True)
d.text(628,410,'4.30 AF pocket, 1.80 deep; M2 nut Z13.40-15.00; M2 x 12 retained.',8.7)
d.text(628,394,'Nominal screw tip Z12.90: 0.50 below nut. Pads and speaker position unchanged.',8.3,color=MUTED)

# C. Noncontact microphone shroud. Capsule is intentionally not dimensioned here.
d.title(40,346,'C  Microphone shroud - section through acoustic holes')
d.text(40,330,'Integrated lid tube narrows the acoustic path; it does not press the microphone.',8.5,color=MUTED)
s=9;ox=215;oy=140
X=lambda x:ox+x*s
Z=lambda z:oy+(z-12)*s
for x0,x1 in [(-9,-3.4),(-1.8,-.8),(.8,1.8),(3.4,9)]:d.hatch_rect(X(x0),Z(21),(x1-x0)*s,3.6*s)
for x0,x1 in [(-5.5,-4),(4,5.5)]:d.hatch_rect(X(x0),Z(13),(x1-x0)*s,8*s)
d.dim_h(X(-5.5),X(5.5),Z(11.0),'DIA 11.00 outside',Z(13))
d.dim_v(Z(13),Z(21),X(11),'8.00 below lid',X(5.5))
d.leader([(X(-4),Z(17)),(X(-14),Z(18))],'DIA 8.00 bore; 1.50 nominal wall',55,Z(20),140)
d.text(385,279,'Lid underside Z21.00',8.5)
d.text(385,263,'Tube bottom Z13.00',8.5)
d.wrap(385,244,'Nominal minimum clearance to assigned components: 0.70 mm. Optional soft gasket requires actual port/frame fitting; no seal or acoustic rating is claimed.',170,8.5,11,MUTED)

# D. The two reinforced short edges remain outside the open OLED aperture.
d.title(628,346,'D  OLED roof bands + corner returns - local section')
d.text(628,330,'Added material lies outside the aperture; the 0.50 mm rim datum remains fixed.',8.5,color=MUTED)
s=17;ox=666;oy=177
X=lambda x:ox+(x-12.5)*s
Z=lambda z:oy+(z-20.5)*s
roof=[(12.8,20.5),(13.8,20.5),(13.8,21),(18.2,21),(18.2,20.5),(27.8,20.5),(27.8,21),(32.2,21),(32.2,20.5),(33.2,20.5),(33.2,22.1),(12.8,22.1)]
d.poly([(X(x),Z(z))for x,z in roof],PALE,INK,.7)
d.rect(X(12.5),Z(22.1),21*s,.6*s,SPEAKER,ACCENT,.7)
d.line((X(16),Z(20)),(X(16),Z(23.2)),MUTED,.5,[8,2,2,2])
d.line((X(30),Z(20)),(X(30),Z(23.2)),MUTED,.5,[8,2,2,2])
d.dim_v(Z(21),Z(22.7),X(35.2),'1.70 at centre',X(32.2))
d.leader([(X(23),Z(22.5)),(X(23),Z(25.0))],'0.60 added height; top Z22.70; top-edge fillet R0.20',X(15),Z(26),310)
d.text(628,155,'Bands X12.50-33.50 at Y42.20-44.55 / 71.55-73.90.',8.3)
d.text(628,142,'Returns X12.50-14.80 / 31.20-33.50 at Y44.40-45.60 / 70.50-71.70.',8.3)
d.text(628,129,'Sampled roofs 1.50-1.70; lower rim Z20.50 and main long-edge face Z22.10 retained.',8.3,color=MUTED)
footer(1);c.showPage()

header(2,'Fit coupon and assembly checks','Seven installed printed parts plus one optional process coupon; no PCB fabrication changes')

# E. Coupon plan is exact in local XY; in CAD its display offset is +100 in X.
d.title(40,729,'E  Optional one-piece fit coupon - plan view')
d.text(40,713,'Local XY coordinates shown. Printed separately; never installed in the enclosure.',8.5,color=MUTED)
s=8.5;ox=88;oy=406
X=lambda x:ox+x*s
Y=lambda y:oy+y*s
c.setFillColor(PALE);c.setStrokeColor(INK);c.roundRect(X(0),Y(0),50*s,32*s,.5*s,fill=1,stroke=1)
for x,diam in [(8,4.4),(19,4.5)]:
 d.circle(X(x),Y(8),3.5*s,None,INK,.75);d.circle(X(x),Y(8),diam/2*s,WHITE,INK,.7)
 d.text(X(x),Y(3.3),f'DIA {diam:.1f}',9,True,align='center')
d.circle(X(39),Y(9),6*s,None,INK,.75);d.circle(X(39),Y(9),4.4*s,WHITE,INK,.7)
d.text(X(39),Y(1.3),'DIA 8.8',9,True,align='center')
for x,af in [(8,4.2),(21,4.3),(34,4.4)]:
 r=af/math.sqrt(3)
 d.poly([(X(x+r*math.cos(i*math.pi/3)),Y(23+r*math.sin(i*math.pi/3)))for i in range(6)],WHITE,INK,.7)
 d.circle(X(x),Y(23),1.2*s,None,MUTED,.55)
 d.text(X(x),Y(27.8),f'{af:.1f} AF',9,True,align='center')
d.dim_h(X(0),X(50),Y(-2.1),'50.00',Y(0));d.dim_v(Y(0),Y(32),X(-3),'32.00',X(0))
d.text(40,361,'Plate 3.20; insert bosses DIA 7 x 6 high; blind pilot depth 5.00.',9,True)
d.text(40,345,'Guide local thickness 3.60; M2 pockets 1.80 deep with 1.40 bearing roof.',8.7)
d.text(40,329,'Every nut pocket has a DIA 2.40 through hole. External plate edges R0.50.',8.7)
d.wrap(40,309,'Pilot 4.4 is the current insert basis; 4.5 is a comparison trial, not an approved substitute. Test the purchased nuts and actual DIA 8 plunger. Record delivered dimensions, process and finish. This coupon does not qualify PTT switch travel.',520,8.7,12,MUTED)
d.title(40,240,'F  Unchanged critical interfaces')
for i,line in enumerate([
 'PCB: 70 x 90 x 1.6; original board datums and mounting holes retained.',
 'Battery: 68 x 36 x 10 reference; 1.00 pad allowance below, 3.00 above.',
 'PTT: 0.25 provisional depression; check actual actuation and release.',
 'OLED: 0.50 nominal rim datum gap; no load on display glass.',
 'Main closure M3 x 22; rear cover M3 x 6. Do not substitute longer screws.'
]):d.text(40,219-i*18,line,8.8)

d.title(628,729,'G  Consolidated enclosure hardware')
rows=[
 ('4','M3 x 22 main closure screws','ISO 4762 / DIN 912 basis'),
 ('4','M3 x 6 battery-cover screws','Blind holes; 0.90 tip clearance'),
 ('8','M3 inserts, OD 5 x 4 long','RX-M3x5x4-compatible'),
 ('2 + 2','M2 x 10 PTT screws + nuts','Nuts 4.00 AF x 1.60'),
 ('2 + 2','M2 x 12 speaker screws + nuts','Nuts 4.00 AF x 1.60'),
 ('2','M2 speaker washers','Reference 5 OD / 2.2 ID / 0.3'),
 ('2','Soft battery straps','Nominal 10 width; no pouch squeeze'),
 ('2','Loose cable ties','2.5 wide; head 4.5 x 4.5 x 2.7'),
 ('as fit','Soft speaker/battery pads','Nonconductive; stationary frames'),
 ('kit','SMA nut / washer arrangement','Owned hardware dimensions govern'),
]
d.text(628,707,'QTY',8.5,True,ACCENT);d.text(680,707,'ITEM',8.5,True,ACCENT);d.text(943,707,'FIT BASIS',8.5,True,ACCENT)
y=687
for qty,item,note in rows:
 d.text(628,y,qty,8.5,True);d.text(680,y,item,8.5);d.text(943,y,note,8.1)
 d.line((628,y-7),(W-40,y-7),METAL,.45);y-=23
d.title(628,426,'H  First-article acceptance record')
checks=[
 'Measure insert/nut/guide fits; record the supplier and finish.',
 'Check key fit, nut engagement, no connector rotation; counter-hold.',
 'Fit real battery and USB plugs together without interference.',
 'Route full slack through installed ties; close slowly without pinching.',
 'Confirm speaker hard-stop seating; support lid while disconnecting.',
 'Measure OLED clearance and PTT actuation/release on owned hardware.',
 'Cycle closures/PTT; then test closed-case audio and intended duty.',
]
y=405
for i,line in enumerate(checks,1):
 d.text(628,y,f'{i}.',8.8,True);y=d.wrap(647,y,line,W-692,8.8,11.5)-8
d.wrap(628,221,'Tie heads are nonprinted fit references; measure the purchased parts. Local speaker-tie lip relief retains 1.20 mm lip and gives 0.45 mm loop clearance.',W-668,8.4,11,MUTED)
d.wrap(628,176,'Unfilled MJF PA12; standard cleaned finish. Supplier-specific accuracy controls the fit. No load, drop, acoustic, thermal or IP rating is established by these drawings.',W-668,8.4,11,MUTED)
footer(2);c.save()

pdf=PdfReader(PDF);assert len(pdf.pages)==2
text='\n'.join(p.extract_text()for p in pdf.pages)
for term in ['8.40','1.40','3.20','DIA 11.00','DIA 8.00','50.00','32.00','PCB','FIT PROTOTYPE']:assert term in text,term
poppler=Path(sys.executable).parent.parent/'native/poppler/Library/bin/pdftoppm.exe'
subprocess.run([str(poppler),'-png','-r','110',str(PDF),str(PDF.with_suffix(''))],check=True)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
report={'ok':True,'pages':2,'pdf_sha256':sha(PDF),'source_hashes':{str(p):sha(p)for p in SOURCES.values()},
 'drawing_kind':'Dimensioned changed-feature schematic and coupon/inspection sheet; native R7 CAD controls contours.',
 'pcb_unchanged_evidence_files':guard['files_checked'],'hardware_fit_qualified':False,'visual_review_pending':True}
(ROOT/'DOCUMENT-VALIDATION.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'pdf':str(PDF),'bytes':PDF.stat().st_size,'pages':2,'visual_review_pending':True}))
