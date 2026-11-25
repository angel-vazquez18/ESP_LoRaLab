"""CAD-derived presentation geometry only; never modifies manufacturing files."""
from pathlib import Path
import struct, uuid, json, hashlib, math
import FreeCAD as App
import Part

ROOT = Path(__file__).resolve().parent
FIT = ROOT.parent
SOURCE_DIR = FIT.parent / 'detailed-import' / 'source-project'
SOURCE = SOURCE_DIR / 'heltec_v4_audio_carrier.kicad_pcb'
DEST = SOURCE_DIR / 'fit-checked-exploded-view.kicad_pcb'
MODELS = SOURCE_DIR / 'models' / 'fit-checked-presentation'
MODELS.mkdir(parents=True, exist_ok=True)

def triangles_from_stl(path):
    raw = path.read_bytes()
    count = struct.unpack_from('<I', raw, 80)[0]
    assert len(raw) == 84 + 50 * count
    points, faces, lookup = [], [], {}
    for i in range(count):
        xyz = struct.unpack_from('<9f', raw, 84 + i*50 + 12)
        ids = []
        for j in (0, 3, 6):
            p = tuple(xyz[j:j+3])
            if p not in lookup:
                lookup[p] = len(points)
                points.append(p)
            ids.append(lookup[p])
        faces.append(ids)
    return points, faces, hashlib.sha256(raw).hexdigest()

def write_wrl(path, points, faces, color, metallic=False):
    spec = '0.7 0.7 0.7' if metallic else '0.12 0.12 0.12'
    shine = 0.7 if metallic else 0.18
    body = ['#VRML V2.0 utf8', '# CAD-derived presentation mesh; 1 unit = 2.54 mm.',
        'Shape { appearance Appearance { material Material { diffuseColor %s specularColor %s shininess %s } }' % (' '.join(map(str,color)), spec, shine),
        'geometry IndexedFaceSet { solid TRUE creaseAngle 0.7 coord Coordinate { point [']
    body += ['%.9f %.9f %.9f,' % tuple(v/2.54 for v in p) for p in points]
    body += ['] } coordIndex [']
    body += ['%d, %d, %d, -1,' % tuple(f) for f in faces]
    body += ['] } }']
    path.write_text('\n'.join(body)+'\n', encoding='utf-8')

def screw(x):
    r = (2**2 + 1.72**2) / (2*1.72)
    sphere = Part.makeSphere(r, App.Vector(x,9,29.32-r))
    head = sphere.common(Part.makeCylinder(2,1.72,App.Vector(x,9,27.6)))
    shaft = Part.makeCylinder(1,10.05,App.Vector(x,9,17.6))
    cross = Part.makeBox(2.6,.6,1.0,App.Vector(x-1.3,8.7,28.62)).fuse(Part.makeBox(.6,2.6,1.0,App.Vector(x-.3,7.7,28.62)))
    return shaft.fuse(head).cut(cross).removeSplitter()

def nut(x):
    r=4/math.sqrt(3)
    points=[App.Vector(x+r*math.cos(math.radians(30+i*60)),9+r*math.sin(math.radians(30+i*60)),18.55) for i in range(6)]
    prism=Part.Face(Part.makePolygon(points+[points[0]])).extrude(App.Vector(0,0,1.6))
    bevel=Part.makeCone(2,r,.2,App.Vector(x,9,18.55)).fuse(Part.makeCylinder(r,1.2,App.Vector(x,9,18.75))).fuse(Part.makeCone(r,2,.2,App.Vector(x,9,19.95)))
    bore=Part.makeCylinder(1,1.8,App.Vector(x,9,18.45))
    bore=bore.fuse(Part.makeCone(1.15,1,.15,App.Vector(x,9,18.55))).fuse(Part.makeCone(1,1.15,.15,App.Vector(x,9,20)))
    return prism.common(bevel).cut(bore).removeSplitter()

records, footprints = [], []
def add_model(ref, points, faces, color, explosion, source_meta, metallic=False):
    model=MODELS/(ref.lower()+'.wrl')
    write_wrl(model,points,faces,color,metallic)
    z=explosion-63
    relative=model.relative_to(SOURCE_DIR).as_posix()
    footprints.append(f'''\n  (footprint "Presentation:{ref}" (layer "F.Cu")
    (uuid "{uuid.uuid4()}") (at 100 190)
    (property "Reference" "{ref}" (at 0 0 0) (layer "F.Fab") (hide yes) (effects (font (size 1 1) (thickness 0.15))))
    (property "Value" "Presentation only" (at 0 0 0) (layer "F.Fab") (hide yes) (effects (font (size 1 1) (thickness 0.15))))
    (attr exclude_from_pos_files exclude_from_bom)
    (model "${{KIPRJMOD}}/{relative}" (offset (xyz 0 0 {z})) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))
  )\n''')
    records.append(dict(reference=ref,model=str(model),triangles=len(faces),vertices=len(points),explosion_mm=explosion,offset_mm=[0,0,z],**source_meta))

for file,ref,color,explosion in [
    ('enclosure-base.stl','MECH_BASE',(0.12,.19,.26),0),
    ('enclosure-lid.stl','MECH_LID',(.72,.78,.82),185),
    ('ptt-plunger.stl','MECH_PTT',(1,.23,.025),150),
    ('ptt-stop-cup.stl','MECH_STOP',(.15,.65,.40),130),
]:
    points,faces,sha=triangles_from_stl(FIT/file)
    add_model(ref,points,faces,color,explosion,dict(source_stl=str(FIT/file),source_sha256=sha,exact_source_triangles=True))
for kind,builder,explosion in [('SCREW',screw,225),('NUT',nut,115)]:
    for index,x in enumerate([42,60],1):
        shape=builder(x)
        assert shape.isValid() and len(shape.Solids)==1
        vs,fs=shape.tessellate(.012)
        points=[(v.x,v.y,v.z) for v in vs]
        add_model(f'MECH_{kind}{index}',points,fs,(.55,.59,.65),explosion,dict(source='Standard-dimension reference geometry, not manufacturer CAD',volume_mm3=shape.Volume,bounds_mm=[shape.BoundBox.XMin,shape.BoundBox.YMin,shape.BoundBox.ZMin,shape.BoundBox.XMax,shape.BoundBox.YMax,shape.BoundBox.ZMax]),True)

source_text=SOURCE.read_text(encoding='utf-8')
idx=source_text.rfind(')')
assert idx>0 and not source_text[idx+1:].strip()
DEST.write_text(source_text[:idx]+''.join(footprints)+source_text[idx:],encoding='utf-8')
manifest=dict(source_board=str(SOURCE),source_board_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),presentation_board=str(DEST),electronics='Actual unchanged assigned KiCad models, including original colors and corrected 14 mm microphone scale',pcb_explosion_mm=55,models=records,fasteners='M2x10 pan-head screws, Ø4 x1.72 max heads, and M2 nuts4 AF x1.6; cross recess/bevels representative, no threads',purpose='Exploded presentation only; not a fabrication PCB or print mesh')
(ROOT/'exploded-view-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'board':str(DEST),'model_count':len(records),'manifest':str(ROOT/'exploded-view-manifest.json')}))
