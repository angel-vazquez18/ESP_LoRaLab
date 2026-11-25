from pathlib import Path
import json
OUT=Path(__file__).resolve().parent;ops=[];names=[]
for x,X in[(12.5,14.8),(31.2,33.5)]:
 for y,Y in[(44.4,45.6),(70.5,71.7)]:
  n='R7OLEDCornerReturn'+str(len(names)+1);names.append(n)
  ops.extend([
   {'tool':'create_object','args':{'type_id':'Part::Box','name':n+'Blank','properties':{'Length':X-x,'Width':Y-y,'Height':.7,'Visibility':False}}},
   {'tool':'cam_set_properties','args':{'object_name':n+'Blank','expressions':{'Placement':f'placement(vector({x};{y};22);rotation(0;0;0))'},'recompute':True}},
   {'tool':'fillet_edges','args':{'object_name':n+'Blank','radius':.2,'edges':['Edge2','Edge6','Edge10','Edge12'],'name':n}}])
r={'operations':ops,'link_deltas_to_merge':{'R7OLEDStrengthMask':{'append':names}}}
(OUT/'oled-corner-returns-addendum.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps({'operations':len(ops),'append':names}))
