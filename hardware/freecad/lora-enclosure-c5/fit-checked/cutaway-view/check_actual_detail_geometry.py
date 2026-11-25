"""Read-only geometry proof for a native cutaway detail of actual PCB and SW1."""
from pathlib import Path
import hashlib
import json

import FreeCAD as App
import Part

outdir = Path(__file__).resolve().parent
source = outdir.parent / 'exploded-view' / 'LoRa-Enclosure-C5-Exploded-With-Hardware.FCStd'
doc = App.openDocument(str(source))


def native_name(index):
    return 'C5_detailed_assembly' + (f'{index:03d}' if index else '')


def bounds(shape):
    b = shape.BoundBox
    return [b.XMin, b.YMin, b.ZMin, b.XMax, b.YMax, b.ZMax]


def geometry(shape):
    return dict(bbox_mm=bounds(shape), solids=len(shape.Solids), shells=len(shape.Shells),
                faces=len(shape.Faces), edges=len(shape.Edges), volume_mm3=shape.Volume,
                area_mm2=shape.Area, valid=shape.isValid(), is_null=shape.isNull())


def evidence(index):
    obj = doc.getObject(native_name(index))
    assert obj is not None, (index, native_name(index))
    parents = [dict(name=p.Name, label=p.Label,
                    placement=str(p.Placement) if hasattr(p, 'Placement') else None)
               for p in obj.InList]
    return dict(index=index, name=obj.Name, label=obj.Label, type=obj.TypeId,
                shape=geometry(obj.Shape), local_placement=str(obj.Placement),
                global_placement=str(obj.getGlobalPlacement()), parents=parents)


indices = list(range(889, 1068)) + [2947, 2948]
carrier = Part.makeCompound([doc.getObject(native_name(i)).Shape.copy() for i in indices])
raw_carrier = geometry(carrier)
carrier.translate(App.Vector(0, 0, 6.4814))
crop = Part.makeBox(26, 13, 32, App.Vector(38, 9, 0))
carrier_cutaway = carrier.common(crop)
sw1 = doc.getObject(native_name(0)).Shape.copy()
raw_sw1 = geometry(sw1)
sw1.translate(App.Vector(0, 0, 6.4814))
# Remove the lower-Y half using an oversized cutting box, retaining Y >= 9.
sw1_cutaway = sw1.cut(Part.makeBox(200, 109, 100, App.Vector(-50, -100, -50)))

failures = []
if abs(raw_sw1['bbox_mm'][5] - 9.5186) > 1e-6:
    failures.append('SW1 local shape top is not the raw STEP top at 9.5186')
if abs(bounds(sw1)[5] - 16.0) > 1e-6:
    failures.append('Assembled SW1 top is not Z16')
if abs(doc.getObject(native_name(1067)).Shape.BoundBox.ZMin) > 1e-6:
    failures.append('Carrier substrate local minimum Z is not the raw STEP datum 0')
if carrier_cutaway.isNull() or sw1_cutaway.isNull():
    failures.append('A requested actual-model cutaway is empty')

report = dict(
    source=str(source), source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    scope='Read-only geometry proof; source CAD was not saved or modified. Not a clearance audit.',
    source_object_count=len(doc.Objects), units='mm',
    raw_shape_evidence=[evidence(i) for i in (0, 889, 1066, 1067, 2947, 2948)],
    assembly_translation_mm=[0, 0, 6.4814], component_mounting_datum_source_z_mm=1.5186,
    component_mounting_datum_assembled_z_mm=8.0,
    carrier_input_indices_inclusive=[[889, 1067], [2947, 2948]], carrier_input_object_count=len(indices),
    carrier_raw_compound=raw_carrier, carrier_assembled_compound=geometry(carrier),
    carrier_crop_box_min_max_mm=[38, 9, 0, 64, 22, 32], carrier_cutaway=geometry(carrier_cutaway),
    sw1_raw=raw_sw1, sw1_assembled=geometry(sw1), sw1_cutaway_keep_y_ge_mm=9,
    sw1_cutaway=geometry(sw1_cutaway), failures=failures, ok=not failures,
)
(outdir / 'actual-detail-geometry-check.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps(dict(ok=report['ok'], failures=failures, report=str(outdir / 'actual-detail-geometry-check.json'),
                     carrier_input_object_count=len(indices), carrier_cutaway=report['carrier_cutaway'],
                     sw1_raw=raw_sw1, sw1_assembled=report['sw1_assembled'], sw1_cutaway=report['sw1_cutaway'])))
App.closeDocument(doc.Name)
