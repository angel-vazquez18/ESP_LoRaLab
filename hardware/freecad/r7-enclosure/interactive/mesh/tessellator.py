"""Read-only tessellation of current native solids and all assigned C5 components.

These display meshes are not replacement manufacturing exports.
"""
from pathlib import Path
from collections import defaultdict
import base64,gzip,hashlib,json,math,time
import FreeCAD as App,Part,MeshPart

DEFLECTION=.08;DECIMALS=3;START=time.time()

def log(text):print(f'[{time.time()-START:.1f}s] {text}',flush=True)
def bounds(s):
 b=s.optimalBoundingBox(False,False)
 return[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def box(bb):
 x0,y0,z0,x1,y1,z1=bb;return Part.makeBox(x1-x0,y1-y0,z1-z0,App.Vector(x0,y0,z0))
colors={'base':[.12,.20,.27],'lid':[.72,.79,.82],'plunger':[.98,.26,.035],
 'cup':[.16,.65,.40],'cover':[.30,.48,.62],'battery':[.13,.63,.39],
 'pad':[.34,.38,.40],'plug':[.82,.83,.79],'lead_positive':[.82,.06,.025],'lead_negative':[.08,.08,.08],
 'pcb_substrate':[.26,.08,.40],'pcb_pads':[.80,.64,.22],'pcb_markings':[.85,.85,.85],
 'heltec_board':[.08,.11,.13],'heltec_chips':[.16,.17,.18],'heltec_metal':[.65,.68,.70],
 'heltec_pins':[.82,.65,.20],'oled':[.035,.045,.05],'microphone':[.34,.27,.08],
 'amplifier':[.34,.12,.44],'switch':[.20,.22,.23],'resistor':[.70,.56,.34]}
labels={'base':'Enclosure base','lid':'Enclosure lid','plunger':'PTT plunger','cup':'PTT stop cup',
 'cover':'Removable battery cover','battery':'68 x 36 x 10 mm battery envelope','pad':'1 mm padding allowance',
 'plug':'Provisional battery plug','lead_positive':'Provisional positive lead','lead_negative':'Provisional negative lead',
 'pcb':'C5 carrier PCB','heltec':'Heltec V4 assembly','oled':'OLED / bracket supplement','microphone':'Round INMP441 module',
 'amplifier':'MAX98357A module','switch':'SW1 tactile switch','resistor':'R8 axial resistor'}
offsets={'base':-30,'lid':80,'plunger':55,'cup':35,'cover':-90,'battery':-60,'pad':-60}
parts=[];audit=[];dropped=0

def export_shapes(ident,semantic,shape_list,variant='full',color=None,source_kind='assigned-component',source_records=None):
 global dropped
 lookup={};positions=[];indices=[];raw_triangles=0;local_dropped=0
 bbs=[]
 for shape in shape_list:
  if shape.isNull():continue
  bbs.append(bounds(shape))
  mesh=MeshPart.meshFromShape(Shape=shape.cleaned(),LinearDeflection=DEFLECTION,AngularDeflection=.5,Relative=False)
  vs,ts=mesh.Topology
  mapped=[]
  for v in vs:
   point=tuple(round(float(c),DECIMALS)for c in(v.x,v.y,v.z))
   if point not in lookup:
    lookup[point]=len(positions)//3;positions.extend(point)
   mapped.append(lookup[point])
  for tri in ts:
   raw_triangles+=1
   a,b,c=[mapped[i]for i in tri]
   if a==b or a==c or b==c:local_dropped+=1;continue
   A=positions[3*a:3*a+3];B=positions[3*b:3*b+3];C=positions[3*c:3*c+3]
   u=[B[i]-A[i]for i in range(3)];v=[C[i]-A[i]for i in range(3)]
   cross=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
   if sum(x*x for x in cross)<1e-14:local_dropped+=1;continue
   indices.extend((a,b,c))
 if not indices:return
 # Remove unused quantized vertices caused by microscopic degenerate faces.
 used=sorted(set(indices));compact={old:i for i,old in enumerate(used)}
 positions=[v for old in used for v in positions[3*old:3*old+3]]
 indices=[compact[i]for i in indices]
 bb=[min(positions[j::3])for j in range(3)]+[max(positions[j::3])for j in range(3)]
 original=[min(b[j]for b in bbs)for j in range(3)]+[max(b[j+3]for b in bbs)for j in range(3)]
 inside=all(bb[i]>=original[i]-.001 and bb[i+3]<=original[i+3]+.001 for i in range(3))
 assert inside,(ident,bb,original)
 group='enclosure'if semantic in('base','lid','cover','plunger','cup')else'reference'if source_kind=='reference'else'electronics'
 parts.append(dict(id=ident,part=semantic,group=group,variant=variant,label=labels[semantic],positions=positions,indices=indices,
                   color=color or colors.get(ident,colors.get(semantic)),bounds=bb,sourceKind=source_kind,
                   explodeZ=offsets.get(semantic,0)if variant=='full'else 0))
 audit.append(dict(id=ident,part=semantic,variant=variant,source_indices=source_records,source_kind=source_kind,
                   source_shapes=len(shape_list),mesh_vertices=len(positions)//3,mesh_triangles=len(indices)//3,
                   source_bounds_mm=original,mesh_bounds_mm=bb,within_source_bounds_plus_quantization=inside,
                   quantization_degenerate_triangles_omitted=local_dropped))
 dropped+=local_dropped
 log(f'{ident}: {len(indices)//3} triangles / {len(positions)//3} vertices')
