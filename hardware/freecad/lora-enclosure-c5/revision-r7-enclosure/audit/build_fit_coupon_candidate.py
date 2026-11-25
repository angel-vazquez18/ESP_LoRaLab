"""Build only derived coupon BREP/audit and exact native MCP operation plan.

No GUI mutation, native-document save or manufacturing mesh export occurs.
"""
from pathlib import Path
from collections import Counter,defaultdict
import math,json,hashlib
import FreeCAD as A,Part,MeshPart

OUT=Path(__file__).resolve().parent
PLAN=OUT/'fit-coupon-plan.json'
p=json.loads(PLAN.read_text())
ops=[]

def op(tool,**args):ops.append({'tool':tool,'args':args})
def primitive(item):
    name,typ=item['name'],item['type'];xyz=item['origin']
    if typ=='Part::Box':
        props=dict(zip(['Length','Width','Height'],item['size']))
        s=Part.makeBox(*item['size'],A.Vector(*xyz))
    elif typ=='Part::Cylinder':
        props={'Radius':item['radius'],'Height':item['height']}
        s=Part.makeCylinder(item['radius'],item['height'],A.Vector(*xyz))
    elif typ=='Part::Prism':
        radius=item['across_flats']/math.sqrt(3)
        props={'Polygon':6,'Circumradius':radius,'Height':item['height']}
        points=[A.Vector(xyz[0]+radius*math.cos(i*math.pi/3),xyz[1]+radius*math.sin(i*math.pi/3),xyz[2]) for i in range(7)]
        s=Part.Face(Part.makePolygon(points)).extrude(A.Vector(0,0,item['height']))
    else:raise ValueError(typ)
    op('create_object',type_id=typ,name=name,properties={'Visibility':False})
    expr={k:str(v) for k,v in props.items()}
    expr['Placement']='placement(vector('+(';'.join(str(v)for v in xyz))+');rotation(0;0;0))'
    op('cam_set_properties',object_name=name,expressions=expr,recompute=True)
    return s

plate=primitive(p['plate'])
plate=plate.makeFillet(p['plate']['all_edge_fillet'],plate.Edges)
op('fillet_edges',object_name='R7CouponPlate',radius=.5,name='R7CouponPlateRounded')
added=[primitive(i)for i in p['additions']]
tools=[primitive(i)for i in p['cuts']]
base=plate.multiFuse(added).removeSplitter()
cutters=tools[0].multiFuse(tools[1:])
shape=base.cut(cutters).removeSplitter()
for name,links in [('R7CouponMaterial',['R7CouponPlateRounded']+[i['name']for i in p['additions']]),('R7CouponCutters',[i['name']for i in p['cuts']])]:
    op('create_object',type_id='Part::MultiFuse',name=name,properties={'Visibility':False})
    op('cam_set_properties',object_name=name,values={'Shapes':links,'Refine':True,'Visibility':False},recompute=True)
op('boolean_operation',operation='cut',object1_name='R7CouponMaterial',object2_name='R7CouponCutters',result_name='R7FitCoupon')
op('cam_set_properties',object_name='R7FitCoupon',values={'Refine':True,'Label':'OPTIONAL - fit coupon (not installed)'},expressions={'Placement':'placement(vector(100;0;0);rotation(0;0;0))'},recompute=True)
shape.translate(A.Vector(100,0,0))
assert shape.isValid()and shape.isClosed()and len(shape.Solids)==1
destination=OUT/'R7FitCoupon.brep';shape.exportBrep(str(destination))

# In-memory tessellation audit; no STL/3MF file is written.
mesh=MeshPart.meshFromShape(Shape=shape,LinearDeflection=.05,AngularDeflection=.35,Relative=False)
triangles=[tuple(tuple(float(v)for v in point)for point in f.Points)for f in mesh.Facets]
vertices={};edges=defaultdict(list);adj=[set()for _ in triangles];degenerate=0
for index,tri in enumerate(triangles):
    ids=[]
    for point in tri:
        k=tuple(round(v,8)for v in point)
        if k not in vertices:vertices[k]=len(vertices)
        ids.append(vertices[k])
    a,b,c=[A.Vector(*v)for v in tri]
    degenerate+=len(set(ids))<3 or ((b-a).cross(c-a)).Length<1e-12
    for u,v in zip(ids,ids[1:]+ids[:1]):edges[tuple(sorted((u,v)))].append((index,u<v))
for owners in edges.values():
    for first,second in zip(owners,owners[1:]):adj[first[0]].add(second[0]);adj[second[0]].add(first[0])
seen=set();components=0
for i in range(len(triangles)):
    if i in seen:continue
    components+=1;todo=[i];seen.add(i)
    while todo:
        j=todo.pop()
        for k in adj[j]-seen:seen.add(k);todo.append(k)
bad_edges=sum(len(o)!=2 for o in edges.values())
bad_winding=sum(len(o)==2 and o[0][1]==o[1][1]for o in edges.values())
assert not bad_edges and not bad_winding and not degenerate and components==1
b=shape.optimalBoundingBox(False,False)
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
report={'ok':True,'scope':'Derived candidate geometry and in-memory topology only; not a manufacturing export or physical fit qualification.',
    'native_source_modified':False,'optional_not_installed':True,'display_translation_mm':[100,0,0],
    'plan_sha256':sha(PLAN),'brep_sha256':sha(destination),'volume_mm3':shape.Volume,
    'bounds_mm':[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax],
    'valid':shape.isValid(),'closed':shape.isClosed(),'solids':len(shape.Solids),
    'mesh':{'triangles':len(triangles),'vertices':len(vertices),'bad_edges':bad_edges,'inconsistent_winding':bad_winding,'degenerate':degenerate,'components':components},
    'dimensions':{'plate':[50,32,3.2],'insert_pilots':[4.4,4.5],'insert_pilot_depth':5,'insert_floor':1,'boss_outer_diameter':7,'guide_bore':8.8,'guide_depth':3.6,'hex_pockets_AF':[4.2,4.3,4.4],'hex_depth':1.8,'nut_bearing_roof':1.4,'screw_bores':2.4}}
(OUT/'fit-coupon-audit.json').write_text(json.dumps(report,indent=2)+'\n')
(OUT/'fit-coupon-native-operations.json').write_text(json.dumps({'scope':'Optional R7 fit coupon; add doc_name to every call; only root executes approved bridge operations.','operations':ops},indent=2)+'\n')
print(json.dumps({'ok':True,'operations':len(ops),'volume_mm3':shape.Volume,'mesh':report['mesh']}))
