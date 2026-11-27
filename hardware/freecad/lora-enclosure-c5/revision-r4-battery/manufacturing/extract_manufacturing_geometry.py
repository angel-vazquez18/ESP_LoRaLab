"""Read native R4, export shop STEP solids and exact projected drawing curves.

Run with FreeCAD bundled Python. Native FCStd is never saved or modified.
"""
from pathlib import Path
import json, hashlib
import FreeCAD as App, Part, TechDraw

here=Path(__file__).resolve().parent
native=here.parent/'cad/LoRa-Enclosure-C5-R4-Battery.FCStd'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
before=sha(native)
doc=App.openDocument(str(native))
steps=here/'cnc-step';steps.mkdir(parents=True,exist_ok=True)
out={'source':str(native),'source_sha256':before,'parts':{},'parameters':{},
     'method':'FreeCAD TechDraw hidden-line projection of saved B-rep; curves sampled at 0.025 mm deflection.',
     'datum':'Carrier lower-left XY=(0,0), USB toward +Y; original floor exterior Z0. R4 rear cover exterior Z-16.4.'}
sheet=doc.getObject('Parameters')
for row in range(1,181):
 try:
  label,value=sheet.get('A'+str(row)),sheet.get('B'+str(row))
  if label:out['parameters'][label]={'row':row,'value':str(value),'formula':sheet.getContents('B'+str(row))}
 except Exception:pass

def bounds(s):
 b=s.optimalBoundingBox(False,False)
 return [b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def points(e,d):
 if e.Length<1e-7:return []
 pts=e.discretize(Deflection=.025)
 def orient(p):
  if d==(0,-1,0):return [p.y,-p.x]
  if d==(1,0,0):return [-p.y,p.x]
  return[p.x,p.y]
 return [[round(v,6) for v in orient(p)] for p in pts]
def project(s,d):
 g=TechDraw.projectEx(s,App.Vector(*d))
 return {'visible':[v for group in g[:5] for e in group.Edges if (v:=points(e,d))],
         'hidden':[v for group in g[5:] for e in group.Edges if (v:=points(e,d))]}

for name,slug in [('EnclosureBase','enclosure-base'),('BatteryCover','battery-cover'),('EnclosureLid','enclosure-lid'),('PTTPlunger','ptt-plunger'),('PTTStopCup','ptt-stop-cup')]:
 s=doc.getObject(name).Shape
 assert s.isValid() and s.isClosed() and len(s.Solids)==1
 file=steps/('C5-R4-'+slug+'.step')
 s.exportStep(str(file))
 readback=Part.Shape();readback.read(str(file))
 delta=s.cut(readback).Volume+readback.cut(s).Volume
 assert readback.isValid() and len(readback.Solids)==1 and delta<1e-5
 rec={'label':doc.getObject(name).Label,'bounds_mm':bounds(s),'volume_mm3':s.Volume,
      'step_file':file.relative_to(here).as_posix(),'step_sha256':sha(file),'step_symmetric_difference_mm3':delta,'views':{},'sections':{}}
 for v,d in [('top',(0,0,1)),('front',(0,-1,0)),('right',(1,0,0))]:
  rec['views'][v]=project(s,d)
 for title,normal,offset,d in [('battery_x27_2',(1,0,0),27.2,(1,0,0)),('ptt_y9',(0,1,0),9,(0,-1,0))]:
  wires=s.slice(App.Vector(*normal),offset)
  if wires:rec['sections'][title]=project(Part.makeCompound(wires),d)
 out['parts'][name]=rec
 print(name,'STEP verified and views extracted',flush=True)

out['source_unchanged']=sha(native)==before
assert out['source_unchanged']
(here/'manufacturing-geometry.json').write_text(json.dumps(out,indent=2)+'\n')
App.closeDocument(doc.Name)
print('Five STEP solids validated; source unchanged')
