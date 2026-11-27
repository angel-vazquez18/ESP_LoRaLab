import json,pathlib
import FreeCAD as App
import Part
root=pathlib.Path(__file__).resolve().parent
doc=App.openDocument(str(root.parent/'cutaway-view'/'LoRa-Enclosure-C5-Assembled-Cutaway.FCStd'))
names=['PTTPlunger','PTTStopCup','PTTLidSection','PTTFastenerLeftScrew','PTTFastenerRightScrew','PTTFastenerLeftNut','PTTFastenerRightNut','PTTDetailPCB','PTTDetailFloor','PTTDetailSwitchSource']
def bb(s):
 b=s.BoundBox;return[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
parts={n:{'bbox':bb(doc.getObject(n).Shape),'placement':str(doc.getObject(n).Placement),'global':str(doc.getObject(n).getGlobalPlacement())} for n in names}
s=doc.getObject('PTTDetailSwitchSource').Shape.copy()
box=Part.makeBox(40,40,40,App.Vector(30,-10,12.5));upper=s.common(box)
sections={str(z):[{'bbox':bb(w),'edges':len(w.Edges)} for w in s.slice(App.Vector(0,0,1),z)] for z in [11.5,12,12.25,12.4999,12.5001,13,14,15,15.7,15.8,15.9,15.9999]}
faces=[{'bbox':bb(f),'surface':str(type(f.Surface)),'radius':getattr(f.Surface,'Radius',None),'area':f.Area} for f in upper.Faces]
data={'parts':parts,'upper':{'bbox':bb(upper),'solids':len(upper.Solids),'valid':upper.isValid(),'faces':faces},'horizontal_sections':sections}
(root/'switch-stem-probe.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
print(json.dumps(data,indent=2))
