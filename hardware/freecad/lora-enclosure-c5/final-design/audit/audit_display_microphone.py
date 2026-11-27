"""Read-only geometry audit of the current enclosure and actual assigned PCB CAD."""
from pathlib import Path
import json, hashlib, math
import FreeCAD as App
import Part

root=Path(__file__).resolve().parents[2]
out=Path(__file__).resolve().parent
src=root/'fit-checked'/'LoRa-Enclosure-C5-Fit-Checked.FCStd'
doc=App.openDocument(str(src))
step=root/'detailed-import'/'C5-detailed-assembly.step'
reference=App.newDocument('CorrectedReferenceReadOnly')
Part.insert(str(step),reference.Name)
def bbox(s):
 b=s.BoundBox
 return [b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
def model(i):
 name='C5_detailed_assembly'+(f'{i:03d}' if i else '')
 ob=reference.getObject(name)
 assert ob is not None,name
 s=ob.Shape.copy()
 s.translate(App.Vector(0,0,6.4814))
 return ob,s
lid=doc.getObject('EnclosureLid').Shape.copy()
oled=[]
for i in range(2811,2831):
 ob,s=model(i)
 d,points,_=lid.distToShape(s)
 oled.append(dict(index=i,name=ob.Name,label=ob.Label,bounds_mm=bbox(s),faces=len(s.Faces),lid_distance_mm=d))
micparts=[model(i)[1] for i in range(1068,1715)]
mic=Part.makeCompound(micparts)
ray=Part.makeLine(App.Vector(54.5,30.5,12.3),App.Vector(54.5,30.5,28))
rayhit=lid.common(ray)
holes=[]
for j in range(6):
 a=math.pi*j/3
 x=54.5+3.6*math.cos(a);y=30.5+3.6*math.sin(a)
 cylinder=Part.makeCylinder(.8,3.6,App.Vector(x,y,24))
 common=lid.common(cylinder)
 holes.append(dict(center_mm=[x,y],diameter_mm=1.6,cut_volume_mm3=common.Volume))
report=dict(source=str(src),source_sha256=hashlib.sha256(src.read_bytes()).hexdigest(),
 scope='Read-only audit; source document not saved or modified.',units='mm',
 source_model_step=str(step),source_model_step_sha256=hashlib.sha256(step.read_bytes()).hexdigest(),
 source_model_mount_translation_mm=[0,0,6.4814],pcb_top_datum_z_mm=8,
 lid_underside_z_mm=24,lid_outside_z_mm=27.6,lid_thickness_mm=3.6,
 display=dict(center_xy_mm=[23,58.05],aperture_mm=[16.4,27],reference_window_mm=[11.4,22],
 outer_frame_mm=[18.6,33],parts=oled,
 provenance='OLED/bracket visual supplement, manufacturer envelope and STEP axes. Glass thickness, frame profile, screw detail, and installed 5 mm gap are approximations; assigned model is not measured owned hardware.'),
 microphone=dict(center_xy_mm=[54.5,30.5],bounds_mm=bbox(mic),acoustic_face_z_mm=12,
 highest_modeled_feature_z_mm=mic.BoundBox.ZMax,existing_lid_hole_diameter_mm=3,
 existing_center_air_path_blocked_by_lid=rayhit.Length>1e-7,existing_center_hit_length_mm=rayhit.Length,
 candidate_peripheral_holes=holes,candidate_pattern='Retain central diameter 3 hole; add six diameter 1.6 holes on diameter 7.2 bolt circle.',
 candidate_smallest_ligament_mm=3.6-1.5-.8,
 provenance='User image supports diameter 14; center port diameter 0.9 and exact location/heights are visual assumptions; project explicitly mounts breakout acoustic/solder face UP. INMP441 IC bottom port does not define breakout facing.'),
 source_notes=[str(root/'detailed-import/source-project/models/INMP441_ROUND_DETAILED_VISUAL.notes.json'),str(root.parent/'heltec-v4-carrier/tools/heltec_model_oled_addon.py')])
(out/'display-microphone-fit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
App.closeDocument(doc.Name)
App.closeDocument(reference.Name)
