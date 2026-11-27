"""Generate direct-MCP native feature instructions; does not call FreeCAD."""
from pathlib import Path
import json
out=Path(__file__).resolve().parents[1]
rows=[
 ['BatteryBayDepth',14,'Rear clear cavity depth below original outside floor'],
 ['BatteryCoverThickness',2.4,'Rear cover plate thickness'],
 ['BatteryPostDiameter',8,'Rear M3 insert support diameter'],
 ['BatteryInsertDepth',4.5,'Rear blind pilot depth for4mm insert'],
 ['BatteryHoodTop',11.1,'Printed chimney top remains belowUSBopening'],
 ['BatteryHoodBack',99.6,'Rear local outside extent'],
 ['BatteryHoodChaseBack',97.2,'Rear chase inside extent'],
 ['BatteryEnvelopeWidth',36,'Conservative width;photo35/modelcode36'],
 ['BatteryEnvelopeLength',68,'Photo overallpouchlength'],
 ['BatteryEnvelopeThickness',10,'Photo nominalpouchthickness'],
 ['BatteryFloorAllowance',1,'Space fornonconductivepadding belowpouch'],
 ['BatteryStrapWidth',10,'Nominalsoftnonconductiveretentionstrap'],
 ['BatteryStrapSlotWidth',2.4,'Strap-slot narrow dimension'],
]
ops=[]
def call(tool,**args):ops.append(dict(tool=tool,args=args))
def create(typ,name,**props):call('create_object',type_id=typ,name=name,properties={'Visibility':False,**props})
def setup(name,values=None,**expr):call('cam_set_properties',object_name=name,values={'Visibility':False,**(values or {})},expressions=expr,recompute=True)
def place(x,y,z):return f'placement(vector({x}; {y}; {z}); rotation(0;0;0))'
def box(name,l,w,h,x,y,z,r=None):
 raw=name+'Blank' if r else name
 create('Part::Box',raw)
 setup(raw,Length=l,Width=w,Height=h,Placement=place(x,y,z))
 if r:call('fillet_edges',object_name=raw,name=name,radius=r,edges=['Edge1','Edge3','Edge5','Edge7'])
 return name
def cyl(name,r,h,x,y,z):
 create('Part::Cylinder',name);setup(name,Radius=r,Height=h,Placement=place(x,y,z));return name
def cut(name,base,tool):
 create('Part::Cut',name);setup(name,values={'Base':base,'Tool':tool,'Refine':True});return name
def fuse(name,parts):
 create('Part::MultiFuse',name);setup(name,values={'Shapes':parts,'Refine':True});return name
box('BatteryBayOuter','Parameters.B45','Parameters.B46','Parameters.B83+0.2','-Parameters.B4-Parameters.B5','-Parameters.B4-Parameters.B5','-Parameters.B83',4.5)
box('BatteryBayCavity','Parameters.B1+2*Parameters.B4','Parameters.B2+2*Parameters.B4','Parameters.B83+0.4','-Parameters.B4','-Parameters.B4','-Parameters.B83-0.1',2.1)
cut('BatteryBayTube','BatteryBayOuter','BatteryBayCavity')
base_add=['BatteryBayTube'];base_cuts=[];cover_holes=[]
centers=[('Parameters.B10','Parameters.B10'),('Parameters.B1-Parameters.B10','Parameters.B10'),('Parameters.B10','Parameters.B2-Parameters.B10'),('Parameters.B1-Parameters.B10','Parameters.B2-Parameters.B10')]
for i,(x,y)in enumerate(centers,1):
 base_add.append(cyl(f'RearPost{i}','Parameters.B85/2','Parameters.B83+0.2',x,y,'-Parameters.B83'))
 base_add.append(box(f'RearWeb{i}','Parameters.B4+Parameters.B10','Parameters.B5','Parameters.B83-2.8','-Parameters.B4' if i in(1,3)else'Parameters.B1-Parameters.B10',f'({y})-Parameters.B5/2','-Parameters.B83+3'))
 base_cuts.append(cyl(f'RearInsertBore{i}','Parameters.B12/2','Parameters.B86+0.1',x,y,'-Parameters.B83-0.1'))
 cover_holes.append(cyl(f'RearCoverHole{i}','Parameters.B14/2','Parameters.B84+0.6',x,y,'-Parameters.B83-Parameters.B84-0.2'))
base_add.append(box('BatteryHarnessHood','14','Parameters.B88-Parameters.B2-Parameters.B4','Parameters.B83+Parameters.B87','Parameters.B18-2','Parameters.B2+Parameters.B4','-Parameters.B83'))
base_cuts.append(box('BatteryHarnessChase','9.2','Parameters.B89-Parameters.B2-Parameters.B4+0.1','Parameters.B83+13.3','Parameters.B18+0.4','Parameters.B2+Parameters.B4-0.1','-Parameters.B83-0.1'))
box('BatteryCoverPlate','Parameters.B45','Parameters.B46','Parameters.B84','-Parameters.B4-Parameters.B5','-Parameters.B4-Parameters.B5','-Parameters.B83-Parameters.B84',4.5)
box('BatteryCoverLipOuter','Parameters.B1+2*Parameters.B4-2*Parameters.B17','Parameters.B2+2*Parameters.B4-2*Parameters.B17','Parameters.B15+0.2','-Parameters.B4+Parameters.B17','-Parameters.B4+Parameters.B17','-Parameters.B83-0.2',1.7)
box('BatteryCoverLipInner','Parameters.B1+2*Parameters.B4-2*Parameters.B17-2*Parameters.B16','Parameters.B2+2*Parameters.B4-2*Parameters.B17-2*Parameters.B16','Parameters.B15+0.4','-Parameters.B4+Parameters.B17+Parameters.B16','-Parameters.B4+Parameters.B17+Parameters.B16','-Parameters.B83-0.3',.5)
cut('BatteryCoverLip','BatteryCoverLipOuter','BatteryCoverLipInner')
cover_add=['BatteryCoverPlate','BatteryCoverLip',box('BatteryCoverHoodTab','14','Parameters.B88-Parameters.B2-Parameters.B4','Parameters.B84','Parameters.B18-2','Parameters.B2+Parameters.B4','-Parameters.B83-Parameters.B84')]
for i,(side,offset)in enumerate([(-1,-22),(1,-22),(-1,8),(1,8)],1):
 x='Parameters.B1/2-Parameters.B90/2-3'if side<0 else'Parameters.B1/2+Parameters.B90/2+1'
 cover_add.append(box(f'BatterySideGuide{i}','2','14','3.1',x,f'Parameters.B2/2+({offset})','-Parameters.B83-0.1',.8))
for i,y in enumerate(['Parameters.B2/2-Parameters.B91/2-3','Parameters.B2/2+Parameters.B91/2+1'],1):
 cover_add.append(box(f'BatteryEndGuide{i}','18','2','3.1','Parameters.B1/2-9',y,'-Parameters.B83-0.1',.8))
cover_cuts=cover_holes[:]
for i,(side,dy)in enumerate([(-1,-15),(1,-15),(-1,15),(1,15)],1):
 x='Parameters.B1/2-Parameters.B90/2-4.8'if side<0 else'Parameters.B1/2+Parameters.B90/2+4.8'
 y=f'Parameters.B2/2+({dy})';length='Parameters.B94+2';width='Parameters.B95';midlen=f'({length})-({width})'
 pieces=[box(f'BatteryStrapSlot{i}Web',width,midlen,'Parameters.B84+0.3',f'({x})-({width})/2',f'({y})-({midlen})/2','-Parameters.B83-Parameters.B84-0.1')]
 for j,s in enumerate([-1,1],1):pieces.append(cyl(f'BatteryStrapSlot{i}End{j}',f'({width})/2','Parameters.B84+0.3',x,f'({y})+({s})*({midlen})/2','-Parameters.B83-Parameters.B84-0.1'))
 cover_cuts.append(fuse(f'BatteryStrapSlot{i}',pieces))
for i,dy in enumerate([-15,15],1):
 cover_cuts.append(box(f'BatteryStrapChannel{i}','Parameters.B90+9.6','Parameters.B94+2','1.1','Parameters.B1/2-Parameters.B90/2-4.8',f'Parameters.B2/2+({dy})-(Parameters.B94+2)/2','-Parameters.B83-Parameters.B84-0.1'))
cover_cuts.append(box('BatteryCoverLipRoute','9.2','Parameters.B4+Parameters.B5-0.2','Parameters.B15+0.1','Parameters.B18+0.4','Parameters.B2+0.3','-Parameters.B83'))
fuse('BatteryCoverMaterial',cover_add);fuse('BatteryCoverCutters',cover_cuts);cut('BatteryCover','BatteryCoverMaterial','BatteryCoverCutters')
box('ReferenceBatteryEnvelope','Parameters.B90','Parameters.B91','Parameters.B92','(Parameters.B1-Parameters.B90)/2','(Parameters.B2-Parameters.B91)/2','-Parameters.B83+Parameters.B93')
setup('ReferenceBatteryEnvelope',values={'Label':'REFERENCE ONLY - LiPo 68 x 36 x 10 mm envelope','Visibility':False})
record=dict(parameter_start_row=83,parameter_rows=rows,operations=ops,base_fuse_additions=base_add,base_cutter_additions=base_cuts,
 final_objects=['EnclosureBase','EnclosureLid','PTTPlunger','PTTStopCup','BatteryCover'],
 root_final_steps=['Append base_fuse_additions to existing BaseWithSupports.Shapes; do not replace existing members.','Append base_cutter_additions to BaseCutters.Shapes; do not replace existing members.','Show EnclosureBase and BatteryCover; hide all intermediate objects and reference envelope for print export.'],
 reference_envelope='ReferenceBatteryEnvelope',
 revised_rear_screws='Four M3x6 buttonhead screws,3.6mm nominal engagement after2.4mm cover. Do notuse8mm screwsagainst4mm blindinsert.',
 connector_chase_top_z=13.2,hood_material_top_z=11.1,
 scope='Native parametric operation plan only; no GUI mutations or file-review bypass.')
(out/'native-battery-operations-plan.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'operations':len(ops),'parameter_rows':len(rows),'path':str(out/'native-battery-operations-plan.json'),'base_additions':base_add,'base_cutters':base_cuts}))
