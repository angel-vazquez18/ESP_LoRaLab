import json,math
from pathlib import Path
from PIL import Image,ImageDraw
p=Path(__file__).resolve().parent
j=json.loads((p/'jp2-connector-geometry.json').read_text())
vs=j['vertices'];ts=j['triangles']
im=Image.new('RGB',(1500,900),'white');d=ImageDraw.Draw(im)
def dot(a,b):return sum(x*y for x,y in zip(a,b))
views=[('Looking from source -X (assembled +Y)',(0,1,0),(0,0,1),(-1,0,0)),('Looking from source +X (assembled -Y)',(0,-1,0),(0,0,1),(1,0,0)),('Underside: source X horizontal, Y vertical',(1,0,0),(0,1,0),(0,0,-1)),('Underside isometric',(0.707,-0.707,0),(.408,.408,.816),(-.577,-.577,.577))]
for i,(title,u,v,w)in enumerate(views):
 ox=(i%2)*750;oy=(i//2)*450
 pts=[(dot(a,u),dot(a,v),dot(a,w)) for a in vs]
 xmin,xmax=min(a[0]for a in pts),max(a[0]for a in pts);ymin,ymax=min(a[1]for a in pts),max(a[1]for a in pts)
 sc=min(650/(xmax-xmin),350/(ymax-ymin));cx=(xmin+xmax)/2;cy=(ymin+ymax)/2
 for t in sorted(ts,key=lambda t:sum(pts[k][2]for k in t)/3):
  a,b,c=[vs[k]for k in t];ab=[b[k]-a[k]for k in range(3)];ac=[c[k]-a[k]for k in range(3)]
  n=[ab[1]*ac[2]-ab[2]*ac[1],ab[2]*ac[0]-ab[0]*ac[2],ab[0]*ac[1]-ab[1]*ac[0]]
  nn=math.sqrt(dot(n,n));shade=130+int(80*abs(dot(n,w))/nn) if nn>1e-12 else 180
  pp=[(ox+375+(pts[k][0]-cx)*sc,oy+235-(pts[k][1]-cy)*sc)for k in t]
  d.polygon(pp,fill=(shade,shade,min(255,shade+15)))
 d.text((ox+20,oy+15),title,fill='black')
 d.rectangle((ox+5,oy+5,ox+745,oy+445),outline='#999999')
im.save(p/'jp2-orientation.png')
