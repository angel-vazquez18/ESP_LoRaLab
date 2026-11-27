"""Create two A3 battery integration sheets from actual CAD sections/renders."""
from pathlib import Path
import json,math,hashlib
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A3,landscape
from reportlab.lib.colors import HexColor,white
from reportlab.lib.utils import ImageReader
from pypdf import PdfReader

root=Path(__file__).resolve().parent
cfg=json.loads((root/'view-config.json').read_text())
data=json.loads((root/'battery-section-geometry.json').read_text())
d=data['dimensions']
sections=data['sections']
out=root/'C5-R4-Battery-Integration.pdf'
W,H=landscape(A3)
c=canvas.Canvas(str(out),pagesize=(W,H))
c.setTitle('LoRa C5 R4 - battery compartment integration')
c.setAuthor('LoRa C5 enclosure engineering')
INK=HexColor('#162F3C'); MUTED=HexColor('#526670'); TEAL=HexColor('#087D91')
RULE=HexColor('#CEDADD'); GREEN=HexColor('#B8D9C8'); LIGHT=HexColor('#F5F8F8')
COLORS={'EnclosureBase':HexColor('#D8E2E8'),'EnclosureLid':HexColor('#D8E2E8'),
        'BatteryCover':HexColor('#A7C5D8'),'ReferenceBatteryEnvelope':HexColor('#8BD5A8'),
        'ReferenceSoftPad':HexColor('#959FA4'),
        'ReferenceBatteryPlug':HexColor('#D5D5D0'),'ReferenceLeadPositive':HexColor('#CA3B29'),'ReferenceLeadNegative':HexColor('#424242'),
        'carrier':HexColor('#A8CABB'),'heltec':HexColor('#B7D9C5'),'oled':HexColor('#F3D2AC')}

def text(x,y,s,size=10,color=INK,font='Helvetica',align='left'):
    c.setFillColor(color);c.setFont(font,size)
    {'left':c.drawString,'center':c.drawCentredString,'right':c.drawRightString}[align](x,H-y,s)
def line(x1,y1,x2,y2,color=INK,width=.6,dash=()):
    c.setStrokeColor(color);c.setLineWidth(width);c.setDash(dash)
    c.line(x1,H-y1,x2,H-y2);c.setDash([])
def box(x,y,w,h,fill=white,stroke=RULE):
    c.setFillColor(fill);c.setStrokeColor(stroke);c.setLineWidth(.7)
    c.rect(x,H-y-h,w,h,fill=1,stroke=1)
def wrap(x,y,s,width,size=10,leading=14,color=MUTED,font='Helvetica'):
    row=''
    for word in s.split():
        trial=(row+' '+word).strip()
        if c.stringWidth(trial,font,size)>width and row:
            text(x,y,row,size,color,font);y+=leading;row=word
        else:row=trial
    if row:text(x,y,row,size,color,font);y+=leading
    return y
def arrow(x,y,dx,dy,color=TEAL,size=4):
    norm=math.hypot(dx,dy);u,v=dx/norm,dy/norm
    p=c.beginPath();p.moveTo(x,H-y);p.lineTo(x+u*size-v*size*.4,H-y-v*size-u*size*.4)
    p.lineTo(x+u*size+v*size*.4,H-y-v*size+u*size*.4);p.close()
    c.setFillColor(color);c.drawPath(p,fill=1,stroke=0)
def hdim(x1,x2,y,yr,label):
    for x in(x1,x2):line(x,yr,x,y-4,TEAL,.5)
    line(x1,y,x2,y,TEAL,.7);arrow(x1,y,1,0);arrow(x2,y,-1,0)
    text((x1+x2)/2,y-6,label,10,TEAL,'Helvetica-Bold','center')
def vdim(y1,y2,x,xr,label):
    for y in(y1,y2):line(xr,y,x+4,y,TEAL,.5)
    line(x,y1,x,y2,TEAL,.7);arrow(x,y1,0,1);arrow(x,y2,0,-1)
    text(x+8,(y1+y2)/2+3,label,10,TEAL,'Helvetica-Bold')
def image(path,x,y,w,h):
    im=ImageReader(str(path));iw,ih=im.getSize();scale=min(w/iw,h/ih)
    ww,hh=iw*scale,ih*scale
    c.drawImage(im,x+(w-ww)/2,H-y-h+(h-hh)/2,ww,hh,mask='auto')
def header(sub,title_right):
    text(36,47,'BATTERY INTEGRATION',27,INK,'Helvetica-Bold')
    text(36,72,'C5 enclosure / Revision R4 / '+sub,11,MUTED)
    text(W-36,47,title_right,21,TEAL,'Helvetica-Bold','right')
    line(36,96,W-36,96,RULE)
def footer(page):
    line(36,H-37,W-36,H-37,RULE)
    text(36,H-19,'LORA WALKIE-TALKIE  |  C5-R4-BATTERY  |  2026-11-24',9,INK,'Helvetica-Bold')
    text(W-36,H-19,f'UNITS mm  /  A3  /  NTS  /  SHEET {page} OF 2',9,MUTED,align='right')

header('Separate rear compartment',f"{d['overall_height_mm']:.1f} mm shell height")
box(36,119,766,620)
text(52,143,'ACTUAL ASSEMBLY / HOUSING CUTAWAY / LID REMOVED',12,INK,'Helvetica-Bold')
image(root/'battery-cutaway.png',48,157,742,472)
wrap(54,652,'Selected housing material, the lid and its PTT parts are removed for visibility. The PCB and six assigned component models retain their assembly positions. The battery, plug and wire geometry are packaging references; actual connector fit is not qualified.',727,10,14)
text(54,720,'Photo body: 68 x 35 x 10 mm  |  Conservative CAD envelope: 68 x 36 x 10 mm',10,TEAL,'Helvetica-Bold')
box(820,119,W-856,620,LIGHT)
y=148
text(838,y,'SEPARATE BATTERY BAY',12,INK,'Helvetica-Bold');y+=32
text(838,y,f"{d['bay_depth_mm']:.1f} mm",24,TEAL,'Helvetica-Bold');y+=24
y=wrap(838,y,'Clear compartment depth beneath the original floor / PCB barrier.',W-892,10,14)+17
for title,body in cfg['overview_notes']:
    text(838,y,title,11,INK,'Helvetica-Bold');y+=17
    y=wrap(838,y,body,W-892,10,14)+18
footer(1);c.showPage()

header('Dimensioned section and connection plan','Heltec battery only')
box(36,119,766,399)
text(52,143,f"A-A  |  LONGITUDINAL SECTION X = {data['section_plane']['value_mm']:.2f}",12,INK,'Helvetica-Bold')
text(52,162,'Y horizontal, Z vertical. Exact section wires from saved native CAD.',9.5,MUTED)
scale=5.75;origin_x=102;origin_y=355
sx=lambda y:origin_x+y*scale
sy=lambda z:origin_y-z*scale
# Paper clipping does not alter actual section geometry or dimensions.
c.saveState();p=c.beginPath();p.rect(48,H-493,742,310);c.clipPath(p,stroke=0)
order=cfg['section_objects']
for name in order:
    for record in sections.get(name,[]):
        pts=record['points']
        if len(pts)<2:continue
        path=c.beginPath();path.moveTo(sx(pts[0][0]),H-sy(pts[0][1]))
        for y,z in pts[1:]:path.lineTo(sx(y),H-sy(z))
        if record['closed']:path.close()
        color=COLORS.get(name,HexColor('#B8C7CE'))
        c.setFillColor(color);c.setStrokeColor(INK);c.setLineWidth(.5)
        c.drawPath(path,fill=int(record['closed']),stroke=1)
c.restoreState()
bb=d['battery_bounds_mm']
text(sx((bb[1]+bb[4])/2),sy((bb[2]+bb[5])/2)+3,'BATTERY ENVELOPE',10,INK,'Helvetica-Bold','center')
hdim(sx(bb[1]),sx(bb[4]),478,sy(bb[2]),f"{bb[4]-bb[1]:.0f} BATTERY")
vdim(sy(d['main_outer_z']),sy(d['cover_outer_z']),739,sx(d['case_ymax']),f"{d['overall_height_mm']:.1f}")
vdim(sy(bb[5]),sy(bb[2]),sx(bb[4])+15,sx(bb[4]),f"{bb[5]-bb[2]:.0f}")
text(53,504,'Battery clearance shown is nominal; no pouch compression or swelling certification is implied.',9,MUTED)
box(820,119,W-856,399,LIGHT)
text(838,147,'PACKAGING DIMENSIONS',12,INK,'Helvetica-Bold')
y=177
for label,value in cfg['dimension_rows']:
    text(838,y,label,10,MUTED);y+=17
    text(838,y,value,13,INK,'Helvetica-Bold');y+=29

box(36,536,W-72,203)
text(52,560,'BATTERY CONNECTION / SCOPE',12,INK,'Helvetica-Bold')
blocks=[(52,583,239,54,'PROTECTED 1S LiPo','3.7 V nominal / 3000 mAh'),
        (335,583,270,54,'POLARITY-VERIFIED LEAD','Extension / adapter if required'),
        (649,583,246,54,'HELTEC V4 JP2 BAT','Pin 1: VBAT   |   Pin 2: GND')]
for x,y,w,h,title,sub in blocks:
    box(x,y,w,h,LIGHT);text(x+w/2,y+20,title,10,INK,'Helvetica-Bold','center')
    text(x+w/2,y+39,sub,9,MUTED,align='center')
for x1,x2 in ((291,335),(605,649)):
    line(x1,610,x2,610,TEAL,1.4);arrow(x2,610,-1,0,TEAL,6)
text(922,601,'AMPLIFIER',10,INK,'Helvetica-Bold')
text(922,620,'USB supply retained',9,MUTED)
wrap(52,659,cfg['connection_note'],W-108,9.5,13)
wrap(52,707,cfg['source_note'],W-108,8,11)
footer(2);c.save()
reader=PdfReader(str(out));assert len(reader.pages)==2
all_text='\n'.join(p.extract_text() or '' for p in reader.pages)
for required in ['BATTERY INTEGRATION','HELTEC V4 JP2 BAT','USB supply retained','SHEET 2 OF 2']:
    assert required in all_text,required
result=dict(pdf=str(out),pages=2,source_geometry_sha256=hashlib.sha256((root/'battery-section-geometry.json').read_bytes()).hexdigest(),pdf_sha256=hashlib.sha256(out.read_bytes()).hexdigest(),page_size_points=list(reader.pages[0].mediabox),text_checks=True,visual_review='pending',ok=False)
(root/'DOCUMENT-VALIDATION.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result))
