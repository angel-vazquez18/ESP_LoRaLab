"""Read-only provisional connector/lead-envelope routing check."""
import json,math,hashlib
from pathlib import Path
import FreeCAD as A,Part
import evaluate_rear_bay as bay
out=Path(__file__).resolve().parent
box=bay.box
body=bay.body;cover=bay.cover;cell=bay.cell
hood_outer=box(21,35,92,99.6,-14,11.1)
hood_chase=box(23.4,32.6,91.9,97.2,-14.1,13.2)
body=body.fuse(hood_outer).cut(hood_chase).removeSplitter()
cover_tab=box(21,35,92,99.6,-16.4,-14)
lip_route=box(23.4,32.6,90.3,94.5,-14,-12.3)
cover=cover.fuse(cover_tab).cut(lip_route).removeSplitter()
# This envelope reserves an unverified mating plug, not a substitute vendor CAD.
plug=box(25.1,30.1,88.42,93.9,9.8,12.8)
points=[(18,79,-8),(18,83,-8),(27.6,88,-8),(27.6,95.9,-8),(27.6,95.9,9)]
for i in range(1,13):
 a=(math.pi/2)*i/12
 points.append((27.6,93.9+2*math.cos(a),9+2*math.sin(a)))
points.append((27.6,93.7,11))
wire_shapes=[];length=0
for a,b in zip(points,points[1:]):
 av,bv=A.Vector(*a),A.Vector(*b);delta=bv-av
 wire_shapes.append(Part.makeCylinder(.8,delta.Length,av,delta));length+=delta.Length
for p in points[1:-1]:wire_shapes.append(Part.makeSphere(.8,A.Vector(*p)))
wire=Part.makeCompound(wire_shapes)
usb_clearance=box(15,31,92,110,11.5,21)
assembly=out.parents[1]/'detailed-import/C5-detailed-assembly.step'
ref=A.newDocument('BatteryHarnessReferenceReadOnly')
Part.insert(str(assembly),ref.Name)
objects=[o for o in ref.Objects if hasattr(o,'Shape') and not o.Shape.isNull()]
checks=[]
for i,o in enumerate(objects):
 s=o.Shape.copy();s.translate(A.Vector(0,0,6.4814));b=s.BoundBox
 if b.XMin>32 or b.XMax<24 or b.YMin>99 or b.YMax<87 or b.ZMin>14 or b.ZMax<8:continue
 checks.append(dict(index=i,plug_distance_mm=plug.distToShape(s)[0],wire_distance_mm=wire.distToShape(s)[0],plug_intersection_mm3=plug.common(s).Volume,wire_intersection_mm3=wire.common(s).Volume))
report={'scope':'Predictive rear chimney and unverified mating-plug/lead envelopes. No CAD document saved/exported.',
 'body':bay.info(body),'cover':bay.info(cover),'hood_outer_bounds_mm':bay.bb(hood_outer),'hood_chase_bounds_mm':bay.bb(hood_chase),
 'plug_assumed_bounds_mm':bay.bb(plug),'plug_assumption':'Five mm width,5.48mm exposed projection,3mm height. Must be replaced/checked against actual purchased mating connector.',
 'lead_centerline_mm':points,'lead_radius_mm':.8,'lead_nominal_polyline_length_mm':length,'photo_lead_length_mm':66,
 'lead_assumptions':'Lead exit at pack upper end X18/Y79;66mm photo length includes unknown termination details. Does not prove exact connector compatibility, bend-radius rating, or service slack.',
 'body_cover_intersection_mm3':body.common(cover).Volume,'body_cell_intersection_mm3':body.common(cell).Volume,'cover_cell_intersection_mm3':cover.common(cell).Volume,
 'plug_body_intersection_mm3':body.common(plug).Volume,'wire_body_intersection_mm3':body.common(wire).Volume,
 'plug_cover_intersection_mm3':cover.common(plug).Volume,'wire_cover_intersection_mm3':cover.common(wire).Volume,
 'new_material_usb_access_intersection_mm3':hood_outer.common(usb_clearance).Volume,
 'plug_usb_access_envelope_overlap_mm3':plug.common(usb_clearance).Volume,'wire_usb_access_envelope_overlap_mm3':wire.common(usb_clearance).Volume,
 'usb_limitation':'No new printed material enters the original USB opening sweep. Assumed battery plug/lead overlaps the provisional USB cable-overmould reservation; actual simultaneous plug/USB cable fit is not qualified.',
 'nearby_electronics':checks,'plug_min_electronics_distance_mm':min(x['plug_distance_mm']for x in checks),'wire_min_electronics_distance_mm':min(x['wire_distance_mm']for x in checks),
 'source_sha256':hashlib.sha256(assembly.read_bytes()).hexdigest()}
report['mechanical_envelope_ok']=all([body.isValid(),cover.isValid(),len(body.Solids)==1,len(cover.Solids)==1,report['body_cover_intersection_mm3']<1e-6,report['body_cell_intersection_mm3']<1e-6,report['cover_cell_intersection_mm3']<1e-6,report['plug_body_intersection_mm3']<1e-6,report['wire_body_intersection_mm3']<1e-6,report['plug_cover_intersection_mm3']<1e-6,report['wire_cover_intersection_mm3']<1e-6,all(x['plug_intersection_mm3']<1e-6 and x['wire_intersection_mm3']<1e-6 for x in checks)])
report['release_fit_qualified']=False
(out/'rear-harness-predictive-report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k not in('nearby_electronics','lead_centerline_mm')},indent=2))
A.closeDocument(ref.Name)
