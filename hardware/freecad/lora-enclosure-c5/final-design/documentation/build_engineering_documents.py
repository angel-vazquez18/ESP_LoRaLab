"""Create vector technical drawings and a review dossier from final CAD evidence.

Run with the bundled document Python after extract_drawing_geometry.py.
The metadata JSON is a small reviewed record of changes/checks and source images.
"""
import argparse
import csv
import json
import math
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, A3, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image, KeepTogether

HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--geometry", default=str(HERE / "drawing-geometry.json"))
parser.add_argument("--metadata", default=str(HERE / "document-metadata.json"))
parser.add_argument("--output-dir", default=str(HERE))
args = parser.parse_args()
OUT = Path(args.output_dir)
OUT.mkdir(parents=True, exist_ok=True)
D = json.loads(Path(args.geometry).read_text(encoding="utf-8"))
M = json.loads(Path(args.metadata).read_text(encoding="utf-8"))
P = D["parameters"]
def p(name):
    return float(P[name]["value"].split()[0])
def fmt(v):
    return f"{v:.3f}".rstrip("0").rstrip(".")

INK = colors.HexColor("#172635")
BLUE = colors.HexColor("#12658A")
GRAY = colors.HexColor("#6F7D86")
LIGHT = colors.HexColor("#EAF0F4")
ORANGE = colors.HexColor("#B2551A")
GREEN = colors.HexColor("#28704B")
W, H = landscape(A3)
drawings = OUT / "Enclosure-Technical-Drawings.pdf"
c = canvas.Canvas(str(drawings), pagesize=(W,H))
c.setTitle("LoRa C5 enclosure - technical drawings")
c.setAuthor("LoRa Walkie-Talkies project")

def label(x,y,text,size=9,color=INK,bold=False):
    c.setFillColor(color)
    c.setFont("Helvetica-Bold" if bold else "Helvetica",size)
    c.drawString(x*mm,y*mm,str(text))

def wrapped(x,y,text,width=170,size=9,leading=4.3,color=INK):
    from reportlab.lib.utils import simpleSplit
    for line in simpleSplit(text,"Helvetica",size,width*mm):
        label(x,y,line,size,color)
        y -= leading
    return y

def sheet(title,index):
    c.setStrokeColor(INK); c.setLineWidth(.5)
    c.rect(10*mm,10*mm,400*mm,277*mm)
    c.line(10*mm,29*mm,410*mm,29*mm)
    label(15,278,title,17,bold=True)
    label(15,269,"CAD-derived nominal geometry | mm | orthographic views independently scaled and labeled",9,GRAY)
    label(15,21,"LORA WALKIE-TALKIE / C5 ENCLOSURE",10,bold=True)
    label(15,15,"Revision: "+M["revision"]+"  |  "+M["date"]+"  |  Fit-check prototype",8,GRAY)
    label(220,21,"DO NOT SCALE. CAD controls dimensions not listed.",9,bold=True)
    label(220,15,"Printer and physical-hardware qualification remain open.  Sheet "+str(index)+" / 4",8,GRAY)

def line(x1,y1,x2,y2,color=INK,width=.5,dash=None):
    c.setStrokeColor(color);c.setLineWidth(width);c.setDash(dash or [])
    c.line(x1*mm,y1*mm,x2*mm,y2*mm);c.setDash([])

def arrow(x,y,dx,dy):
    # Filled dimension arrow; dimensions given in page millimetres.
    n=math.hypot(dx,dy);dx/=n;dy/=n
    path=c.beginPath();path.moveTo(x*mm,y*mm)
    path.lineTo((x+2.0*dx+.65*dy)*mm,(y+2.0*dy-.65*dx)*mm)
    path.lineTo((x+2.0*dx-.65*dy)*mm,(y+2.0*dy+.65*dx)*mm)
    path.close();c.setFillColor(INK);c.drawPath(path,stroke=0,fill=1)

def dimx(tf,a,b,y,text):
    xa,ya=tf(a[0],a[1]);xb,yb=tf(b[0],b[1])
    line(xa,ya,xa,y+2,GRAY,.35);line(xb,yb,xb,y+2,GRAY,.35)
    line(xa,y,xb,y,INK,.4);arrow(xa,y,1,0);arrow(xb,y,-1,0)
    c.setFont("Helvetica",8);tw=c.stringWidth(text,"Helvetica",8)/mm
    c.setFillColor(colors.white);c.rect(((xa+xb-tw)/2-1)*mm,(y-1)*mm,(tw+2)*mm,4*mm,fill=1,stroke=0)
    label((xa+xb-tw)/2,y+.4,text,8)

def dimy(tf,a,b,x,text):
    xa,ya=tf(a[0],a[1]);xb,yb=tf(b[0],b[1])
    line(xa,ya,x-2,ya,GRAY,.35);line(xb,yb,x-2,yb,GRAY,.35)
    line(x,ya,x,yb,INK,.4);arrow(x,ya,0,1);arrow(x,yb,0,-1)
    c.saveState();c.translate((x-1.2)*mm,((ya+yb)/2)*mm);c.rotate(90)
    c.setFillColor(colors.white);tw=c.stringWidth(text,"Helvetica",8)
    c.rect(-tw/2-3,-2,tw+6,10,fill=1,stroke=0)
    c.setFillColor(INK);c.setFont("Helvetica",8);c.drawCentredString(0,0,text);c.restoreState()

def get_lines(data):
    return [pt for k in ("visible","hidden") for path in data.get(k,[]) for pt in path]

def draw_view(data,rect,title,color=INK,frame=None,hidden=True,heading=True,tf=None):
    x,y,w,h=rect
    pts=get_lines(data)
    if not pts:return lambda a,b:(x,y)
    if frame is None:
        frame=[min(q[0] for q in pts),min(q[1] for q in pts),max(q[0] for q in pts),max(q[1] for q in pts)]
    if tf is None:
        s=min((w-4)/(frame[2]-frame[0]),(h-4)/(frame[3]-frame[1]))
        ox=x+w/2-(frame[0]+frame[2])*s/2;oy=y+h/2-(frame[1]+frame[3])*s/2
        tf=lambda a,b:(ox+a*s,oy+b*s)
    c.saveState();clip=c.beginPath();clip.rect(x*mm,y*mm,w*mm,h*mm);c.clipPath(clip,stroke=0)
    for kind in (["hidden","visible"] if hidden else ["visible"]):
        c.setStrokeColor(GRAY if kind=="hidden" else color)
        c.setLineWidth(.3 if kind=="hidden" else .7)
        c.setDash([2,2] if kind=="hidden" else [])
        for points in data.get(kind,[]):
            if len(points)<2:continue
            path=c.beginPath();xx,yy=tf(*points[0]);path.moveTo(xx*mm,yy*mm)
            for q in points[1:]:
                xx,yy=tf(*q);path.lineTo(xx*mm,yy*mm)
            c.drawPath(path)
    c.restoreState()
    if heading:label(x,y+h+4,title,10,bold=True)
    return tf

def small_table(x,y,width,rows,headers=None,row_h=7,font=8):
    widths=[width*.34,width*.66]
    for i,row in enumerate(([headers] if headers else [])+rows):
        if i==0 and headers:
            c.setFillColor(LIGHT);c.rect(x*mm,(y-row_h)*mm,width*mm,row_h*mm,stroke=0,fill=1)
        xx=x
        for j,cell in enumerate(row):
            label(xx+2,y-row_h+2,str(cell),font,bold=bool(i==0 and headers))
            xx+=widths[j]
        line(x,y-row_h,x+width,y-row_h,LIGHT,.4)
        y-=row_h
    return y

base=D["parts"]["EnclosureBase"]
lid=D["parts"]["EnclosureLid"]
plunger=D["parts"]["PTTPlunger"]
cup=D["parts"]["PTTStopCup"]
outer0=-p("Wall")-p("EdgeClearance")
outerx=p("PCBWidth")-outer0;outery=p("PCBLength")-outer0

sheet("01 / Base, mounting datums and connector access",1)
tf=draw_view(base["views"]["top"],(31,85,151,166),"BASE / TOP",heading=False)
label(31,262,"BASE / TOP",10,bold=True)
dimx(tf,(outer0,outery),(outerx,outery),258,fmt(p("OuterWidth")))
dimy(tf,(outer0,outer0),(outer0,outery),23,fmt(p("OuterLength")))
xx,yy=tf(0,0);line(xx,yy,xx+10,yy,BLUE);line(xx,yy,xx,yy+10,BLUE)
label(xx+11,yy-1,"X",8,BLUE);label(xx-1,yy+11,"Y",8,BLUE);label(xx+2,yy+2,"O",8,BLUE)
draw_view(base["views"]["front"],(222,190,173,51),"BASE / FRONT (-Y)")
draw_view(base["views"]["right"],(222,112,173,52),"BASE / RIGHT (+X)")
small_table(215,95,184,[
    ["Exterior base height",fmt(p("SeamHeight"))],
    ["Wall / floor",fmt(p("Wall"))+" / "+fmt(p("Floor"))],
    ["PCB support plane","Z "+fmt(p("PCBTop")-p("PCBThickness"))],
    ["Four mount axes","(4,4), (66,4), (4,86), (66,86)"],
    ["RX-M3x5x4 insert pilot","dia "+fmt(p("InsertBore"))+" x "+fmt(p("InsertPilotDepth"))+" deep"],
    ["USB notch","16 wide; X 15..31; Z 11.5.."+fmt(p("SeamHeight"))],
    ["Speaker / coax passages","dia 5 at Y66 / dia 4 at X43"],
],headers=["FEATURE","NOMINAL REQUIREMENT"],row_h=6.5)
wrapped(23,67,"Datum O: lower-left carrier PCB corner. Z0: outside base bottom. The enclosure origin is (-4.4,-4.4,0). USB faces +Y. Mount axes use the carrier datum, not the enclosure edge.",165,8,4)
wrapped(23,47,"For FDM: print floor down. USB opening reaches the seam to remove the former closed 16 mm bridge. Insert: ruthex RX-M3x5x4, actual length 4 mm in a 5 mm deep pilot. Qualify installation on the coupon.",165,8,4)
c.showPage()

sheet("02 / Lid, display window and microphone hole pattern",2)
tf=draw_view(lid["views"]["top"],(32,85,150,166),"LID / TOP (OUTSIDE)",heading=False)
label(32,262,"LID / TOP (OUTSIDE)",10,bold=True)
dimx(tf,(outer0,outery),(outerx,outery),258,fmt(p("OuterWidth")))
dimy(tf,(outer0,outer0),(outer0,outery),23,fmt(p("OuterLength")))
table_y=250
small_table(211,table_y,188,[
    ["OLED window",fmt(p("OLEDWidth"))+" x "+fmt(p("OLEDLength"))+"; center (23,58.05)"],
    ["PTT shaft guide","dia "+fmt(p("ButtonDiameter")+2*p("ButtonGap"))+"; (51,9)"],
    ["Main screw clearance","4 x dia "+fmt(p("ScrewClearance"))+"; mount axes per sheet 01"],
    ["Cup screw clearance","2 x dia "+fmt(p("PTTStopScrewHole"))+"; (42,9), (60,9)"],
    ["Reset / user access","2 x dia 3.2; X15.094 / 30.906; Y86"],
    ["Mic center","(54.5,30.5); 7 x dia "+fmt(M["microphone"]["hole_diameter_mm"])],
    ["Six outer mic holes","R "+fmt(M["microphone"]["pattern_radius_mm"])+" at 0,60,120,180,240,300 deg"],
    ["Lid thickness / lip depth",fmt(p("LidThickness"))+" / "+fmt(p("LipDepth"))],
    ["Lip wall / side clearance",fmt(p("LipThickness"))+" / "+fmt(p("FitGap"))],
],headers=["FEATURE","NOMINAL REQUIREMENT"],row_h=7)
draw_view(lid["views"]["front"],(219,96,173,60),"LID / FRONT (-Y), including PCB clamps")
label(29,66,"MICROPHONE PATTERN / XY CENTERS",9,bold=True)
cx,cy,s=56,48,3.5
R=M["microphone"]["pattern_radius_mm"];r=M["microphone"]["hole_diameter_mm"]/2
for dx,dy in [(0,0)]+[(R*math.cos(i*math.pi/3),R*math.sin(i*math.pi/3)) for i in range(6)]:
    c.setStrokeColor(INK);c.setLineWidth(.6);c.circle((cx+dx*s)*mm,(cy+dy*s)*mm,r*s*mm,stroke=1,fill=0)
line(cx-14,cy,cx+14,cy,GRAY,.3,[2,2]);line(cx,cy-14,cx,cy+14,GRAY,.3,[2,2])
wrapped(81,58,"One center hole plus six equally spaced holes. Center at (54.5,30.5). Openings pass through the lid; no grille membrane or acoustic seal is included.",101,8,4)
wrapped(216,76,"No rigid lid-to-screen contact is intended. The reduced lid height brings the opening close to the display while retaining nominal clearance. Verify the installed screen/header height before tightening the lid.",180,9,4.5)
wrapped(216,52,"Mic port is placed above the project model's upward-facing acoustic inlet. Sound path and ingress protection remain unqualified. Check that the purchased module's inlet matches the drawing.",180,8,4)
c.showPage()

sheet("03 / PTT plunger, stop cup and functional stack",3)
draw_view(plunger["views"]["front"],(31,127,94,119),"PLUNGER / FRONT (-Y)",color=ORANGE)
draw_view(plunger["views"]["top"],(139,161,77,77),"PLUNGER / TOP",color=ORANGE)
draw_view(cup["views"]["top"],(240,164,145,76),"STOP CUP / TOP",color=GREEN)
draw_view(cup["views"]["front"],(240,109,145,37),"STOP CUP / FRONT (-Y)",color=GREEN)
small_table(23,115,185,[
    ["Shaft / flange / contact foot","dia 8 / dia 12 / dia 4"],
    ["Flange thickness",fmt(p("ButtonFlangeThickness"))],
    ["Flange bottom in CAD pose","Z "+fmt(p("PTTStopContactZ")+p("SwitchReleaseGap")+p("PTTSwitchTravel"))],
    ["Button protrusion",fmt(p("ButtonProtrusion"))+" above outer lid"],
    ["Nominal guide radial gap",fmt(p("ButtonGap"))],
    ["Initial tip-to-switch gap",fmt(p("SwitchReleaseGap"))],
    ["Reference switch depression",fmt(p("PTTSwitchTravel"))],
    ["Total downstroke from CAD pose",fmt(p("SwitchReleaseGap")+p("PTTSwitchTravel"))],
],headers=["PLUNGER / MOTION","VALUE"],row_h=7)
small_table(229,91,171,[
    ["Outer / cavity / foot bore","dia 16.6 / 13.2 / 5.2"],
    ["Lugs / screw span","dia 6 / 18"],
    ["Stop shelf thickness",fmt(p("PTTStopShelf"))],
    ["Cup height",fmt(p("PTTStopHeight"))],
    ["Shelf plane / underside","Z "+fmt(p("PTTStopContactZ"))+" / "+fmt(p("PTTStopBottomZ"))],
    ["Fasteners","2 x M2 x 10 pan screws + M2 nuts"],
],headers=["STOP CUP","VALUE"],row_h=7)
wrapped(23,49,"Support the plunger's flange from its upper retention side when printing button-face down; keep the lower stop surface clean. Print the cup cavity up. Neither CAD travel nor a typical-switch comparison establishes safe overtravel for the owned switch.",185,8,4)
c.showPage()

sheet("04 / Assembled sections: actual assigned PCB and component models",4)
family_colors={"EnclosureBase":INK,"EnclosureLid":INK,"PTTPlunger":ORANGE,"PTTStopCup":GREEN,"PCB":GREEN,"Heltec":BLUE,"OLED":ORANGE,"Microphone":BLUE,"Amplifier":BLUE,"Switch":BLUE}
def section(title,key,rect,frame):
    allparts={name:rec.get("sections",{}) for name,rec in D["parts"].items()}
    allparts.update(D.get("electronics_sections",{}))
    tf=None
    for name,sections in allparts.items():
        if key not in sections:continue
        tf=draw_view(sections[key],rect,title,color=family_colors.get(name,GRAY),frame=frame,hidden=False,heading=False,tf=tf)
    label(rect[0],rect[1]+rect[3]+4,title,10,bold=True)
    return tf
section("A-A / DISPLAY CENTER, X23 (Y-Z)","display_x23",(21,166,183,85),[-5,0,95,28])
section("B-B / MIC CENTER, X54.5 (Y-Z)","microphone_x54_5",(221,166,178,85),[-5,0,95,28])
section("C-C / PTT CENTER, Y9 (X-Z), enlarged", "ptt_y9",(22,59,185,79),[36,4,66,27])
small_table(222,141,175,[
    ["PCB lower / upper planes","Z 6.4 / 8 nominal"],
    ["Inside lid / outside lid","Z "+fmt(p("SeamHeight"))+" / "+fmt(p("TotalHeight"))],
    ["Headroom above PCB",fmt(p("Headroom"))],
    ["Glass-to-lid-plane gap",str(M["display"]["glass_gap_mm"])+" nominal"],
    ["Highest OLED feature gap",str(M["display"]["highest_feature_gap_mm"])+" nominal"],
    ["PCB support gap below","4 above 2.4 floor"],
],headers=["STACK / CLEARANCE","VALUE (mm)"],row_h=7)
wrapped(222,84,"Sections use the actual assigned project meshes/B-reps. The Heltec body is manufacturer CAD; OLED/audio parts include visual approximations. Section profiles and nominal clearances are not physical measurements.",176,8,4)
wrapped(222,61,"Colors: dark = enclosure; green = PCB / stop cup; blue = electronics; orange = OLED / plunger. This sheet omits fastener sections for clarity; screw/nut dimensions and the load-path sequence are in the dossier.",176,8,4)
wrapped(22,43,"PTT shown in the native released/free-play pose. At 0.45 mm down, the flange contacts the shelf after 0.20 mm free motion and 0.25 mm modeled switch depression. Physical actuation/release must be tested.",185,8,4)
c.showPage();c.save()

# Dossier uses flowing text and tables to prevent fixed-position text overflow.
styles=getSampleStyleSheet()
styles.add(ParagraphStyle(name="TitleX",fontName="Helvetica-Bold",fontSize=24,leading=28,textColor=INK,spaceAfter=12))
styles.add(ParagraphStyle(name="H1X",fontName="Helvetica-Bold",fontSize=15,leading=19,textColor=BLUE,spaceBefore=8,spaceAfter=9))
styles.add(ParagraphStyle(name="BodyX",fontName="Helvetica",fontSize=9.5,leading=14,textColor=INK,spaceAfter=8))
styles.add(ParagraphStyle(name="SmallX",fontName="Helvetica",fontSize=8,leading=11,textColor=GRAY,spaceAfter=5))
styles.add(ParagraphStyle(name="CellX",fontName="Helvetica",fontSize=8,leading=11,textColor=INK))
story=[]
def para(text,style="BodyX"):
    story.append(Paragraph(text,styles[style]))
def heading(text):para(text,"H1X")
def table(rows,widths):
    data=[[Paragraph(str(cell),styles["CellX"]) for cell in row] for row in rows]
    t=Table(data,colWidths=[n*mm for n in widths],hAlign="LEFT",repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),LIGHT),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),("LINEBELOW",(0,0),(-1,-1),.3,LIGHT)]))
    story.append(t);story.append(Spacer(1,8))
def photo(path,caption,width=170,max_h=100):
    path=Path(path)
    if not path.exists():return
    from PIL import Image as PILImage
    with PILImage.open(path) as im:iw,ih=im.size
    h=width*ih/iw
    if h>max_h:width*=max_h/h;h=max_h
    story.append(Image(str(path),width=width*mm,height=h*mm,hAlign="LEFT"))
    para(caption+" Illustration colors distinguish parts; all four ordered PA12 parts are natural gray.","SmallX")

para("LoRa walkie-talkie<br/>Enclosure design dossier","TitleX")
para("C5 carrier | "+M["revision"]+" | "+M["date"],"SmallX")
para("<b>Release basis:</b> Parametric prototype and supplier handoff. Craftcloud unfilled MJF PA12 with standard depowdering is the primary process; critical-fit supplier review and installed-hardware acceptance remain required. CNC-shop handoff is neutral geometry and drawings, with toolpaths generated by the shop for its stock, tooling and fixtures.")
if M.get("views"):photo(M["views"][0]["path"],M["views"][0]["caption"],max_h=75)
heading("Design intent")
para("A USB-powered case for the 70 x 90 mm C5 carrier, Heltec ESP32/LoRa module with OLED, upward-facing microphone module, amplifier and PTT switch. Speaker and antenna leads leave the enclosure. There is no internal battery or speaker cavity.")
table([["Requirement","Design disposition"],
 ["Screen close to enclosure top",f"Headroom reduced from 16 to {fmt(p('Headroom'))} mm. Lid underside Z{fmt(p('SeamHeight'))}; nominal glass gap {M['display']['glass_gap_mm']} mm. Keep rigid plastic off the screen."],
 ["Direct speech access",f"Seven through-holes, dia {M['microphone']['hole_diameter_mm']} mm: one center plus six on R{M['microphone']['pattern_radius_mm']} mm over the modeled inlet."],
 ["Friendly to 3D printing","USB notch opens to seam; oriented parts and fit coupons support calibration. Print orientations and critical surfaces are listed below."],
 ["Documented fabrication","Native parametric CAD, neutral STEP, print meshes, technical drawings, PCB fabrication output and BOM with source/check records."]],[52,118])
story.append(PageBreak())
heading("01 / Dimensional design and fit")
table([["Stack or feature","Nominal model value","Interpretation"],
 ["Case footprint",f"{fmt(p('OuterWidth'))} x {fmt(p('OuterLength'))} mm","Same PCB mounting pattern and enclosure footprint."],
 ["Case height",f"{fmt(p('TotalHeight'))} mm; button +{fmt(p('ButtonProtrusion'))} mm","Case body reduced by 3 mm; hardware heads may project higher."],
 ["Carrier datum","PCB bottom Z6.4; top Z8","Imported PCB layers differ slightly from nominal stack thickness."],
 ["Display clearance",f"Glass-to-lid plane {M['display']['glass_gap_mm']} mm; highest feature {M['display']['highest_feature_gap_mm']} mm","Reference-model vertical gap. No hard contact with glass."],
 ["Lid registration",f"{fmt(p('LipDepth'))} deep; {fmt(p('LipThickness'))} wall; {fmt(p('FitGap'))} per-side gap","Calibrate with fit coupon before a full print."],
 ["PTT guide",f"8 mm shaft / {fmt(p('ButtonDiameter')+2*p('ButtonGap'))} mm bore",f"{fmt(p('ButtonGap'))} mm nominal radial clearance."],
 ["PTT stop","0.20 mm release gap + 0.25 mm reference switch travel","The switch part and permissible overtravel remain unconfirmed."],
 ["Insert / screw stack",f"{fmt(p('InsertBore'))} x {fmt(p('InsertPilotDepth'))} mm pilot; RX-M3x5x4 insert; M3 x 22 screws","Actual insert length 4 mm. Approx. 3.8 mm nominal engagement and 1.4 mm tip-relief clearance; verify installed stack."]],[43,61,66])
heading("Tolerance and acceptance policy")
para("Dimensions are nominal CAD design values. Craftcloud's general MJF tolerance has a 0.3 mm floor; that is larger than the 0.25 mm reference PTT switch travel. Request supplier review of the functional fits and stop stack, and use the supplied coupons before accepting full parts. Do not scale the entire model to tune one fit: that changes mounting pitch, display registration and PTT stop geometry.")
para("Before tightening the case, measure the installed carrier-to-display stack and confirm that the screen, frame screws and connectors clear the lid. Height variation in headers, solder and the visual OLED model can consume the available clearance. Adjust the headroom parameter and regenerate dependent parts if the owned assembly differs.")
heading("Microphone pathway")
para("The holes open the lid directly above the modeled acoustic inlet. The project model shows the microphone board's acoustic/solder face upward; the purchased module's inlet must be checked. There is no validated acoustic tube, foam seal, mesh, waterproof membrane or isolation chamber. Verify speech recording level and quality with the actual assembly.")
story.append(PageBreak())
heading("02 / PTT stop mechanism and hardware")
para("In the native CAD pose, the tip sits 0.20 mm above the representative switch. Pressing closes that gap, then depresses the switch by 0.25 mm before the flange meets the cup shelf. The complete nominal movement from the CAD pose is 0.45 mm. The animation's released position begins after closing the free gap, so its displayed active movement is 0.25 mm.")
table([["Load-path step","Role when the stop engages"],
 ["1. Plunger flange","Pushes downward on the cup shelf. The shelf reaction resists further plunger movement."],
 ["2. Stop cup","Transfers the shelf load to its mounting lugs, which bear down on the nuts."],
 ["3. Nuts","Transmit the downward load through their threads to the screws."],
 ["4. Screws","Carry tension between the nuts and heads. Thread engagement and fastener details are representative envelopes."],
 ["5. Lid","Supports the screw heads and passes the load through the enclosure and its attachments."]],[43,127])
para("No force magnitude, allowable stress, switch safe-overtravel or drop resistance has been certified. The 0.25 mm setting comes from comparable switch data, not a measured or uniquely identified installed switch. Test continuity and release gently; adjust or shim the stop if necessary.")
heading("Mechanical bill of materials")
bom=[
 ["Item","Qty","Specification / status"],
 ["Base, lid, plunger, stop cup","1 each","Craftcloud unfilled MJF PA12, standard depowdered; no smoothing/coating on functional interfaces."],
 ["Main enclosure screws","4","M3 x 22 socket-head, nominal length under head; check actual stack."],
 ["M3 heat-set inserts","4","ruthex RX-M3x5x4: OD 5 mm, actual length 4 mm. Design pilot dia 4.4 x 5 mm deep; top flush at Z6.4."],
 ["PTT cup screws","2","M2 x 10 pan-head; reviewed envelope dia 4 head x 1.72 maximum high."],
 ["PTT cup nuts","2","M2 full hex; 4 across flats x 1.6 high reference envelope."],
 ["Cable tie / lead protection","As required","Nominal 2.5 mm tie slots; select against the actual speaker and coax leads."],
 ["PCB and electronics","1 set","Use the separately generated PCB BOM and assembly documentation; no electronic redesign in this revision."],
]
table(bom,[47,20,103])
para("The combined BOM in the supplier handoff is the authoritative purchase/assembly list; this table summarizes mechanical requirements.","SmallX")
story.append(PageBreak())
heading("03 / 3D-print preparation")
para("Primary process: Craftcloud unfilled MJF PA12, standard depowdered finish. Leave the guide, stop faces, nut seats, insert pilots and locating lip unsmoothed and uncoated. Powder-bed support avoids FDM support scars under the plunger flange, but all cup cavities, small bores and microphone holes require complete powder removal and inspection. Supplier orientation and process planning remain the supplier's responsibility.")
para("General dimensional tolerance does not qualify the small PTT stroke. Obtain a supplier critical-feature review and test a prototype. A tighter manufacturing requirement must be explicitly agreed with the supplier rather than inferred from the model or mesh precision.")
heading("Optional FDM route")
para("PETG is a budget alternative when an FDM process is selected; the nozzle, profile and local fit compensation still need qualification. The table below is an FDM orientation guide, not an MJF build-layout requirement. No desktop printer was selected when this package was prepared.")
table([["Part","Bed orientation","Support and surface requirements"],
 ["Base","Outside floor down","The USB opening reaches the seam, removing its closed roof bridge. Inspect cable passages and tie slots in the slicer."],
 ["Lid","Outside face down","Lip and PCB clamps point upward. Keep aperture edges and the PTT guide free of elephant-foot and support residue."],
 ["PTT plunger","Button face down","Local support beneath the flange's upper retention side may be needed. Keep the lower stop face and contact tip clean and flat."],
 ["Stop cup","Flat bottom down; cavity up","Do not place support in the cavity or on the stop shelf. Verify shelf height, flatness and bore roundness."],
 ["Fit coupons","As supplied / labeled","Test sliding gap, lip fit and the actual insert before committing to full parts."]],[28,48,94])
heading("Slicer review before printing")
para("Confirm millimetres, correct part orientation, watertight single components and adequate bed clearance. Inspect every layer for floating regions, unsupported bridges, missing thin walls, closed microphone holes, support on functional surfaces and first-layer expansion. Use enough perimeters to preserve the 1.2 mm lip and insert ligament. Layer height and extrusion width must be selected for the printer; the small PTT travel needs particular dimensional care.")
para("Use the coupon results to set only the intended local compensation or CAD parameters. After printing, deburr passages and clean guides. The chosen insert has a 4 mm body; the 5 mm pilot includes axial allowance. The nominal boss ligament is 1.3 mm. Qualify the insert in the selected PA12 or PETG coupon, and install/cool inserts before adding electronics.")
heading("Printer-independent handoff")
para("The package provides geometry, orientation and inspection requirements. Machine-specific slicing profiles and G-code are intentionally pending the printer, nozzle and filament. A mesh that passes topology checks is not evidence of printer accuracy, material strength or reliable switch operation.")
para('Material references: <link href="https://craftcloud3d.com/en/material-guide/hp-mjf-nylon-pa12" color="#12658A">Craftcloud HP MJF PA12 guide</link>; <link href="https://help.prusa3d.com/article/petg_2059" color="#12658A">Prusa PETG guide</link>. Insert basis: <link href="https://www.ruthex.de/en/products/ruthex-gewindeeinsatz-m3-100-stuck-made-for-voron-rx-m3x5x4-messing-gewindebuchsen-fur-3d-druck" color="#12658A">ruthex RX-M3x5x4</link> and <link href="https://www.igo3d.com/mediafiles/Sonstiges/Ruthex/ruthex_Datenblatt_RX-Serie.pdf" color="#12658A">manufacturer RX-series datasheet</link>.',"SmallX")
story.append(PageBreak())
heading("04 / Assembly and engineering acceptance")
for i,text in enumerate([
 "Inspect printed or machined parts; remove burrs without changing stop height or the PCB seating planes. Verify the selected insert on a coupon.",
 "Install and cool the four M3 inserts before electronics. Check usable thread depth and the M3 x 22 screw stack; screws must not bottom out.",
 "Insert the plunger from inside the lid. Place the stop cup over its flange/contact foot, cavity toward the lid. Fit M2 x 10 screws from outside and nuts under the lugs; tighten gently while preserving free movement.",
 "Seat the carrier on the four supports. Check component clearance and solder-tail clearance. Route paired speaker leads and antenna coax with abrasion protection and strain relief; neither amplifier speaker terminal is ground.",
 "Lower the lid without tightening. Confirm OLED clearance and microphone inlet alignment, cable movement, and USB plug insertion/removal using the actual cable boot.",
 "Tighten the four main screws evenly and gently. The clamps must bear on intended PCB mounting regions without bending the board. Recheck display clearance and button freedom.",
 "Perform gentle switch continuity and reliable-return checks. Test speech pickup, USB power, audio, radio operation and thermal behavior with the assembled project. These are hardware acceptance tests, not CAD deductions."
],1):para(f"<b>{i}.</b> {text}")
table([["Gate","Acceptance evidence required"],
 ["Installed display stack","Measured glass/frame clearance with lid seated; no plastic or screw contact with glass."],
 ["Microphone path","Purchased inlet matches port location; speech recording test accepted."],
 ["PTT operation","Electrical actuation before hard stop, reliable release, no binding; owned-switch travel verified."],
 ["Insert and closure","Coupon fit accepted; inserts secure; screw tips clear; PCB remains flat."],
 ["Cable access","Actual USB cable seats fully; speaker/coax strain relief accepted; no sharp-edge contact."],
 ["Print/process","Actual selected process inspected; critical dimensions meet the local fit test."],
 ["Electronics","PCB source checks and physical-module registration accepted before fabrication/assembly release."]],[44,126])
story.append(PageBreak())
heading("05 / CNC-shop and PCB fabrication handoff")
para("For CNC quotation, use the final per-part STEP solids together with the technical drawings and any supplied DXF reference profiles. STEP is the controlling three-dimensional geometry. DXF profiles do not encode all depths, undercuts, fillets, tolerances or setups. The shop must select stock/material, fixturing, datum transfer, cutters, feeds, speeds, work offsets and postprocessor, and simulate toolpaths on its machine.")
para("Request DFM review of the thin lid lip, 1.3 mm insert-boss ligament, small microphone holes, blind insert pockets, cup cavity and flange. The RX-M3x5x4 heat-set-insert pilot is not automatically suitable for a machined press-fit or other insert process. The shop must propose material and insert installation appropriate to its process; a metal alternative also needs RF/antenna and electrical-insulation review.")
para("Unfilled POM-C is a candidate for shop review, separate from the primary PA12 MJF process. Deep thin walls and bosses, lateral USB/cable features and 3 x 1.2 mm tie slots may require multiple setups, small tooling and corner-radius changes. This package does not claim machinability as-is with arbitrary tools. Any shop-driven geometry change must preserve critical fit datums and be reviewed before manufacture.")
para('CNC material references: <link href="https://www.ensingerplastics.com/en/thermoplastic-materials/pom-acetal/pom-machining" color="#12658A">Ensinger POM machining guidance</link>; <link href="https://www.ensingerplastics.com/en-us/shapes/acetal-tecaform-ah-natural" color="#12658A">TECAFORM AH natural POM-C</link>.',"SmallX")
para("The carrier is a separate PCB fabrication item. Gerber copper/mask/silkscreen/outline data and Excellon plated/nonplated drill files belong to the PCB package, not the enclosure. The electronics source revision was not altered for the enclosure revision. Use the PCB package's fabrication summary, stackup, BOM and fresh checks to decide release status.")
story.append(PageBreak())
heading("06 / Verification record and provenance")
for note in M.get("verification_notes",[]):para(note)
heading("Source and change provenance")
para("The technical drawings were projected from the final saved FreeCAD B-rep. Curves are sampled at 0.025 mm deflection only for PDF line rendering. The native CAD and neutral solids retain the modeled surfaces. Imported PCB/component sections use the canonical detailed assembly and the +6.4814 mm mounting translation.")
para("CAD source: "+D["source"],"SmallX")
para("CAD SHA-256: "+D["source_sha256"],"SmallX")
for source in M.get("evidence_files",[]):para(source,"SmallX")
para("The electronic models include a manufacturer Heltec body, an authored OLED supplement, photo-derived audio modules and a representative switch. Their visual detail does not establish owned-unit dimensions. No ingress-protection, acoustic, RF, thermal, structural or production-process certification is claimed.","SmallX")
for item in M.get("views",[])[1:]:
    story.append(PageBreak());heading(item.get("title","Assembly view"));photo(item["path"],item["caption"],170,max_h=200)
    para("Presentation uses the final enclosure and assigned PCB/component models. This page is a fit illustration; use the technical drawings for nominal dimensions.","SmallX")

report=OUT/"Enclosure-Engineering-Dossier.pdf"
def footer(cv,doc):
    cv.setFillColor(GRAY);cv.setFont("Helvetica",8)
    cv.drawString(20*mm,13*mm,"LoRa C5 / "+M["revision"]+" / "+M["date"])
    cv.drawRightString(190*mm,13*mm,"Page "+str(doc.page))
    cv.setStrokeColor(LIGHT);cv.line(20*mm,18*mm,190*mm,18*mm)
SimpleDocTemplate(str(report),pagesize=A4,rightMargin=20*mm,leftMargin=20*mm,topMargin=20*mm,bottomMargin=23*mm,title="LoRa enclosure engineering dossier",author="LoRa Walkie-Talkies project").build(story,onFirstPage=footer,onLaterPages=footer)
print(json.dumps({"drawings":str(drawings),"dossier":str(report)},indent=2))
