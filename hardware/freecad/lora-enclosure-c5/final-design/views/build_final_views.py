"""Build presentation-only KiCad boards from the final CAD and actual PCB models.

No manufacturing CAD, PCB, or mesh export is written or changed.
"""
from pathlib import Path
import json,hashlib,math,re,uuid
import FreeCAD as App
import Part
root=Path(__file__).resolve().parents[1]
out=Path(__file__).resolve().parent
presentation=out/'presentation';models=presentation/'models';models.mkdir(parents=True,exist_ok=True)
cad=root/'cad/LoRa-Enclosure-C5-R1.FCStd'
source=root/'pcb-fabrication/source/heltec_v4_audio_carrier.kicad_pcb'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
doc=App.openDocument(str(cad))
def bb(s):
 b=s.BoundBox;return[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def box(x0,x1,y0,y1,z0,z1):return Part.makeBox(x1-x0,y1-y0,z1-z0,App.Vector(x0,y0,z0))
def screw_m2(x):
 z=24.6;r=(4+1.72**2)/(2*1.72)
 head=Part.makeSphere(r,App.Vector(x,9,z+1.72-r)).common(Part.makeCylinder(2,1.72,App.Vector(x,9,z)))
 shaft=Part.makeCylinder(1,10.05,App.Vector(x,9,z-10))
 cross=box(x-1.3,x+1.3,8.7,9.3,z+1.02,z+2).fuse(box(x-.3,x+.3,7.7,10.3,z+1.02,z+2))
 return shaft.fuse(head).cut(cross).removeSplitter()
def nut_m2(x):
 r=4/math.sqrt(3);z=15.55
 pts=[App.Vector(x+r*math.cos(math.radians(30+i*60)),9+r*math.sin(math.radians(30+i*60)),z) for i in range(6)]
 prism=Part.Face(Part.makePolygon(pts+[pts[0]])).extrude(App.Vector(0,0,1.6))
 bevel=Part.makeCone(2,r,.2,App.Vector(x,9,z)).fuse(Part.makeCylinder(r,1.2,App.Vector(x,9,z+.2))).fuse(Part.makeCone(r,2,.2,App.Vector(x,9,z+1.4)))
 return prism.common(bevel).cut(Part.makeCylinder(1,1.8,App.Vector(x,9,z-.1))).removeSplitter()
def screw_m3(x,y):
 shaft=Part.makeCylinder(1.5,22.05,App.Vector(x,y,2.6));head=Part.makeCylinder(2.75,3,App.Vector(x,y,24.6))
 r=2.5/math.sqrt(3)
 pts=[App.Vector(x+r*math.cos(math.pi*i/3),y+r*math.sin(math.pi*i/3),26.1) for i in range(6)]
 socket=Part.Face(Part.makePolygon(pts+[pts[0]])).extrude(App.Vector(0,0,1.6))
 return shaft.fuse(head).cut(socket).removeSplitter()
def insert_m3(x,y):return Part.makeCylinder(2.5,4,App.Vector(x,y,2.4)).cut(Part.makeCylinder(1.5,4,App.Vector(x,y,2.4)))
parts={n:doc.getObject(n).Shape.copy() for n in ('EnclosureBase','EnclosureLid','PTTPlunger','PTTStopCup')}
colors={'EnclosureBase':(.12,.19,.26),'EnclosureLid':(.72,.78,.82),'PTTPlunger':(1,.23,.025),'PTTStopCup':(.15,.65,.40)}
for i,x in enumerate((42,60),1):
 parts[f'M2Screw{i}']=screw_m2(x);parts[f'M2Nut{i}']=nut_m2(x)
 colors[f'M2Screw{i}']=colors[f'M2Nut{i}']=(.58,.61,.65)
for i,(x,y) in enumerate(((4,4),(66,4),(4,86),(66,86)),1):
 parts[f'M3Screw{i}']=screw_m3(x,y);parts[f'M3Insert{i}']=insert_m3(x,y)
 colors[f'M3Screw{i}']=(.56,.59,.64);colors[f'M3Insert{i}']=(.65,.46,.16)
for n,s in parts.items():assert s.isValid() and len(s.Solids)==1,(n,bb(s))
source_text=source.read_text(encoding='utf-8')
actual_models=[]
for path in re.findall(r'\(model\s+"([^"]+)"',source_text):
 local=source.parent/path.replace('${KIPRJMOD}/','')
 actual_models.append(dict(path=path,source=str(local),sha256=sha(local)))
assert len(actual_models)==6
# Portable relative paths from views/presentation to pcb-fabrication/source.
template=source_text.replace('${KIPRJMOD}/','${KIPRJMOD}/../../pcb-fabrication/source/')
manifest=dict(cad=str(cad),cad_sha256=sha(cad),source_board=str(source),source_pcb_sha256=sha(source),actual_electronics_models=actual_models,source_geometry='Four final native printed shapes and six original assigned KiCad component models; no hidden obsolete microphone import included.',hardware='Representative dimensional envelopes for two M2x10 pan screws, two M2 nuts, four M3x22 socket screws and four M3x5x4 inserts. Thread helices/knurl details are not modeled.',views=[])
front=box(-10,80,-10,9,1.2,45)
right=box(70,80,-10,82,1.2,45)
roof=box(6,64,-10,82,21,45)
keep=box(38,64,9,18,20.9,24.7)
housing_cut=front.fuse(right).fuse(roof.cut(keep)).removeSplitter()
def face_on(face,axis,value):
 b=face.BoundBox;return abs(getattr(b,axis+'Min')-value)<1e-6 and abs(getattr(b,axis+'Max')-value)<1e-6
def export_wrl(path,shape,color,planes=()):
 lines=['#VRML V2.0 utf8','# Presentation only; 1 VRML unit = 2.54 mm.']
 triangles=0;sectionfaces=0
 for f in shape.Faces:
  section=any(face_on(f,a,v) for a,v in planes);c=(.88,.65,.35) if section else color
  sectionfaces+=int(section);vs,fs=f.tessellate(.025);triangles+=len(fs)
  lines+=['Shape { appearance Appearance { material Material { diffuseColor %s specularColor .22 .22 .22 shininess .3 } } geometry IndexedFaceSet { solid TRUE creaseAngle .7 coord Coordinate { point ['%' '.join(map(str,c))]
  lines+=['%.9f %.9f %.9f,'%tuple(float(vv)/2.54 for vv in (v.x,v.y,v.z)) for v in vs]
  lines+=['] } coordIndex [']+['%d,%d,%d,-1,'%tuple(t) for t in fs]+['] } }']
 path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
 return dict(path=str(path),sha256=sha(path),triangles=triangles,colored_section_faces=sectionfaces)
for view in ('assembled','cutaway','exploded','top-open'):
 extras=[];items=[]
 for n,original in parts.items():
  if view=='top-open' and not (n=='EnclosureBase' or n.startswith('M3Insert')):continue
  shape=original.copy();explosion=0;planes=()
  if view=='cutaway':
   if n in ('EnclosureBase','EnclosureLid'):shape=shape.cut(housing_cut).removeSplitter();planes=(('Y',9),('X',70),('Z',1.2),('X',6),('X',64),('Y',82),('X',38),('Y',18))
   elif n in ('PTTPlunger','PTTStopCup') or n.startswith('M2'):shape=shape.cut(front).removeSplitter();planes=(('Y',9),)
   elif n.startswith('M3Screw') or n.startswith('M3Insert'):continue
  if view=='exploded':
   explosion={'EnclosureBase':-55,'EnclosureLid':130,'PTTPlunger':95,'PTTStopCup':75}.get(n,170 if n.startswith('M2Screw') else 60 if n.startswith('M2Nut') else 170 if n.startswith('M3Screw') else -40)
  assert shape.isValid() and len(shape.Solids)>0,(view,n)
  path=models/(view+'-'+n+'.wrl');meta=export_wrl(path,shape,colors[n],planes)
  ref='VIEW_'+n.upper();uid=uuid.uuid5(uuid.NAMESPACE_URL,view+ref)
  extras.append(f'''\n  (footprint "Presentation:{ref}" (layer "F.Cu")
    (uuid "{uid}") (at 100 190)
    (property "Reference" "{ref}" (at 0 0 0) (layer "F.Fab") (hide yes) (effects (font (size 1 1) (thickness 0.15))))
    (property "Value" "Presentation only" (at 0 0 0) (layer "F.Fab") (hide yes) (effects (font (size 1 1) (thickness 0.15))))
    (attr exclude_from_pos_files exclude_from_bom)
    (model "${{KIPRJMOD}}/models/{path.name}" (offset (xyz 0 0 {explosion-8})) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))
  )\n''')
  items.append(dict(name=n,assembled_bounds_mm=bb(original),shown_bounds_mm=bb(shape),explosion_mm=explosion,**meta))

 idx=template.rfind(')');board=presentation/(view+'.kicad_pcb')
 board.write_text(template[:idx]+''.join(extras)+template[idx:],encoding='utf-8')
 manifest['views'].append(dict(view=view,board=str(board),sha256=sha(board),models=items,sectioned=view=='cutaway'))
manifest['source_files_unchanged']=sha(cad)==manifest['cad_sha256'] and sha(source)==manifest['source_pcb_sha256']
(out/'view-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print(json.dumps(dict(views=[v['board'] for v in manifest['views']],actual_models=len(actual_models),unchanged=manifest['source_files_unchanged'])))
App.closeDocument(doc.Name)
