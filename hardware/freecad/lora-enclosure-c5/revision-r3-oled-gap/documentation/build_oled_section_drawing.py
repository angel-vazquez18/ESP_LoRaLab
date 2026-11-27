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
OUT = ROOT / 'C5-R3-OLED-Dimensioned-Section.pdf'
data = json.loads(SOURCE.read_text(encoding='utf-8-sig'))
d = data['dimensions']
sections = data['sections']
required = ['glass_top_z','local_inner_lid_z','main_inner_lid_z','main_outer_z','recessed_face_z','aperture_width','local_thickness','recess_depth','screw_clearance_mm','minimum_relief_roof_thickness','frame_clearance_mm','recess_floor_width','recess_floor_length','recess_top_width','recess_top_length']
assert all(k in d for k in required), (required, list(d))
for k in ('lid_r2','lid_r3','oled_glass','oled_frame'):
    assert sections[k]['wires'], 'No actual section linework: '+k

W,H=landscape(A3)
c=canvas.Canvas(str(OUT),pagesize=(W,H))
c.setTitle('C5 R3 - dimensioned OLED window cross-section')
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
text(36,73,'C5 enclosure  /  Revision R3  /  Dimensioned section through the display',11,MUTED)
text(W-36,48,'0.50 mm inner gap',20,TEAL,'Helvetica-Bold','right')
text(W-36,72,'Locally lowered bezel; PCB and main lid datums retained',10,MUTED,align='right')
line(36,96,W-36,96,RULE,1)

# Main exact section detail.
box(36,118,802,429)
text(52,143,'A-A  |  DISPLAY DETAIL',12,INK,'Helvetica-Bold')
text(52,160,'Section plane Y = 58.05 mm  |  X horizontal, Z vertical  |  Enlarged; not to scale',9,MUTED)
T=transform(70,443,20,8,16)
clip=(70,174,620,285)
shape('lid_r3',T,LID,linewidth=1.0,clip=clip)
shape('oled_frame',T,FRAME,ORANGE,.8,clip)
shape('oled_glass',T,GLASS,TEAL,1.0,clip)

zg=d['glass_top_z'];zi=d['local_inner_lid_z'];zm=d['main_inner_lid_z'];zo=d['main_outer_z'];zr=d['recessed_face_z']
gap=zr-zg;igap=zi-zg;outergap=zo-zg
xc=23.0;half=d['aperture_width']/2
xleft,xright=xc-half,xc+half
L,R=T((xleft,zr)),T((xright,zr))
hdim(L[0],R[0],205,L[1],f"{d['aperture_width']:.2f} OPENING")
datum(T,zm,xleft,xright,f'Gray dashed: main underside Z{zm:.2f} (unchanged)',290,439)
line(*T((xleft,zi)),*T((xright,zi)),TEAL,.5,[2,2])
text(290,453,f'Blue dashed: local rim underside Z{zi:.2f}; aperture is open',8.5,TEAL)

# The dimension locations explicitly distinguish local and main outer faces.
vdim(T((23,zr))[0],T((23,zr))[1],T((23,zg))[1],T((17.3,zg))[0],f'{gap:.2f}',extend=False)
line(T((12.8,zr))[0],T((12.8,zr))[1],T((23,zr))[0]+4,T((23,zr))[1],TEAL,.45,[2,2])
text(T((23,zr))[0]+14,T((23,zr))[1]-9,'LOCAL FACE',8.2,TEAL,'Helvetica-Bold')
smallx=T((26.5,zi))[0];smalltop=T((26.5,zi))[1];smallbottom=T((26.5,zg))[1]
line(smallx,smalltop,smallx,smallbottom,TEAL,.7)
arrow(smallx,smalltop,0,1,size=2.5);arrow(smallx,smallbottom,0,-1,size=2.5)
label_plate(smallx+11,smalltop-7,f'{igap:.2f}',12,align='left')
text(smallx+11,smalltop-25,'INNER GAP',7.7,TEAL,'Helvetica-Bold')
vdim(103,T((9.5,zo))[1],T((12.8,zr))[1],T((12.8,zr))[0],f"{d['recess_depth']:.2f}",labelside=-1)
text(70,338,'RECESS',7.7,TEAL,'Helvetica-Bold')
vdim(726,T((33.2,zr))[1],T((33.2,zi))[1],T((33.2,zr))[0],f"{d['local_thickness']:.2f}")
text(714,290,'RIM',7.7,TEAL,'Helvetica-Bold')
vdim(791,T((38,zo))[1],T((38,zg))[1],T((37.8,zo))[0],f'{outergap:.2f}',labelside=-1)
text(746,239,'MAIN FACE',7.7,TEAL,'Helvetica-Bold')
transition_x=xc-(d['recess_floor_width']+d['recess_top_width'])/4
leader([T((transition_x,(zo+zr)/2)),(172,235),(215,235)],'45 deg transition',220,238)

# Labels sit below the measured assembly and use leaders to exact section geometry.
leader([T((20,zg-.16)),(225,472),(106,472)],'OLED glass (modeled)',106,489,TEAL)
leader([T((14.2,18.2)),(85,458),(85,501),(106,501)],'OLED frame / bracket',106,518,ORANGE)
leader([T((2*xc-transition_x,(zo+zr)/2)),(649,468),(675,468)],'R3 lid section',675,485,MUTED)
text(435,516,'Air clearance retained; no glass contact or compression',9.4,MUTED)

# Summary cards.
box(856,118,W-892,429,HexColor('#F4F8F9'))
text(872,144,'FIT SUMMARY',11,INK,'Helvetica-Bold')
text(872,185,f'{igap:.2f} mm',29,TEAL,'Helvetica-Bold')
text(872,207,'Glass to local inner rim plane',10.5,INK)
text(872,227,f'R2: {zm-zg:.2f} mm  >  R3: {igap:.2f} mm',10,MUTED)
line(872,243,W-52,243,RULE)
text(872,273,f'{gap:.2f} mm',23,INK,'Helvetica-Bold')
text(872,294,'Glass to recessed outer face',10.5,INK)
yy=wrap(872,313,'The aperture remains open. Both dimensions reference local rim planes; no glass compression is designed.',W-924,9.4)
line(872,354,W-52,354,RULE)
text(872,378,'LOCAL RELIEFS PRESERVE SCREW CLEARANCE',9.0,INK,'Helvetica-Bold')
text(872,403,f"{d['screw_clearance_mm']:.3f} mm",17,INK,'Helvetica-Bold')
text(872,422,'OLED screw-to-lid gap (off-section)',9.8,INK)
text(872,449,f"{d['minimum_relief_roof_thickness']:.2f} mm",17,INK,'Helvetica-Bold')
text(872,468,'Minimum roof over reliefs (off-section)',9.5,INK)
wrap(872,490,f"Normal rim: {d['local_thickness']:.2f} mm. Minimum frame clearance: {d['frame_clearance_mm']:.3f} mm. Nominal CAD values.",W-924,9.2)

# Lower exact assembly context and engineering notes.
box(36,564,528,222)
text(52,589,'ASSEMBLY CONTEXT',11,INK,'Helvetica-Bold')
text(52,605,'Same A-A section; full width. Dashed outline shows previous R2 lid.',9,MUTED)
Tc=transform(84,765,5.25,0,0)
contextclip=(52,616,498,160)
for name,fill,color in [('carrier',GREEN,HexColor('#3A6D59')),('heltec',HexColor('#BAD7C8'),HexColor('#417E66')),('oled_frame',FRAME,ORANGE),('oled_glass',GLASS,TEAL)]:
    if name in sections and sections[name]['wires']:shape(name,Tc,fill,color,.45,contextclip)
shape('lid_r3',Tc,LID,INK,.65,contextclip)
shape('lid_r2',Tc,None,GHOST,.75,contextclip,[3,2])
lo=Tc((10.8,25.4));rr=Tc((35.2,16.5))
c.setStrokeColor(TEAL);c.setLineWidth(.65);c.setDash([3,2]);c.rect(lo[0],H-rr[1],rr[0]-lo[0],rr[1]-lo[1],stroke=1,fill=0);c.setDash([])
text(66,777,'Carrier PCB',8.6,HexColor('#3A6D59'))
text(240,777,'Heltec module',8.6,HexColor('#417E66'))
text(418,777,'Detail A-A',8.6,TEAL)

box(582,564,W-618,222)
text(598,589,'RECESSED BEZEL GEOMETRY',11,INK,'Helvetica-Bold')
rows=[('Opening (unchanged)',f"{d['aperture_width']:.2f} x {d.get('aperture_length',27):.2f} mm"),('Recess floor footprint',f"{d['recess_floor_width']:.2f} x {d['recess_floor_length']:.2f} mm"),('Recess at main outer face',f"{d['recess_top_width']:.2f} x {d['recess_top_length']:.2f} mm"),('Ledge width / transition',f"{d.get('ledge_width',2):.2f} mm / 45 deg")]
for i,(label,value) in enumerate(rows):
    yy=614+i*20
    text(598,yy,label,9.7,MUTED);text(870,yy,value,9.7,INK,'Helvetica-Bold')
line(598,687,W-52,687,RULE)
yy=wrap(598,707,'Nominal fit only. The OLED supplement and 5 mm module mounting gap are approximate. Confirm physical clearance and print tolerances before production.',W-650,9.2,12)
wrap(598,yy+7,'PCB, display, PTT and the main lid underside remain fixed. Only the local bezel moves down; screw reliefs create thinner roof regions outside this section.',W-650,9.2,12)

# Compact title block with explicit source traceability.
line(36,804,W-36,804,RULE,.8)
text(36,822,'LORA WALKIE-TALKIE  |  C5-R3-OLED-SECTION  |  REV R3  |  2026-11-24',9,INK,'Helvetica-Bold')
text(W-36,822,'UNITS mm  /  A3  /  NTS  /  SHEET 1 OF 1',9,MUTED,align='right')
c.showPage();c.save()
pdf=PdfReader(str(OUT));assert len(pdf.pages)==1
extracted=pdf.pages[0].extract_text()
for token in ('2.10','0.50','1.60','2.50','4.60','16.40','0.699','1.10','Y = 58.05'):
    assert token in extracted,token
meta={'pdf':str(OUT),'pages':len(pdf.pages),'page_size_points':list(pdf.pages[0].mediabox),'source_geometry':str(SOURCE),'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'pdf_sha256':hashlib.sha256(OUT.read_bytes()).hexdigest(),'values_mm':{'glass_to_local_face':gap,'glass_to_inner_reference':igap,'glass_to_main_outer':outergap},'section_geometry':'Actual B-rep slice wires supplied by CAD audit; no synthesized model outlines.','render_review':'Pending PNG review'}
(ROOT/'drawing-validation.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
print(json.dumps(meta,indent=2))
