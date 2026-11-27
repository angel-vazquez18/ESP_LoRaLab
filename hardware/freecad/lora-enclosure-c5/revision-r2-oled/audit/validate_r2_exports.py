"""Read-only R2 native/STEP and printable lid STL/3MF validation.

Run with FreeCAD 1.1's bundled bin/python.exe after approved exports exist.
Only r2-export-validation.json is written. CAD sources are never saved/exported.
"""
from pathlib import Path
from collections import Counter
import hashlib
import importlib.util
import itertools
import json
import math
import sys
import xml.etree.ElementTree as ET
import zipfile

import FreeCAD as App
import Part

ROOT = Path(__file__).resolve().parents[1]
NAMES = ('EnclosureBase', 'EnclosureLid', 'PTTPlunger', 'PTTStopCup')
FILES = {
    'native': ROOT / 'cad/LoRa-Enclosure-C5-R2-OLED.FCStd',
    'step': ROOT / 'cad/LoRa-Enclosure-C5-R2-OLED.step',
    'stl': ROOT / 'printing/C5-R2-enclosure-lid-mm.stl',
    '3mf': ROOT / 'printing/C5-R2-enclosure-lid-mm.3mf',
}
REPORT = ROOT / 'audit/r2-export-validation.json'
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()


def bbox(shape):
    # OCCT's conservative BoundBox can retain the loft cutter overrun on a
    # trimmed B-spline support surface. Use exact trimmed geometry extents.
    b = shape.optimalBoundingBox(False, False)
    return [b.XMin, b.YMin, b.ZMin, b.XMax, b.YMax, b.ZMax]


def info(shape):
    return dict(valid=shape.isValid(), closed=shape.isClosed(), solids=len(shape.Solids),
                volume_mm3=shape.Volume, bounds_mm=bbox(shape))


def compare(a, b):
    bounds_delta = max(abs(x - y) for x, y in zip(bbox(a), bbox(b)))
    volume_delta = abs(a.Volume - b.Volume)
    symmetric = abs(a.cut(b).Volume) + abs(b.cut(a).Volume)
    return dict(max_bounds_difference_mm=bounds_delta,
                absolute_volume_difference_mm3=volume_delta,
                symmetric_difference_volume_mm3=symmetric,
                matches=bounds_delta < 1e-6 and volume_delta < 1e-5 and symmetric < 1e-5)


def read_3mf(path):
    """Resolve 3MF build/component transforms before comparing manufacturing meshes."""
    ns = {'m': 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'}
    with zipfile.ZipFile(path) as package:
        if package.testzip() is not None:
            raise ValueError('3MF ZIP CRC failed')
        candidates = [n for n in package.namelist() if n.lower().endswith('.model')]
        if len(candidates) != 1:
            raise ValueError('Expected one model resource; cross-resource builds are unsupported')
        model = ET.fromstring(package.read(candidates[0]))
    if model.get('unit', 'millimeter') != 'millimeter':
        raise ValueError('3MF units must be millimeter')
    resources = {o.get('id'): o for o in model.findall('m:resources/m:object', ns)}
    builds = model.findall('m:build/m:item', ns)
    if len(builds) != 1:
        raise ValueError('Expected exactly one printable lid build item')
    transforms = []

    def matrix(value):
        if value is None:
            return None
        values = [float(v) for v in value.split()]
        if len(values) != 12 or not all(math.isfinite(v) for v in values):
            raise ValueError('Invalid 3MF affine transform')
        transforms.append(values)
        return values

    def transformed(point, chain):
        x, y, z = point
        for m in chain:
            if m is not None:
                x, y, z = (x*m[0] + y*m[3] + z*m[6] + m[9],
                           x*m[1] + y*m[4] + z*m[7] + m[10],
                           x*m[2] + y*m[5] + z*m[8] + m[11])
        return (x, y, z)

    def resolve(object_id, chain, visited):
        if object_id in visited:
            raise ValueError('Cyclic 3MF component graph')
        obj = resources[object_id]
        mesh = obj.find('m:mesh', ns)
        triangles = []
        if mesh is not None:
            vertices = [transformed(tuple(float(v.get(k)) for k in ('x','y','z')), chain)
                        for v in mesh.findall('m:vertices/m:vertex', ns)]
            for t in mesh.findall('m:triangles/m:triangle', ns):
                indices = [int(t.get(k)) for k in ('v1','v2','v3')]
                if any(i < 0 or i >= len(vertices) for i in indices):
                    raise ValueError('3MF vertex index out of bounds')
                triangles.append(tuple(vertices[i] for i in indices))
        for c in obj.findall('m:components/m:component', ns):
            triangles.extend(resolve(c.get('objectid'), [matrix(c.get('transform'))] + chain,
                                     visited | {object_id}))
        if not triangles:
            raise ValueError('Empty 3MF object')
        return triangles

    item = builds[0]
    triangles = resolve(item.get('objectid'), [matrix(item.get('transform'))], set())
    return triangles, dict(unit=model.get('unit', 'millimeter'), model_resource=candidates[0],
                           mesh_objects=len(model.findall('.//m:mesh', ns)),
                           build_items=len(builds), applied_transforms=transforms,
                           triangle_count=len(triangles), zip_integrity='passed')


def mesh_vs_native(topology, native):
    mb = topology['bbox_mm']['min'] + topology['bbox_mm']['max']
    bounds_delta = max(abs(x-y) for x,y in zip(mb, bbox(native)))
    volume_error = abs(topology['absolute_volume_mm3'] - native.Volume) / native.Volume
    return dict(assembly_coordinate_bounds_difference_mm=bounds_delta,
                relative_volume_error=volume_error,
                matches=bounds_delta < .05 and volume_error < .005)


def triangle_keys(triangles):
    # Winding is checked separately; canonical coordinates compare triangle surfaces.
    return Counter(tuple(sorted(tuple(round(c, 5) for c in p) for p in tri))
                   for tri in triangles)


def main():
    report = dict(scope='Saved native/STEP equality, lid mesh integrity and transform-aware 3MF readback; no physical qualification.',
                  brep_bounds_method='optimalBoundingBox(useTriangulation=False, useShapeTolerance=False); trims rather than support-surface overrun',
                  files={}, parts={}, failures=[], limitations=[
                      'STL/3MF to B-rep comparison uses bounds and volume, not pointwise surface deviation.',
                      'Manifold checks do not prove absence of self-intersections or mechanical strength.',
                      'Electronics fit is independently documented in r2-oled-fit-validation.json.'])
    doc = None

    def check(condition, failure):
        if not condition:
            report['failures'].append(failure)

    try:
        for name, path in FILES.items():
            if not path.is_file():
                raise FileNotFoundError('Approved export not present: ' + str(path))
            report['files'][name] = dict(path=str(path), bytes=path.stat().st_size, sha256=sha(path))
        spec = importlib.util.spec_from_file_location('fit_checked_mesh_validation', ROOT.parent/'fit-checked/verify_exports.py')
        mv = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mv)
        report['native_archive'] = mv.validate_fcstd(FILES['native'])
        check(report['native_archive']['ok'], 'Native archive integrity/parametric feature check failed')
        doc = App.openDocument(str(FILES['native']))
        saved = {n: doc.getObject(n).Shape.copy() for n in NAMES}
        p = doc.getObject('Parameters')
        expected = {'B8':13, 'B44':21, 'B47':24.6, 'B73':1.6, 'B74':2, 'B75':2, 'B76':22.6, 'B77':.1}
        report['parameters'] = {cell:dict(value=float(str(p.get(cell)).split()[0]), expected=value,
                                         expression=p.getContents(cell)) for cell,value in expected.items()}
        check(all(abs(d['value']-d['expected']) < 1e-7 for d in report['parameters'].values()), 'Native parameter mismatch')
        loft = doc.getObject('OLEDBezelRecess')
        report['native_recess_links'] = dict(type=loft.TypeId, solid=loft.Solid, ruled=loft.Ruled,
                                            profiles=[x.Name for x in loft.Sections],
                                            linked_to_lid_cutters=loft in doc.getObject('LidCutters').Shapes)
        check(loft.TypeId == 'Part::Loft' and loft.Solid and loft.Ruled and
              report['native_recess_links']['profiles'] == ['OLEDRecessFloor','OLEDRecessTop'] and
              report['native_recess_links']['linked_to_lid_cutters'], 'Native recess history is not linked')
        solids = Part.read(str(FILES['step'])).Solids
        report['step_solid_count'] = len(solids)
        check(len(solids) == 4, 'STEP must contain four printable solids')
        if len(solids) == 4:
            pairing = min(itertools.permutations(range(4)), key=lambda order:
                          sum(sum(abs(a-b) for a,b in zip(bbox(saved[n]), bbox(solids[i]))) +
                              abs(saved[n].Volume-solids[i].Volume)/max(1,saved[n].Volume)
                              for n,i in zip(NAMES,order)))
            for n,i in zip(NAMES,pairing):
                native, imported = info(saved[n]), info(solids[i])
                comparison = compare(saved[n], solids[i])
                report['parts'][n] = dict(native=native, step=imported, step_index=i, comparison=comparison)
                check(all(d['valid'] and d['closed'] and d['solids']==1 for d in (native,imported)) and
                      comparison['matches'], 'Native/STEP geometry failed for ' + n)
        doc.recompute()
        report['recompute'] = {n:compare(s, doc.getObject(n).Shape) for n,s in saved.items()}
        check(all(d['matches'] for d in report['recompute'].values()), 'Saved CAD geometry changes on recompute')
        stl_topology = mv.validate_mesh(FILES['stl'])
        _, stl_triangles = mv.read_stl(FILES['stl'])
        report['stl'] = dict(topology=stl_topology, native_comparison=mesh_vs_native(stl_topology, saved['EnclosureLid']))
        check(stl_topology['ok'] and stl_topology['signed_volume_mm3']>0 and report['stl']['native_comparison']['matches'],
              'STL topology/orientation/native comparison failed')
        mf_triangles, mf_meta = read_3mf(FILES['3mf'])
        # Reuse the same topology validator without creating an intermediate STL.
        original_reader = mv.read_stl
        try:
            mv.read_stl = lambda path: ('3mf_transform_resolved', mf_triangles)
            mf_topology = mv.validate_mesh(FILES['3mf'])
        finally:
            mv.read_stl = original_reader
        mf_meta['topology'] = mf_topology
        mf_meta['native_comparison'] = mesh_vs_native(mf_topology, saved['EnclosureLid'])
        mf_meta['same_triangles_as_stl_at_1e_minus_5_mm'] = triangle_keys(stl_triangles) == triangle_keys(mf_triangles)
        # FreeCAD's XML vertex formatting and binary STL float32 serialization
        # have different rounding. Verify corresponding triangles explicitly;
        # quantization-bin equality alone can falsely reject nearby coordinates.
        vertex_delta = None
        if len(stl_triangles) == len(mf_triangles):
            vertex_delta = max(min(max(abs(x-y) for p,q in zip(t,order) for x,y in zip(p,q))
                                   for order in itertools.permutations(u))
                               for t,u in zip(stl_triangles,mf_triangles))
        a,b=stl_topology['bbox_mm'],mf_topology['bbox_mm']
        mf_meta['stl_comparison'] = dict(max_bounds_difference_mm=max(abs(x-y) for x,y in zip(a['min']+a['max'],b['min']+b['max'])),
                                         absolute_volume_difference_mm3=abs(stl_topology['absolute_volume_mm3']-mf_topology['absolute_volume_mm3']),
                                         relative_volume_difference=abs(stl_topology['absolute_volume_mm3']-mf_topology['absolute_volume_mm3'])/stl_topology['absolute_volume_mm3'],
                                         corresponding_triangle_max_vertex_difference_mm=vertex_delta,
                                         coordinate_round_trip_tolerance_mm=1e-4,
                                         relative_volume_tolerance=1e-6,
                                         precision_note='STL float32 and FreeCAD 3MF XML decimal serialization differ; ordered triangles compared with vertex permutation.')
        report['3mf'] = mf_meta
        check(mf_topology['ok'] and mf_topology['signed_volume_mm3']>0 and mf_meta['native_comparison']['matches'],
              '3MF topology/orientation/units/native comparison failed')
        check(mf_meta['stl_comparison']['max_bounds_difference_mm'] < 1e-4 and
              mf_meta['stl_comparison']['relative_volume_difference'] < 1e-6 and
              vertex_delta is not None and vertex_delta < 1e-4,
              '3MF differs from the STL manufacturing mesh')
    except Exception as exc:
        report['failures'].append(type(exc).__name__ + ': ' + str(exc))
    finally:
        if doc is not None:
            App.closeDocument(doc.Name)
        report['source_files_unchanged'] = {name:sha(FILES[name])==record['sha256'] for name,record in report['files'].items()}
        check(all(report['source_files_unchanged'].values()), 'An input file changed during validation')
        report['ok'] = not report['failures']
        REPORT.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(ok=report['ok'],failures=report['failures'],report=str(REPORT),
                          step_solids=report.get('step_solid_count'),
                          step_matches={n:d['comparison']['matches'] for n,d in report['parts'].items()},
                          stl=report.get('stl',{}).get('native_comparison'),
                          three_mf=report.get('3mf',{}).get('stl_comparison')), indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
