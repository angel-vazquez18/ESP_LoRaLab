from pathlib import Path
import FreeCAD as App, Part, json, hashlib

root=Path(__file__).resolve().parent
file=root/'C5-detailed-assembly.step'
doc=App.newDocument('OfflineCorrectedAssemblyCheck')
print('CORRECTED_IMPORT_START',flush=True)
Part.insert(str(file),doc.Name)
rows=[]
for index,obj in enumerate(doc.Objects):
    if not hasattr(obj,'Shape') or obj.Shape.isNull():continue
    b=obj.Shape.BoundBox
    rows.append({'index':index,'name':obj.Name,'bbox':[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax],'faces':len(obj.Shape.Faces)})
start=next(i for i,r in enumerate(rows) if abs(r['bbox'][0]-47.5)<1e-6 and abs(r['bbox'][3]-61.5)<1e-6 and r['faces']>1000)
end=next(i for i in range(start,len(rows)) if rows[i]['bbox'][1]>50)
mic=rows[start:end]
bounds=[min(r['bbox'][j] for r in mic) for j in range(3)]+[max(r['bbox'][j] for r in mic) for j in range(3,6)]
assert abs(bounds[3]-bounds[0]-14)<1e-6,bounds
report={'file':str(file),'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'object_count':len(doc.Objects),'microphone_object_index_range':[mic[0]['index'],mic[-1]['index']],'microphone_parts':len(mic),'microphone_bounds_mm':bounds,'microphone_diameter_x_mm':bounds[3]-bounds[0],'part_origin_mm':[54.5,30.5,1.5186],'mic_footprint_scale_prebaked':1/2.54,'native_live_import_note':'The earlier live import used an oversized MIC with different topology. Its original repair mapping is647objects1068..1714; this report describes the corrected file only.'}
(root/'corrected-assembly-check.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report),flush=True)
App.closeDocument(doc.Name)
