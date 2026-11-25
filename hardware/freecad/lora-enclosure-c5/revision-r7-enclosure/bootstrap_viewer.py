"""Seed the R7 viewer's source pipeline from established R6 scripts."""
from pathlib import Path
R7=Path(__file__).resolve().parent;SRC=R7.parent/'revision-r6-speaker/interactive';OUT=R7/'interactive'
files=['rebuild_viewer.py','build_viewer.py','r6-enclosure-viewer.template.html','mesh/export_r6_meshes.py','mesh/pack_display_meshes.py','mesh/verify_packed_mesh.py','focus/export_focus_meshes.py','focus/verify_focus_pack.py','dimensions/dimensions.json','qa/r6-viewer-qa.cjs']
for name in files:
 target=OUT/name.replace('r6','r7');target.parent.mkdir(parents=True,exist_ok=True)
 text=(SRC/name).read_text(encoding='utf-8').replace('R6','R7').replace('r6','r7')
 target.write_text(text,encoding='utf-8')
p=OUT/'mesh/export_r7_meshes.py';s=p.read_text();s=s.replace("R5=ENC/'revision-r5-sma';R4=", "R6=ENC/'revision-r6-speaker';R4=").replace("previous_path=R5/", "previous_path=R6/").replace("(R5/'interactive/mesh/MESH-VALIDATION.json')", "(R6/'interactive/mesh/MESH-VALIDATION.json')")
s=s.replace("if part['part'] not in ('base','lid')", "if part['part'] not in config['changed_semantics']").replace("if entry['part'] not in ('base','lid')", "if entry['part'] not in config['changed_semantics']").replace('reused_identically_from_R5','reused_identically_from_R6')
s=s.replace("if ident in ('base','lid'):continue", "if ident in ('base','lid') or record.get('reuse_mesh'):continue")
s=s.replace("R5 actual electronics, retained printed parts, battery/SMA and coax meshes retain exact arrays; source hashes and R7 native comparisons are recorded separately.", "R6 actual electronics, retained printed parts, battery and speaker-reference meshes retain exact arrays. R7 base, lid, retainer, key, nuts, ties and R10 coax are regenerated from audited shapes.")
s=s.replace("ctx['colors'].update(speaker=", "ctx['labels'].update(sma_key='Removable SMA anti-rotation key',speaker_tie='Loose speaker lead tie',coax_tie='Loose coax tie',sma_body='SMA bulkhead reference',coax='R10 LoRa coax reference')\nctx['colors'].update(sma_key=[.5,.5,.6],speaker_tie=[.3,.3,.3],coax_tie=[.3,.3,.3],sma_body=[.7,.6,.3],coax=[.3,.3,.3])\nctx['colors'].update(speaker=")
p.write_text(s)
p=OUT/'focus/export_focus_meshes.py';s=p.read_text();s=s.replace("NATIVE=R7/'cad/LoRa-Enclosure-C5-R7-Speaker.FCStd'\nR5=ENC/'revision-r5-sma'\nNATIVE=R5/'cad/LoRa-Enclosure-C5-R5-SMA.FCStd'", "R6=ENC/'revision-r6-speaker'\nNATIVE=R6/'cad/LoRa-Enclosure-C5-R6-Speaker.FCStd'")
s=s.replace('immutable retained R5 parts','immutable retained R6 parts');p.write_text(s)
p=OUT/'build_viewer.py';s=p.read_text().replace("'speaker_lead_a','speaker_lead_b'}", "'speaker_lead_a','speaker_lead_b','sma_key','speaker_tie','coax_tie'}");p.write_text(s)
p=OUT/'r7-enclosure-viewer.template.html';s=p.read_text(encoding='utf-8')
s=s.replace('    <button class="btn" type="button" data-inspection="coax_route">Coax route</button>', '    <button class="btn" type="button" data-inspection="coax_route">Coax route</button>\n    <button class="btn" type="button" data-inspection="microphone_path">Microphone path</button>')
needle="  const dimensionLabels=root.querySelector"
s=s.replace(needle,"  focusViews.set('microphone_path',{id:'microphone_path',overviewGeometry:true,fullHousing:true,target_mm:[54.5,30.5,16],frame_mm:[44,20,6,65,42,26],yaw:145,pitch:25,selected:'microphone',shell:'transparent'});\n"+needle)
s=s.replace("  const rad=Math.PI/180", "  Object.assign(labels,{sma_key:'SMA anti-rotation key',speaker_tie:'Speaker lead tie reference'});\n  Object.assign(details,{all:'R7 enclosure reinforcements · PCB and component positions unchanged',lid:'Strengthened OLED relief edges · Noncontact microphone shroud · 0.50 mm OLED datum gap',microphone:'14 mm assigned capsule · Shroud OD11 / ID8 mm · Minimum model clearance 0.70 mm',speaker_retainer:'3.2 mm retainer with 1.4 mm nut-bearing roof · Hard stop retained at Z16.4 mm',speaker_nuts:'M2 nut reference lowered 0.6 mm · M2 × 12 screw tip projects nominally 0.5 mm',speaker_tie:'Loose 2.5 mm lead-retention tie · Disconnect amplifier terminals before full lid removal',sma_key:'Removable 8 mm AF reference key · Actual bulkhead flats require fit check',coax:'R10 mm nominal sweep route · 132.2 mm centreline · Cable and connector fit remain provisional',coax_tie:'Loose 2.5 mm tie · Route support without crushing the coax'});\n  const rad=Math.PI/180")
s=s.replace("  const offset=m=>", "  Object.assign(offsets,{sma_key:[0,0,20],speaker_tie:[0,0,80]});\n  const offset=m=>")
s=s.replace("else if(id==='coax_tie')", "else if(id==='sma_key')c=mix(palette.series[2],bg,.18);\n      else if(id==='coax_tie'||id==='speaker_tie')")
s=s.replace("R7 backing, round bore and tie anchor · Hardware sizes remain provisional.", "R7 removable anti-rotation key and backing · Actual bulkhead dimensions require fit checking.")
s=s.replace("Provisional coax to the LoRa socket · Loose tie placement and remaining cable slack to verify.", "R10 mm nominal coax route to the LoRa socket · Loose tie and remaining cable slack to verify.")
s=s.replace("    if(state.mode==='exploded')root.querySelector", "    if(state.focus==='microphone_path')root.querySelector('#r7-dimension-note').textContent='Noncontact acoustic shroud · Minimum model clearance 0.70 mm · Does not clamp the capsule.';\n    if(state.mode==='exploded')root.querySelector")
p.write_text(s,encoding='utf-8')
p=OUT/'qa/r7-viewer-qa.cjs';s=p.read_text();s=s.replace("['speaker_mount','sma_mount','coax_route']", "['speaker_mount','sma_mount','coax_route','microphone_path']");s=s.replace("id==='sma_mount'?'sma_body':'coax'", "id==='sma_mount'?'sma_body':id==='microphone_path'?'microphone':'coax'")
s=s.replace("'speaker','speaker_retainer'])", "'speaker','speaker_retainer','sma_key','speaker_tie','coax_tie'])").replace("'speaker_retainer','speaker_lead_a'])", "'speaker_retainer','speaker_lead_a','sma_key','speaker_tie','coax_tie'])");p.write_text(s)
print('Seeded R7 viewer sources')
