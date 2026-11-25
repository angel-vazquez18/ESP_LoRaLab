from pathlib import Path
import json
OUT=Path(__file__).resolve().parent
ops=[]
def op(tool,**args):ops.append({'tool':tool,'args':args})
def primitive(kind,name,expr,props=None):
 op('create_object',type_id=kind,name=name,properties=dict({'Visibility':False},**(props or {})))
 op('cam_set_properties',object_name=name,expressions={k:str(v)for k,v in expr.items()},recompute=True)
def box(name,a,b,r=None,result=None):
 primitive('Part::Box',name,{'Length':b[0]-a[0],'Width':b[1]-a[1],'Height':b[2]-a[2],
  'Placement':f'placement(vector({a[0]};{a[1]};{a[2]});rotation(0;0;0))'})
 if r is not None:op('fillet_edges',object_name=name,radius=r,name=result)
def union(name,children):op('create_object',type_id='Part::MultiFuse',name=name,properties={'Shapes':children,'Visibility':False})
op('spreadsheet_create',name='AntennaParameters')
for i,(label,value)in enumerate([('Rear-key parallel jaw gap (mm)',8.4),('Illustrative rear hex AF (mm)',8),('Key guide clearance per side (mm)',.3),('Key top Z (mm)',20.3),('Coax reference centerline bend (mm)',10),('Coax reference OD (mm)',1.32)],1):
 for c,v in [('A',label),('B',value)]:op('spreadsheet_set_cell',spreadsheet_name='AntennaParameters',cell=f'{c}{i}',value=v)
op('spreadsheet_set_cell',spreadsheet_name='Parameters',cell='B99',value=4.2)
box('SMAKeyCarrierBlank',[38.5,87.8,9.2],[55.5,92.2,20.6],.4,'SMAKeyCarrier')
primitive('Part::Box','SMAKeyPocket',{'Length':'14+2*AntennaParameters.B3','Width':'2+2*AntennaParameters.B3','Height':10.8,
 'Placement':'placement(vector(Parameters.B40-7-AntennaParameters.B3;89.6-AntennaParameters.B3;10.4);rotation(0;0;0))'})
primitive('Part::Box','SMAKeyBlank',{'Length':14,'Width':2,'Height':'AntennaParameters.B4-10.4',
 'Placement':'placement(vector(Parameters.B40-7;89.6;10.4);rotation(0;0;0))'})
op('fillet_edges',object_name='SMAKeyBlank',radius=.3,name='SMAKeyRounded')
primitive('Part::Box','SMAKeyJawRelief',{'Length':'AntennaParameters.B1','Width':2.2,'Height':8.9,
 'Placement':'placement(vector(Parameters.B40-AntennaParameters.B1/2;89.5;10.3);rotation(0;0;0))'})
op('boolean_operation',operation='cut',object1_name='SMAKeyRounded',object2_name='SMAKeyJawRelief',result_name='SMAKey')
box('R7CoaxAnchorBodyBlank',[55,84,14],[61.5,89.8,18],.4,'R7CoaxAnchorBody')
box('R7CoaxAnchorNeckBlank',[60,89.2,14],[61.5,92.2,18],.4,'R7CoaxAnchorNeck')
union('R7CoaxAnchor',['R7CoaxAnchorBody','R7CoaxAnchorNeck'])
box('R7CoaxTieSlotBlank',[56.5,83.9,15.2],[59.5,89.9,16.7],.35,'R7CoaxTieSlot')
box('SMAKeyLipRelief',[38.1,87.4,18.8],[55.9,92,21])
box('SMATieLipRelief',[55.35,89.8,19],[60.65,91.1,21])

reference=[]
saved=ops;ops=reference
primitive('Part::Prism','ReferenceSMAFixedHexR7',{'Circumradius':'AntennaParameters.B2/sqrt(3)','Height':2.6,
 'Placement':'placement(vector(Parameters.B40;89.4;Parameters.B96);rotation(0;30;-90))'},{'Polygon':6})
primitive('Part::Cylinder','ReferenceSMATailR7',{'Radius':3,'Height':7.4,
 'Placement':'placement(vector(Parameters.B40;82;Parameters.B96);rotation(0;0;-90))'})
union('ReferenceSMARearBodyR7',['ReferenceSMAFixedHexR7','ReferenceSMATailR7'])

plan={'revision':'R7','scope':'Enclosure-only antenna key, corrected tie anchor and local lid clearance; PCB/component mounting datums unchanged',
 'native_operations':saved,'reference_operations':reference,
 'link_updates':{'BaseWithSupports':{'remove':['SMACoaxAnchor'],'add':['SMAKeyCarrier','R7CoaxAnchor']},'BaseCutters':{'remove':['SMACoaxTieSlot'],'add':['SMAKeyPocket','R7CoaxTieSlot']},'LidCutters':{'remove':[],'add':['SMAKeyLipRelief','SMATieLipRelief']}},
 'hide_superseded_reference':['ReferenceSMARearBody'],'printed_extra_part':'SMAKey',
 'important':['Use native Part::MultiFuse links, not static fuse_all output.','Native operations omit doc_name intentionally; root adds current GUI document.','Hide primitives/cutters/reference body from all manufacturingexports.','Reference rear hex8mmAF is illustrative; ownedhardware must be gauged. Published mountingnutAF doesnotidentify rearbodyAF.','Key jaw gap is parametric; do not alter original roundbulkheadbore or2.4mmseat withoutmeasurement.'],
 'key_dimensions_mm':{'outer':[40,89.6,10.4,54,91.6,20.3],'jaw_relief':[42.8,89.5,10.3,51.2,91.7,19.2],'outer_fillet':.3,'jaw_gap':8.4,'roof_thickness_nominal':1.1,'guide_clearance_per_side':.3,'roof_clearance_to_lid':.7,'floor_contact_z':10.4},
 'new_hardware':[{'quantity':1,'item':'Loose2.5mmwide cabletie','reference_strap_thickness_mm':.5,'note':'Physicalfit of head, closure,flexibility and preload requirescheck; intendedonlyto guideinsulatedcoax.'}],
 'route':{'file':'route-r10-audit.json','brep':'CoaxR10Final.brep','centerline_radius_mm':10,'assumed_diameter_mm':1.32,'length_mm':132.16519583282542,'note':'Actualkit usable leadlength/OD/bend limitunverified;169mm pictured assembly isnot guaranteedavailablecable length. Extraactualslackmustbe fittedwithoutpinching.'}}
(OUT/'antenna-native-plan.json').write_text(json.dumps(plan,indent=2)+'\n')
print('Wrote',len(saved),'native operations plus',len(reference),'reference operations')
