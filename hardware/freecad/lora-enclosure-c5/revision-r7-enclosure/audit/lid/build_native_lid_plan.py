"""Prepare/replay native operations in memory; never save source or FCStd."""
from pathlib import Path
import FreeCAD as A, Part, json, hashlib
OUT=Path(__file__).resolve().parent;ENC=OUT.parents[2]
NATIVE=ENC/'revision-r6-speaker/cad/LoRa-Enclosure-C5-R6-Speaker.FCStd'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();initial=sha(NATIVE)
d=A.openDocument(str(NATIVE));ops=[]
def add(tool,**args):ops.append({'tool':tool,'args':args})
def create(name,typ,props=None):
 props=props or {};add('create_object',type_id=typ,name=name,properties=dict(props,Visibility=False))
 o=d.addObject(typ,name)
 for k,v in props.items():setattr(o,k,v)
 return o
def expr(name,**values):
 add('cam_set_properties',object_name=name,expressions=values,recompute=True)
 for k,v in values.items():d.getObject(name).setExpression(k,str(v))
 d.recompute()
def place(name,x,y,z):expr(name,Placement=f'placement(vector({x};{y};{z});rotation(0;0;0))')
def makebox(name,bounds):
 x,y,z,X,Y,Z=bounds;o=create(name,'Part::Box',{'Length':X-x,'Width':Y-y,'Height':Z-z});place(name,x,y,z);return o
def cylinder(name,r,h,x,y,z):
 o=create(name,'Part::Cylinder',{'Radius':r,'Height':h});place(name,x,y,z);return o
def fillet(name,base,r,indices=None):
 b=d.getObject(base);indices=indices or list(range(1,len(b.Shape.Edges)+1))
 add('fillet_edges',object_name=base,radius=r,edges=['Edge'+str(i)for i in indices],name=name)
 o=d.addObject('Part::Fillet',name);o.Base=b;o.Edges=[(i,r,r)for i in indices];d.recompute();return o
def cut(name,base,tool):
 add('boolean_operation',operation='cut',object1_name=base,object2_name=tool,result_name=name)
 o=d.addObject('Part::Cut',name);o.Base=d.getObject(base);o.Tool=d.getObject(tool);o.Refine=True;d.recompute();return o
def union(name,names):
 o=create(name,'Part::MultiFuse');add('cam_set_properties',object_name=name,values={'Shapes':names},recompute=True);o.Shapes=[d.getObject(n)for n in names];o.Refine=True;d.recompute();return o
def shape_delta(a,b):
 return {'symmetric_difference_mm3':a.cut(b).Volume+b.cut(a).Volume,'volume_difference_mm3':abs(a.Volume-b.Volume),'valid':a.isValid(),'solids':len(a.Solids)}
add('spreadsheet_set_cell',spreadsheet_name='SpeakerParameters',cell='B11',value=3.2);d.SpeakerParameters.set('B11','3.2');d.recompute()
for i,(x,y)in enumerate([(43.5,47),(65.5,42)],1):
 place('ReferenceSpeakerNutBlank'+str(i),x,y,'SpeakerParameters.B6-SpeakerParameters.B7-SpeakerParameters.B3-SpeakerParameters.B8-SpeakerParameters.B11+0.2')
 place('ReferenceSpeakerNutBore'+str(i),x,y,'SpeakerParameters.B6-SpeakerParameters.B7-SpeakerParameters.B3-SpeakerParameters.B8-SpeakerParameters.B11+0.1')

cylinder('R7MicrophoneShroudBlank',5.5,8.2,54.5,30.5,13)
fillet('R7MicrophoneShroudRounded','R7MicrophoneShroudBlank',.4)
cylinder('R7MicrophoneShroudBore',4,8.5,54.5,30.5,12.9)
cut('R7MicrophoneShroud','R7MicrophoneShroudRounded','R7MicrophoneShroudBore')
for i,y in enumerate([42.2,71.55],1):
 makebox('R7OLEDStrengthBandBlank'+str(i),[12.5,y,22,33.5,y+2.35,22.7]);fillet('R7OLEDStrengthBand'+str(i),'R7OLEDStrengthBandBlank'+str(i),.2,[2,6,10,12])
return_names=[];return_ops_start=len(ops)
for x,X in[(12.5,14.8),(31.2,33.5)]:
 for y,Y in[(44.4,45.6),(70.5,71.7)]:
  name='R7OLEDCornerReturn'+str(len(return_names)+1)
  makebox(name+'Blank',[x,y,22,X,Y,22.7]);fillet(name,name+'Blank',.2,[2,6,10,12]);return_names.append(name)
return_ops=ops[return_ops_start:]
union('R7OLEDStrengthMask',['R7OLEDStrengthBand1','R7OLEDStrengthBand2']+return_names)
cutters=[o.Name for o in d.LidCutters.Shapes]
recess=[n for n in cutters if 'Recess' in n]
assert len(recess)==1,recess
cut('R7OLEDRecessCutter',recess[0],'R7OLEDStrengthMask')
makebox('R7SpeakerTieAnchorBlank',[68.3,53.6,16.8,70,59,21.2]);fillet('R7SpeakerTieAnchorRounded','R7SpeakerTieAnchorBlank',.4)
makebox('R7SpeakerTieSlot',[68.2,54.8,18.7,70.1,57.8,19.5]);cut('R7SpeakerTieAnchor','R7SpeakerTieAnchorRounded','R7SpeakerTieSlot')

# Installed loose tie reference: a rounded XZ loop extruded alongY, plus head.
for name,bounds,r in [('R7SpeakerTieOuter',[65.2,55.05,16,71.3,57.55,19.35],.8),('R7SpeakerTieInner',[65.65,54.95,16.45,70.85,57.65,18.9],.35)]:
 o=makebox(name+'Blank',bounds);width=bounds[4]-bounds[1]
 ids=[i for i,e in enumerate(o.Shape.Edges,1)if len(e.Vertexes)==2 and abs(e.Vertexes[1].Point.y-e.Vertexes[0].Point.y)>width-1e-7]
 fillet(name,name+'Blank',r,ids)
cut('R7SpeakerTieLoop','R7SpeakerTieOuter','R7SpeakerTieInner')
makebox('R7SpeakerTieHeadBlank',[66.8,54.05,13.6,71.3,58.55,16.3]);fillet('R7SpeakerTieHead','R7SpeakerTieHeadBlank',.3)
union('ReferenceSpeakerTie',['R7SpeakerTieLoop','R7SpeakerTieHead'])
makebox('R7SpeakerTieLipRelief',[70.1,54.55,19.25,72.2,58.05,19.8])

changes={'LidWithClamps':{'append':['R7MicrophoneShroud','R7SpeakerTieAnchor']},
 'LidCutters':{'replace':{recess[0]:'R7OLEDRecessCutter'},'append':['R7SpeakerTieLipRelief']}}
# Replay dependency edits for equivalence only. Root must MERGE these with
# antenna-agent link changes, never overwrite the complete link lists.
d.LidWithClamps.Shapes=list(d.LidWithClamps.Shapes)+[d.R7MicrophoneShroud,d.R7SpeakerTieAnchor]
d.LidCutters.Shapes=[d.getObject('R7OLEDRecessCutter'if o.Name==recess[0]else o.Name)for o in d.LidCutters.Shapes]+[d.R7SpeakerTieLipRelief]
d.recompute()
comparisons={}
for n in ['EnclosureLid','SpeakerRetainer','ReferenceSpeakerTie']:
 s=Part.Shape();s.read(str(OUT/(n+'.brep')));comparisons[n]=shape_delta(d.getObject(n).Shape,s)
assert all(v['valid'] and v['symmetric_difference_mm3']<1e-6 for v in comparisons.values()),comparisons
unchanged=sha(NATIVE)==initial;assert unchanged
plan={'source_sha256':initial,'operations':ops,'link_deltas_to_merge':changes,
 'printable_final_names':['EnclosureLid','SpeakerRetainer'],
 'reference_final_names':['ReferenceSpeakerTie','ReferenceSpeakerNut1','ReferenceSpeakerNut2'],
 'hide': [o['args']['name']for o in ops if o['tool']in['create_object','fillet_edges']and'name'in o['args']]+[o['args']['result_name']for o in ops if o['tool']=='boolean_operation'],
 'equivalence_to_audited_candidate':comparisons,'source_unchanged':unchanged,
 'notes':['SpeakerParameters B11 drives blank, window, nut-pocket and screw-hole elevations. Existing M2x12 shafts remain fixed; new nuts13.4..15.0 leave0.5mmnominal exposedthread below.',
 'The OLED strengthmask modifies only the recesscutter. Mainlocalface22.1 andunderside/window aperture unchanged; shortedgebands top22.7.',
 'Microphone shroud has0.7mmminimum tohighest assignedcapsulefeatures; it does not clamp or sealunmeasuredhardware. Optionalsoftgasket requires actualfit.',
 'Tie is a loose 2.5 mm wide, 0.45 mm thick reference with 4.5 x 4.5 x 2.7 mm head. Actual tie must fit this envelope; do not tighten onto insulation or claim strain qualification.',
 'ReferenceSpeakerTie is nonprinted. NoPCB,componentplacement,firmwareorownedwirelengthchange.']}
(OUT/'native-lid-operation-plan-final.json').write_text(json.dumps(plan,indent=2)+'\n')
(OUT/'oled-corner-returns-addendum.json').write_text(json.dumps({'operations':return_ops,'link_deltas_to_merge':{'R7OLEDStrengthMask':{'append':return_names}}},indent=2)+'\n')
print(json.dumps({'ok':True,'operations':len(ops),'links':changes,'comparisons':comparisons,'source_unchanged':unchanged}))
A.closeDocument(d.Name)
