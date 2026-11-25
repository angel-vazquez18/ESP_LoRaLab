"""Dimensioned R6 speaker integration sheet from the audited geometric plan."""
from pathlib import Path
import hashlib,json,math,subprocess,sys
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A3,landscape
from pypdf import PdfReader
from drawing_helpers import Drawing,INK,MUTED,ACCENT,PALE,SPEAKER,METAL,GASKET,WARN,WHITE

ROOT=Path(__file__).resolve().parent
REV=ROOT.parent
PLAN=REV/'audit/speaker-geometry-plan.json'
AUDIT=REV/'audit/speaker-fit-audit.json'
plan=json.loads(PLAN.read_text())
audit=json.loads(AUDIT.read_text())
assert audit['ok']
speaker=plan['speaker']['bounds'];cradle=plan['cradle_blank']['bounds'];cavity=plan['cradle_cavity']['bounds']
ret=plan['retainer_blank']['bounds'];window=plan['retainer_window']['bounds'];bosses=plan['bosses']
assert speaker==[47,42,16.9,62,52,20.4]
assert [b['position']for b in bosses]==[[43.5,47,16.4],[65.5,42,16.4]]
assert all(z==[21.0,24.6]for z in audit['local_lid_face_z_mm'].values())
assert all(p['across_flats']==4.3 for p in plan['retainer_nut_pockets'])
assert plan['grille']['centres_y']==[44,47,50]
pocket_r=plan['retainer_nut_pockets'][0]['circumradius']
PDF=ROOT/'LoRa-C5-R6-Speaker-Mount-Drawing.pdf'
W,H=landscape(A3);c=canvas.Canvas(str(PDF),pagesize=(W,H),pageCompression=1)
c.setTitle('LoRa C5 R6 - internal speaker mount and terminal wiring')
c.setAuthor('LoRa enclosure project');d=Drawing(c)

d.text(34,H-43,'R6  |  Internal speaker mount',22,True)
d.text(W-34,H-40,'LoRa walkie-talkie / C5 carrier',11,True,align='right')
d.text(W-34,H-57,'2026-11-25  -  Nominal millimetres  -  Sheet 1 of 1',9,color=MUTED,align='right')
d.text(34,H-67,'One 15 x 10 x 3.5 mm reference speaker; support the stationary body, not the diaphragm.',10.5,True,WARN)
d.line((34,H-82),(W-34,H-82),ACCENT,1.2)

# A: XY mechanical plan, as seen through the removed lid toward +Z.
d.title(40,729,'A  Lid underside - speaker cradle and retainer footprint')
d.text(40,714,'Coordinates use the original PCB frame. X right; Y up. Retainer outline dashed.',8.5,color=MUTED)
s=12;ox=75;oy=454
X=lambda x:ox+(x-39)*s
Y=lambda y:oy+(y-36)*s
# Cradle, bosses, conservative speaker outline, rear-window and grille pattern.
d.rect(X(cradle[0]),Y(cradle[1]),(cradle[3]-cradle[0])*s,(cradle[4]-cradle[1])*s,PALE)
for b in bosses:d.circle(X(b['position'][0]),Y(b['position'][1]),b['radius']*s,PALE)
d.rect(X(cavity[0]),Y(cavity[1]),(cavity[3]-cavity[0])*s,(cavity[4]-cavity[1])*s,WHITE)
d.rect(X(speaker[0]),Y(speaker[1]),15*s,10*s,SPEAKER)
c.setDash([4,3]);d.rect(X(ret[0]),Y(ret[1]),(ret[3]-ret[0])*s,(ret[4]-ret[1])*s,None,MUTED,.65);c.setDash([])
c.setDash([2,2]);d.rect(X(window[0]),Y(window[1]),13*s,8*s,None,MUTED,.6);c.setDash([])
for b in bosses:
    x,y,_=b['position'];d.circle(X(x),Y(y),1.2*s,None,INK,.8)
    d.line((X(x)-6,Y(y)),(X(x)+6,Y(y)),MUTED,.5);d.line((X(x),Y(y)-6),(X(x),Y(y)+6),MUTED,.5)
for x in plan['grille']['centres_x']:
    for y in plan['grille']['centres_y']:d.circle(X(x),Y(y),.9*s,None,ACCENT,.7)
# The real opening in the right cradle wall.
rel=plan['lead_relief']['bounds'];d.rect(X(62.3),Y(rel[1]),1.3*s,3*s,WHITE,ACCENT,.8)
d.line((X(62),Y(47)),(X(68.2),Y(47)),ACCENT,1.1);d.head((X(68.2),Y(47)),(-1,0),4)
d.text(X(68.5),Y(47)-3,'Leads',8.5,color=ACCENT)
d.dim_h(X(47),X(62),Y(55.3),'15.00 body',Y(52))
d.dim_v(Y(42),Y(52),X(37.6),'10.00 body',X(47))
d.dim_h(X(43.5),X(65.5),Y(35.3),'22.00 screw X offset',Y(42))
d.dim_v(Y(42),Y(47),X(72),'5.00 Y offset',X(65.5))
d.leader([(X(57.5),Y(plan['grille']['centres_y'][-1])),(X(67),Y(56.3))],'9 x DIA 1.80 through grille; 3.00 pitch X / Y',X(67),Y(57.4),170)
d.text(40,426,'Cradle cavity 15.60 x 10.60: 0.30 nominal side clearance per side.',9,True)
d.text(40,410,f'Retainer {ret[3]-ret[0]:.2f} x {ret[4]-ret[1]:.2f} x 2.60; rear opening 13.00 x 8.00; outside R0.40.',9)
d.text(40,394,'Screw centres (43.50, 47.00) / (65.50, 42.00), DIA 2.40; grille webs 1.20.',8.5,color=MUTED)

# B: XZ section through Y47 and the left screw axis. Right screw lies out of plane.
d.title(628,729,'B  X-Z section at Y47 - sound face toward +Z')
d.text(628,714,'Right screw is at Y42 and is not in this section. Hardware drawn schematically.',8.5,color=MUTED)
sx=13;bx=636;bz=459
U=lambda x:bx+(x-39)*sx
Z=lambda z:bz+(z-11)*sx
# Local roof, cut on the screw and centre grille holes.
roof_segments=[(39.5,42.3),(44.7,50.6),(52.4,53.6),(55.4,56.6),(58.4,70)]
for x0,x1 in roof_segments:d.hatch_rect(U(x0),Z(21),(x1-x0)*sx,3.6*sx)
# Side cradle; right wall lead slot is shown at this section.
d.hatch_rect(U(45.5),Z(16.4),1.2*sx,4.6*sx)
d.hatch_rect(U(62.3),Z(16.4),1.2*sx,.7*sx)
d.hatch_rect(U(62.3),Z(20.3),1.2*sx,.7*sx)
# Left cylindrical boss cross-section with screw passage.
for x0,x1 in [(43.5-bosses[0]['radius'],42.3),(44.7,min(cavity[0],43.5+bosses[0]['radius']))]:d.hatch_rect(U(x0),Z(16.4),(x1-x0)*sx,4.6*sx)
# Retainer rail and window, with left nut recess cut from underside.
for x0,x1 in [(ret[0],43.5-pocket_r),(43.5+pocket_r,48),(61,ret[3])]:d.hatch_rect(U(x0),Z(13.8),(x1-x0)*sx,2.6*sx)
for x0,x1 in [(43.5-pocket_r,42.3),(44.7,43.5+pocket_r)]:d.hatch_rect(U(x0),Z(15.6),(x1-x0)*sx,.8*sx)
d.rect(U(47),Z(16.9),15*sx,3.5*sx,SPEAKER)
for x0,x1 in [(47,48),(61,62)]:
    d.rect(U(x0),Z(20.4),(x1-x0)*sx,.6*sx,GASKET,MUTED,.5)
    d.rect(U(x0),Z(16.4),(x1-x0)*sx,.5*sx,GASKET,MUTED,.5)
# Shaft, washer, head and nut show the load path independently of the speaker.
d.rect(U(42.5),Z(12.9),2*sx,12*sx,METAL,MUTED,.5)
d.rect(U(41),Z(24.6),5*sx,.3*sx,METAL,MUTED,.5)
c.setFillColor(METAL);c.setStrokeColor(MUTED);c.roundRect(U(41.5),Z(24.9),4*sx,1.5*sx,.5*sx,fill=1,stroke=1)
nut_r=4/math.sqrt(3)
d.rect(U(43.5-nut_r),Z(14),2*nut_r*sx,1.6*sx,METAL,MUTED,.6)
d.line((U(43.5),Z(12)),(U(43.5),Z(27.2)),MUTED,.5,[8,2,2,2])
d.text(U(54.5),Z(18.3),'Speaker reference',9,True,align='center')
d.dim_v(Z(16.9),Z(20.4),U(70.8),'3.50 body',U(62))
d.dim_v(Z(21),Z(24.6),U(73),'3.60 roof',U(68.7))
d.leader([(U(61.5),Z(20.7)),(U(64),Z(27.5))],'0.60 front gasket allowance',U(51),Z(29),245)
d.leader([(U(61.5),Z(16.65)),(U(65),Z(12.4))],'0.50 back-pad allowance',U(53),Z(11.5),230)
d.text(628,426,'Retainer hard stop Z16.40; speaker Z16.90-20.40; lid underside Z21.00.',8.5,True)
d.text(628,410,'2 x M2 x 12 + 0.30 washer + M2 nut; nominal screw end Z12.90.',8.5)
d.text(628,394,'Hex nut recess 4.30 AF, 1.80 actual depth; retain 0.80 roof above pocket.',8.5,color=MUTED)

# Lower left: wiring diagram and incremental materials.
d.title(40,360,'C  Wiring and added materials')
d.text(40,345,'Connection schematic only; terminal left/right polarity is not implied.',8.5,color=MUTED)
d.rect(54,281,128,43,PALE);d.text(118,305,'1 W / 8 ohm',10,True,align='center');d.text(118,291,'One speaker',9,align='center')
d.rect(380,273,173,59,PALE);d.text(466.5,313,'MAX98357A',10,True,align='center')
d.text(409,290,'SPK+',9,True,align='center');d.text(510,290,'SPK-',9,True,align='center')
d.line((182,313),(247,313),ACCENT,1.1);d.line((247,313),(247,299),ACCENT,1.1);d.line((247,299),(409,299),ACCENT,1.1)
d.line((182,289),(234,289),MUTED,1.1);d.line((234,289),(234,266),MUTED,1.1);d.line((234,266),(510,266),MUTED,1.1);d.line((510,266),(510,281),MUTED,1.1)
d.text(263,321,'+ lead / removed plug',8.5,color=ACCENT);d.text(257,250,'- lead; never system GND',8.5,color=MUTED)
items=[('1','Speaker','15 x 10 x 3.5 reference; 1 W / 8 ohm'),('1','Printed retainer','R6 geometry; unfilled PA12'),('2 + 2','M2 x 12 screws + nuts','DIN 934 nut: 4.00 AF x 1.60'),('2','M2 flat washers','Reference 5.0 OD / 2.2 ID / 0.30'),('1 + 1','Gasket + back pad','Frame only; 0.60 / 0.50 installed allowance')]
y=224
for qty,item,note in items:
    d.text(40,y,qty,8.7,True);d.text(87,y,item,8.7,True);d.text(265,y,note,8.5);y-=19

# Lower right: actual audit, then short assembly sequence.
d.title(628,360,'D  Assembly and fit evidence')
checks=[('Speaker to actual components',audit['actual_electronics']['ReferenceSpeakerEnvelope']['minimum_mm']),('Retainer to actual components',audit['actual_electronics']['SpeakerRetainer']['minimum_mm']),('Retainer to R5 coax reference',audit['coax']['SpeakerRetainer']['distance_mm'])]
y=338
for label,value in checks:
    d.text(628,y,label,9);d.text(W-40,y,f'{value:.3f} mm',9,True,align='right');d.line((628,y-6),(W-40,y-6),METAL,.45);y-=21
steps=[
'Fit the speaker body to the cradle with a frame-only gasket; keep the diaphragm and rear vents clear.',
'Insert the two nuts from the underside of the retainer. Fit back padding, retainer, washers and screws; stop at the printed bosses.',
'Route the pair through the 3 mm relief to marked SPK+ / SPK-. Support the lid; disconnect leads before full lid removal.',
'Check body retention, no wire pinch and no diaphragm pressure. Start at low volume; validate a level limit for the 1 W speaker.'
]
for i,t in enumerate(steps,1):y=d.wrap(628,y-2,f'{i}. {t}',W-668,8.8,11.5)-5

d.line((34,113),(W-34,113),ACCENT,.9)
d.text(40,96,'SCOPE',9,True,ACCENT)
d.text(98,96,'R6 base + lid + retainer; former external-speaker passage closed. PCB, battery, OLED and SMA positions retained.',9)
d.wrap(40,78,'Speaker geometry is a conservative listing envelope. Select pad thickness by physical fit; no diaphragm load, acoustic performance, clamp torque or speaker output-power limit is qualified by nominal CAD checks. Full contours and all unshown dimensions are controlled by the native R6 CAD.',W-80,8.5,11,MUTED)
d.text(40,39,'Sources: audited R6 plan + actual C5 STEP; Amazon B0GX6GZFJ2 listing; Analog Devices MAX98357A datasheet.',8,color=MUTED)
d.text(W-40,24,'R6-SPK-01  /  FIT PROTOTYPE',9,True,WARN,align='right')
c.linkURL('https://www.amazon.com/dp/B0GX6GZFJ2',(310,35,530,48),relative=0,thickness=0)
c.linkURL('https://www.analog.com/media/en/technical-documentation/data-sheets/max98357a-max98357b.pdf',(540,35,870,48),relative=0,thickness=0)
c.save()
doc=PdfReader(PDF);assert len(doc.pages)==1
extracted=doc.pages[0].extract_text()
for term in ['15.00','10.00','3.50','0.60','0.50','22.00','5.00','SPK+','SPK-','FIT PROTOTYPE']:assert term in extracted,term
poppler=Path(sys.executable).parent.parent/'native/poppler/Library/bin/pdftoppm.exe'
subprocess.run([str(poppler),'-png','-singlefile','-r','115',str(PDF),str(PDF.with_suffix(''))],check=True)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
report=dict(ok=True,pages=1,pdf_sha256=sha(PDF),plan_sha256=sha(PLAN),audit_sha256=sha(AUDIT),drawing_kind='Dimensioned schematic integration detail; native CAD governs complete contours.',hardware_fit_qualified=False,visual_review_pending=True)
(ROOT/'DOCUMENT-VALIDATION.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(dict(pdf=str(PDF),bytes=PDF.stat().st_size)))
