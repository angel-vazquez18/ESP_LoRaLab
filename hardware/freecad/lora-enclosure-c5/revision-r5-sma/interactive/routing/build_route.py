from pathlib import Path
import FreeCAD as A, Part, MeshPart, json, math, hashlib, time, runpy, re
OUT=Path(__file__).resolve().parent;RADIUS=4.8;CABLE_RADIUS=.66
if not (OUT/'component-0.brep').is_file():runpy.run_path(str(OUT/'probe_route.py'),run_name='__main__')
V=lambda p:A.Vector(*p)
points=[[47,82,14],[47,76.3,14],[62,76.3,20],[62,87.3,19.2],[37.5,87.3,20],[37.5,31,17.8],[23.00004,31,16.8],[23.00004,39.14914,16.8]]
def unit(p):return p/p.Length
def sample_line(a,b):
 return [a+(b-a)*i/max(1,math.ceil((b-a).Length/.35)) for i in range(1,max(1,math.ceil((b-a).Length/.35))+1)]
def fillet(a,b,c,r):
 u=unit(b-a);v=unit(c-b);angle=math.acos(max(-1,min(1,u.dot(v))));t=r*math.tan(angle/2)
 p=b-u*t;q=b+v*t;n=unit(u.cross(v));center=p+n.cross(u)*r
 r0=p-center;theta=angle
 def at(s):return center+r0*math.cos(s)+n.cross(r0)*math.sin(s)
 middle=at(theta/2);arc=Part.Arc(p,middle,q).toShape()
 samples=[at(theta*j/max(2,math.ceil(r*theta/.35)))for j in range(1,max(2,math.ceil(r*theta/.35))+1)]
 return p,q,arc,samples,t,angle
edges=[];samples=[V(points[0])];last=V(points[0]);turns=[];trims=[]
for i in range(1,len(points)-1):
 p,q,arc,pts,t,angle=fillet(V(points[i-1]),V(points[i]),V(points[i+1]),RADIUS)
 if (p-last).dot(V(points[i])-V(points[i-1]))<0:raise ValueError(('overlapping bends',i,t))
 edges.append(Part.makeLine(last,p));samples.extend(sample_line(last,p));edges.append(arc);samples.extend(pts);last=q
 turns.append({'waypoint':i,'centerline_radius_mm':RADIUS,'inside_radius_mm':RADIUS-CABLE_RADIUS,'angle_deg':math.degrees(angle),'trim_mm':t})
edges.append(Part.makeLine(last,V(points[-1])));samples.extend(sample_line(last,V(points[-1])))
wire=Part.Wire(edges);profile=Part.Wire([Part.makeCircle(CABLE_RADIUS,V(points[0]),A.Vector(0,-1,0))]);coax=wire.makePipeShell([profile],True,False)
assert coax.isValid() and coax.isClosed()
plug=Part.makeCylinder(1.35,1.5,A.Vector(23.00004,39.14914,15.81875))
shapes={'coax':coax,'coax_plug':plug}
def bb(s):
 b=s.BoundBox;return[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def overlap(a,b):return all(a[i]<=b[i+3]+1e-7 and a[i+3]+1e-7>=b[i]for i in range(3))
def load(p):s=Part.Shape();s.read(str(p));return s
components=json.loads((OUT/'component-bounds.json').read_text());collisions={};checks={};native_checks={};minimums={}
for ident,s in shapes.items():
 b=bb(s);hits=[];n=0
 for c in components:
  if not overlap(b,c['bb']):continue
  other=load(OUT/f"component-{c['i']}.brep");n+=1;vol=s.common(other).Volume
  if vol>1e-6:hits.append({'index':c['i'],'label':c['label'],'volume_mm3':vol,'bounds':c['bb']})
 checks[ident]={'source_objects_scanned':len(components),'exact_booleans':n};collisions[ident]=hits;native_checks[ident]={}
 for name in ['EnclosureBase','EnclosureLid','PTTPlunger','PTTStopCup','BatteryCover','ReferenceBatteryEnvelope','ReferenceSMARearBody']:
  other=load(OUT/f'{name}.brep');vol=s.common(other).Volume
  distance=s.distToShape(other)[0];native_checks[ident][name]={'intersection_mm3':vol,'distance_mm':distance}
  print(ident,name,'volume',vol,'distance',distance,flush=True)
  if vol>1e-6:hits.append({'native':name,'volume_mm3':vol})
 print('collisions',ident,hits,flush=True)
 def lower_bound(a,b):return math.sqrt(sum(max(a[i]-b[i+3],b[i]-a[i+3],0)**2 for i in range(3)))
 ordered=sorted((lower_bound(bb(s),c['bb']),c['i'])for c in components);best=float('inf');nearest=None;count=0
 for lower,i in ordered:
  if lower>best+1e-7:break
  other=load(OUT/f'component-{i}.brep');dist=s.distToShape(other)[0];count+=1
  if dist<best:best=dist;nearest=i
 minimums[ident]={'distance_mm':best,'component_index':nearest,'exact_distance_checks':count,'all_source_bounds_scanned':len(components),'method':'Sorted conservative AABB lower bounds, exact distances until all remaining lower bounds exceed minimum.'}
 print('nearest',ident,minimums[ident],flush=True)
sources={str(OUT.parents[1]/'cad/LoRa-Enclosure-C5-R5-SMA.FCStd'):'b2c616f78a5f2515217f5c06ec199f38b0106067289fdab60a29e0879d1d9678',str(OUT.parents[2]/'detailed-import/C5-detailed-assembly.step'):'65143fecb376c40ac75cf7b3b2ffdf477c9ff656706a80c1fda63717d1041a19'}
unchanged={p:hashlib.sha256(Path(p).read_bytes()).hexdigest()==sha for p,sha in sources.items()};assert all(unchanged.values())
report={'ok':not any(collisions.values()),'centerline_mm':[[p.x,p.y,p.z]for p in samples],'waypoints_mm':points,'centerline_length_mm':wire.Length,'diameter_mm':2*CABLE_RADIUS,'bends':turns,'checks':checks,'collisions':collisions,'native_clearances':native_checks,'component_minimums':minimums,'source_hashes':sources,'source_files_unchanged':unchanged,'basis':'Provisional illustrative 1.32 mm OD cable, centerline bend R4.8 mm; actual kit cable OD, usable length and minimum bend radius unverified. Not a claim that the pictured 169 mm pigtail equals this centerline length.','endpoint_mating_face_mm':[23.00004,39.14914,15.81875],'mount_contact':'Coax start plane Y82 coincides with the rear face of the representative SMA body. The small illustrative IPEX plug rests on the assigned LoRa socket, not the separate underside 2.4 GHz connector.','tie_anchor_note':'Coax passes above/near the slot anchor. Tie geometry and exact retention arrangement are not represented; fit with a loose tie and confirm strain relief on real hardware.','safety_limit':'Geometric clearance study of a proposed route only; does not validate real cable flexibility, connector strain, RF performance or the actual kit lead length.'}
(OUT/'ROUTE-VALIDATION.json').write_text(json.dumps(report,indent=2))
parts=[]
for ident,s in shapes.items():
 s.exportBrep(str(OUT/f'{ident}.brep'));m=MeshPart.meshFromShape(Shape=s,LinearDeflection=.07,AngularDeflection=.4,Relative=False);vs,ts=m.Topology
 positions=[round(float(c),3)for v in vs for c in(v.x,v.y,v.z)];indices=[i for t in ts for i in t]
 b=[min(positions[j::3])for j in range(3)]+[max(positions[j::3])for j in range(3)]
 parts.append({'id':ident,'part':ident,'group':'reference','variant':'full','label':'Provisional coax route'if ident=='coax'else'Provisional LoRa IPEX plug','positions':positions,'indices':indices,'color':[.08,.09,.10]if ident=='coax'else[.78,.65,.3],'bounds':b,'sourceKind':'reference','explodeZ':-30})
(OUT/'route-mesh-data.json').write_text(json.dumps({'schema':1,'units':'mm','parts':parts},separators=(',',':')))
print('Route length',wire.Length,'triangles',sum(len(p['indices'])//3 for p in parts),flush=True)
# These are reproducible read-only audit caches, not source or delivery CAD.
native_cache=['EnclosureBase','EnclosureLid','PTTPlunger','PTTStopCup','BatteryCover','ReferenceBatteryEnvelope','ReferenceSMARearBody']
cache_paths=[p for p in OUT.glob('component-*.brep')if re.fullmatch(r'component-\d+\.brep',p.name)]+[OUT/f'{n}.brep'for n in native_cache]
for p in cache_paths:
 if p.resolve().parent!=OUT.resolve():raise RuntimeError('Cache path escaped routing output directory')
 if p.is_file():p.unlink()
print('Removed',len(cache_paths),'reproducible BREP cache files; retained final coax/plug BREPs.',flush=True)
