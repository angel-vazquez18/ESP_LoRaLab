"""Dimensioned R5 mount documentation; consumes audits, never edits CAD."""
from pathlib import Path
import hashlib, json, math, subprocess, sys
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.colors import HexColor, Color
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parent
REV=ROOT.parent
AUDIT=REV/'audit'
report=json.loads((AUDIT/'final-plan-validation.json').read_text())
assert report['ok'] and all(report['source_files_unchanged'].values())
assert all(report['parts'][p]['valid'] and report['parts'][p]['closed'] and report['parts'][p]['solids']==1 for p in ('EnclosureBase','EnclosureLid'))
PDF=ROOT/'LoRa-C5-R5-SMA-Mount-Drawing.pdf'
W,H=landscape(A3)
c=canvas.Canvas(str(PDF),pagesize=(W,H),pageCompression=1)
c.setTitle('LoRa C5 R5 - SMA bulkhead mount and cable restraint')
c.setAuthor('LoRa enclosure project')
INK=HexColor('#18272e');MUTED=HexColor('#56666d');ACCENT=HexColor('#006d82')
PALE=HexColor('#edf4f6');METAL=HexColor('#dbe1e3');WARN=HexColor('#8b4f00')

def text(x,y,s,size=9,bold=False,color=INK,align='left'):
    c.setFillColor(color);c.setFont('Helvetica-Bold' if bold else 'Helvetica',size)
    {'left':c.drawString,'center':c.drawCentredString,'right':c.drawRightString}[align](x,y,s)
def wrap(x,y,s,width,size=9,leading=12,color=INK,bold=False):
    words=s.split();line=''
    for word in words:
        test=(line+' '+word).strip()
        if c.stringWidth(test,'Helvetica-Bold' if bold else 'Helvetica',size)>width and line:
            text(x,y,line,size,bold,color);y-=leading;line=word
        else:line=test
    if line:text(x,y,line,size,bold,color);y-=leading
    return y
def line(a,b,color=INK,width=.7,dash=None):
    c.setStrokeColor(color);c.setLineWidth(width);c.setDash(dash or []);c.line(*a,*b);c.setDash([])
def poly(pts,fill=None,stroke=INK,width=.7,closed=True):
    p=c.beginPath();p.moveTo(*pts[0])
    for q in pts[1:]:p.lineTo(*q)
    if closed:p.close()
    c.setStrokeColor(stroke);c.setLineWidth(width)
    if fill:c.setFillColor(fill)
    c.drawPath(p,fill=bool(fill),stroke=1)
def rect(x,y,w,h,fill=None,stroke=INK,width=.7):poly([(x,y),(x+w,y),(x+w,y+h),(x,y+h)],fill,stroke,width)
def head(tip,back,size=4):
    n=math.hypot(*back);u=[v/n for v in back];v=[-u[1],u[0]]
    poly([tip,(tip[0]+u[0]*size+v[0]*size*.35,tip[1]+u[1]*size+v[1]*size*.35),(tip[0]+u[0]*size-v[0]*size*.35,tip[1]+u[1]*size-v[1]*size*.35)],INK,INK,.3)
def dim_h(x1,x2,y,label,witness_y=None):
    if witness_y is not None:
        for x in (x1,x2):line((x,witness_y),(x,y+3 if y>witness_y else y-3),MUTED,.45)
    line((x1,y),(x2,y),INK,.55);head((x1,y),(1,0));head((x2,y),(-1,0));text((x1+x2)/2,y+5,label,9,False,align='center')
def dim_v(y1,y2,x,label,witness_x=None):
    if witness_x is not None:
        for y in (y1,y2):line((witness_x,y),(x+3 if x>witness_x else x-3,y),MUTED,.45)
    line((x,y1),(x,y2),INK,.55);head((x,y1),(0,1));head((x,y2),(0,-1))
    c.saveState();c.translate(x+10,(y1+y2)/2);c.rotate(90);text(0,0,label,9,align='center');c.restoreState()
def leader(points,label,x,y,width=180):
    for a,b in zip(points,points[1:]):line(a,b,ACCENT,.7)
    head(points[0],(points[1][0]-points[0][0],points[1][1]-points[0][1]),3.5)
    return wrap(x,y,label,width,8.5,11,ACCENT)
def panel_title(x,y,label):text(x,y,label,11,True,ACCENT)
def hatch_rect(x,y,w,h):
    rect(x,y,w,h,PALE)
    c.saveState();p=c.beginPath();p.rect(x,y,w,h);c.clipPath(p,stroke=0)
    for dx in range(-int(h)-10,int(w)+10,7):line((x+dx,y),(x+dx+h,y+h),HexColor('#c2d3d8'),.45)
    c.restoreState()

# Header and purpose.
text(34,H-43,'R5  |  SMA bulkhead mount',22,True)
text(W-34,H-40,'LoRa walkie-talkie / C5 carrier',11,True,align='right')
text(W-34,H-57,'2026-11-24  -  Nominal millimetres  -  Sheet 1 of 1',9,False,MUTED,'right')
text(34,H-67,'Parametric fit prototype: verify the owned connector before placing a manufacturing order.',11,True,WARN)
line((34,H-82),(W-34,H-82),ACCENT,1.2)

# Inside-facing end wall X-Z layout.
panel_title(40,728,'A  End-wall layout - viewed from inside toward +Y')
text(40,713,'X increases right; Z increases up. +Y points out through the antenna mount.',8.5,False,MUTED)
s=5.4;ox=91;oz=544
X=lambda x:ox+s*x
Z=lambda z:oz+s*z
# Silhouette only; enclosure contour/radii outside the detail remain controlled by CAD.
rect(X(-4.4),Z(-16.4),78.8*s,41*s,None,INK,1.0)
line((X(-4.4),Z(21)),(X(74.4),Z(21)),MUTED,.65)
line((X(-4.4),Z(-14)),(X(74.4),Z(-14)),MUTED,.65)
rect(X(15),Z(11.5),16*s,9.5*s,None,MUTED,.7)
text(X(23),Z(13.5),'USB',8,False,MUTED,'center')
# Projected rear battery chase, not part of mount detail.
line((X(21),Z(-16.4)),(X(21),Z(11.1)),MUTED,.5,[3,3]);line((X(21),Z(11.1)),(X(35),Z(11.1)),MUTED,.5,[3,3]);line((X(35),Z(11.1)),(X(35),Z(-16.4)),MUTED,.5,[3,3])
text(X(28),Z(-8),'Battery',8,False,MUTED,'center');text(X(28),Z(-10.2),'chase',8,False,MUTED,'center')
c.setStrokeColor(ACCENT);c.setLineWidth(1.2);c.circle(X(47),Z(14),3.3*s,stroke=1,fill=0)
c.setStrokeColor(MUTED);c.setLineWidth(.55);c.setDash([3,3]);c.circle(X(47),Z(14),5.6*s,stroke=1,fill=0);c.rect(X(38),Z(9.2),18*s,9.8*s,stroke=1,fill=0);c.setDash([])
line((X(47)-25,Z(14)),(X(47)+25,Z(14)),MUTED,.5,[8,2,2,2]);line((X(47),Z(14)-25),(X(47),Z(14)+25),MUTED,.5,[8,2,2,2])
rect(X(55),Z(14),6.5*s,4*s,PALE,ACCENT,.7)
line((X(0),Z(-19)),(X(0),Z(26)),MUTED,.5,[8,2,2,2]);line((X(-6),Z(0)),(X(78),Z(0)),MUTED,.5,[8,2,2,2])
text(X(-6),Z(0)-11,'Z0',8,False,MUTED)
text(X(0)+3,Z(25.5),'PCB X0',8,False,MUTED)
dim_h(X(0),X(47),Z(-20),'47.00',Z(14))
dim_v(Z(0),Z(14),X(80),'14.00',X(47))
leader([(X(47)+14,Z(14)+10),(X(67),Z(27))],'THRU DIA 6.60',X(59),Z(29),130)
leader([(X(43),Z(21)),(X(43),Z(27)),(X(31),Z(27))],'Close old seam coax exit in base and lid.',X(0),701,165)
leader([(X(39),Z(9.3)),(X(10),Z(6))],'18.0 wide backing; rear relief DIA 11.2 (hidden).',X(1),Z(9),168)
text(40,416,'X0 = PCB left edge. Z0 = original external floor. End-wall outline is contextual.',8.5,False,MUTED)

# Main cross-section at X47.
panel_title(628,728,'B  Mount section at X47 - antenna points +Y')
text(628,713,'Section through bore centre Z14. Hardware envelopes are illustrative.',8.5,False,MUTED)
s2=11;oy=628;oz2=447
Y=lambda y:oy+(y-78)*s2
Q=lambda z:oz2+(z-4)*s2
for a,b in ((4,10.7),(17.3,21)):hatch_rect(Y(92),Q(a),2.4*s2,(b-a)*s2)
hatch_rect(Y(90.4),Q(19.4),1.2*s2,1.6*s2)
hatch_rect(Y(89),Q(21),5.4*s2,3.6*s2)
text(Y(96),Q(22.5),'Lid',9,True)
line((Y(78),Q(14)),(Y(116),Q(14)),MUTED,.5,[9,2,2,2])
# Reference body / stud and washer-nut assembly; intentionally unthreaded illustration.
c.setStrokeColor(MUTED);c.setLineWidth(.7);c.setDash([4,3]);c.rect(Y(82),Q(9),10*s2,10*s2,stroke=1,fill=0);c.setDash([])
rect(Y(90),Q(14-3.175),13.4*s2,6.35*s2,None,MUTED,.7)
rect(Y(94.4),Q(8.9),.5*s2,10.2*s2,METAL,MUTED,.5)
rect(Y(94.9),Q(10),1.7*s2,8*s2,METAL,MUTED,.7)
line((Y(102),Q(14)),(Y(115),Q(14)),ACCENT,1.2);head((Y(115),Q(14)),(-1,0),5)
text(Y(110),Q(15.5),'Antenna +Y',9,True,ACCENT)
line((Y(78),Q(14)),(Y(82),Q(14)),MUTED,1)
text(Y(78),Q(12.4),'Coax',8.5,False,MUTED)
dim_h(Y(92),Y(94.4),Q(27),'2.40 seat',Q(21))
dim_v(Q(10.7),Q(17.3),Y(108),'DIA 6.60 bore',Y(94.4))
leader([(Y(85),Q(9)),(Y(82),Q(5.3))],'DIA 10 x 10 rear-body reservation, not a verified kit model.',Y(78),Q(3),190)
leader([(Y(95.8),Q(18)),(Y(101),Q(21))],'Supplied nut + washer stack; counter-hold the fixed rear hex.',Y(101),Q(23),174)
text(628,416,'Round bore has no keyed hex capture. Retention is by the supplied hardware clamp.',8.5,True,WARN)

# Lower-left tie anchor enlarged Y-Z side detail.
panel_title(40,382,'C  Cable-tie anchor - local Y-Z detail (through X)')
s3=12;ax=74;az=224
AY=lambda y:ax+(y-82)*s3
AZ=lambda z:az+(z-13)*s3
rect(AY(92),AZ(13),2.4*s3,8*s3,PALE,MUTED,.7)
c.setFillColor(PALE);c.setStrokeColor(INK);c.setLineWidth(.9);c.roundRect(AY(84),AZ(14),8.2*s3,4*s3,.6*s3,fill=1,stroke=1)
c.setFillColor(HexColor('#ffffff'));c.roundRect(AY(85.8),AZ(15.2),3*s3,1.5*s3,.4*s3,fill=1,stroke=1)
line((AY(82),AZ(19.0)),(AY(94.4),AZ(19.0)),MUTED,.5,[3,3]);text(AY(83),AZ(20.5),'Nearest lid feature, Z19.0',8.5,False,MUTED)
dim_v(AZ(18),AZ(19),AY(96),'1.00 min',AY(91))
dim_h(AY(85.8),AY(88.8),AZ(12.8),'3.00',AZ(15.2))
dim_v(AZ(15.2),AZ(16.7),AY(82),'1.50',AY(85.8))
text(285,343,'Anchor envelope',9,True)
wrap(285,328,'X55.0-61.5 / Y84.0-92.2 / Z14.0-18.0',267,9,12)
wrap(285,300,'Slot runs through X. Outer edges R0.60; slot cutter R0.40. Fit a loose 2.5 mm tie, with its head beside the cable, not above it.',267,9,12)
wrap(285,249,'Route with service slack. The 169 mm pigtail is retained at full length; a 10 mm bend-radius allowance is provisional.',267,9,12)

# Lower-right validation and installation notes.
panel_title(628,382,'D  Fit checks and assembly')
metrics=[('Rear body envelope to PCB', '1.035 mm'),('Rear body envelope to lid', '0.400 mm'),('Tie anchor to lid', '1.000 mm'),('Battery upper / pad allowance', '3.00 / 1.00 mm'),('OLED to inner-rim datum', '0.50 mm (retained)')]
y=360
for label,value in metrics:
    text(628,y,label,9);text(W-40,y,value,9,True,align='right');line((628,y-6),(W-40,y-6),HexColor('#d6dfe2'),.45);y-=22
text(628,y-2,'Use the supplied flat / locking washer arrangement and nut.',9,True)
y=wrap(628,y-18,'Insert the bulkhead from inside. Counter-hold the fixed SMA body while tightening its mounting nut and the antenna coupling; do not transfer twisting force into the coax or U.FL connector.',W-668,9,12)
y=wrap(628,y-6,'Confirm the actual thread, rear shoulder, washer bearing land and antenna engagement. Close the lid slowly and check for pinched cable, connector movement and clearance at the anchor.',W-668,9,12)

# Shared lower bands.
line((34,170),(W-34,170),ACCENT,.9)
text(40,151,'LOAD PATH',9,True,ACCENT)
text(122,151,'Antenna > SMA body > rear shoulder + nut/washer clamp > 2.4 mm seat > enclosure base',10,True)
text(40,131,'CHANGE SCOPE',9,True,ACCENT)
text(122,131,'Replace the base and lid with the R5 pair. Battery cover, PTT plunger and stop cup retain R4 geometry.',9)
wrap(40,111,'Verification: final-plan Boolean checks show valid, closed, single-solid base and lid, zero base/lid interference, unchanged OLED region and unchanged battery gap. Exact component clearances above are nominal geometry checks; they do not qualify printing tolerances, polymer clamp torque, impact loads or RF performance.',W-80,8.5,11,MUTED)
text(40,69,'Sources: project R4/C5 CAD + R5 fit audits; TE/Linx CSH-SGFB analogue; Hirose U.FL handling catalog.',8,False,MUTED)
text(40,55,'User photo: 50 x 8 mm antenna; 169 mm cable. Owned-kit mounting dimensions are unverified. Dimensions govern; hardware is reference only.',8,False,MUTED)
text(W-40,39,'R5-SMA-01  /  FIT PROTOTYPE',9,True,WARN,'right')
c.linkURL('https://www.te.com/en/product-CSH-SGFB-200-UFFR.html',(40,64,520,78),relative=0,thickness=0)
c.linkURL('https://www.hirose.com/en/product/series/U.FL',(520,64,810,78),relative=0,thickness=0)
c.save()

installation='''R5 SMA antenna mount - installation and fit notes
2026-11-24 | Nominal millimetres | Fit prototype

The R5 revision replaces the old split coax exit at the lid seam with a round
SMA bulkhead hole in the USB-end wall. The mount centre is X47, Z14 and its
axis points +Y. Coordinates are in the existing CAD frame: PCB left edge X0,
original external floor Z0. The battery cover remains below Z0.

PARAMETRIC DESIGN
- Through bore: 6.60 mm diameter, provisional for a typical 6.35 mm SMA stud.
- Local clamping seat: 2.40 mm, between Y92.00 and Y94.40.
- Internal backing: X38-56, Y89-92.2, Z9.2-19.0; outer fillets R0.60.
- Back relief: 11.20 mm diameter, ending at Y92.00. It leaves reinforced
  side cheeks and access around the fixed rear connector body.
- Tie anchor: X55-61.5, Y84-92.2, Z14-18; outer fillets R0.60.
- Through-X tie slot: Y85.8-88.8, Z15.2-16.7; cutter fillets R0.40.
- Reference rear connector reservation: diameter 10 x 10 mm, not owned CAD.
- Round mounting bore; no verified keyed hex capture or positive anti-rotation
  key is provided. The supplied nut/washer clamp resists movement. Counter-hold
  the fixed connector body when tightening the nut or antenna coupling.

ASSEMBLY
1. Check the owned bulkhead stud, rear shoulder, usable thread and washer
   dimensions against the CAD before ordering or committing a print run.
   The 6.6 mm bore / 2.4 mm seat are a fit prototype, not a measured kit fit.
2. Install the SMA female bulkhead from inside. Fit the supplied washer and
   locking washer arrangement and nut as the hardware manufacturer specifies.
   Ensure the washer bears flat around the hole. Keep the rear hex accessible
   for counter-holding and use only the torque specified for the owned hardware
   and compatible polymer mounting surface; no torque value is qualified here.
3. Attach the antenna while counter-holding the SMA body, separately from the
   mounting nut. Do not let the pigtail twist or use its U.FL end as a restraint.
4. Route the complete 169 mm pigtail with gentle service slack. A provisional
   10 mm centreline bend-radius allowance is used until the cable is identified.
   Retain slack with a loose 2.5 mm cable tie at the rounded anchor. Do not crush
   the jacket. Place the tie head beside the cable so it cannot foul the lid.
5. Connect to the Heltec LoRa IPEX/U.FL port, not the second RF connector.
   The model's LoRa mating-face reference is approximately
   [23.00004, 39.14914, 15.81875] mm. Confirm against the owned board's markings.
   Mate the plug axially with the proper support; do not pull or pry its cable.
6. Close the lid slowly; check cable slack and no pinch, full antenna engagement,
   no connector rotation/free play and retention of the nut. Physical print fit,
   mounting torque/creep, impact strength and RF performance still need checks.

CHECKS AND SCOPE
The audited CAD plan has valid, closed, single-solid base and lid. They have no
intersection volume. The antenna connector reference clears the actual PCB by
1.035 mm and the lid by 0.400 mm; the rounded tie anchor clears the lid by
1.000 mm. These clearances are nominal, before manufacturing variation.
The R4 battery fit remains 3.00 mm above its envelope and 1.00 mm pad allowance
below. The retained OLED-to-inner-rim datum offset is 0.5012807412 mm, displayed
as 0.50 mm; it is not the minimum solid distance across the open window.

Use the R5 base and lid together. The battery cover, PTT plunger and stop cup
retain the R4 geometry. No PCB, firmware, battery powering arrangement or
electrical design is changed by this mechanical modification. This drawing
does not establish a seal/IP rating or measured antenna performance.

SOURCES
TE/Linx CSH-SGFB product and manufacturer drawing (analogue, not owned kit):
https://www.te.com/en/product-CSH-SGFB-200-UFFR.html
Hirose U.FL series handling documentation:
https://www.hirose.com/en/product/series/U.FL
Project evidence: ../audit/final-plan-validation.json,
../audit/sma-block-fit-audit.json, ../audit/final-anchor-audit.json,
../research/SMA-MOUNT-SOURCES.txt.
'''
(ROOT/'SMA-MOUNT-INSTALLATION.txt').write_text(installation,encoding='utf-8')
doc=PdfReader(PDF)
assert len(doc.pages)==1
page=doc.pages[0]
poppler=Path(sys.executable).parent.parent/'native/poppler/Library/bin/pdftoppm.exe'
subprocess.run([str(poppler),'-png','-singlefile','-r','115',str(PDF),str(PDF.with_suffix(''))],check=True)
extracted=page.extract_text()
for word in ('6.60','2.40','47.00','14.00','1.035','0.400','1.000','0.50','FIT PROTOTYPE'):
    assert word in extracted,word
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
(ROOT/'DOCUMENT-VALIDATION.json').write_text(json.dumps(dict(ok=True,pages=len(doc.pages),page_size_points=[float(x)for x in page.mediabox],pdf_sha256=sha(PDF),source_audit_sha256=sha(AUDIT/'final-plan-validation.json'),drawing_kind='Dimensioned schematic mount detail; CAD governs full contours.',hardware_fit_qualified=False,visual_review_pending=True),indent=2)+'\n')
print(json.dumps(dict(pdf=str(PDF),pages=len(doc.pages),bytes=PDF.stat().st_size)))
