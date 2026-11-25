"""Read-only saved-CAD R2 audit and exact OLED cross-section extraction.

Run with the FreeCAD bundled Python. Never saves or exports a CAD document.
"""
from pathlib import Path
import hashlib
import json
import math
import FreeCAD as App
import Part

root = Path(__file__).resolve().parents[1]
source = root.parent / 'final-design/cad/LoRa-Enclosure-C5-R1.FCStd'
revised = root / 'cad/LoRa-Enclosure-C5-R2-OLED.FCStd'
assembly = root.parent / 'detailed-import/C5-detailed-assembly.step'
baseline_audit = root.parent / 'final-design/audit/final-actual-clearance.json'
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
initial_hashes = {str(p): sha(p) for p in (source, revised, assembly)}
report = {'scope': 'Read-only saved native geometry, parametric dependencies and exact model section; no physical qualification.', 'sources': initial_hashes, 'failures': []}

def check(condition, text):
    if not condition:
        report['failures'].append(text)

def bounds(s):
    b = s.optimalBoundingBox(False, False)
    return [b.XMin, b.YMin, b.ZMin, b.XMax, b.YMax, b.ZMax]

def info(s):
    return {'valid': s.isValid(), 'closed': s.isClosed(), 'solids': len(s.Solids), 'volume_mm3': s.Volume, 'bounds_mm': bounds(s)}

def delta(a, b):
    return a.cut(b).Volume + b.cut(a).Volume

before = App.openDocument(str(source))
after = App.openDocument(str(revised))
names = ('EnclosureBase', 'EnclosureLid', 'PTTPlunger', 'PTTStopCup')
original = {n: before.getObject(n).Shape.copy() for n in names}
saved = {n: after.getObject(n).Shape.copy() for n in names}
report['parts'] = {n: info(s) for n, s in saved.items()}
for n, s in saved.items():
    check(s.isValid() and s.isClosed() and len(s.Solids) == 1, n + ' is not one valid closed solid')

old_lid, lid = original['EnclosureLid'], saved['EnclosureLid']
added = lid.cut(old_lid)
removed = old_lid.cut(lid)
above = Part.makeBox(200, 200, 10, App.Vector(-50, -50, 24.600001))
below = Part.makeBox(200, 200, 32.599999, App.Vector(-50, -50, -10))
raw_box = removed.BoundBox
report['lid_change'] = {'added_volume_mm3': added.Volume, 'removed_volume_mm3': removed.Volume, 'removed_bounds_mm': bounds(removed), 'bounds_method': 'OCCT optimalBoundingBox without triangulation or shape tolerance; trimmed physical geometry.', 'raw_conservative_surface_bounds_mm': [raw_box.XMin, raw_box.YMin, raw_box.ZMin, raw_box.XMax, raw_box.YMax, raw_box.ZMax], 'bounding_note': 'The basic bounding box includes the untrimmed ruled loft surface overrun. Optimal bounds, actual vertices and zero-volume clipping establish the material extents.', 'removed_above_outer_face_mm3': removed.common(above).Volume, 'removed_below_local_face_mm3': removed.common(below).Volume, 'all_change_is_exterior_subtraction': added.Volume < 1e-6 and bounds(removed)[2] >= 22.6 - 1e-6}
check(report['lid_change']['all_change_is_exterior_subtraction'], 'Change is not limited to exterior subtraction')
check(report['lid_change']['removed_above_outer_face_mm3'] < 1e-8 and report['lid_change']['removed_below_local_face_mm3'] < 1e-8, 'Removed material extends outside intended exterior recess height')
check(abs(removed.Volume - 595.4666666667) < 1e-5, 'Unexpected removed volume')
report['unchanged_parts'] = {n: {'symmetric_difference_mm3': delta(original[n], saved[n])} for n in names if n != 'EnclosureLid'}
check(all(x['symmetric_difference_mm3'] < 1e-6 for x in report['unchanged_parts'].values()), 'A non-lid printed part changed')

p = after.getObject('Parameters')
val = lambda cell: float(str(p.get(cell)).split()[0])
expected = {'B73': 1.6, 'B74': 2, 'B75': 2, 'B76': 22.6, 'B77': .1}
report['parameters'] = {cell: {'actual': val(cell), 'expected': target, 'formula': p.getContents(cell)} for cell, target in expected.items()}
check(all(abs(v['actual'] - v['expected']) < 1e-8 for v in report['parameters'].values()), 'R2 parameter mismatch')
loft = after.getObject('OLEDBezelRecess')
report['parametric_dependency'] = {'loft_type': loft.TypeId, 'profiles': [o.Name for o in loft.Sections], 'profile_types': [o.TypeId for o in loft.Sections], 'solid': loft.Solid, 'ruled': loft.Ruled, 'floor_expressions': dict(after.getObject('OLEDRecessFloor').ExpressionEngine), 'top_expressions': dict(after.getObject('OLEDRecessTop').ExpressionEngine), 'linked_to_lid_cutters': loft in after.getObject('LidCutters').Shapes}
check(loft.TypeId == 'Part::Loft' and loft.Solid and loft.Ruled and report['parametric_dependency']['linked_to_lid_cutters'], 'Native loft dependency invalid')
after.recompute()
report['recompute_difference_mm3'] = {n: delta(s, after.getObject(n).Shape) for n, s in saved.items()}
check(all(v < 1e-6 for v in report['recompute_difference_mm3'].values()), 'Saved geometry changes on recompute')

# In-memory sensitivity test proves the new geometry is spreadsheet-driven.
# No save/export operation occurs; restore and recheck afterward.
p.set('B73', '1.8')
after.recompute()
changed = after.getObject('EnclosureLid').Shape.copy()
report['parameter_sensitivity'] = {'temporary_thickness_mm': 1.8, 'temporary_floor_z_mm': val('B76'), 'changed_volume_mm3': changed.Volume, 'positive_volume_increase_mm3': changed.Volume - lid.Volume}
check(abs(val('B76') - 22.8) < 1e-8 and changed.Volume > lid.Volume + 1, 'Bezel thickness parameter does not drive solid')
p.set('B73', '1.6')
after.recompute()
report['parameter_sensitivity']['restored_difference_mm3'] = delta(lid, after.getObject('EnclosureLid').Shape)
check(report['parameter_sensitivity']['restored_difference_mm3'] < 1e-6, 'In-memory sensitivity test failed to restore geometry')
print('Saved CAD and parameter checks completed', flush=True)

reference = App.newDocument('R2CorrectedReferenceReadOnly')
Part.insert(str(assembly), reference.Name)
objects = [o for o in reference.Objects if hasattr(o, 'Shape') and not o.Shape.isNull()]
check(len(objects) == 2949, 'Unexpected corrected reference shape count')
assert len(objects) == 2949
check(abs(objects[1067].Shape.BoundBox.ZMin) < 1e-6, 'Corrected reference index mapping mismatch')

def model(i):
    s = objects[i].Shape.copy()
    s.translate(App.Vector(0, 0, 6.4814))
    return s

glass = model(2812)
oled = [model(i) for i in range(2811, 2831)]
screws = [model(i) for i in range(2818, 2830)]
report['oled_fit'] = {'glass': info(glass), 'glass_intersection_mm3': lid.common(glass).Volume, 'glass_minimum_distance_to_actual_lid_mm': lid.distToShape(glass)[0], 'all_oled_intersection_mm3': sum(lid.common(s).Volume for s in oled), 'screw_minimum_clearance_mm': min(lid.distToShape(s)[0] for s in screws), 'entire_oled_minimum_clearance_mm': min(lid.distToShape(s)[0] for s in oled)}
check(report['oled_fit']['all_oled_intersection_mm3'] < 1e-7, 'OLED intersects revised lid')
check(abs(report['oled_fit']['screw_minimum_clearance_mm'] - .69878073914) < 1e-6, 'OLED screw clearance changed unexpectedly')
report['baseline_clearance_evidence'] = {'file': str(baseline_audit), 'sha256': sha(baseline_audit), 'recorded_ok': json.loads(baseline_audit.read_text())['ok'], 'reason_existing_clearances_cannot_decrease': 'R2 lid is an exact subset of R1 lid, with zero added volume, and all other printed shapes and electronic placements unchanged. Exterior-only removal cannot introduce material interference or reduce separation.'}
check(report['baseline_clearance_evidence']['recorded_ok'], 'Baseline component audit did not pass')

section_y = 58.05
normal = App.Vector(0, 1, 0)

def section(shapes, indices=None):
    wires, wire_closed = [], []
    for s in shapes:
        b = s.BoundBox
        if b.YMin - 1e-7 <= section_y <= b.YMax + 1e-7:
            for w in s.slice(normal, section_y):
                pts = w.discretize(Deflection=.01)
                poly = [[round(v.x, 8), round(v.z, 8)] for v in pts]
                if w.isClosed() and poly and poly[-1] != poly[0]:
                    poly.append(poly[0])
                wires.append(poly)
                wire_closed.append(w.isClosed())
    return {'wires': wires, 'bounds_mm': bounds(Part.makeCompound(shapes)), 'wire_closed': wire_closed, 'source_indices': indices}

families = {'oled_glass': [2812], 'oled_frame': [2811, 2813, 2830], 'heltec': list(range(1, 889)) + list(range(2145, 2811)), 'carrier': list(range(889, 1068)) + [2947, 2948]}
sections = {'lid_r1': section([old_lid]), 'lid_r2': section([lid])}
for name, indices in families.items():
    sections[name] = section([model(i) for i in indices], indices)
    print('Sectioned ' + name + ': ' + str(len(sections[name]['wires'])) + ' wires', flush=True)

dimensions = {'glass_top_z': glass.BoundBox.ZMax, 'inner_lid_z': val('B44'), 'main_outer_z': val('B47'), 'recessed_face_z': val('B76'), 'aperture_width': val('B20'), 'aperture_height': val('B21'), 'local_thickness': val('B73'), 'recess_depth': val('B75'), 'ledge_width': val('B74'), 'screw_clearance_mm': report['oled_fit']['screw_minimum_clearance_mm'], 'glass_to_recessed_face_mm': val('B76') - glass.BoundBox.ZMax, 'glass_to_main_outer_mm': val('B47') - glass.BoundBox.ZMax, 'glass_to_inner_plane_mm': val('B44') - glass.BoundBox.ZMax, 'window_center_x': val('B18'), 'window_center_y': val('B19'), 'bevel_angle_degrees': 45}
report['dimensions_mm'] = dimensions
report['source_files_unchanged'] = {path: sha(Path(path)) == initial for path, initial in initial_hashes.items()}
check(all(report['source_files_unchanged'].values()), 'Source file modified during read-only audit')
report['ok'] = not report['failures']
geometry = {'units': 'mm', 'section_plane': {'axis': 'Y', 'value_mm': section_y, 'drawing_axes': ['X', 'Z']}, 'method': 'Exact B-rep plane slices; actual closed wires discretized at 0.01 mm deflection. CAD and corrected assembly read only.', 'sources': initial_hashes, 'sections': sections, 'dimensions': dimensions, 'audit_ok': report['ok'], 'limitations': ['OLED supplement glass, frame and mounting hardware are visual approximations; module header mounting height is unmeasured.', 'The inner-lid gap is measured to a reference plane through the open aperture, not to material above the glass.', 'The main enclosure face remains 4.60 mm above glass; only the local recessed window rim moves closer.', 'Physical fit and material load capacity are not established by this model audit.']}
(root / 'documentation/oled-section-geometry.json').write_text(json.dumps(geometry, indent=2) + '\n', encoding='utf-8')
(root / 'audit/r2-oled-fit-validation.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
for d in (before, after, reference):
    App.closeDocument(d.Name)
print(json.dumps({'ok': report['ok'], 'failures': report['failures'], 'lid_change': report['lid_change'], 'dimensions': dimensions, 'sections': {k: len(v['wires']) for k, v in sections.items()}}, indent=2))
if not report['ok']:
    raise SystemExit(1)
