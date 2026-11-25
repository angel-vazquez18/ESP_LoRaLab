"""Render an A3 engineering detail from verified FreeCAD section wire data.

Requires oled-section-geometry.json produced by the independent CAD audit.
No CAD outline is synthesized by this renderer. Coordinates are physical X,Z.
"""
from pathlib import Path
import json, math, hashlib
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.colors import HexColor, Color, white
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'oled-section-geometry.json'
OUT = ROOT / 'C5-R2-OLED-Dimensioned-Section.pdf'
data = json.loads(SOURCE.read_text(encoding='utf-8-sig'))
d = data['dimensions']
sections = data['sections']
required = ['glass_top_z','inner_lid_z','main_outer_z','recessed_face_z','aperture_width','local_thickness','recess_depth','screw_clearance_mm']
assert all(k in d for k in required), (required, list(d))
for k in ('lid_r1','lid_r2','oled_glass','oled_frame'):
    assert sections[k]['wires'], 'No actual section linework: '+k

W,H=landscape(A3)
c=canvas.Canvas(str(OUT),pagesize=(W,H))
c.setTitle('C5 R2 - dimensioned OLED window cross-section')
c.setAuthor('LoRa C5 enclosure engineering')
c.setSubject('Actual FreeCAD section at Y58.05; nominal prototype dimensions, mm')
INK=HexColor('#162F3C'); MUTED=HexColor('#526670'); RULE=HexColor('#CEDADD')
TEAL=HexColor('#087D91'); GLASS=HexColor('#AEE6EF'); FRAME=HexColor('#F8D5AB')
LID=HexColor('#DCE5E9'); GREEN=HexColor('#9BC5B5'); ORANGE=HexColor('#B96928')
GHOST=HexColor('#9AAEB5')

def text(x,y,s,size=10,color=INK,font='Helvetica',align='left'):
    c.setFillColor(color);c.setFont(font,size)
    {'left':c.drawString,'center':c.drawCentredString,'right':c.drawRightString}[align](x,H-y,s)

def line(x1,y1,x2,y2,color=INK,width=.6,dash=None):
    c.setStrokeColor(color);c.setLineWidth(width);c.setDash(dash or [])
    c.line(x1,H-y1,x2,H-y2);c.setDash([])

def box(x,y,w,h,fill=white,stroke=RULE,r=0):
    c.setFillColor(fill);c.setStrokeColor(stroke);c.setLineWidth(.7)
    if r:c.roundRect(x,H-y-h,w,h,r,stroke=1,fill=1)
    else:c.rect(x,H-y-h,w,h,stroke=1,fill=1)

def wrap(x,y,s,width,size=9.4,leading=13,color=MUTED,font='Helvetica'):
    words=s.split();row='';yy=y
    for word in words:
        trial=(row+' '+word).strip()
        if c.stringWidth(trial,font,size)>width and row:
            text(x,yy,row,size,color,font);yy+=leading;row=word
        else:row=trial
    if row:text(x,yy,row,size,color,font)
    return yy+leading

def arrow(x,y,dx,dy,color=TEAL,size=4):
    norm=math.hypot(dx,dy);ux,uy=dx/norm,dy/norm
    px,py=-uy,ux
    p=c.beginPath();p.moveTo(x,H-y)
    p.lineTo(x+ux*size+px*size*.38,H-(y+uy*size+py*size*.38))
    p.lineTo(x+ux*size-px*size*.38,H-(y+uy*size-py*size*.38));p.close()
    c.setFillColor(color);c.drawPath(p,fill=1,stroke=0)

def label_plate(x,y,s,size=10,color=TEAL,align='center'):
    tw=c.stringWidth(s,'Helvetica-Bold',size)
    left=x-tw/2 if align=='center' else x if align=='left' else x-tw
    c.setFillColor(white);c.rect(left-3,H-y-3,tw+6,size+5,stroke=0,fill=1)
    text(x,y,s,size,color,'Helvetica-Bold',align)

def hdim(x1,x2,y,yref,s):
    for x in(x1,x2):line(x,yref,x,y-4,TEAL,.5)
    line(x1,y,x2,y,TEAL,.7)
    arrow(x1,y,1,0);arrow(x2,y,-1,0)
    label_plate((x1+x2)/2,y-5,s)

def vdim(x,y1,y2,xref,s,labelside=1,extend=True):
    ya,yb=sorted((y1,y2))
    if extend:
        for y in(ya,yb):line(xref,y,x+labelside*4,y,TEAL,.45)
    line(x,ya,x,yb,TEAL,.7)
    arrow(x,ya,0,1);arrow(x,yb,0,-1)
    label_plate(x+labelside*9,(ya+yb)/2+3,s,9.8,align='left' if labelside>0 else 'right')

def leader(points,label,tx,ty,color=MUTED,align='left',size=9.5):
    for a,b in zip(points,points[1:]):line(*a,*b,color,.7)
    if len(points)>1:
        a,b=points[:2];arrow(*a,b[0]-a[0],b[1]-a[1],color,3.4)
    text(tx,ty,label,size,color,'Helvetica',align)

def transform(x0,y0,scale,xorigin=0,zorigin=0):
    return lambda p:(x0+(p[0]-xorigin)*scale,y0-(p[1]-zorigin)*scale)

def shape(name,T,fill,stroke=INK,linewidth=.75,clip=None,dash=None):
    c.saveState()
    if clip:
        x,y,w,h=clip;cp=c.beginPath();cp.rect(x,H-y-h,w,h);c.clipPath(cp,stroke=0,fill=0)
    path=c.beginPath();seen=0
    for wire in sections[name]['wires']:
        if len(wire)<2:continue
        x,y=T(wire[0]);path.moveTo(x,H-y)
        for p in wire[1:]:
            x,y=T(p);path.lineTo(x,H-y)
        if math.dist(wire[0],wire[-1])<1e-4:path.close()
        seen+=1
    assert seen,name
    c.setStrokeColor(stroke);c.setLineWidth(linewidth);c.setDash(dash or [])
    if fill is not None:c.setFillColor(fill)
    c.drawPath(path,stroke=1,fill=int(fill is not None),fillMode=0)
    c.restoreState()

def datum(T,z,x1,x2,label,labelx,labely):
    a=T((x1,z));b=T((x2,z));line(*a,*b,MUTED,.5,[3,3])
    text(labelx,labely,label,8.5,MUTED)

# Page heading.
text(36,48,'OLED WINDOW FIT',25,INK,'Helvetica-Bold')
text(36,73,'C5 enclosure  /  Revision R2  /  Dimensioned section through the display',11,MUTED)
text(W-36,48,'2.00 mm closer',20,TEAL,'Helvetica-Bold','right')
text(W-36,72,'Local recessed bezel; internal mounting datums retained',10,MUTED,align='right')
line(36,96,W-36,96,RULE,1)

# Main exact section detail.
box(36,118,802,429)
text(52,143,'A-A  |  DISPLAY DETAIL',12,INK,'Helvetica-Bold')
text(52,160,'Section plane Y = 58.05 mm  |  X horizontal, Z vertical  |  Enlarged; not to scale',9,MUTED)
T=transform(70,443,20,8,16)
clip=(70,174,620,285)
shape('lid_r2',T,LID,linewidth=1.0,clip=clip)
shape('oled_frame',T,FRAME,ORANGE,.8,clip)
shape('oled_glass',T,GLASS,TEAL,1.0,clip)

zg=d['glass_top_z'];zi=d['inner_lid_z'];zo=d['main_outer_z'];zr=d['recessed_face_z']
gap=zr-zg;igap=zi-zg;outergap=zo-zg
xc=23.0;half=d['aperture_width']/2
xleft,xright=xc-half,xc+half
L,R=T((xleft,zr)),T((xright,zr))
hdim(L[0],R[0],205,L[1],f"{d['aperture_width']:.2f} OPENING")
datum(T,zi,xleft,xright,'Dashed: inner lid datum; aperture is open',290,444)

# The dimension locations explicitly distinguish local and main outer faces.
vdim(T((23,zr))[0],T((23,zr))[1],T((23,zg))[1],T((17.3,zg))[0],f'{gap:.2f}',extend=False)
line(T((12.8,zr))[0],T((12.8,zr))[1],T((23,zr))[0]+4,T((23,zr))[1],TEAL,.45,[2,2])
text(T((23,zr))[0]+14,T((23,zr))[1]-9,'LOCAL FACE',8.2,TEAL,'Helvetica-Bold')
vdim(T((29.8,zi))[0],T((29.8,zi))[1],T((29.8,zg))[1],T((28.7,zg))[0],f'{igap:.2f}')
vdim(103,T((9.5,zo))[1],T((12.8,zr))[1],T((12.8,zr))[0],f"{d['recess_depth']:.2f}",labelside=-1)
text(70,328,'RECESS',7.7,TEAL,'Helvetica-Bold')
vdim(726,T((33.2,zr))[1],T((33.2,zi))[1],T((33.2,zr))[0],f"{d['local_thickness']:.2f}")
text(714,290,'RIM',7.7,TEAL,'Helvetica-Bold')
vdim(791,T((38,zo))[1],T((38,zg))[1],T((37.8,zo))[0],f'{outergap:.2f}',labelside=-1)
text(746,239,'MAIN FACE',7.7,TEAL,'Helvetica-Bold')
leader([T((11.8,(zo+zr)/2)),(172,235),(215,235)],'45 deg transition',220,238)

# Labels sit below the measured assembly and use leaders to exact section geometry.
leader([T((20,zg-.16)),(225,472),(106,472)],'OLED glass (modeled)',106,489,TEAL)
leader([T((14.2,18.2)),(85,458),(85,501),(106,501)],'OLED frame / bracket',106,518,ORANGE)
leader([T((34.3,(zo+zr)/2)),(649,468),(675,468)],'R2 lid section',675,485,MUTED)
text(435,516,'Air clearance retained; no glass contact or compression',9.4,MUTED)

# Summary cards.
box(856,118,W-892,429,HexColor('#F4F8F9'))
text(872,144,'FIT SUMMARY',11,INK,'Helvetica-Bold')
text(872,185,f'{gap:.2f} mm',29,TEAL,'Helvetica-Bold')
text(872,207,'Glass to recessed window face',10.5,INK)
text(872,227,f'R1: {outergap:.2f} mm  >  R2: {gap:.2f} mm',10,MUTED)
line(872,243,W-52,243,RULE)
text(872,273,f'{igap:.2f} mm',23,INK,'Helvetica-Bold')
text(872,294,'Glass to inner lid datum plane',10.5,INK)
yy=wrap(872,313,'The aperture is open. This is a vertical reference gap, not glass-to-ceiling contact.',W-924,9.4)
line(872,354,W-52,354,RULE)
text(872,378,'UNCHANGED',9.8,INK,'Helvetica-Bold')
yy=wrap(872,398,'PCB, display, lid underside and PTT mounting positions are retained.',W-924,9.4)
text(872,445,f"{d['screw_clearance_mm']:.3f} mm",17,INK,'Helvetica-Bold')
text(872,464,'Minimum OLED screw-to-lid gap',9.8,INK)
wrap(872,482,'Off-section minimum from the full 3D geometry check. Nominal model value.',W-924,9.2)

# Lower exact assembly context and engineering notes.
box(36,564,528,222)
text(52,589,'ASSEMBLY CONTEXT',11,INK,'Helvetica-Bold')
text(52,605,'Same A-A section; full width. Dashed outline shows previous R1 lid.',9,MUTED)
Tc=transform(84,765,5.25,0,0)
contextclip=(52,616,498,160)
for name,fill,color in [('carrier',GREEN,HexColor('#3A6D59')),('heltec',HexColor('#BAD7C8'),HexColor('#417E66')),('oled_frame',FRAME,ORANGE),('oled_glass',GLASS,TEAL)]:
    if name in sections and sections[name]['wires']:shape(name,Tc,fill,color,.45,contextclip)
shape('lid_r2',Tc,LID,INK,.65,contextclip)
shape('lid_r1',Tc,None,GHOST,.75,contextclip,[3,2])
lo=Tc((10.8,25.4));rr=Tc((35.2,16.5))
c.setStrokeColor(TEAL);c.setLineWidth(.65);c.setDash([3,2]);c.rect(lo[0],H-rr[1],rr[0]-lo[0],rr[1]-lo[1],stroke=1,fill=0);c.setDash([])
text(66,777,'Carrier PCB',8.6,HexColor('#3A6D59'))
text(240,777,'Heltec module',8.6,HexColor('#417E66'))
text(418,777,'Detail A-A',8.6,TEAL)

box(582,564,W-618,222)
text(598,589,'RECESSED BEZEL GEOMETRY',11,INK,'Helvetica-Bold')
rows=[('Opening (unchanged)','16.40 x 27.00 mm'),('Recess floor footprint','20.40 x 31.00 mm'),('Recess at main outer face','24.40 x 35.00 mm'),('Ledge width / transition','2.00 mm / 45 deg')]
for i,(label,value) in enumerate(rows):
    yy=614+i*20
    text(598,yy,label,9.7,MUTED);text(870,yy,value,9.7,INK,'Helvetica-Bold')
line(598,687,W-52,687,RULE)
yy=wrap(598,707,'Nominal CAD dimensions only. The supplemental OLED geometry and 5 mm module mounting gap are approximate; verify your actual assembly before production.',W-650,9.2,12)
wrap(598,yy+7,'The local rim is 1.6 mm thick. This drawing documents fit geometry, not material strength or a measured tolerance stack.',W-650,9.2,12)

# Compact title block with explicit source traceability.
line(36,804,W-36,804,RULE,.8)
text(36,822,'LORA WALKIE-TALKIE  |  C5-R2-OLED-SECTION  |  REV R2  |  2026-11-24',9,INK,'Helvetica-Bold')
text(W-36,822,'UNITS mm  /  A3  /  NTS  /  SHEET 1 OF 1',9,MUTED,align='right')
c.showPage();c.save()
pdf=PdfReader(str(OUT));assert len(pdf.pages)==1
extracted=pdf.pages[0].extract_text()
for token in ('2.60','1.00','1.60','2.00','4.60','16.40','0.699','Y = 58.05'):
    assert token in extracted,token
meta={'pdf':str(OUT),'pages':len(pdf.pages),'page_size_points':list(pdf.pages[0].mediabox),'source_geometry':str(SOURCE),'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'pdf_sha256':hashlib.sha256(OUT.read_bytes()).hexdigest(),'values_mm':{'glass_to_local_face':gap,'glass_to_inner_reference':igap,'glass_to_main_outer':outergap},'section_geometry':'Actual B-rep slice wires supplied by CAD audit; no synthesized model outlines.','render_review':'Pending PNG review'}
(ROOT/'drawing-validation.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
print(json.dumps(meta,indent=2))
