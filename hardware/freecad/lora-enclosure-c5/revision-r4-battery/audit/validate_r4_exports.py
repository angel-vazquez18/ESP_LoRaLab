"""Read-only R4 native/STEP and five printable-part STL/3MF validation.

Run with FreeCAD 1.1's bundled bin/python.exe after approved exports exist.
Only r4-export-validation.json is written. CAD sources are never saved/exported.
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
PART_STEMS = {'EnclosureBase':'enclosure-base', 'EnclosureLid':'enclosure-lid',
              'PTTPlunger':'ptt-plunger', 'PTTStopCup':'ptt-stop-cup', 'BatteryCover':'battery-cover'}
NAMES = tuple(PART_STEMS)
FILES = {
    'native': ROOT / 'cad/LoRa-Enclosure-C5-R4-Battery.FCStd',
    'step': ROOT / 'cad/LoRa-Enclosure-C5-R4-Battery.step',
    'native_plan': ROOT / 'native-battery-operations-plan.json',
}
for part, stem in PART_STEMS.items():
    for extension in ('stl','3mf'):
        FILES[part+'.'+extension] = ROOT / ('printing/C5-R4-'+stem+'-mm.'+extension)
REPORT = ROOT / 'audit/r4-export-validation.json'
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
        raise ValueError('Expected exactly one printable part build item')
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


def mesh_vs_native(topology, native, to_assembly=(0,0,0)):
    mb = [v+to_assembly[i%3] for i,v in enumerate(topology['bbox_mm']['min'] + topology['bbox_mm']['max'])]
    bounds_delta = max(abs(x-y) for x,y in zip(mb, bbox(native)))
    volume_error = abs(topology['absolute_volume_mm3'] - native.Volume) / native.Volume
    return dict(assembly_coordinate_bounds_difference_mm=bounds_delta,
                relative_volume_error=volume_error,
                matches=bounds_delta < .05 and volume_error < .005)


def triangle_keys(triangles):
    # Winding is checked separately; canonical coordinates compare triangle surfaces.
    return Counter(tuple(sorted(tuple(round(c, 5) for c in p) for p in tri))
                   for tri in triangles)


def shifted_triangles(triangles, translation):
    return [tuple(tuple(value+translation[i] for i,value in enumerate(point))
                  for point in triangle) for triangle in triangles]


def check_mesh_pair(part, saved, validator, to_assembly):
    stl_path, mf_path = FILES[part+'.stl'], FILES[part+'.3mf']
    stl_topology = validator.validate_mesh(stl_path)
    _, stl_raw = validator.read_stl(stl_path)
    mf_raw, meta = read_3mf(mf_path)
    original_reader = validator.read_stl
    try:
        validator.read_stl = lambda path: ('3mf_transform_resolved', mf_raw)
        mf_topology = validator.validate_mesh(mf_path)
    finally:
        validator.read_stl = original_reader
    stl_comparison = mesh_vs_native(stl_topology, saved, to_assembly)
    mf_comparison = mesh_vs_native(mf_topology, saved, to_assembly)
    stl_triangles, mf_triangles = shifted_triangles(stl_raw,to_assembly), shifted_triangles(mf_raw,to_assembly)
    vertex_delta = None
    if len(stl_triangles)==len(mf_triangles):
        vertex_delta = max(min(max(abs(x-y) for p,q in zip(t,order) for x,y in zip(p,q))
                               for order in itertools.permutations(u))
                           for t,u in zip(stl_triangles,mf_triangles))
    a,b = stl_topology['bbox_mm'],mf_topology['bbox_mm']
    comparison = dict(max_bounds_difference_mm=max(abs(x-y) for x,y in zip(a['min']+a['max'],b['min']+b['max'])),
                      absolute_volume_difference_mm3=abs(stl_topology['absolute_volume_mm3']-mf_topology['absolute_volume_mm3']),
                      relative_volume_difference=abs(stl_topology['absolute_volume_mm3']-mf_topology['absolute_volume_mm3'])/stl_topology['absolute_volume_mm3'],
                      corresponding_triangle_max_vertex_difference_mm=vertex_delta,
                      coordinate_round_trip_tolerance_mm=1e-4, relative_volume_tolerance=1e-6,
                      precision_note='STL float32 and FreeCAD 3MF XML serialization differ; ordered triangles compared with vertex permutation.')
    ok = (stl_topology['ok'] and mf_topology['ok'] and
          stl_topology['signed_volume_mm3']>0 and mf_topology['signed_volume_mm3']>0 and
          stl_comparison['matches'] and mf_comparison['matches'] and
          comparison['max_bounds_difference_mm']<1e-4 and comparison['relative_volume_difference']<1e-6 and
          vertex_delta is not None and vertex_delta<1e-4)
    return dict(ok=ok, translation_from_print_to_assembly_mm=list(to_assembly),
                stl=dict(topology=stl_topology,native_comparison=stl_comparison),
                three_mf=dict(**meta,topology=mf_topology,native_comparison=mf_comparison),
                stl_three_mf_comparison=comparison)


def main():
    report = dict(scope='Five saved native/STEP solid comparisons and five STL/3MF pairs; no physical qualification.',
                  brep_bounds_method='optimalBoundingBox(useTriangulation=False,useShapeTolerance=False)',
                  files={}, parts={}, meshes={}, provenance={}, failures=[], limitations=[
                      'Mesh to B-rep comparison uses bounds and volume, not pointwise surface deviation.',
                      'Manifold checks do not establish mechanical strength or absence of self-intersections.',
                      'Battery/electronics fit and charging suitability are outside this export-integrity audit.'])
    doc = None

    def check(condition,failure):
        if not condition:
            report['failures'].append(failure)

    try:
        for name,path in FILES.items():
            if not path.is_file():
                raise FileNotFoundError('Approved export or operation plan not present: '+str(path))
            report['files'][name] = dict(path=str(path),bytes=path.stat().st_size,sha256=sha(path))
        spec = importlib.util.spec_from_file_location('fit_checked_mesh_validation',ROOT.parent/'fit-checked/verify_exports.py')
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        validator.FINAL_FEATURES = dict(validator.FINAL_FEATURES,BatteryCover='Part::Cut')
        report['native_archive'] = validator.validate_fcstd(FILES['native'])
        check(report['native_archive']['ok'],'Native archive/parametric feature declarations failed')
        doc = App.openDocument(str(FILES['native']))
        saved = {name:doc.getObject(name).Shape.copy() for name in NAMES}
        plan = json.loads(FILES['native_plan'].read_text(encoding='utf-8'))
        check(tuple(plan['final_objects'])==NAMES,'Plan final objects differ from five printables')
        parameters = doc.getObject('Parameters')
        report['parameters'] = {}
        for row,(name,target,description) in enumerate(plan['parameter_rows'],start=plan['parameter_start_row']):
            cell='B'+str(row)
            value=float(str(parameters.get(cell)).split()[0])
            label=parameters.get('A'+str(row))
            report['parameters'][cell]=dict(name=label,expected_name=name,value=value,expected=target,
                                           stored_label=parameters.getContents('A'+str(row)),
                                           expression=parameters.getContents(cell))
            check(label==name and abs(value-float(target))<1e-7,'Battery parameter mismatch '+cell)
        fuse_names=[o.Name for o in doc.getObject('BaseWithSupports').Shapes]
        cutter_names=[o.Name for o in doc.getObject('BaseCutters').Shapes]
        cover=doc.getObject('BatteryCover')
        report['native_battery_links']=dict(base_fuse_additions={n:n in fuse_names for n in plan['base_fuse_additions']},
            base_cutter_additions={n:n in cutter_names for n in plan['base_cutter_additions']},
            cover_type=cover.TypeId,cover_base=cover.Base.Name,cover_tool=cover.Tool.Name)
        links=report['native_battery_links']
        check(all(links['base_fuse_additions'].values()) and all(links['base_cutter_additions'].values()) and
              cover.TypeId=='Part::Cut' and cover.Base.Name=='BatteryCoverMaterial' and cover.Tool.Name=='BatteryCoverCutters',
              'Battery native feature dependency is incomplete')
        solids=Part.read(str(FILES['step'])).Solids
        report['step_solid_count']=len(solids)
        check(len(solids)==len(NAMES),'STEP must contain exactly five printable solids')
        if len(solids)==len(NAMES):
            # Cache these comparatively costly optimal bounds before testing 120 assignments.
            native_bounds={n:bbox(s) for n,s in saved.items()}
            step_bounds=[bbox(s) for s in solids]
            costs={(n,i):sum(abs(a-b) for a,b in zip(native_bounds[n],step_bounds[i]))+
                   abs(saved[n].Volume-solids[i].Volume)/max(1,saved[n].Volume)
                   for n in NAMES for i in range(len(solids))}
            pairing=min(itertools.permutations(range(len(solids))),
                        key=lambda order:sum(costs[n,i] for n,i in zip(NAMES,order)))
            for name,index in zip(NAMES,pairing):
                native,imported=info(saved[name]),info(solids[index])
                comparison=compare(saved[name],solids[index])
                report['parts'][name]=dict(native=native,step=imported,step_index=index,comparison=comparison)
                check(all(i['valid'] and i['closed'] and i['solids']==1 for i in (native,imported)) and comparison['matches'],
                      'Native/STEP solid mismatch: '+name)
        doc.recompute()
        report['recompute']={n:compare(s,doc.getObject(n).Shape) for n,s in saved.items()}
        check(all(r['matches'] for r in report['recompute'].values()),'Saved geometry changes on recompute')
        # Reused PTT pairs are exact R1 normalized Craftcloud copies. Use only
        # their documented translation, never a freely fitted mesh alignment.
        r1_manifest_path=ROOT.parent/'final-design/craftcloud/upload-manifest.json'
        r1_manifest=json.loads(r1_manifest_path.read_text(encoding='utf-8'))
        report['reuse_manifest']=dict(path=str(r1_manifest_path),sha256=sha(r1_manifest_path))
        records={row['part']:row for row in r1_manifest['files']}
        for name,stem in PART_STEMS.items():
            to_assembly=[0,0,0]
            if name in ('PTTPlunger','PTTStopCup'):
                record=records[stem]
                to_assembly=[-float(x) for x in record['translation_from_assembly_mm']]
                source_files={ext:ROOT.parent/('final-design/craftcloud/upload/C5-R1-'+stem+'-mm.'+ext)
                              for ext in ('stl','3mf')}
                reuse={ext:dict(source=str(source),source_sha256=sha(source),
                    manifest_sha256=record[ext+'_sha256'],
                    r4_sha256=report['files'][name+'.'+ext]['sha256'],
                    exact_byte_copy=sha(source)==record[ext+'_sha256']==report['files'][name+'.'+ext]['sha256'])
                    for ext,source in source_files.items()}
                check(all(r['exact_byte_copy'] for r in reuse.values()),'PTT reuse differs from approved R1 normalized source: '+name)
                report['provenance'][name]=dict(revision='R1',source_coordinates='Recorded Craftcloud normalized coordinates',
                    source_files=reuse,translation_from_assembly_mm=record['translation_from_assembly_mm'],
                    verification_transform='Inverse of R1 upload-manifest translation only')
            elif name=='EnclosureLid':
                source_files={ext:ROOT.parent/('revision-r3-oled-gap/printing/C5-R3-enclosure-lid-mm.'+ext)
                              for ext in ('stl','3mf')}
                reuse={ext:dict(source=str(source),source_sha256=sha(source),
                    r4_sha256=report['files'][name+'.'+ext]['sha256'],
                    exact_byte_copy=sha(source)==report['files'][name+'.'+ext]['sha256'])
                    for ext,source in source_files.items()}
                check(all(r['exact_byte_copy'] for r in reuse.values()),'Lid reuse differs from approved R3 source')
                report['provenance'][name]=dict(revision='R3',source_coordinates='Assembly coordinates',source_files=reuse)
            else:
                report['provenance'][name]=dict(revision='R4',source='New approved native FreeCAD exports',source_coordinates='Assembly coordinates, including negative battery-bay Z')
            report['meshes'][name]=check_mesh_pair(name,saved[name],validator,to_assembly)
            check(report['meshes'][name]['ok'],'Manufacturing mesh pair validation failed: '+name)
    except Exception as exc:
        report['failures'].append(type(exc).__name__+': '+str(exc))
    finally:
        if doc is not None:
            App.closeDocument(doc.Name)
        report['source_files_unchanged']={name:sha(FILES[name])==r['sha256'] for name,r in report['files'].items()}
        check(all(report['source_files_unchanged'].values()),'An input file changed during validation')
        report['ok']=not report['failures']
        REPORT.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(ok=report['ok'],failures=report['failures'],report=str(REPORT),
        step_solids=report.get('step_solid_count'),
        step_matches={n:r['comparison']['matches'] for n,r in report['parts'].items()},
        mesh_pairs={n:dict(ok=r['ok'],triangles=r['stl']['topology']['triangles'],
            native_volume_error=r['stl']['native_comparison']['relative_volume_error'],
            format_vertex_difference_mm=r['stl_three_mf_comparison']['corresponding_triangle_max_vertex_difference_mm'])
            for n,r in report['meshes'].items()}),indent=2))
    return 0 if report['ok'] else 1


if __name__=='__main__':
    sys.exit(main())
