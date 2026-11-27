"""Predictive, unsaved recompute of headroom13 and 7-hole microphone grille."""
from pathlib import Path
import FreeCAD as App
import Part
import hashlib,json,math,time,sys
root=Path(__file__).resolve().parents[2]
out=Path(__file__).resolve().parent
src=Path(sys.argv[1]) if len(sys.argv)>1 else root/'fit-checked/LoRa-Enclosure-C5-Fit-Checked.FCStd'
final_mode=len(sys.argv)>1
report_path=out/('final-actual-clearance.json' if final_mode else 'headroom13-predictive-clearance.json')
step=root/'detailed-import/C5-detailed-assembly.step'
start=time.time()
def log(s): print(f'[{time.time()-start:.1f}s] {s}',flush=True)
def bbox(s):
 b=s.BoundBox
 return [b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def lower(a,b):return math.sqrt(sum(max(a[i]-b[i+3],b[i]-a[i+3],0)**2 for i in range(3)))
def comp(i):
 if i==0:return 'SW1'
 if i<=888:return 'Heltec'
 if i<=1066:return 'Carrier pads'
 if i==1067:return 'Carrier substrate'
 if i<=1714:return 'Microphone'
 if i<=2137:return 'Amplifier'
 if i<=2144:return 'R8'
 if i<=2810:return 'Heltec'
 if i<=2830:return 'OLED supplement'
 return 'Carrier surface'
doc=App.openDocument(str(src));p=doc.getObject('Parameters')
if not final_mode:
 p.set('B8','13.0');p.set('B37','9.5');p.set('B24','1.6');doc.recompute()
names=['EnclosureBase','EnclosureLid','PTTPlunger','PTTStopCup']
parts={n:doc.getObject(n).Shape.copy() for n in names}
grille=[]
for j in range(6):
 a=j*math.pi/3;x=54.5+2.6*math.cos(a);y=30.5+2.6*math.sin(a)
 grille.append(Part.makeCylinder(.8,3.8,App.Vector(x,y,20.9)))
if not final_mode:parts['EnclosureLid']=parts['EnclosureLid'].cut(Part.makeCompound(grille)).removeSplitter()
reference=App.newDocument('Headroom13ReferenceReadOnly');Part.insert(str(step),reference.Name)
sources=[]
for i,ob in enumerate(reference.Objects):
 if not hasattr(ob,'Shape') or ob.Shape.isNull():continue
 s=ob.Shape.copy();s.translate(App.Vector(0,0,6.4814));sources.append((i,comp(i),s,bbox(s)))
assert len(sources)==2949,len(sources)
log('Loaded candidate and actual corrected models')
for x in (42,60):
 parts[f'M2ScrewEnvelope{x}']=Part.makeCylinder(1,10,App.Vector(x,9,14.6)).fuse(Part.makeCylinder(2,1.72,App.Vector(x,9,24.6)))
 r=4/math.sqrt(3);z=15.55
 v=[App.Vector(x+r*math.cos(math.radians(30+j*60)),9+r*math.sin(math.radians(30+j*60)),z) for j in range(6)]
 parts[f'M2NutEnvelope{x}']=Part.Face(Part.makePolygon(v+[v[0]])).extrude(App.Vector(0,0,1.6)).cut(Part.makeCylinder(1,1.6,App.Vector(x,9,z)))
if final_mode:
 for x,y in ((4,4),(66,4),(4,86),(66,86)):
  parts[f'M3ScrewEnvelope{x}_{y}']=Part.makeCylinder(1.5,22,App.Vector(x,y,2.6)).fuse(Part.makeCylinder(2.75,3,App.Vector(x,y,24.6)))
  parts[f'M3InsertEnvelope{x}_{y}']=Part.makeCylinder(2.5,4,App.Vector(x,y,2.4)).cut(Part.makeCylinder(1.5,4,App.Vector(x,y,2.4)))
report=dict(source=str(src),source_sha256=hashlib.sha256(src.read_bytes()).hexdigest(),reference_step=str(step),reference_sha256=hashlib.sha256(step.read_bytes()).hexdigest(),scope='Read-only saved final CAD verification; no native document saved or exported.' if final_mode else 'Unsaved predictive recompute; no CAD document exported or source saved.',parameters={'Headroom':13.0,'USBHeight':9.5,'MicPort':1.6,'additional_mic_holes':6,'mic_ring_radius':2.6},parts={},errors=[])
for name,case in parts.items():
 log('Checking '+name)
 facebounds=[bbox(f) for f in case.Faces];mins={};penetrations=[];exact=0
 candidates=sorted([(min(lower(bb,fb) for fb in facebounds),i,c,s,bb) for i,c,s,bb in sources],key=lambda q:q[0])
 for bd,i,c,s,bb in candidates:
  if bd>max(1.00001,mins.get(c,{}).get('distance_mm',float('inf'))):continue
  try:
   d,pts,info=case.distToShape(s);exact+=1
   rec=dict(index=i,component=c,distance_mm=d,bounds_mm=bb)
   if c not in mins or d<mins[c]['distance_mm']:mins[c]=rec
   if d<1e-7:
    common=case.common(s);inside=[]
    for f in common.Faces:
     if any(sol.isInside(f.CenterOfMass,1e-7,False) for sol in case.Solids):inside.append([f.CenterOfMass.x,f.CenterOfMass.y,f.CenterOfMass.z])
    if (len(s.Solids)>0 and common.Volume>1e-7) or inside:
     penetrations.append(dict(**rec,common_volume_mm3=common.Volume,common_area_mm2=common.Area,strict_inside_face_samples=inside[:3]))
  except Exception as e:report['errors'].append(dict(part=name,index=i,error=repr(e)))
 report['parts'][name]=dict(valid=case.isValid(),closed=case.isClosed(),solids=len(case.Solids),bounds_mm=bbox(case),volume_mm3=case.Volume,minimum_by_component=mins,penetrations=penetrations,exact_evaluations=exact)
 report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
 log(name+' minima '+str({c:round(v['distance_mm'],6) for c,v in mins.items()})+' penetrations='+str(len(penetrations)))
report['ptt_travel']=[]
for down in (0,.2,.45,.46):
 plunger=parts['PTTPlunger'].copy();plunger.translate(App.Vector(0,0,-down))
 common=plunger.common(parts['PTTStopCup']);d,_,_=plunger.distToShape(parts['PTTStopCup'])
 report['ptt_travel'].append(dict(down_mm=down,cup_distance_mm=d,common_volume_mm3=common.Volume,common_area_mm2=common.Area))
report['housing_intersections']={}
for a,b in [('EnclosureBase','EnclosureLid'),('PTTPlunger','EnclosureLid'),('PTTStopCup','EnclosureLid')]:
 common=parts[a].common(parts[b]);report['housing_intersections'][a+'__'+b]=dict(volume_mm3=common.Volume,area_mm2=common.Area)
report['elapsed_seconds']=time.time()-start
report['source_file_unchanged']=hashlib.sha256(src.read_bytes()).hexdigest()==report['source_sha256']
report['ok']=not report['errors'] and all(v['valid'] and v['closed'] and v['solids']==1 and not v['penetrations'] for v in report['parts'].values()) and report['source_file_unchanged']
report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
log('Complete '+str(report_path))
App.closeDocument(doc.Name);App.closeDocument(reference.Name)
