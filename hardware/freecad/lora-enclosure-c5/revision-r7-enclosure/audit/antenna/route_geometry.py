import FreeCAD as A,Part,math
def route(points,radius,cable_radius=.66):
 V=lambda p:A.Vector(*p)
 unit=lambda v:v/v.Length
 edges=[];last=V(points[0]);samples=[list(points[0])];turns=[]
 def sample(e):
  for p in e.discretize(Deflection=.025):samples.append([p.x,p.y,p.z])
 for i in range(1,len(points)-1):
  a,b,c=map(V,points[i-1:i+2]);u=unit(b-a);v=unit(c-b)
  angle=math.acos(max(-1,min(1,u.dot(v))));t=radius*math.tan(angle/2)
  p=b-u*t;q=b+v*t;n=unit(u.cross(v));center=p+n.cross(u)*radius;r0=p-center
  if(p-last).dot(b-a)<-1e-8:raise ValueError(('overlapping bends',i,t))
  if(p-last).Length>1e-8:line=Part.makeLine(last,p);edges.append(line);sample(line)
  mid=center+r0*math.cos(angle/2)+n.cross(r0)*math.sin(angle/2)
  arc=Part.Arc(p,mid,q).toShape();edges.append(arc);sample(arc);last=q
  turns.append({'waypoint':i,'radius_mm':radius,'angle_deg':math.degrees(angle),'trim_mm':t})
 line=Part.makeLine(last,V(points[-1]));edges.append(line);sample(line)
 wire=Part.Wire(edges);profile=Part.Wire([Part.makeCircle(cable_radius,V(points[0]),unit(V(points[1])-V(points[0])))])
 s=wire.makePipeShell([profile],True,False)
 assert s.isValid()and s.isClosed()
 return s,{'waypoints_mm':points,'centerline_mm':samples,'length_mm':wire.Length,'radius_mm':radius,'diameter_mm':2*cable_radius,'bends':turns}
