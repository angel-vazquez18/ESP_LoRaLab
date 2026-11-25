"""Preserve project VRML facets and colors as open STEP presentation surfaces.

No remodelling or solidification. Coordinates normally multiply by2.54 because
KiCad VRML units are0.1in. For KiCad STEP substitution, use
--bake-microphone-scale: the project U2 model scale1/2.54 is pre-applied because
the STEP exporter ignores that model-scale field. Source files stay unchanged.
"""
from pathlib import Path
from collections import defaultdict
import argparse, hashlib, json, math, re

NUMBER = r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?'

def shapes(text):
    for match in re.finditer(r'(?:DEF\s+(\w+)\s+)?\bShape\s*\{',text):
        start=match.end(); depth=1; end=start
        while depth:
            if text[end]=='{':depth+=1
            elif text[end]=='}':depth-=1
            end+=1
        yield match.group(1) or f'Shape_{match.start()}',text[start:end-1]

def parse(path,coordinate_scale=2.54):
    text=path.read_text(encoding='utf-8')
    if re.search(r'\b(?:Transform|USE|Box|Cylinder|Sphere)\b',text):
        raise ValueError('Only the project flat IndexedFaceSet models are supported')
    groups=defaultdict(lambda:{'triangles':[],'names':[]})
    total_faces=0; degenerate=0
    for name,body in shapes(text):
        point_text=re.search(r'\bpoint\s*\[([^]]*)\]',body,re.S).group(1)
        floats=[float(v) for v in re.findall(NUMBER,point_text)]
        assert len(floats)%3==0
        points=[tuple(v*coordinate_scale for v in floats[i:i+3]) for i in range(0,len(floats),3)]
        color=tuple(float(v) for v in re.findall(NUMBER,re.search(r'\bdiffuseColor\s+([^\n{}]+)',body).group(1))[:3])
        opacity_match=re.search(r'\btransparency\s+('+NUMBER+')',body)
        transparency=float(opacity_match.group(1)) if opacity_match else 0.0
        if transparency !=0: raise ValueError('A nonzero transparency needs an explicit STEP rendering style')
        group=groups[color];group['names'].append(name)
        idx=[int(v) for v in re.findall(r'-?\d+',re.search(r'\bcoordIndex\s*\[([^]]*)\]',body,re.S).group(1))]
        polygon=[]
        for index in idx:
            if index!=-1:polygon.append(index);continue
            if polygon:
                total_faces+=1
                for i in range(1,len(polygon)-1):
                    tri=tuple(points[n] for n in (polygon[0],polygon[i],polygon[i+1]))
                    a=tuple(tri[1][j]-tri[0][j] for j in range(3));b=tuple(tri[2][j]-tri[0][j] for j in range(3))
                    cross=(a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
                    if sum(v*v for v in cross)<1e-24:degenerate+=1
                    else:group['triangles'].append(tri)
            polygon=[]
        assert not polygon
    return groups,total_faces,degenerate

def number(value):
    result=format(float(value),'.16g').replace('e','E')
    if '.' not in result and 'E' not in result:result+='.'
    return result

def vec(v):return '('+','.join(number(x) for x in v)+')'
def refs(values):return '('+','.join('#'+str(v) for v in values)+')'
def quoted(v):return "'"+v.replace("'","''")+"'"

class Step:
    def __init__(self):self.lines=[]
    def add(self,s):self.lines.append(s);return len(self.lines)

def write_step(source,target,independent_faces=False,coordinate_scale=2.54):
    groups,polygons,degenerate=parse(source,coordinate_scale)
    s=Step()
    app=s.add("APPLICATION_CONTEXT('core data for automotive mechanical design processes')")
    s.add(f"APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,#{app})")
    pc=s.add(f"PRODUCT_CONTEXT('',#{app},'mechanical')")
    prod=s.add(f"PRODUCT({quoted(source.stem)},{quoted(source.stem)},'',(#{pc}))")
    form=s.add(f"PRODUCT_DEFINITION_FORMATION('','',#{prod})")
    pdc=s.add(f"PRODUCT_DEFINITION_CONTEXT('part definition',#{app},'design')")
    pd=s.add(f"PRODUCT_DEFINITION('design','',#{form},#{pdc})")
    pds=s.add(f"PRODUCT_DEFINITION_SHAPE('','',#{pd})")
    lu=s.add('(LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.))')
    au=s.add('(NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.))')
    su=s.add('(NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT())')
    un=s.add(f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-07),#{lu},'distance_accuracy_value','confusion accuracy')")
    ctx=s.add(f"(GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#{un})) GLOBAL_UNIT_ASSIGNED_CONTEXT((#{lu},#{au},#{su})) REPRESENTATION_CONTEXT('','3D Context'))")
    pts={};items=[];styles=[];total_triangles=0;all_points=[]
    for color,group in groups.items():
        faces=[]
        rgb=s.add("COLOUR_RGB('',"+','.join(number(x) for x in color)+')')
        fillcolor=s.add(f"FILL_AREA_STYLE_COLOUR('',#{rgb})")
        fill=s.add(f"FILL_AREA_STYLE('',(#{fillcolor}))")
        surf=s.add(f'SURFACE_STYLE_FILL_AREA(#{fill})')
        side=s.add(f"SURFACE_SIDE_STYLE('',(#{surf}))")
        usage=s.add(f'SURFACE_STYLE_USAGE(.BOTH.,#{side})')
        assignment=s.add(f'PRESENTATION_STYLE_ASSIGNMENT((#{usage}))')
        for tri in group['triangles']:
            pids=[]
            for p in tri:
                if p not in pts:pts[p]=s.add("CARTESIAN_POINT('',"+vec(p)+')')
                pids.append(pts[p])
            loop=s.add("POLY_LOOP('',"+refs(pids)+')')
            bound=s.add(f"FACE_OUTER_BOUND('',#{loop},.T.)")
            a=tuple(tri[1][j]-tri[0][j] for j in range(3));b=tuple(tri[2][j]-tri[0][j] for j in range(3))
            cross=(a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
            norm=math.sqrt(sum(v*v for v in cross));alen=math.sqrt(sum(v*v for v in a))
            normal=s.add("DIRECTION('',"+vec(v/norm for v in cross)+')')
            edge=s.add("DIRECTION('',"+vec(v/alen for v in a)+')')
            axis=s.add(f"AXIS2_PLACEMENT_3D('',#{pids[0]},#{normal},#{edge})")
            plane=s.add(f"PLANE('',#{axis})")
            face=s.add(f"FACE_SURFACE('',(#{bound}),#{plane},.T.)")
            faces.append(face)
            styles.append(s.add(f"STYLED_ITEM('color',(#{assignment}),#{face})"))
            total_triangles+=1
        shells=([s.add(f"OPEN_SHELL('',(#{face}))") for face in faces] if independent_faces else [s.add("OPEN_SHELL('',"+refs(faces)+')')])
        label=','.join(group['names'])[:220]
        items.append(s.add(f'SHELL_BASED_SURFACE_MODEL({quoted(label)},'+refs(shells)+')'))
    rep=s.add("MANIFOLD_SURFACE_SHAPE_REPRESENTATION('',"+refs(items)+f',#{ctx})')
    s.add(f'SHAPE_DEFINITION_REPRESENTATION(#{pds},#{rep})')
    s.add("MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('',"+refs(styles)+f',#{ctx})')
    output="ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('Exact project VRML facets; open presentation surfaces'),'2;1');\nFILE_NAME("+quoted(target.name)+",'2026-11-24T00:00:00',('Codex'),(''),'Project VRML facet converter','','');\nFILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));\nENDSEC;\nDATA;\n"
    output+='\n'.join('#'+str(i)+' = '+line+';' for i,line in enumerate(s.lines,1))+'\nENDSEC;\nEND-ISO-10303-21;\n'
    target.write_text(output,encoding='ascii')
    all_points=list(pts)
    return {'source':str(source),'target':str(target),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'scale_mm_per_vrml_unit':coordinate_scale,'pre_applied_footprint_scale':coordinate_scale/2.54,'scale_note':'KiCad STEP substitution ignores footprint model scaling; the microphone scale is pre-applied when requested. Original VRML and board assignments are unchanged.','source_polygons':polygons,'source_shapes':sum(len(g['names']) for g in groups.values()),'triangles':total_triangles,'zero_area_fan_triangles_skipped':degenerate,'colors':list(groups),'bbox_mm':{'min':[min(p[i] for p in all_points) for i in range(3)],'max':[max(p[i] for p in all_points) for i in range(3)]},'step_entities':len(s.lines),'bytes':target.stat().st_size,'geometry_kind':'Open presentation surface facets; no inferred solid volume'}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('source_dir',type=Path);parser.add_argument('target_dir',type=Path);parser.add_argument('--only');parser.add_argument('--bake-microphone-scale',action='store_true')
    args=parser.parse_args();args.target_dir.mkdir(parents=True,exist_ok=True)
    records=[]
    for source in sorted(args.source_dir.glob('*.wrl')):
        if args.only and source.stem!=args.only:continue
        scale=1.0 if args.bake_microphone_scale and source.stem=='INMP441_ROUND_DETAILED_VISUAL' else 2.54
        record=write_step(source,args.target_dir/(source.stem+'.step'),coordinate_scale=scale);records.append(record)
        print(json.dumps(record),flush=True)
    audit_path=args.target_dir.parent/'vrml-step-conversion-audit.json'
    if args.only and audit_path.exists():
        replaced={Path(r['source']).name for r in records}
        records=[r for r in json.loads(audit_path.read_text()) if Path(r['source']).name not in replaced]+records
    audit_path.write_text(json.dumps(records,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
