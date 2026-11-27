"""Small ReportLab drawing helpers for the dimensioned R6 design sheet."""
import math
from reportlab.lib.colors import HexColor

INK=HexColor('#18272e')
MUTED=HexColor('#58666d')
ACCENT=HexColor('#006c82')
PALE=HexColor('#edf4f6')
SPEAKER=HexColor('#d7e8d9')
METAL=HexColor('#dce1e4')
GASKET=HexColor('#e6d9bc')
WARN=HexColor('#874a00')
WHITE=HexColor('#ffffff')

class Drawing:
    def __init__(self,canvas):self.c=canvas
    def text(self,x,y,s,size=9,bold=False,color=INK,align='left'):
        c=self.c;c.setFillColor(color);c.setFont('Helvetica-Bold' if bold else 'Helvetica',size)
        {'left':c.drawString,'center':c.drawCentredString,'right':c.drawRightString}[align](x,y,s)
    def wrap(self,x,y,s,width,size=9,leading=12,color=INK,bold=False):
        words=s.split();line=''
        for word in words:
            test=(line+' '+word).strip()
            if self.c.stringWidth(test,'Helvetica-Bold' if bold else 'Helvetica',size)>width and line:
                self.text(x,y,line,size,bold,color);y-=leading;line=word
            else:line=test
        if line:self.text(x,y,line,size,bold,color);y-=leading
        return y
    def line(self,a,b,color=INK,width=.7,dash=None):
        c=self.c;c.setStrokeColor(color);c.setLineWidth(width);c.setDash(dash or []);c.line(*a,*b);c.setDash([])
    def poly(self,pts,fill=None,stroke=INK,width=.7,closed=True):
        c=self.c;p=c.beginPath();p.moveTo(*pts[0])
        for q in pts[1:]:p.lineTo(*q)
        if closed:p.close()
        c.setStrokeColor(stroke);c.setLineWidth(width)
        if fill:c.setFillColor(fill)
        c.drawPath(p,fill=bool(fill),stroke=1)
    def rect(self,x,y,w,h,fill=None,stroke=INK,width=.7):
        self.poly([(x,y),(x+w,y),(x+w,y+h),(x,y+h)],fill,stroke,width)
    def circle(self,x,y,r,fill=None,stroke=INK,width=.7):
        c=self.c;c.setStrokeColor(stroke);c.setLineWidth(width)
        if fill:c.setFillColor(fill)
        c.circle(x,y,r,fill=bool(fill),stroke=1)
    def head(self,tip,back,size=4):
        n=math.hypot(*back);u=[v/n for v in back];v=[-u[1],u[0]]
        self.poly([tip,(tip[0]+u[0]*size+v[0]*size*.35,tip[1]+u[1]*size+v[1]*size*.35),(tip[0]+u[0]*size-v[0]*size*.35,tip[1]+u[1]*size-v[1]*size*.35)],INK,INK,.3)
    def dim_h(self,x1,x2,y,label,witness_y=None):
        if witness_y is not None:
            for x in (x1,x2):self.line((x,witness_y),(x,y+3 if y>witness_y else y-3),MUTED,.45)
        self.line((x1,y),(x2,y),INK,.55);self.head((x1,y),(1,0));self.head((x2,y),(-1,0));self.text((x1+x2)/2,y+5,label,9,align='center')
    def dim_v(self,y1,y2,x,label,witness_x=None):
        if witness_x is not None:
            for y in (y1,y2):self.line((witness_x,y),(x+3 if x>witness_x else x-3,y),MUTED,.45)
        self.line((x,y1),(x,y2),INK,.55);self.head((x,y1),(0,1));self.head((x,y2),(0,-1))
        self.c.saveState();self.c.translate(x+10,(y1+y2)/2);self.c.rotate(90);self.text(0,0,label,9,align='center');self.c.restoreState()
    def leader(self,points,label,x,y,width=160):
        for a,b in zip(points,points[1:]):self.line(a,b,ACCENT,.7)
        self.head(points[0],(points[1][0]-points[0][0],points[1][1]-points[0][1]),3.5)
        return self.wrap(x,y,label,width,8.5,11,ACCENT)
    def hatch_rect(self,x,y,w,h):
        self.rect(x,y,w,h,PALE)
        c=self.c;c.saveState();p=c.beginPath();p.rect(x,y,w,h);c.clipPath(p,stroke=0)
        for dx in range(-int(h)-10,int(w)+10,7):self.line((x+dx,y),(x+dx+h,y+h),HexColor('#bfd2d8'),.45)
        c.restoreState()
    def title(self,x,y,label):self.text(x,y,label,11,True,ACCENT)
