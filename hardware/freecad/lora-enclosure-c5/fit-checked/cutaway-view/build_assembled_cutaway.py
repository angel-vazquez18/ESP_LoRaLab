"""Assembled, sectioned CAD presentation. Manufacturing data are read-only."""
from pathlib import Path
import hashlib,json,math,re,uuid
import FreeCAD as App
import Part

ROOT=Path(__file__).resolve().parent
FIT=ROOT.parent
SOURCE_DIR=FIT.parent/'detailed-import'/'source-project'
SOURCE=SOURCE_DIR/'heltec_v4_audio_carrier.kicad_pcb'
DEST=SOURCE_DIR/'fit-checked-assembled-cutaway.kicad_pcb'
MODELS=SOURCE_DIR/'models'/'fit-checked-cutaway'
MODELS.mkdir(parents=True,exist_ok=True)
CAD=FIT/'LoRa-Enclosure-C5-Fit-Checked.FCStd'
source_hash=hashlib.sha256(CAD.read_bytes()).hexdigest()
doc=App.openDocument(str(CAD))

def box(x0,x1,y0,y1,z0,z1):
    return Part.makeBox(x1-x0,y1-y0,z1-z0,App.Vector(x0,y0,z0))
front=box(-10,80,-10,9,1.2,40)
right=box(70,80,-10,82,1.2,40)
roof=box(6,64,-10,82,24,40)
keep=box(38,64,9,18,23.9,28)
housing_tool=front.fuse(right).fuse(roof.cut(keep)).removeSplitter()

def screw(x):
    r=(2**2+1.72**2)/(2*1.72)
    head=Part.makeSphere(r,App.Vector(x,9,29.32-r)).common(Part.makeCylinder(2,1.72,App.Vector(x,9,27.6)))
    shaft=Part.makeCylinder(1,10.05,App.Vector(x,9,17.6))
    cross=Part.makeBox(2.6,.6,1,App.Vector(x-1.3,8.7,28.62)).fuse(Part.makeBox(.6,2.6,1,App.Vector(x-.3,7.7,28.62)))
    return shaft.fuse(head).cut(cross).removeSplitter()

def nut(x):
    r=4/math.sqrt(3)
    pts=[App.Vector(x+r*math.cos(math.radians(30+i*60)),9+r*math.sin(math.radians(30+i*60)),18.55) for i in range(6)]
    prism=Part.Face(Part.makePolygon(pts+[pts[0]])).extrude(App.Vector(0,0,1.6))
    bevel=Part.makeCone(2,r,.2,App.Vector(x,9,18.55)).fuse(Part.makeCylinder(r,1.2,App.Vector(x,9,18.75))).fuse(Part.makeCone(r,2,.2,App.Vector(x,9,19.95)))
    bore=Part.makeCylinder(1,1.8,App.Vector(x,9,18.45)).fuse(Part.makeCone(1.15,1,.15,App.Vector(x,9,18.55))).fuse(Part.makeCone(1,1.15,.15,App.Vector(x,9,20)))
    return prism.common(bevel).cut(bore).removeSplitter()

def on_plane(face,axis,value):
    bb=face.BoundBox
    return abs(getattr(bb,axis+'Min')-value)<1e-6 and abs(getattr(bb,axis+'Max')-value)<1e-6

records,footprints=[],[]
def add_model(ref,original,tool,color,cutcolor,planes,source_meta):
    cut=original.cut(tool).removeSplitter()
    assert cut.isValid() and len(cut.Solids)>0
    body=['#VRML V2.0 utf8','# Exact sectioned CAD presentation;1 unit=2.54 mm.']
    count=0
    cut_count=0
    for face in cut.Faces:
        section=any(on_plane(face,a,v) for a,v in planes)
        c=cutcolor if section else color
        cut_count+=section
        vs,fs=face.tessellate(.025)
        count+=len(fs)
        body+=['Shape { appearance Appearance { material Material { diffuseColor %s specularColor 0.22 0.22 0.22 shininess 0.3 } }' % ' '.join(map(str,c)),
            'geometry IndexedFaceSet { solid TRUE creaseAngle 0.7 coord Coordinate { point [']
        body+=['%.9f %.9f %.9f,' % (v.x/2.54,v.y/2.54,v.z/2.54) for v in vs]
        body+=['] } coordIndex [']
        body+=['%d,%d,%d,-1,' % tuple(f) for f in fs]
        body+=['] } }']
    model=MODELS/(ref.lower()+'.wrl')
    model.write_text('\n'.join(body)+'\n',encoding='utf-8')
    relative=model.relative_to(SOURCE_DIR).as_posix()
    footprints.append(f'''\n  (footprint "Presentation:{ref}" (layer "F.Cu")
    (uuid "{uuid.uuid4()}") (at 100 190)
    (property "Reference" "{ref}" (at 0 0 0) (layer "F.Fab") (hide yes) (effects (font (size 1 1) (thickness 0.15))))
    (property "Value" "Assembled cutaway only" (at 0 0 0) (layer "F.Fab") (hide yes) (effects (font (size 1 1) (thickness 0.15))))
    (attr exclude_from_pos_files exclude_from_bom)
    (model "${{KIPRJMOD}}/{relative}" (offset (xyz 0 0 -8)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))
  )\n''')
    bb=cut.BoundBox
    records.append(dict(reference=ref,model=str(model),sha256=hashlib.sha256(model.read_bytes()).hexdigest(),source_volume_mm3=original.Volume,cutaway_volume_mm3=cut.Volume,solids=len(cut.Solids),faces=len(cut.Faces),colored_section_faces=cut_count,triangles=count,bounds_mm=[bb.XMin,bb.YMin,bb.ZMin,bb.XMax,bb.YMax,bb.ZMax],offset_mm=[0,0,-8],explosion_mm=0,**source_meta))

housing_planes=[('Y',9),('X',70),('Z',1.2),('X',6),('X',64),('Y',82),('X',38),('Y',18)]
for name,ref,color,cutcolor,tool,planes in [
    ('EnclosureBase','CUT_BASE',(.12,.19,.26),(.88,.65,.35),housing_tool,housing_planes),
    ('EnclosureLid','CUT_LID',(.72,.78,.82),(.88,.65,.35),housing_tool,housing_planes),
    ('PTTPlunger','CUT_PTT',(1,.23,.025),(1,.62,.28),front,[('Y',9)]),
    ('PTTStopCup','CUT_STOP',(.15,.65,.40),(.52,.88,.60),front,[('Y',9)]),
]:
    add_model(ref,doc.getObject(name).Shape.copy(),tool,color,cutcolor,planes,dict(source_fcstd=str(CAD),source_object=name))
for kind,builder in [('SCREW',screw),('NUT',nut)]:
    for index,x in enumerate([42,60],1):
        add_model(f'CUT_{kind}{index}',builder(x),front,(.55,.59,.65),(.8,.83,.86),[('Y',9)],dict(source='Reviewed standard-dimension fastener reference, not manufacturer CAD'))

source_text=SOURCE.read_text(encoding='utf-8')
idx=source_text.rfind(')')
DEST.write_text(source_text[:idx]+''.join(footprints)+source_text[idx:],encoding='utf-8')
actual=Path(r'C:\Users\Homar\Documents\Arduino\esp32-audio-chunker-test\hardware\kicad\heltec_v4_audio_carrier')
actual_models=[]
for model in re.findall(r'\(model\s+"([^"]+)"',source_text):
    rel=model.replace('${KIPRJMOD}/','')
    staged=SOURCE_DIR/rel
    original=actual/rel
    sha=hashlib.sha256(staged.read_bytes()).hexdigest()
    assert sha==hashlib.sha256(original.read_bytes()).hexdigest()
    actual_models.append(dict(model=model,sha256=sha,unchanged_from_original=True))
assert len(actual_models)==6
manufacturing=json.loads((FIT/'export-sha256.json').read_text(encoding='utf-8-sig'))
for item in manufacturing:
    assert hashlib.sha256((FIT/item['file']).read_bytes()).hexdigest().upper()==item['sha256'].upper()
assert hashlib.sha256(CAD.read_bytes()).hexdigest()==source_hash
manifest=dict(source_fcstd=str(CAD),source_fcstd_sha256=source_hash,source_board=str(SOURCE),source_board_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),presentation_board=str(DEST),explosion_mm=0,pcb_components='Complete original KiCad geometry at assembled positions',models=records,actual_electronics_models=actual_models,manufacturing_hashes_verified=manufacturing,cut_tools=dict(front=[-10,80,-10,9,1.2,40],right=[70,80,-10,82,1.2,40],roof=[6,64,-10,82,24,40],roof_keep=[38,64,9,18,23.9,28]),purpose='Assembled cutaway illustration only; not fabrication or printing data')
(ROOT/'cutaway-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
App.closeDocument(doc.Name)
print(json.dumps({'board':str(DEST),'models':len(records),'source_models_unchanged':6,'manufacturing_files_unchanged':len(manufacturing)}))
