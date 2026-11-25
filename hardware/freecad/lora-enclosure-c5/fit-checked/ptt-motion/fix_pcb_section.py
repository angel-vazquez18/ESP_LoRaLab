import json,pathlib,hashlib,time
import FreeCAD as App
import Part
OUT=pathlib.Path(__file__).resolve().parent
SOURCE=OUT.parent/'cutaway-view'/'LoRa-Enclosure-C5-Assembled-Cutaway.FCStd'
P=OUT/'ptt-section-geometry.json'
data=json.loads(P.read_text(encoding='utf-8'))
before={k:json.dumps(v,sort_keys=True) for k,v in data['parts'].items() if k!='PTTDetailPCB'}
source_hash=hashlib.sha256(SOURCE.read_bytes()).hexdigest()
doc=App.openDocument(str(SOURCE));s=doc.getObject('PTTDetailPCB').Shape.copy();Y=9.0001
def bbox(s):
 b=s.BoundBox;return[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
audit=[];faces=[]
plane=Part.makePlane(100,40,App.Vector(0,Y,40),App.Vector(0,1,0),App.Vector(1,0,0))
for i,solid in enumerate(s.Solids):
 sec=solid.section(plane)
 wires=[Part.Wire(es) for es in Part.sortEdges(sec.Edges)] if sec.Edges else []
 fs=[Part.Face(w) for w in wires if w.isClosed()]
 audit.append({'solid_index':i,'bbox_mm':bbox(solid),'volume_mm3':solid.Volume,'section_wires':len(wires),'section_area_mm2':sum(f.Area for f in fs)})
 faces.extend(fs)
assert faces,'No individual-solid sections'
combined=faces[0]
for f in faces[1:]:combined=combined.fuse(f)
combined=combined.removeSplitter()
closed=[]
for w in combined.Wires:
 assert w.isClosed()
 ps=[[round(p.x,9),round(p.z,9)] for p in w.discretize(Deflection=.005)]
 if ps and ps[0]!=ps[-1]:ps.append(ps[0])
 if ps:closed.append(ps)
path=' '.join('M '+' L '.join(f'{x:.8f} {z:.8f}' for x,z in p[:-1])+' Z' for p in closed)
print(json.dumps({'diagnostic_source_solids':audit,'source_bbox':bbox(s),'source_volume':s.Volume,'combined_area':combined.Area},indent=2),flush=True)
assert combined.Area>30,combined.Area
assert combined.BoundBox.XLength>25.9,combined.BoundBox
data['parts']['PTTDetailPCB']={'source_object':'PTTDetailPCB','section_y_mm':Y,'shape_bbox_mm':bbox(s),'shape_valid':s.isValid(),'solid_count':len(s.Solids),'closed_loops_xz':closed,'open_polylines_xz':[],'svg_path_xz':path,'svg_open_path_xz':'','svg_fill_rule':'evenodd','closed_loop_count':len(closed),'open_polyline_count':0,'point_count':sum(map(len,closed)),'section_area_mm2':combined.Area,'section_bbox_mm':bbox(combined),'extraction_method':'Slice every solid of actual cropped PCB separately, convert closed wires to planar faces, then fuse their actual sections. No substituted primitive geometry.'}
unchanged=all(before[k]==json.dumps(data['parts'][k],sort_keys=True) for k in before)
assert unchanged
P.write_text(json.dumps(data,indent=2),encoding='utf-8')
report={'ok':True,'source_file':str(SOURCE),'source_sha256':source_hash,'source_unchanged':hashlib.sha256(SOURCE.read_bytes()).hexdigest()==source_hash,'part':'PTTDetailPCB','source_solids':audit,'combined_section_area_mm2':combined.Area,'combined_section_bbox_mm':bbox(combined),'closed_loops':len(closed),'points':sum(map(len,closed)),'other_parts_and_endpoints_unchanged':unchanged}
(OUT/'pcb-section-correction.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
