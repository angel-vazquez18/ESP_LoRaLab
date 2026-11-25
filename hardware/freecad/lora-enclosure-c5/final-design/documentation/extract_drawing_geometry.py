"""Read-only, CAD-derived linework for engineering documentation.

Run with the FreeCAD bundled Python. The input document is never saved.
Every line is obtained from the actual B-rep; no nominal outline substitutes.
"""
import argparse
import hashlib
import json
from pathlib import Path

import FreeCAD as App
import Part
import TechDraw

parser = argparse.ArgumentParser()
parser.add_argument("document")
parser.add_argument("--output", default=str(Path(__file__).with_name("drawing-geometry.json")))
parser.add_argument("--parts", nargs="+", default=["EnclosureBase", "EnclosureLid", "PTTPlunger", "PTTStopCup"])
parser.add_argument("--assembly-step", default=str(Path(__file__).resolve().parents[2] / "detailed-import" / "C5-detailed-assembly.step"))
args = parser.parse_args()
source = Path(args.document).resolve()
doc = App.openDocument(str(source))


def bounds(shape):
    b = shape.BoundBox
    return [b.XMin, b.YMin, b.ZMin, b.XMax, b.YMax, b.ZMax]


def edge_points(edge, direction):
    if edge.Length < 1e-7:
        return []
    pts = edge.discretize(Deflection=0.025)
    def orient(p):
        if direction == (0, -1, 0):
            return [p.y, -p.x]  # physical X, Z
        if direction == (1, 0, 0):
            return [-p.y, p.x]  # physical Y, Z
        return [p.x, p.y]       # physical X, Y
    return [[round(v, 6) for v in orient(p)] for p in pts]


def project(shape, direction):
    groups = TechDraw.projectEx(shape, App.Vector(*direction))
    return {
        "visible": [p for g in groups[:5] for e in g.Edges if (p := edge_points(e, direction))],
        "hidden": [p for g in groups[5:] for e in g.Edges if (p := edge_points(e, direction))],
    }


out = {
    "source": str(source),
    "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    "method": "FreeCAD TechDraw projectEx exact hidden-line projection; B-rep curves discretized to 0.025 mm deflection for PDF paths.",
    "coordinate_system": "Carrier XY: lower-left PCB corner (0,0), USB +Y. Z0 outside base bottom. All lengths in mm.",
    "parts": {},
    "parameters": {},
    "electronics_sections": {},
}

sheet = doc.getObject("Parameters")
if sheet:
    for row in range(1, 181):
        try:
            label, value = sheet.get("A" + str(row)), sheet.get("B" + str(row))
            if label:
                out["parameters"][label] = {"row": row, "value": str(value), "formula": sheet.getContents("B" + str(row))}
        except Exception:
            pass

for name in args.parts:
    obj = doc.getObject(name)
    if obj is None or not hasattr(obj, "Shape") or obj.Shape.isNull():
        raise RuntimeError("Missing printable object: " + name)
    s = obj.Shape
    rec = {"name": name, "label": obj.Label, "bounds_mm": bounds(s), "volume_mm3": s.Volume, "valid": s.isValid(), "solids": len(s.Solids), "views": {}}
    for view, direction in [("top", (0, 0, 1)), ("front", (0, -1, 0)), ("right", (1, 0, 0))]:
        rec["views"][view] = project(s, direction)
    # The below sections are actual material intersections, independent of visibility.
    rec["sections"] = {}
    for title, origin, normal, viewdir in [
        ("display_x23", (23, 0, 0), (1, 0, 0), (1, 0, 0)),
        ("microphone_x54_5", (54.5, 0, 0), (1, 0, 0), (1, 0, 0)),
        ("ptt_y9", (0, 9, 0), (0, 1, 0), (0, -1, 0)),
    ]:
        # A bounded face could miss one side of its origin; a large thin slab
        # would alter true section depth. slice() instead yields exact planar wires.
        distance = sum(a*b for a,b in zip(origin,normal))
        wires = s.slice(App.Vector(*normal), distance)
        if wires:
            section = Part.makeCompound(wires)
            rec["sections"][title] = project(section, viewdir)
    out["parts"][name] = rec
    print("Extracted", name, flush=True)

# Use the corrected assembly STEP, not hidden FCStd history objects. In the
# historical FCStd the original oversized microphone objects remain hidden.
assembly_source = Path(args.assembly_step).resolve()
assembly_doc = App.newDocument("DocumentationCorrectedAssembly")
Part.insert(str(assembly_source), assembly_doc.Name)
assembly_objects = [o for o in assembly_doc.Objects if hasattr(o, "Shape") and not o.Shape.isNull()]
assert len(assembly_objects) == 2949, len(assembly_objects)
assert abs(assembly_objects[1067].Shape.BoundBox.ZMin) < 1e-6
if assembly_objects:
    families = {
        "PCB": list(range(889, 1068)) + [2947, 2948],
        "Heltec": list(range(1, 889)) + list(range(2145, 2811)),
        "OLED": list(range(2811, 2831)),
        "Microphone": list(range(1068, 1715)),
        "Amplifier": list(range(1715, 2138)),
        "Switch": [0],
    }
    section_defs = [
        ("display_x23", (1, 0, 0), 23, (1, 0, 0), 0),
        ("microphone_x54_5", (1, 0, 0), 54.5, (1, 0, 0), 0),
        ("ptt_y9", (0, 1, 0), 9, (0, -1, 0), 1),
    ]
    for family, indices in families.items():
        out["electronics_sections"][family] = {}
        for title, normal, distance, viewdir, axis in section_defs:
            wires = []
            for i in indices:
                o = assembly_objects[i]
                shape = o.Shape.copy()
                shape.translate(App.Vector(0, 0, 6.4814))
                bb = bounds(shape)
                if bb[axis] - 1e-6 <= distance <= bb[axis+3] + 1e-6:
                    wires.extend(shape.slice(App.Vector(*normal), distance))
            if wires:
                out["electronics_sections"][family][title] = project(Part.makeCompound(wires), viewdir)
        print("Sectioned actual models:", family, flush=True)
    out["electronics_section_provenance"] = {
        "corrected_assembly_source": str(assembly_source),
        "corrected_assembly_sha256": hashlib.sha256(assembly_source.read_bytes()).hexdigest(),
        "source_shape_count": len(assembly_objects),
        "raw_component_top_datum_mm": 1.5186,
        "translation_mm": [0, 0, 6.4814],
        "modeled_pcb_top_datum_mm": 8.0,
        "family_index_ranges": families,
        "limitations": "Heltec manufacturer geometry; OLED/audio visual estimates and representative switch. Sections are model-based, not owned-unit measurements.",
    }
    mic = Part.makeCompound([assembly_objects[i].Shape for i in range(1068, 1715)])
    out["electronics_section_provenance"]["corrected_microphone_bounds_mm_before_mounting"] = bounds(mic)

Path(args.output).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
App.closeDocument(doc.Name)
App.closeDocument(assembly_doc.Name)
print(args.output)
