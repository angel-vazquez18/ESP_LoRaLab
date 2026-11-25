"""Nine-sheet R7 engineering set from read-only exact-BREP projections."""
from pathlib import Path
import argparse,hashlib,json,math,subprocess,sys
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A3,landscape
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parent
arg=argparse.ArgumentParser();arg.add_argument('--preflight',action='store_true');opt=arg.parse_args()
source=ROOT/('manufacturing-geometry-preflight.json'if opt.preflight else'manufacturing-geometry.json')
D=json.loads(source.read_text(encoding='utf-8'));assert D['ok'] and D['release_ready']==(not opt.preflight)
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert all(sha(p)==h for p,h in D['source_hashes'].items())
pdf=ROOT/(('DRAFT-'if opt.preflight else'')+'C5-R7-Manufacturing-Drawings.pdf')
W,H=landscape(A3);c=canvas.Canvas(str(pdf),pagesize=(W,H),pageCompression=1)
c.setTitle('LoRa C5 R7 - manufacturing and engineering drawings'+(' - candidate preflight'if opt.preflight else''))
INK=colors.HexColor('#173341');BLUE=colors.HexColor('#087F94');GRAY=colors.HexColor('#536773');LIGHT=colors.HexColor('#E6EEF1');ORANGE=colors.HexColor('#BC5A21');GREEN=colors.HexColor('#25825A')
def label(x,y,s,size=9,color=INK,bold=False):
 c.setFillColor(color);c.setFont('Helvetica-Bold'if bold else'Helvetica',size);c.drawString(x*mm,y*mm,str(s))
def wrap(x,y,s,w=175,size=9,leading=4.4,color=GRAY):
 for t in simpleSplit(s,'Helvetica',size,w*mm):label(x,y,t,size,color);y-=leading
 return y
def line(a,b,color=INK,width=.5,dash=()):
 c.setStrokeColor(color);c.setLineWidth(width);c.setDash(dash);c.line(a[0]*mm,a[1]*mm,b[0]*mm,b[1]*mm);c.setDash([])
def box(x,y,w,h,fill=None):
 c.setStrokeColor(LIGHT);c.setLineWidth(.6)
 if fill:c.setFillColor(fill)
 c.rect(x*mm,y*mm,w*mm,h*mm,stroke=1,fill=bool(fill))
def arrow(x,y,dx,dy,color=INK):
 n=math.hypot(dx,dy);dx/=n;dy/=n;p=c.beginPath();p.moveTo(x*mm,y*mm)
 p.lineTo((x+1.8*dx+.6*dy)*mm,(y+1.8*dy-.6*dx)*mm);p.lineTo((x+1.8*dx-.6*dy)*mm,(y+1.8*dy+.6*dx)*mm);p.close();c.setFillColor(color);c.drawPath(p,fill=1,stroke=0)
def page(title,i):
 box(10,10,400,277);line((10,29),(410,29),LIGHT)
 label(17,277,title,17,bold=True)
 label(17,269,'R7 | 2026-11-25 | nominal mm | views independently scaled | DO NOT SCALE',9,GRAY)
 label(17,21,'LORA C5 / ENCLOSURE / ENGINEERING AND MANUFACTURING',10,bold=True)
 label(17,15,'PCB design, component positions, Gerbers, drills and firmware remain unchanged.',8,GRAY)
 label(339,21,f'A3 / SHEET {i} OF 9',9,bold=True)
 label(250,261,'DRAFT - APPROVED NATIVE/STEP PENDING'if opt.preflight else'FIT PROTOTYPE - FIRST ARTICLE REQUIRED',9,ORANGE,True)
def dims(data):
 pts=[p for k in ['visible','hidden']for a in data[k]for p in a]
 return[min(p[0]for p in pts),min(p[1]for p in pts),max(p[0]for p in pts),max(p[1]for p in pts)]
def view(data,rect,title,color=INK,framebounds=None):
 x,y,w,h=rect;b=framebounds or dims(data);scale=min((w-4)/max(b[2]-b[0],.01),(h-4)/max(b[3]-b[1],.01));ox=x+w/2-(b[0]+b[2])*scale/2;oy=y+h/2-(b[1]+b[3])*scale/2;tf=lambda a,z:(ox+a*scale,oy+z*scale)
 c.saveState();clip=c.beginPath();clip.rect(x*mm,y*mm,w*mm,h*mm);c.clipPath(clip,stroke=0)
 for kind in ['hidden','visible']:
  c.setStrokeColor(GRAY if kind=='hidden'else color);c.setLineWidth(.25 if kind=='hidden'else .65);c.setDash([2,2]if kind=='hidden'else [])
  for pts in data[kind]:
   if len(pts)<2:continue
   p=c.beginPath();a,z=tf(*pts[0]);p.moveTo(a*mm,z*mm)
   for point in pts[1:]:a,z=tf(*point);p.lineTo(a*mm,z*mm)
   c.drawPath(p)
 c.restoreState()
 if title:label(x,y+h+4,title,10,color,True)
 return tf
def dimx(tf,a,b,y,s):
 xa,ya=tf(*a);xb,yb=tf(*b);line((xa,ya),(xa,y+1),GRAY,.35);line((xb,yb),(xb,y+1),GRAY,.35);line((xa,y),(xb,y));arrow(xa,y,1,0);arrow(xb,y,-1,0)
 tw=c.stringWidth(s,'Helvetica',9)/mm;c.setFillColor(colors.white);c.rect(((xa+xb-tw)/2-1)*mm,(y-1)*mm,(tw+2)*mm,5*mm,fill=1,stroke=0);label((xa+xb-tw)/2,y+.3,s)
def dimy(tf,a,b,x,s):
 xa,ya=tf(*a);xb,yb=tf(*b);line((xa,ya),(x+1,ya),GRAY,.35);line((xb,yb),(x+1,yb),GRAY,.35);line((x,ya),(x,yb));arrow(x,ya,0,1);arrow(x,yb,0,-1)
 c.saveState();c.translate((x-1.2)*mm,(ya+yb)*mm/2);c.rotate(90);tw=c.stringWidth(s,'Helvetica',9);c.setFillColor(colors.white);c.rect(-tw/2-3,-2,tw+6,12,fill=1,stroke=0);c.setFillColor(INK);c.setFont('Helvetica',9);c.drawCentredString(0,0,s);c.restoreState()
def table(x,y,w,rows):
 box(x,y-7,w,7,LIGHT);label(x+2,y-5,'FEATURE',8,bold=True);label(x+w*.39,y-5,'NOMINAL / LOCATION',8,bold=True);y-=7
 for a,b in rows:line((x,y-7.5),(x+w,y-7.5),LIGHT,.4);label(x+2,y-5.4,a,8);label(x+w*.39,y-5.4,b,8);y-=7.5
 return y
features={
'EnclosureBase':([('Main walls / partition','2.4 / 2.4'),('PCB support / PCB top','Z6.4 / Z8.0'),('Battery bay','Z-14 to Z0 = 14 clear'),('Rear insert axes','X4/66, Y4/86'),('Rear / upper pilots','dia 4.4 x 4.5 / dia 4.4 x 5'),('SMA axis','X47, Z14; axis along Y'),('Key carrier pocket','14.6 wide x 2.6 axial'),('Coax route reference','R10 bends; dia 1.32')],
 ['SMA pocket and loose-tie anchor are integrated; the round bulkhead bore and seating wall are retained. Fixed rear hex is provisional, not measured hardware.',
  'Preserve the continuous 2.4 mm PCB/battery partition. Opposed cavities, hood and tie-slot access require a shop tooling review. Source STEP controls contours.']),
'EnclosureLid':([('Main inner / outer lid','Z21 / Z24.6'),('OLED opening / center','16.4 x 27 / X23, Y58.05'),('Rim underside / long face','Z20.5 / Z22.1'),('OLED added bands top','Z22.7; sampled roofs 1.5-1.7'),('PTT guide / center','dia 8.8 / X51, Y9'),('Mic holes / shroud','7 x dia 1.6 / OD11, ID8'),('Mic shroud bottom','Z13; 8 below inner lid'),('Speaker grille','9 x dia 1.8; pitch 3'),('Speaker stop plane','Z16.4; screws M2 x 12')],
 ['OLED aperture and mounting datums stay fixed; the nominal glass-to-rim gap remains 0.50 mm. Short bands and corner returns strengthen prior screw-relief roofs.',
  'Speaker tie lip relief retains 1.2 mm lip, with 0.45 mm nominal loop clearance. See the changed-feature drawing for key, shroud, reinforcement and pocket details.']),
'BatteryCover':([('Main plate / guides','2.4 / 5.4 overall'),('Screw clearances','4 x dia 3.4; X4/66, Y4/86'),('Rear screws','4 x M3 x 6'),('Guide space / battery','70 x 38 / 68 x 36'),('Soft-strap slots','4 x 2.4 x 12 rounded'),('Slot centers','X12.2/57.8, Y30/60'),('Strap channels','12 wide x 1 deep'),('Residual channel floor','1.4')],
 ['Geometry retained from R6. The pouch sits on a nominal 1 mm insulating pad, with 3 mm above its 10 mm reference thickness.',
  'Use two soft 10 mm straps without squeezing the pouch. M3 x 6 rear screws have nominal 0.9 mm blind-end clearance; do not substitute longer screws.']),
'PTTPlunger':([('Shaft / flange / foot','dia 8 / dia 12 / dia 4'),('Flange thickness','1.2'),('Released flange bottom','Z19.6'),('Initial switch-tip gap','0.20 nominal'),('Downstroke to shelf','0.45 nominal'),('Switch depression','0.25 PROVISIONAL'),('Guide diametral allowance','0.8 (8 shaft / 8.8 guide)')],
 ['Geometry and actual switch location are retained. The switch operating travel and safe overtravel have not been measured.',
  'Verify free sliding, continuity at actuation and reliable release gently before load/cycle testing. The cup, not the PCB, is intended to carry stop load.']),
'PTTStopCup':([('Cup OD / cavity / foot bore','16.6 / 13.2 / 5.2'),('Cup overall height','3.85'),('Stop shelf thickness','2.0'),('Shelf / underside','Z19.15 / Z17.15'),('Lug OD / screw span','6 / 18'),('Mounting hardware','2 x M2 x 10 + 2 M2 nuts'),('Nut reference','4 AF x 1.6 high')],
 ['Retained cup geometry provides flange-to-shelf contact at the nominal 0.45 mm button downstroke.',
  'Stop load transfers from flange to shelf, cup lugs, nut bearing, screw tension and lid head bearing. No switch-force or structural torque rating is established.']),
'SpeakerRetainer':([('Overall / stop plane','30 x 15.5 x 3.2 / Z16.4'),('Underside plane','Z13.2'),('Speaker window','13 x 8'),('Screw axes','X43.5 Y47 / X65.5 Y42'),('Screw clearance','2 x dia 2.4'),('Nut pockets','4.3 AF x 1.8 deep'),('Nut-bearing roof','1.4 (was 0.8)'),('Nuts / screws','4 AF x 1.6 / M2 x 12')],
 ['Reinforced retainer lowers its underside while preserving the original hard-stop plane, speaker position and pad allowances.',
  'Nut Z13.4-15.0 and screw tip Z12.9 give nominal 0.5 mm projection. Support only the stationary speaker frame; keep diaphragm and vents unloaded.']),
'SMAKey':([('Overall','14 x 2 x 9.9'),('Jaw gap','8.4'),('Top bridge / side legs','1.1 / 2.8'),('Outer edge fillet','R0.3'),('Rear fixed-hex reference','8 AF; UNMEASURED'),('Guide allowance','0.3 per side and axial'),('Key top / lid underside','Z20.3 / Z21 = 0.7 gap')],
 ['Removable key is captured by the closed lid. Measure the fixed rear hex body, not the bulkhead nut; also check shoulder, axial depth and thread engagement.',
  'The nominal reference engages by +/-8 degrees with guide play included. This demonstrates geometric restraint only; counter-hold during antenna fitting.'])}
order=['EnclosureBase','EnclosureLid','BatteryCover','PTTPlunger','PTTStopCup','SpeakerRetainer','SMAKey']
titles=['BASE - PCB cavity, rear bay and SMA support','LID - OLED, microphone and speaker interfaces','BATTERY COVER - padded soft-strap retention','PTT PLUNGER - retained actuator datums','PTT STOP CUP - retained load-bearing shelf','SPEAKER RETAINER - reinforced nut-bearing roof','SMA KEY - replaceable fixed-body restraint']
for i,(name,title)in enumerate(zip(order,titles),1):
 p=D['parts'][name];b=p['bounds_mm'];page(f'{i:02d} / '+title,i)
 tf=view(p['views']['top'],(37,112,151,136),'');label(37,104,'TOP (+Z)',10,bold=True)
 top=dims(p['views']['top']);dimx(tf,(top[0],top[3]),(top[2],top[3]),257,f'{b[3]-b[0]:.2f} overall X');dimy(tf,(top[0],top[1]),(top[0],top[3]),25,f'{b[4]-b[1]:.2f} overall Y')
 fv=view(p['views']['front'],(220,210,174,36),'FRONT (-Y)');fb=dims(p['views']['front']);dimy(fv,(fb[2],fb[1]),(fb[2],fb[3]),402,f'{b[5]-b[2]:.2f} overall Z')
 view(p['views']['right'],(220,145,174,40),'RIGHT (+X)')
 table(215,131,185,features[name][0]);y=94
 label(25,y,name+' / QTY 1 / UNFILLED MJF PA12',10,BLUE,True);y-=8
 for note in features[name][1]:y=wrap(25,y,note,177,9,4.5)-5
 label(25,35,'Nominal interfaces only. STEP controls unlisted surfaces and fillets.',8,GRAY)
 c.showPage()

page('08 / ASSEMBLY SECTIONS - unchanged PCB and component locations',8)
def section(name,rect,title,b=None):
 groups=D['sections'][name]['groups'];merged={k:sum([g[k]for g in groups.values()],[])for k in ['visible','hidden']};frame=b or dims(merged)
 tf=None
 for group,col in [('enclosure',INK),('actual_electronics',BLUE),('reference_hardware',GREEN)]:
  if groups[group]['visible'] or groups[group]['hidden']:tf=view(groups[group],rect,'',col,frame)
 label(rect[0],rect[1]+rect[3]+4,title,10,INK,True);return tf
tf=section('battery_x27_2',(24,149,184,91),'A-A / X27.2, looking +X: battery / PCB / lid')
section('ptt_y9',(230,166,166,75),'B-B / Y9: PTT released position',[35,7.5,67,28])
section('speaker_y47',(230,59,166,76),'C-C / Y47: speaker and reinforced retainer',[38,7.5,73,26])
label(25,135,'SECTION COLOURS',10,bold=True);label(25,127,'Enclosure',9,INK);label(67,127,'Actual assigned electronics',9,BLUE);label(25,119,'Nominal battery / speaker envelopes',9,GREEN)
y=106
for text in ['A-A: 10 mm battery reference, 1 mm pad allowance below, 3 mm nominal space above. PCB support Z6.4 and top Z8 remain fixed.',
 'B-B: released flange bottom Z19.60, shelf Z19.15. Travel to contact 0.45; switch depression 0.25 remains provisional.',
 'C-C: speaker Z16.9-20.4; front pad 0.6, rear pad 0.5; retainer stop Z16.4, underside Z13.2. Actual rigid frame must be checked.']:
 y=wrap(25,y,text,178,9,4.5)-5
label(230,44,f'{D["actual_component_objects"]} assigned component objects retained; section curves are exact BREP slices.',8,GRAY)
c.showPage()

page('09 / LOAD PATHS, DESIGN TRACE AND MANUFACTURING FLOW',9)
label(22,248,'PTT STOP LOAD PATH',11,bold=True)
for i,(text,x)in enumerate([('FLANGE',22),('CUP SHELF',100),('NUTS',178),('SCREWS',256),('LID',334)]):
 box(x,227,62,13,LIGHT);label(x+5,232,text,10,bold=True)
 if i<4:line((x+62,233),(x+76,233),BLUE,1);arrow(x+76,233,-1,0,BLUE)
wrap(22,219,'The cup protects the switch by carrying stop load through nut bearing and screw tension into lid head bearing. SMA lateral/rotation load is transferred through the fixed rear body and key into the base carrier; the lid retains the key. Battery straps and pads retain the pouch without rigid compression.',374,9,4.5)
label(22,192,'DESIGN DEVELOPMENT',11,bold=True)
trace=[('R1-R3','PCB-based enclosure; microphone ports and PTT cup; OLED recess refined to 0.50 mm nominal gap.'),('R4','Independent rear battery bay/cover, soft straps and lead chase; upper PCB/OLED datums retained.'),('R5-R6','SMA bulkhead mount and coax routing; one lid-mounted speaker, grille and removable retainer.'),('R7','Stronger retainer/OLED roofs, noncontact mic shroud, two loose tie guides, removable SMA key and R10 coax route.')]
y=182
for rev,txt in trace:label(22,y,rev,9,BLUE,True);y=wrap(44,y,txt,350,9,4.5)-3
label(22,128,'MANUFACTURING AND ACCEPTANCE FLOW',11,bold=True)
for i,(text,x)in enumerate([('CAD / FILE CHECKS',22),('SHOP DFM / QUOTE',119),('FIRST ARTICLE',216),('FIT ACCEPTANCE',313)]):
 box(x,107,88,13,LIGHT);label(x+4,112,text,9,bold=True)
 if i<3:line((x+88,113),(x+95,113),BLUE,1);arrow(x+95,113,-1,0,BLUE)
wrap(22,99,'Primary route: seven separate MJF PA12 parts, standard cleaned finish, mm at 100% scale. Coupon is optional. Craftcloud files are prepared without placing an order. The exact approved STEP supplies CNC geometry; shop DFM, stock, tooling, fixtures, work offsets, cutting conditions and postprocessor remain shop tasks.',374,9,4.5)
wrap(22,78,'Inspect critical fits and actual hardware before a batch: SMA body/key/thread, inserts and nuts, OLED stack, PTT travel, speaker frame/pads, cable service slack and battery/USB coexistence. File checks do not establish strength, impact, ingress, thermal or acoustic ratings.',374,9,4.5)
wrap(22,57,'PCB, Gerbers/drills and firmware are preserved. The amplifier remains USB powered. The unchanged electronics manufacturing archive is for traceability; R7 introduces no board redesign or reorder. No machine-specific G-code has been fabricated.',374,9,4.5)
c.showPage();c.save()
reader=PdfReader(pdf);assert len(reader.pages)==9
text='\n'.join(p.extract_text()for p in reader.pages)
for term in ['SMA KEY','SPEAKER RETAINER','0.50','4.3 AF','0.45','FIRST ARTICLE','Gerbers','2949']:assert term in text,term
preview=ROOT/('preflight-previews'if opt.preflight else'drawing-previews');preview.mkdir(exist_ok=True)
ppm=Path(sys.executable).parent.parent/'native/poppler/Library/bin/pdftoppm.exe'
subprocess.run([str(ppm),'-png','-r','100',str(pdf),str(preview/'R7-sheet')],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
report={'ok':False,'release_ready':not opt.preflight,'pages':9,'pdf':pdf.name,'pdf_sha256':sha(pdf),'geometry_sha256':sha(source),
 'native_sha256':None if opt.preflight else sha(ROOT.parents[1]/'cad/LoRa-Enclosure-C5-R7-Reinforced.FCStd'),
 'step_sha256':None if opt.preflight else sha(ROOT.parents[1]/'cad/LoRa-Enclosure-C5-R7-Reinforced.step'),
 'text_checks':True,'visual_review_pending':True,'source_hashes':{str(source):sha(source),**D['source_hashes']},'read_only_extraction':True,'machine_code_generated':False}
(ROOT/('PREFLIGHT-DRAWING-VALIDATION.json'if opt.preflight else'MANUFACTURING-DRAWING-VALIDATION.json')).write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'pdf':str(pdf),'pages':9,'release_ready':not opt.preflight,'visual_review_pending':True}))
