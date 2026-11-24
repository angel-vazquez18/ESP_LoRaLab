"""Create a presentation-only KiCad copy using exact enclosure STL triangles."""
from pathlib import Path
import struct, uuid, json, hashlib

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source-project' / 'heltec_v4_audio_carrier.kicad_pcb'
DEST = SOURCE.with_name('exploded-view.kicad_pcb')
MODELS = SOURCE.parent / 'models' / 'enclosure-presentation'
MODELS.mkdir(exist_ok=True)
specs = [
    ('enclosure-base.stl', 'MECH_BASE', (0.12, 0.19, 0.26), -63.0),
    ('enclosure-lid.stl', 'MECH_LID', (0.72, 0.78, 0.82), 82.0),
    ('ptt-plunger.stl', 'MECH_PTT', (1.0, 0.23, 0.025), 112.0),
]
records, footprints = [], []
for file, ref, color, z in specs:
    stl = ROOT.parent / file
    raw = stl.read_bytes()
    count = struct.unpack_from('<I', raw, 80)[0]
    assert len(raw) == 84 + 50 * count
    points, indexes, lookup = [], [], {}
    for i in range(count):
        xyz = struct.unpack_from('<9f', raw, 84 + i * 50 + 12)
        face = []
        for p in range(0, 9, 3):
            point = tuple(xyz[p:p+3])
            if point not in lookup:
                lookup[point] = len(points)
                points.append(point)
            face.append(lookup[point])
        indexes.append(face)
    model = MODELS / (stl.stem + '.wrl')
    body = ['#VRML V2.0 utf8', '# Exact triangles from verified enclosure STL; 1 unit = 2.54 mm.',
        'Shape { appearance Appearance { material Material { diffuseColor %s specularColor 0.12 0.12 0.12 shininess 0.18 } }' % ' '.join(map(str,color)),
        'geometry IndexedFaceSet { solid TRUE creaseAngle 0.7 coord Coordinate { point [']
    body += ['%.9f %.9f %.9f,' % tuple(v/2.54 for v in p) for p in points]
    body += ['] } coordIndex [']
    body += ['%d, %d, %d, -1,' % tuple(f) for f in indexes]
    body += ['] } }']
    model.write_text('\n'.join(body)+'\n', encoding='utf-8')
    relative = model.relative_to(SOURCE.parent).as_posix()
    footprints.append(f'''\n  (footprint "Presentation:{ref}" (layer "F.Cu")
    (uuid "{uuid.uuid4()}") (at 100 190)
    (property "Reference" "{ref}" (at 0 0 0) (layer "F.Fab") (hide yes) (effects (font (size 1 1) (thickness 0.15))))
    (property "Value" "Presentation only" (at 0 0 0) (layer "F.Fab") (hide yes) (effects (font (size 1 1) (thickness 0.15))))
    (attr exclude_from_pos_files exclude_from_bom)
    (model "${{KIPRJMOD}}/{relative}" (offset (xyz 0 0 {z})) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))
  )\n''')
    records.append({'reference':ref, 'source_stl':str(stl),'sha256':hashlib.sha256(raw).hexdigest(),'triangles':count,'vertices':len(points),'model':str(model),'offset_mm':[0,0,z]})
text = SOURCE.read_text(encoding='utf-8')
idx = text.rfind(')')
assert idx > 0 and not text[idx+1:].strip()
DEST.write_text(text[:idx] + ''.join(footprints) + text[idx:], encoding='utf-8')
(ROOT/'exploded-view-manifest.json').write_text(json.dumps({'source_board':str(SOURCE),'presentation_board':str(DEST),'enclosure_models':records,'electronics':'Unchanged active component models from KiCad project','purpose':'Visualization only; not a fabrication board'},indent=2)+'\n',encoding='utf-8')
print(json.dumps({'board':str(DEST),'models':len(records)}))
