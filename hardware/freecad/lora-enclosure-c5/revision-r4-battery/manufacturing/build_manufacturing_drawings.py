"""R4 A3 manufacturing supplement from native B-rep projections."""
from pathlib import Path
import json,math,hashlib
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A3,landscape
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit,ImageReader
from pypdf import PdfReader
import subprocess

root=Path(__file__).resolve().parent
D=json.loads((root/'manufacturing-geometry.json').read_text());P=D['parameters']
W,H=landscape(A3);pdf=root/'C5-R4-Manufacturing-Drawings.pdf'
c=canvas.Canvas(str(pdf),pagesize=(W,H));c.setTitle('LoRa C5 R4 battery housing - manufacturing and engineering drawings')
INK=colors.HexColor('#173341');BLUE=colors.HexColor('#087F94');GRAY=colors.HexColor('#536773');LIGHT=colors.HexColor('#E6EEF1');ORANGE=colors.HexColor('#BC5A21');GREEN=colors.HexColor('#25825A')
def p(n):return float(P[n]['value'].split()[0])
def f(v):return f'{v:.3f}'.rstrip('0').rstrip('.')
def label(x,y,s,size=9,color=INK,bold=False):
 c.setFillColor(color);c.setFont('Helvetica-Bold'if bold else'Helvetica',size);c.drawString(x*mm,y*mm,str(s))
def wrap(x,y,s,w=178,size=9,leading=4.5,color=GRAY):
 for t in simpleSplit(s,'Helvetica',size,w*mm):label(x,y,t,size,color);y-=leading
 return y
def line(a,b,color=INK,width=.5,dash=()):
 c.setStrokeColor(color);c.setLineWidth(width);c.setDash(dash);c.line(a[0]*mm,a[1]*mm,b[0]*mm,b[1]*mm);c.setDash([])
def frame(x,y,w,h,fill=None):
 c.setStrokeColor(LIGHT);c.setLineWidth(.6)
 if fill:c.setFillColor(fill)
 c.rect(x*mm,y*mm,w*mm,h*mm,stroke=1,fill=bool(fill))
def sheet(title,i):
 frame(10,10,400,277);line((10,29),(410,29),LIGHT)
 label(17,277,title,17,bold=True)
 label(17,269,'R4 | 2026-11-24 | mm | nominal CAD geometry | views independently scaled | DO NOT SCALE',9,GRAY)
 label(17,21,'LORA C5 / BATTERY HOUSING / MANUFACTURING SUPPLEMENT',10,bold=True)
 label(17,15,'Prototype shop handoff. Supplier capability and physical first article remain unqualified.',8,GRAY)
 label(330,21,'A3 / SHEET '+str(i)+' OF 6',9,bold=True)
 label(330,15,'STEP controls unlisted surfaces.',8,GRAY)
def arrow(x,y,dx,dy,color=INK):
 n=math.hypot(dx,dy);dx/=n;dy/=n
 q=c.beginPath();q.moveTo(x*mm,y*mm);q.lineTo((x+2*dx+.65*dy)*mm,(y+2*dy-.65*dx)*mm);q.lineTo((x+2*dx-.65*dy)*mm,(y+2*dy+.65*dx)*mm);q.close()
 c.setFillColor(color);c.drawPath(q,fill=1,stroke=0)
def dimx(tf,a,b,y,s):
 xa,ya=tf(*a);xb,yb=tf(*b)
 line((xa,ya),(xa,y+2),GRAY,.35);line((xb,yb),(xb,y+2),GRAY,.35);line((xa,y),(xb,y));arrow(xa,y,1,0);arrow(xb,y,-1,0)
 tw=c.stringWidth(s,'Helvetica',9)/mm;c.setFillColor(colors.white);c.rect(((xa+xb-tw)/2-1)*mm,(y-1)*mm,(tw+2)*mm,5*mm,fill=1,stroke=0);label((xa+xb-tw)/2,y+.3,s)
def dimy(tf,a,b,x,s):
 xa,ya=tf(*a);xb,yb=tf(*b)
 line((xa,ya),(x+2,ya),GRAY,.35);line((xb,yb),(x+2,yb),GRAY,.35);line((x,ya),(x,yb));arrow(x,ya,0,1);arrow(x,yb,0,-1)
 c.saveState();c.translate((x-1.2)*mm,(ya+yb)*mm/2);c.rotate(90);tw=c.stringWidth(s,'Helvetica',9);c.setFillColor(colors.white);c.rect(-tw/2-3,-2,tw+6,12,fill=1,stroke=0);c.setFillColor(INK);c.setFont('Helvetica',9);c.drawCentredString(0,0,s);c.restoreState()
def view(data,rect,title,color=INK,framebounds=None):
 x,y,w,h=rect;pts=[p for k in('visible','hidden')for path in data.get(k,[])for p in path]
 bounds=framebounds or [min(p[0]for p in pts),min(p[1]for p in pts),max(p[0]for p in pts),max(p[1]for p in pts)]
 scale=min((w-4)/(bounds[2]-bounds[0]),(h-4)/(bounds[3]-bounds[1]));ox=x+w/2-(bounds[0]+bounds[2])*scale/2;oy=y+h/2-(bounds[1]+bounds[3])*scale/2
 tf=lambda a,b:(ox+a*scale,oy+b*scale)
 for kind in('hidden','visible'):
  c.setStrokeColor(GRAY if kind=='hidden'else color);c.setLineWidth(.28 if kind=='hidden'else .7);c.setDash([2,2]if kind=='hidden'else [])
  for pts in data.get(kind,[]):
   if len(pts)<2:continue
   path=c.beginPath();a,b=tf(*pts[0]);path.moveTo(a*mm,b*mm)
   for q in pts[1:]:a,b=tf(*q);path.lineTo(a*mm,b*mm)
   c.drawPath(path)
 c.setDash([]);label(x,y+h+4,title,10,color,bold=True)
 return tf
def table(x,y,w,rows,rowh=7):
 frame(x,y-7,w,7,LIGHT);label(x+2,y-5,'FEATURE',8,bold=True);label(x+w*.37,y-5,'NOMINAL / LOCATION',8,bold=True);y-=7
 for a,b in rows:
  line((x,y-rowh),(x+w,y-rowh),LIGHT,.4);label(x+2,y-rowh+2,a,8);label(x+w*.37,y-rowh+2,b,8);y-=rowh
 return y
def image(path,x,y,w,h):
 im=ImageReader(str(path));iw,ih=im.getSize();s=min(w*mm/iw,h*mm/ih);c.drawImage(im,(x*mm+(w*mm-iw*s)/2),(y*mm+(h*mm-ih*s)/2),iw*s,ih*s)

base=D['parts']['EnclosureBase'];cover=D['parts']['BatteryCover'];lid=D['parts']['EnclosureLid'];plunger=D['parts']['PTTPlunger'];cup=D['parts']['PTTStopCup']
sheet('01 / BASE - original PCB cavity and new rear battery bay',1)
tf=view(base['views']['top'],(36,89,154,159),'TOP (+Z), PCB side')
dimx(tf,(-4.4,99.6),(74.4,99.6),258,'78.8');dimy(tf,(-4.4,-4.4),(-4.4,99.6),24,'104 max / 98.8 main body')
xx,yy=tf(0,0);line((xx,yy),(xx+10,yy),BLUE);line((xx,yy),(xx,yy+10),BLUE);label(xx+11,yy,'X',8,BLUE);label(xx,yy+11,'Y',8,BLUE)
view(base['views']['front'],(215,195,181,52),'FRONT (-Y), Z-14 .. Z21')
view(base['views']['right'],(215,115,181,51),'RIGHT (+X), rear hood at +Y')
table(211,97,187,[('Base overall','78.8 x 104 x 35'),('Main wall / separator','2.4 / 2.4'),('Battery bay','Z-14 .. Z0 = 14 clear'),('Rear insert axes','(4,4), (66,4), (4,86), (66,86)'),('Rear insert pilots','4 x dia 4.4 x 4.5 blind from Z-14'),('Rear post / upper pilot','dia 8 / upper pilots dia 4.4 x 5')],rowh=7)
wrap(23,78,'Datum O is the lower-left PCB corner; Z0 is the original floor exterior. The battery bay is added below Z0. PCB support plane remains Z6.4; PCB top Z8.0. No carrier holes are added.',177,9)
wrap(23,55,'Rear hood: X21..35, Y92..99.6, Z-14..11.1. Chase: X23.4..32.6, Y91.9..97.2. Preserve the 2.4 mm separator under the pouch. All edge details/depth transitions are controlled by STEP.',177,8)
c.showPage()

sheet('02 / BATTERY COVER - removable, padded, soft-strap retention',2)
tf=view(cover['views']['top'],(36,89,154,159),'TOP (+Z), battery side')
dimx(tf,(-4.4,99.6),(74.4,99.6),258,'78.8');dimy(tf,(-4.4,-4.4),(-4.4,99.6),24,'104 max')
view(cover['views']['front'],(215,201,181,44),'FRONT (-Y), Z-16.4 .. Z-11')
view(cover['views']['right'],(215,135,181,37),'RIGHT (+X), guides and locating tongue')
table(211,119,187,[('Plate / total height','2.4 / 5.4 incl. guide ribs'),('Screw holes','4 x dia 3.4; axes per sheet 01'),('Locating tongue','1.2 wall; 0.4 side clearance'),('Battery guide space','70 x 38; pouch 68 x 36'),('Soft-strap slots','4 x 2.4 x 12, rounded ends'),('Slot centers','X12.2 / 57.8; Y30 / 60'),('Underside strap channels','12 wide x 1 deep; 1.4 floor remains'),('Rear screws','4 x M3 x 6; no M3 x 8 substitution')],rowh=7)
wrap(23,78,'Battery envelope: X17..53, Y11..79, Z-13..-3. Use about 1 mm smooth nonconductive padding beneath and two soft nonconductive 10 mm straps. Retain without squeezing the pouch.',177,9)
wrap(23,55,'M3 x 6 gives 3.6 mm nominal engagement and 0.9 mm blind-pilot tip clearance. Four OD5 x length4 M3 inserts are outside the pouch. Verify actual insert installation and strap overlap thickness.',177,8)
c.showPage()

sheet('03 / LID - retained R3 OLED fit and acoustic opening',3)
tf=view(lid['views']['top'],(36,89,154,159),'TOP (+Z), outside')
dimx(tf,(-4.4,94.4),(74.4,94.4),258,'78.8');dimy(tf,(-4.4,-4.4),(-4.4,94.4),24,'98.8')
view(lid['views']['front'],(215,201,181,44),'FRONT (-Y), PCB clamps retained')
table(211,188,187,[('OLED opening / center','16.4 x 27 / (23,58.05)'),('Local rim underside / face','Z20.5 / Z22.1'),('Main inner / outer lid','Z21 / Z24.6'),('Rim / minimum relief roof','1.6 / 1.1'),('OLED screw reliefs','R2.2; X16/30, Y43.55/72.55'),('PTT guide / center','dia 8.8 / (51,9)'),('Cup screw clearance','2 x dia 2.4; (42,9), (60,9)'),('Microphone pattern','7 x dia 1.6; center (54.5,30.5)'),('Outer six mic holes','R2.6; 60-degree spacing'),('Reset / user openings','dia 3.2; X15.094/30.906, Y86'),('Main closure / screws','4 x dia 3.4 / 4 x M3 x 22')],rowh=7)
wrap(23,78,'OLED glass top Z19.998719 gives 0.501281 mm nominal vertical gap to the surrounding rim underside, shown as 0.50. The aperture is open; no solid lens or compressive gasket is present.',177,9)
wrap(23,55,'The modeled frame minimum clearance is 0.441281 mm and OLED screw minimum is 0.698781 mm. Confirm the owned display/header stack and print tolerances before tightening the lid.',177,8)
wrap(213,99,'Recess floor is 20.4 x 31, with a 2 mm ledge. Upper recess is 25.4 x 36 with 45-degree transitions. Microphone acoustic performance and ingress protection are not qualified.',183,8)
c.showPage()

sheet('04 / PTT - plunger, stop cup and mechanical load path',4)
view(plunger['views']['front'],(25,154,89,89),'PLUNGER / FRONT',ORANGE)
view(plunger['views']['top'],(131,174,63,63),'PLUNGER / TOP',ORANGE)
view(cup['views']['top'],(228,185,162,58),'STOP CUP / TOP',GREEN)
view(cup['views']['front'],(228,146,162,26),'STOP CUP / FRONT',GREEN)
table(22,138,182,[('Shaft / flange / foot','dia 8 / 12 / 4'),('Flange thickness','1.2'),('Unloaded CAD flange bottom','Z19.6'),('Initial tip gap / switch travel','0.20 / 0.25 reference'),('Full CAD downstroke','0.45 to shelf contact'),('Button above lid','1.8 nominal')],rowh=7)
table(222,130,175,[('Cup OD / cavity / foot bore','16.6 / 13.2 / 5.2'),('Cup height / shelf thickness','3.85 / 2'),('Shelf / underside planes','Z19.15 / Z17.15'),('Lug OD / screw span','6 / 18'),('Hardware','2 x M2 x 10 + 2 M2 nuts')],rowh=7)
nodes=[('FLANGE',22),('CUP SHELF',100),('NUTS',178),('SCREWS',256),('LID',334)]
for i,(name,x)in enumerate(nodes):
 frame(x,61,62,13,LIGHT);label(x+5,66,name,10,bold=True)
 if i<4:line((x+62,67),(x+76,67),BLUE,1.2);arrow(x+76,67,-1,0,BLUE)
wrap(22,52,'At full depression, the flange bears on the shelf. The cup transfers load to nuts bearing below it, screw tension and screw-head bearing at the lid. Actual switch travel and force remain first-article requirements; the 0.25 mm switch travel is a reference assumption.',375,8,4)
c.showPage()

sheet('05 / ASSEMBLY - actual PCB models, separate cell, preserved datums',5)
image(root.parent/'documentation/battery-exploded.png',19,39,163,218)
label(199,250,'ASSEMBLY SEQUENCE',11,bold=True)
y=239
for title,body in [('1 / Finish printed surfaces','Depowder and finish battery-facing edges. Test inserts, locating tongue and PTT sliding fits before installing electronics.'),('2 / Preserve the upper assembly','Install the C5 carrier at its existing supports, Heltec/OLED and other components. Retain the R3 lid, PTT cup, nuts and screws.'),('3 / Retain the battery','Fit smooth padding and soft straps to the removable cover. Route the lead through the rear chase without trapping it. Keep strain off the pouch tabs.'),('4 / Confirm connection before power','C5 carrier + local-node-homar context: amplifier stays USB-powered. Verify BAT plug keying/polarity and battery-plug/USB-cable fit. Confirm the pack permits Heltec charging current.'),('5 / Close and verify the prototype','Use M3 x 6 on the battery cover, M3 x 22 on the main lid. Check OLED clearance, switch stop travel, cable service slack and all screw lengths physically.')]:
  label(199,y,title,10,bold=True);y=wrap(199,y-6,body,193,9,4.7)-7
line((199,71),(398,71),LIGHT)
wrap(199,64,'The green battery is a conservative packaging envelope, not manufacturer CAD. Actual assigned PCB/component models are shown. The existing two-page Battery Integration drawing supplies the exact X27.2 assembled section and battery connection diagram.',192,8,4.2)
c.showPage()

sheet('06 / DESIGN DECISIONS - manufacture, inspection and release limits',6)
label(20,251,'REVISION TRACE',11,bold=True)
rows=[('R1','PCB-based enclosure, microphone holes and independently retained PTT stop cup.'),('R2','Exterior OLED recess brings the window face closer while retaining PCB and PTT datums.'),('R3','Local OLED rim lowered 0.50 mm with screw reliefs; nominal glass-to-rim gap 0.50 mm.'),('R4','Separate rear battery bay, removable cover, soft straps and rear lead chase; upper fit unchanged.')]
y=239
for rev,body in rows:label(20,y,rev,10,BLUE,True);y=wrap(36,y,body,160,9,4.6)-7
label(215,251,'CNC SHOP HANDOFF / PROPOSED SETUP LOGIC',11,bold=True)
y=239
for title,body in [('Base','Opposed PCB/battery cavities require at least two setups. Support the retained thin floor, register from agreed datums and machine side cable/connector access with suitable reorientation.'),('Cover','Machine battery side/guide ribs and flip for 1 mm-deep strap channels. Preserve the 1.4 mm residual floor. Narrow 2.4 mm slots require tool/access review.'),('Lid / PTT','Lid has underside clamps, pockets and reliefs as well as top recess. The plunger flange and cup cavity require separate operations or lathe/mill combinations chosen by the shop.')]:
 label(215,y,title,10,bold=True);y=wrap(215,y-6,body,181,9,4.6)-6
label(20,135,'PROCESS RELEASE FLOW',11,bold=True)
flow=[('CAD VERIFIED',20),('SHOP DFM',116),('FIRST ARTICLE',212),('FIT ACCEPTANCE',308)]
for i,(txt,x)in enumerate(flow):
 frame(x,111,88,14,LIGHT);label(x+5,116,txt,10,bold=True)
 if i<3:line((x+88,118),(x+94,118),BLUE,1);arrow(x+94,118,-1,0,BLUE)
wrap(20,101,'MJF PA12 is the primary printing route. The separate STEP/DXF set is a CNC quotation and CAM-input handoff. The shop must select stock/material, fixtures, tools, work offsets, feeds, speeds and postprocessor, then simulate CAM. No machine-executable G-code is included.',375,9,4.6)
wrap(20,82,'CNC DFM: sharp internal corner transitions, deep thin walls, narrow ports/slots and 1.1 mm local lid relief roofs may need special tooling or agreed geometry changes. Do not add unreviewed fillets or change insert pilots. Setup choices require the shop to confirm tooling and access.',375,9,4.6)
wrap(20,63,'All dimensions are nominal. Supplier must propose process tolerances for the 0.4 mm fits, PTT motion, insert pilots and 0.50 mm OLED gap. No physical fit, swelling, drop, thermal, acoustic, ingress, charging or firmware qualification follows from file checks.',375,9,4.6)
wrap(20,45,'Electrical scope: C5 carrier and reviewed local-node-homar firmware only. Battery-only use requires a verified speaker-disabled Heltec build holding AMP_SD LOW. Upstream generic bench hardware/firmware is not modified by this mechanical archive.',375,8,4)
c.showPage();c.save()

doc=PdfReader(pdf);renders=root/'drawing-previews';renders.mkdir(exist_ok=True)
runtime=Path('C:/Program Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1123-915-0_26.1123.915.0_x64__3k8sg7r9htsxt/dependencies')
ppm=next(runtime.rglob('pdftoppm.exe'))
for i,page in enumerate(doc.pages):
 subprocess.run([str(ppm),'-f',str(i+1),'-l',str(i+1),'-singlefile','-r','100','-png',str(pdf),str(renders/f'C5-R4-Manufacturing-Sheet-{i+1}')],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
text='\n'.join(p.extract_text()for p in PdfReader(pdf).pages)
required=['104 max','M3 x 6','0.50','CNC SHOP','0.45','1.4','R4','MJF PA12','AMP_SD LOW']
assert all(t in text for t in required)
print(json.dumps({'pdf':str(pdf),'pages':len(doc.pages),'text_checks':True,'visual_review':'pending'}))
