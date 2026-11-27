"""Read-only predictive OLED bezel variants. No CAD document save/export."""
from pathlib import Path
import hashlib,json,math
import FreeCAD as A
import Part

root=Path(__file__).resolve().parents[1]
source=root.parent/'revision-r2-oled/cad/LoRa-Enclosure-C5-R2-OLED.FCStd'
refpath=root.parent/'detailed-import/C5-detailed-assembly.step'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
hashes={str(p):sha(p) for p in (source,refpath)}
d=A.openDocument(str(source));lid=d.getObject('EnclosureLid').Shape.copy()
r=A.newDocument('HalfMmReference');Part.insert(str(refpath),r.Name)
obs=[o for o in r.Objects if hasattr(o,'Shape') and not o.Shape.isNull()]
assert len(obs)==2949
def bounds(s):
 b=s.optimalBoundingBox(False,False)
 return [b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
models=[]
for ob in obs:
 s=ob.Shape.copy();s.translate(A.Vector(0,0,6.4814));models.append(s)
glass=models[2812];glass_z=glass.BoundBox.ZMax;drop=.5;bottom=21-drop
centers=[]
for i in range(2818,2822):
 b=models[i].BoundBox;centers.append([(b.XMin+b.XMax)/2,(b.YMin+b.YMax)/2])

def box(x,y,z,dx,dy,dz):return Part.makeBox(dx,dy,dz,A.Vector(x,y,z))
def ring(width,relief):
 outer=box(14.8-width,44.55-width,bottom,16.4+2*width,27+2*width,21.05-bottom)
 inner=box(14.8,44.55,bottom-.1,16.4,27,21.25-bottom)
 s=outer.cut(inner)
 if relief:
  s=s.cut(Part.makeCompound([Part.makeCylinder(relief,1,A.Vector(x,y,bottom-.1)) for x,y in centers]))
 return s.removeSplitter()
def pocket(floor):
 run=24.6-floor
 def w(extra,z):
  x0,y0=12.8-extra,42.55-extra;x1,y1=33.2+extra,73.55+extra
  return Part.makePolygon([A.Vector(x0,y0,z),A.Vector(x1,y0,z),A.Vector(x1,y1,z),A.Vector(x0,y1,z),A.Vector(x0,y0,z)])
 return Part.makeLoft([w(0,floor),w(run+.1,24.7)],True,True)

out={'source_hashes':hashes,'nominal_glass_top_z':glass_z,'local_underside_z':bottom,'drop_mm':drop,'gap_note':'Practical 0.50 mm datum drop produces 0.5012807412 mm to the approximate OLED glass; rounds to 0.50 mm.','screw_centers_xy':centers,'candidates':{}}
for name,width,relief,lower_top in [('plain_2mm',2,0,False),('relieved_2mm_r2p2',2,2.2,False),('narrow_0p8mm',.8,0,False),('relieved_lowered_face',2,2.2,True)]:
 print('Checking '+name,flush=True)
 addedring=ring(width,relief)
 base=lid.cut(pocket(22.6-drop)).removeSplitter() if lower_top else lid
 s=base.fuse(addedring).removeSplitter()
 actual_added=s.cut(lid)
 oled_results=[]
 for i in range(2811,2831):
  ob=models[i];distance,pts,_=s.distToShape(ob)
  oled_results.append({'index':i,'distance_mm':distance,'intersection_mm3':s.common(ob).Volume,'bounds_mm':bounds(ob)})
 # Analyze only local candidate addition vs every object: bounding-box distance
 # prefilter is conservative, followed by exact distances and intersections.
 near=[];ab=actual_added.BoundBox
 for i,ob in enumerate(models):
  bb=ob.BoundBox
  dd=math.sqrt(sum(max(0,a0-b1,b0-a1)**2 for a0,a1,b0,b1 in [(ab.XMin,ab.XMax,bb.XMin,bb.XMax),(ab.YMin,ab.YMax,bb.YMin,bb.YMax),(ab.ZMin,ab.ZMax,bb.ZMin,bb.ZMax)]))
  if dd<=1.0:
   near.append({'index':i,'distance_mm':actual_added.distToShape(ob)[0],'intersection_mm3':actual_added.common(ob).Volume})
 entries={n:actual_added.common(d.getObject(n).Shape).Volume for n in ('EnclosureBase','PTTPlunger','PTTStopCup')}
 out['candidates'][name]={'valid':s.isValid(),'closed':s.isClosed(),'solids':len(s.Solids),'volume_mm3':s.Volume,'added_volume_mm3':actual_added.Volume,'removed_volume_mm3':lid.cut(s).Volume,'glass_to_underside_reference_mm':bottom-glass_z,'glass_to_local_outer_face_mm':(22.6-drop if lower_top else 22.6)-glass_z,'rim_thickness_mm':(22.6-drop if lower_top else 22.6)-bottom,'minimum_corner_roof_thickness_mm':(22.6-drop if lower_top else 22.6)-21,'oled':oled_results,'nearest_oled_mm':min(v['distance_mm'] for v in oled_results),'screw_minimum_mm':min(v['distance_mm'] for v in oled_results if 2818<=v['index']<=2829),'frame_minimum_mm':oled_results[0]['distance_mm'],'glass_actual_minimum_mm':oled_results[1]['distance_mm'],'oled_intersection_mm3':sum(v['intersection_mm3'] for v in oled_results),'added_to_all_electronics_within_1mm':near,'other_printed_part_intersections_mm3':entries}
out['source_unchanged']=all(sha(Path(p))==h for p,h in hashes.items())
(root/'audit/half-mm-candidate-report.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:{kk:vv for kk,vv in v.items() if kk not in ('oled','added_to_all_electronics_within_1mm')} for k,v in out['candidates'].items()},indent=2))
A.closeDocument(d.Name);A.closeDocument(r.Name)
