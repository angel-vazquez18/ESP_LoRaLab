"""Exact rational proof of the approved retainer STL/3MF rounding difference.

Read-only input handling. No CAD or mesh is changed. The certificate is tied
to this pair's SHA256 hashes and does not relax any general mesh tolerance.
"""
from pathlib import Path
from fractions import Fraction as F
from collections import Counter
import hashlib,itertools,json,struct,xml.etree.ElementTree as ET,zipfile

OUT=Path(__file__).resolve().parent;ROOT=OUT.parent
STL=ROOT/'printing/C5-R6-speaker-retainer-mm.stl';MF=ROOT/'printing/C5-R6-speaker-retainer-mm.3mf'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
before={str(p):sha(p)for p in [STL,MF]}
raw=STL.read_bytes();count=struct.unpack_from('<I',raw,80)[0]
assert len(raw)==84+50*count
st=[]
for offset in range(84,len(raw),50):
 values=struct.unpack_from('<9f',raw,offset+12)
 st.append(tuple(tuple(F.from_float(v)for v in values[i:i+3])for i in [0,3,6]))
with zipfile.ZipFile(MF)as z:
 assert z.testzip()is None
 names=[n for n in z.namelist()if n.endswith('.model')];assert len(names)==1
 model=ET.fromstring(z.read(names[0]))
ns={'m':'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'}
assert model.get('unit','millimeter')=='millimeter'
objects=model.findall('m:resources/m:object',ns);items=model.findall('m:build/m:item',ns)
assert len(objects)==len(items)==1 and items[0].get('objectid')==objects[0].get('id')
transform=[F(x)for x in items[0].get('transform','1 0 0 0 1 0 0 0 1 0 0 0').split()]
assert transform==[1,0,0,0,1,0,0,0,1,0,0,0]
verts_xml=objects[0].findall('m:mesh/m:vertices/m:vertex',ns)
tokens=[v.attrib[k]for v in verts_xml for k in ['x','y','z']]
vertices=[tuple(F(v.attrib[k])for k in ['x','y','z'])for v in verts_xml]
indices=[tuple(int(t.attrib[k])for k in ['v1','v2','v3'])for t in objects[0].findall('m:mesh/m:triangles/m:triangle',ns)]
assert len(indices)==len(st)
assert all(len(set(t))==3 and min(t)>=0 and max(t)<len(vertices)for t in indices)
assert len(set(vertices))==len(vertices)
precision=Counter(len(t.partition('.')[2])for t in tokens)
grid=F(1,10000);half_grid=grid/2
assert all((q/grid).denominator==1 for p in vertices for q in p)

# Establish one global bijection and identical oriented triangle connectivity.
mapping={};inverse={};paired=[];max_error=F(0);same_order=0
for a,ids in zip(st,indices):
 rotations=[ids,ids[1:]+ids[:1],ids[2:]+ids[:2]]
 choices=[(max(abs(x-y)for p,j in zip(a,rot)for x,y in zip(p,vertices[j])),rot)for rot in rotations]
 delta,matched=min(choices)
 assert delta<half_grid
 same_order+=matched==ids;max_error=max(max_error,delta)
 for p,j in zip(a,matched):
  assert p not in mapping or mapping[p]==j
  assert j not in inverse or inverse[j]==p
  mapping[p]=j;inverse[j]=p
 paired.append(tuple(vertices[j]for j in matched))
assert len(mapping)==len(inverse)==len(vertices)
def cyclic(t):return min(t,t[1:]+t[:1],t[2:]+t[:2])
assert Counter(cyclic(tuple(mapping[p]for p in a))for a in st)==Counter(cyclic(t)for t in indices)
edge_owners={}
for i,t in enumerate(indices):
 for u,v in zip(t,t[1:]+t[:1]):edge_owners.setdefault(tuple(sorted((u,v))),[]).append((i,u<v))
assert all(len(a)==2 and a[0][1]!=a[1][1]for a in edge_owners.values())
adj=[set()for _ in indices]
for owners in edge_owners.values():a,b=owners[0][0],owners[1][0];adj[a].add(b);adj[b].add(a)
seen={0};pending=[0]
while pending:
 i=pending.pop()
 for j in adj[i]-seen:seen.add(j);pending.append(j)
assert len(seen)==len(indices)

# Exact tetrahedral volumes about one common, local origin. All input numbers
# are exact rationals: binary32 coordinates and literal decimal XML tokens.
origin=tuple((min(p[i]for p in vertices)+max(p[i]for p in vertices))/2 for i in range(3))
sub=lambda a,b:tuple(x-y for x,y in zip(a,b))
def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
def det(a,b,c):return a[0]*(b[1]*c[2]-b[2]*c[1])-a[1]*(b[0]*c[2]-b[2]*c[0])+a[2]*(b[0]*c[1]-b[1]*c[0])
st_vol=F(0);mf_vol=F(0);triangle_delta_bound=F(0);multilinear_bound=F(0);max_tri_delta=F(0)
for aa,bb in zip(st,paired):
 a,b,c=[sub(p,origin)for p in aa];u,v,w=[sub(p,origin)for p in bb]
 da,db,dc=sub(u,a),sub(v,b),sub(w,c)
 ds,dm=det(a,b,c),det(u,v,w)
 assert any(cross(sub(b,a),sub(c,a)))and any(cross(sub(v,u),sub(w,u)))
 terms=[det(da,b,c),det(a,db,c),det(a,b,dc),det(da,db,c),det(da,b,dc),det(a,db,dc),det(da,db,dc)]
 assert sum(terms)==dm-ds
 st_vol+=ds/6;mf_vol+=dm/6
 d=abs(dm-ds)/6;triangle_delta_bound+=d;max_tri_delta=max(max_tri_delta,d)
 multilinear_bound+=sum(abs(t)for t in terms)/6
absolute_delta=abs(mf_vol-st_vol)
assert st_vol>0 and mf_vol>0 and absolute_delta<=triangle_delta_bound<=multilinear_bound
nearest_rounding=all(abs(p[k]-vertices[j][k])<half_grid for p,j in mapping.items()for k in range(3))
assert nearest_rounding and max_error<F(1,10000)
def exact(q):return {'value':float(q),'numerator':str(q.numerator),'denominator':str(q.denominator)}
unchanged={p:sha(Path(p))==h for p,h in before.items()};assert all(unchanged.values())
report={
 'ok':True,'scope':'Certificate for the exact approved retainer STL/3MF pair only; no tolerance or file changes.',
 'source_hashes':before,'source_files_unchanged':unchanged,
 'serialization':{'stl':'IEEE754 binary32','three_mf_unit':'millimeter','xml_decimal_places_histogram':dict(precision),'xml_coordinate_grid_mm':float(grid),'all_xml_coordinates_are_nearest_0_0001_mm_rounding_of_corresponding_stl':nearest_rounding,'half_grid_bound_mm':float(half_grid),'max_axis_coordinate_difference_mm':exact(max_error),'pointwise_1e_4_mm_gate_passed':max_error<F(1,10000)},
 'correspondence':{'triangles':count,'vertices':len(vertices),'global_bijective_vertex_mapping':True,'identical_oriented_triangle_connectivity':True,'triangles_already_same_vertex_order':same_order,'undirected_edges':len(edge_owners),'every_edge_has_two_opposite_directed_owners':True,'exact_zero_area_triangles_in_either_mesh':0,'connected_components':1,'3mf_build_transform':'identity'},
 'volume_certificate':{'common_recentring_origin_mm':[float(q)for q in origin],'stl_signed_volume_mm3':exact(st_vol),'three_mf_signed_volume_mm3':exact(mf_vol),'absolute_volume_difference_mm3':exact(absolute_delta),'relative_difference':exact(absolute_delta/st_vol),'exact_sum_absolute_per_triangle_volume_deltas_mm3':exact(triangle_delta_bound),'exact_multilinear_coordinate_perturbation_bound_mm3':exact(multilinear_bound),'max_single_triangle_volume_delta_mm3':exact(max_tri_delta),'delta_is_within_exact_bounds':True,'arithmetic':'Python Fraction exact rational arithmetic; no numerical tolerance in determinant identity or inequality checks','derivation':'For each triangle, det(a+da,b+db,c+dc)-det(a,b,c) expands into seven multilinear terms. Summing their absolute values/6 bounds the absolute mesh volume change; the sharper sum of absolute per-triangle determinant differences/6 also bounds it.'},
 'interpretation':'Every 3MF vertex is the nearest0.0001mm rounded STL vertex, with identical oriented connectivity. The observed volume mismatch is fully accounted for by this coordinate serialization. This supplements rather than relaxes the failed1ppm volume heuristic. Native-CAD deviation, manufacturing topology and pointwise checks remain separate required gates.'}
(OUT/'retainer-format-precision.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'ok':True,'vertices':len(vertices),'triangles':count,'max_axis_delta_mm':float(max_error),'volume_delta_mm3':float(absolute_delta),'exact_L1_triangle_bound_mm3':float(triangle_delta_bound),'exact_multilinear_bound_mm3':float(multilinear_bound),'rounding_grid_mm':float(grid)}))
