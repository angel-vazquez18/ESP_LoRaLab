"""Package approved native STL exports as unit-bearing, single-part order files.

No scaling or geometric remodeling. Each mesh is translated to XYZ >= 0 only.
The 3MF files are neutral models, not printer profiles or sliced G-code.
"""
from pathlib import Path
import struct, json, hashlib, zipfile, math
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
PARTS = ['enclosure-base', 'enclosure-lid', 'ptt-plunger', 'ptt-stop-cup', 'battery-cover']
DEST = ROOT / 'craftcloud' / 'upload'
DEST.mkdir(parents=True, exist_ok=True)
NS = 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'
ET.register_namespace('', NS)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

records = []
for part in PARTS:
    source = ROOT / 'printing' / ('C5-R4-' + part + '-mm.stl')
    raw = source.read_bytes()
    count = struct.unpack_from('<I', raw, 80)[0]
    assert len(raw) == 84 + 50 * count, source
    triangles = []
    for i in range(count):
        xyz = struct.unpack_from('<9f', raw, 96 + i * 50)
        triangles.append([tuple(xyz[j:j+3]) for j in (0, 3, 6)])
    lower = [min(p[a] for t in triangles for p in t) for a in range(3)]
    upper = [max(p[a] for t in triangles for p in t) for a in range(3)]
    shifted = [[tuple(p[a] - lower[a] for a in range(3)) for p in t] for t in triangles]
    out = bytearray(('LoRa C5 R4 | ' + part + ' | MILLIMETRES | 1:1 | one part').encode('ascii').ljust(80, b' '))
    out += struct.pack('<I', count)
    vertices, faces, lookup = [], [], {}
    for tri in shifted:
        ids = []
        for p in tri:
            # Preserve source STL connectivity exactly; translation changes origin only.
            if p not in lookup:
                lookup[p] = len(vertices)
                vertices.append(p)
            ids.append(lookup[p])
        faces.append(ids)
        u = [tri[1][a]-tri[0][a] for a in range(3)]
        v = [tri[2][a]-tri[0][a] for a in range(3)]
        n = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
        norm = math.sqrt(sum(x*x for x in n))
        assert norm > 0
        out += struct.pack('<12fH', *(x/norm for x in n), *(x for p in tri for x in p), 0)
    stl = DEST / ('C5-R4-' + part + '-mm.stl')
    stl.write_bytes(out)
    model = ET.Element('{%s}model' % NS, {'unit': 'millimeter', '{http://www.w3.org/XML/1998/namespace}lang': 'en-US'})
    ET.SubElement(model, '{%s}metadata' % NS, {'name': 'Title'}).text = 'C5 R4 ' + part
    res = ET.SubElement(model, '{%s}resources' % NS)
    obj = ET.SubElement(res, '{%s}object' % NS, {'id': '1', 'type': 'model', 'name': part})
    mesh = ET.SubElement(obj, '{%s}mesh' % NS)
    verts = ET.SubElement(mesh, '{%s}vertices' % NS)
    for p in vertices:
        ET.SubElement(verts, '{%s}vertex' % NS, dict(zip(('x','y','z'), (format(x, '.10g') for x in p))))
    ts = ET.SubElement(mesh, '{%s}triangles' % NS)
    for face in faces:
        ET.SubElement(ts, '{%s}triangle' % NS, dict(zip(('v1','v2','v3'), map(str, face))))
    build = ET.SubElement(model, '{%s}build' % NS)
    ET.SubElement(build, '{%s}item' % NS, {'objectid': '1'})
    three_mf = stl.with_suffix('.3mf')
    with zipfile.ZipFile(three_mf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        z.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        z.writestr('3D/3dmodel.model', ET.tostring(model, encoding='utf-8', xml_declaration=True))
    with zipfile.ZipFile(three_mf) as z:
        assert z.testzip() is None
        checked = ET.fromstring(z.read('3D/3dmodel.model'))
        assert checked.attrib['unit'] == 'millimeter'
        assert len(checked.findall('.//{%s}object' % NS)) == 1
        assert len(checked.findall('.//{%s}triangle' % NS)) == count
        imported = [[float(e.attrib[k]) for k in ('x','y','z')] for e in checked.findall('.//{%s}vertex' % NS)]
        assert max(abs(imported[i][a] - vertices[i][a]) for i in range(len(vertices)) for a in range(3)) < 1e-7
    # Check that binary STL serialization preserves a translation-only mapping.
    checkraw = stl.read_bytes()
    max_delta = 0.0
    for ti, tri in enumerate(shifted):
        xyz = struct.unpack_from('<9f', checkraw, 96 + ti*50)
        max_delta = max(max_delta, max(abs(xyz[3*j+k]-tri[j][k]) for j in range(3) for k in range(3)))
    assert max_delta < 1e-5
    records.append({'stl_translation_round_trip_error_mm': max_delta,'part': part, 'quantity': 1, 'source': str(source), 'source_sha256': sha(source), 'stl': str(stl), 'stl_sha256': sha(stl), '3mf': str(three_mf), '3mf_sha256': sha(three_mf), 'units': 'mm', 'scale': 1, 'triangles': count, 'dimensions_mm': [upper[a]-lower[a] for a in range(3)], 'translation_from_source_mm': [-x for x in lower], 'geometry_change': 'translation only', '3mf_round_trip_verified': True})

(ROOT / 'craftcloud' / 'upload-manifest.json').write_text(json.dumps({'revision': 'C5-R4', 'files': records, 'upload_instruction': 'Upload ONE format per part (five STL files OR five 3MF files), never both. Quantity 1 for each. Units millimetres; scale 100%. No hardware or PCB is included in these meshes.', 'configuration': 'Neutral models; supplier selects manufacturing orientation and process settings.'}, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'packaged_parts': len(records), 'destination': str(DEST), 'all_3mf_round_trips_passed': True}))
