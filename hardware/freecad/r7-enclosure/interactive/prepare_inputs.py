"""Inspect current R7 native and retained reference inputs without writing files.

Run with FreeCAD's Python. This checks readable shapes and global placement; it
does not regenerate the viewer or certify mechanical clearance after CAD edits.
"""
from pathlib import Path
import hashlib,json
import FreeCAD as App,Part
ROOT=Path(__file__).resolve().parent
NATIVE=ROOT.parent/'cad/LoRa-Enclosure-C5-R7-Reinforced.FCStd'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def bounds(shape):
 b=shape.BoundBox
 return [b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def global_shape(obj):
 shape=obj.Shape.copy()
 shape.Placement=obj.getGlobalPlacement()
 return shape
sources={NATIVE.relative_to(ROOT.parent).as_posix():sha(NATIVE)}
build=json.loads((ROOT/'BUILD-VALIDATION.json').read_text())
assert build['saved_native_verified'] and sources[NATIVE.relative_to(ROOT.parent).as_posix()]==build['native_sha256'],'Native differs from the approved viewer; rebuild and revalidate before release'
document=App.openDocument(str(NATIVE))
try:
 components=[obj for obj in document.Objects if obj.Name.startswith('C5_detailed_assembly') and hasattr(obj,'Shape') and not obj.Shape.isNull()]
 assert len(components)==2949, len(components)
 component_bounds=[]
 for index,obj in enumerate(components):
  expected='C5_detailed_assembly'+(f'{index:03d}' if index else '')
  assert obj.Name==expected,(index,obj.Name)
  shape=global_shape(obj)
  assert shape.isValid(),obj.Name
  component_bounds.append(bounds(shape))
 native_parts={}
 for name in ['EnclosureBase','EnclosureLid','BatteryCover','PTTPlunger','PTTStopCup','SpeakerRetainer','SMAKey','ReferenceBatteryEnvelope']:
  obj=document.getObject(name);assert obj is not None,name
  shape=global_shape(obj);assert shape.isValid() and shape.isClosed(),name
  native_parts[name]={'bounds_mm':bounds(shape),'volume_mm3':shape.Volume}
finally:
 App.closeDocument(document.Name)
references={}
manifest=json.loads((ROOT/'PORTABLE-REFERENCES.json').read_text())
for ident,record in manifest['references'].items():
 path=(ROOT/record['path']).resolve()
 assert path.is_relative_to(ROOT.resolve()),path
 digest=sha(path);assert digest==record['sha256'],path
 sources[path.relative_to(ROOT.parent).as_posix()]=digest
 if path.suffix=='.brep':
  shape=Part.Shape();shape.read(str(path));assert shape.isValid(),ident
  references[ident]={'bounds_mm':bounds(shape),'sha256':digest}
 else:
  references[ident]={'data':json.loads(path.read_text()),'sha256':digest}
for name in ['CoaxR10Final','ReferenceCoaxTie']:
 path=ROOT.parent/'audit/antenna'/f'{name}.brep'
 shape=Part.Shape();shape.read(str(path));assert shape.isValid(),name
 digest=sha(path);sources[path.relative_to(ROOT.parent).as_posix()]=digest
 references[name]={'bounds_mm':bounds(shape),'sha256':digest}
assert all(sha(ROOT.parent/path)==digest for path,digest in sources.items()),'Inputs changed during inspection'
overall=[min(bb[i] for bb in component_bounds) for i in range(3)]+[max(bb[i] for bb in component_bounds) for i in range(3,6)]
print(json.dumps({'ok':True,'writes':False,'native_sha256':build['native_sha256'],'actual_component_count':len(components),'global_placement_applied':True,'first_component_bounds_mm':component_bounds[0],'all_components_bounds_mm':overall,'native_parts':native_parts,'retained_references':references,'source_hashes':sources},indent=2))
