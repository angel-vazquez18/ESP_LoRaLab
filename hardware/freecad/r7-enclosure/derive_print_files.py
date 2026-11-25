"""Derive individual neutral print files from an approved multi-part 3MF.

No FreeCAD document or CAD export is written. The reviewed master is parsed,
its transforms are baked using exact rational arithmetic, and its separate
closed meshes are matched uniquely to the audited saved native parts. Output
3MF coordinates round-trip exactly; STL float32 conversion is checked. Order
files differ only by translation to a nonnegative origin. No slicing/orders.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, localcontext
from fractions import Fraction as F
from pathlib import Path, PurePosixPath
import hashlib, importlib.util, itertools, json, math, os, re, struct, sys, tempfile
import urllib.parse, xml.etree.ElementTree as ET, zipfile

ROOT=Path(__file__).resolve().parent
MASTER=ROOT/'printing/C5-R7-all-parts-mm.3mf'
NATIVE=ROOT/'cad/LoRa-Enclosure-C5-R7-Reinforced.FCStd'
PLAN=ROOT/'release-plan.json'
AUDIT=ROOT/'audit/current-native-validation.json'
REPORT=ROOT/'audit/current-print-validation.json'
NS='http://schemas.microsoft.com/3dmanufacturing/core/2015/02'
M={'m':NS};IDENTITY=tuple(map(F,[1,0,0,0,1,0,0,0,1,0,0,0]))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

@dataclass
class Chunk:
    vertices:list
    faces:list
    labels:list
    provenance:dict

def require(condition,message):
    if not condition:raise ValueError(message)

def matrix(text):
    vals=IDENTITY if not text else tuple(F(v)for v in text.split())
    require(len(vals)==12,'3MF transform requires12 coefficients')
    a,b,c,d,e,f,g,h,i=vals[:9]
    require(a*(e*i-f*h)-b*(d*i-f*g)+c*(d*h-e*g)!=0,'Singular3MF transform')
    return vals

def determinant(m):
    a,b,c,d,e,f,g,h,i=m[:9]
    return a*(e*i-f*h)-b*(d*i-f*g)+c*(d*h-e*g)

def point(p,chain):
    x,y,z=p
    for m in chain:
        if m!=IDENTITY:x,y,z=(x*m[0]+y*m[3]+z*m[6]+m[9],x*m[1]+y*m[4]+z*m[7]+m[10],x*m[2]+y*m[5]+z*m[8]+m[11])
    return x,y,z

def model_path(path,base=''):
    require(not urllib.parse.urlsplit(path).scheme,'External3MF resources are unsupported')
    path=urllib.parse.unquote(path).replace('\\','/')
    p=PurePosixPath(path.lstrip('/'))if path.startswith('/')else PurePosixPath(base).parent/path
    out=[]
    for segment in p.parts:
        if segment in ('','.'):continue
        if segment=='..':
            require(bool(out),'3MF resource escaped package');out.pop()
        else:out.append(segment)
    return '/'.join(out)

def read_master(path):
    """Resolve every build item/component chain, retaining mesh boundaries."""
    leaves=[]
    with zipfile.ZipFile(path)as z:
        require(z.testzip()is None,'3MF ZIP CRC failure')
        names=z.namelist();require(len(names)==len(set(names)),'Duplicate ZIP entries')
        root_name=None
        if '_rels/.rels'in names:
            rels=ET.fromstring(z.read('_rels/.rels'))
            models=[r for r in rels if r.get('Type','').endswith('/3dmodel')]
            require(len(models)==1,'Expected exactly one3MF root relationship')
            require(models[0].get('TargetMode','Internal')!='External','External root model')
            root_name=model_path(models[0].get('Target',''))
        if root_name is None:
            candidates=[n for n in names if n.lower().endswith('.model')]
            require(len(candidates)==1,'Ambiguous root3MF model');root_name=candidates[0]
        models={}
        def resource(name):
            if name not in models:
                require(name in names,'Missing3MF resource '+name)
                root=ET.fromstring(z.read(name))
                require(root.tag=='{'+NS+'}model','Unexpected3MF namespace')
                require(root.get('unit','millimeter')=='millimeter','All source units must be millimeter')
                objects=root.findall('m:resources/m:object',M)
                ids=[o.get('id')for o in objects]
                require(None not in ids and len(ids)==len(set(ids)),'Duplicate/missing object ID')
                models[name]=(root,dict(zip(ids,objects)))
            return models[name]
        def walk(name,ident,chain,labels,trace,active):
            key=(name,ident);require(key not in active,'Cyclic3MF component graph')
            _,objects=resource(name);require(ident in objects,'Missing object '+str(key))
            obj=objects[ident];labels=labels+[obj.get('name',''),obj.get('partnumber','')]
            meshes=obj.findall('m:mesh',M);groups=obj.findall('m:components',M)
            require((len(meshes)==1 and not groups)or(not meshes and len(groups)==1),'Object must contain one mesh or component group')
            if meshes:
                mesh=meshes[0]
                vertices=[point(tuple(F(v.get(k))for k in ('x','y','z')),chain)for v in mesh.findall('m:vertices/m:vertex',M)]
                faces=[tuple(int(t.get(k))for k in ('v1','v2','v3'))for t in mesh.findall('m:triangles/m:triangle',M)]
                require(vertices and faces,'Empty source mesh')
                require(all(len(set(t))==3 and min(t)>=0 and max(t)<len(vertices)for t in faces),'Invalid source triangle indices')
                reflected=math.prod(1 if determinant(m)>0 else -1 for m in chain)<0
                if reflected:faces=[(a,c,b)for a,b,c in faces]
                leaves.append(Chunk(vertices,faces,[s for s in labels if s],{'model_resource':name,'object_id':ident,'component_path':trace,'transforms':[[str(v)for v in m]for m in chain],'reflection_winding_reversed':reflected}))
            else:
                children=groups[0].findall('m:component',M);require(children,'Empty component group')
                for i,c in enumerate(children):
                    external=next((v for k,v in c.attrib.items()if k.rsplit('}',1)[-1]=='path'),None)
                    child_name=model_path(external,name)if external else name
                    walk(child_name,c.get('objectid'),[matrix(c.get('transform'))]+chain,labels,trace+[i],active|{key})
        root,_=resource(root_name);build=root.findall('m:build/m:item',M)
        require(build,'Source has no build items')
        for i,item in enumerate(build):
            require(item.get('printable','1')not in ('0','false'),'Nonprintable build item in manufacturing master')
            external=next((v for k,v in item.attrib.items()if k.rsplit('}',1)[-1]=='path'),None)
            walk(model_path(external,root_name)if external else root_name,item.get('objectid'),[matrix(item.get('transform'))],[],[i],set())
    return leaves

def split_connected(mesh):
    """Preserve indexed islands, including touching but separate closed parts.

    FreeCAD's export_3mf combines Mesh objects with addMesh. That operation
    preserves separate vertex indices even where assembled solids touch.
    Welding coordinates before splitting would join the lid/base/cup at
    intentional contacts. Only duplicate vertices within an already separate
    indexed island are merged. Ambiguous triangle soups fail downstream.
    """
    parents=list(range(len(mesh.faces)))
    def root(i):
        while parents[i]!=i:parents[i]=parents[parents[i]];i=parents[i]
        return i
    edge_owner={}
    for i,face in enumerate(mesh.faces):
        for a,b in zip(face,face[1:]+face[:1]):
            require(mesh.vertices[a]!=mesh.vertices[b],'Collapsed source edge')
            e=tuple(sorted((a,b)))
            if e in edge_owner:parents[root(i)]=root(edge_owner[e])
            else:edge_owner[e]=i
    groups=defaultdict(list)
    for i,face in enumerate(mesh.faces):groups[root(i)].append(face)
    result=[]
    for number,faces in enumerate(groups.values()):
        verts=[];lookup={};out=[]
        for face in faces:
            ids=[]
            for i in face:
                p=mesh.vertices[i]
                if p not in lookup:lookup[p]=len(verts);verts.append(p)
                ids.append(lookup[p])
            out.append(tuple(ids))
        result.append(Chunk(verts,out,mesh.labels,dict(mesh.provenance,split_component=number,components_in_leaf=len(groups))))
    return result

def bounds(mesh):
    return [min(v[i]for v in mesh.vertices)for i in range(3)]+[max(v[i]for v in mesh.vertices)for i in range(3)]

def triangles(mesh):return [tuple(tuple(float(x)for x in mesh.vertices[i])for i in f)for f in mesh.faces]

def load_validator():
    path=ROOT/'tools/mesh_validation.py'
    spec=importlib.util.spec_from_file_location('r7_topology_validator',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def topology(mesh,path,validator):
    original=validator.read_stl
    try:
        validator.read_stl=lambda _:('3mf_resolved',triangles(mesh))
        r=validator.validate_mesh(path)
    finally:validator.read_stl=original
    require(r['ok'] and r['signed_volume_mm3']>0,'Invalid source/derived topology: '+json.dumps(r))
    return r

def expected_parts(plan,audit):
    entries=plan.get('parts')
    require(isinstance(entries,list)and len(entries)==8,'release-plan.parts must contain exactly8 entries')
    require(all(isinstance(p,dict)and p.get('name')and p.get('stem')for p in entries),'Part entries require name/stem/optional')
    require(len({p['name']for p in entries})==8 and len({p['stem']for p in entries})==8,'Duplicate release parts')
    require(all(p.get('quantity')==1 for p in entries),'Release quantity must be one per part')
    require(sum(bool(p.get('optional',False))for p in entries)==1,'Exactly one optional coupon required')
    require(next(p['name']for p in entries if p.get('optional',False))=='R7FitCoupon','Unexpected optional part')
    require(all(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',p['stem'])for p in entries),'Unsafe output stem')
    native=audit.get('parts',audit.get('native'))
    require(isinstance(native,dict),'Native audit must expose parts')
    for p in entries:
        require(p['name']in native,'Native audit missing '+p['name'])
        n=native[p['name']]
        require(n.get('valid')and n.get('closed')and n.get('solids')==1,'Native part not valid/closed/single solid')
        require(len(n['bounds_mm'])==6 and n['volume_mm3']>0,'Native bounds/volume missing')
    return entries,native

def unique_assignment(chunks,entries,native,topologies):
    candidates=[];details=[]
    norm=lambda s:re.sub(r'[^a-z0-9]','',s.lower())
    for i,chunk in enumerate(chunks):
        cb=list(map(float,bounds(chunk)));cv=topologies[i]['absolute_volume_mm3'];options=[];checks={}
        labels={norm(s)for s in chunk.labels}
        known={p['name']for p in entries if norm(p['name'])in labels or norm(p['stem'])in labels}
        for p in entries:
            n=native[p['name']];bd=max(abs(a-b)for a,b in zip(cb,n['bounds_mm']));ve=abs(cv-n['volume_mm3'])/n['volume_mm3']
            passes=bd<.05 and ve<.005
            checks[p['name']]={'max_bounds_difference_mm':bd,'relative_volume_error':ve,'matches':passes}
            if passes and(not known or p['name']in known):options.append(p['name'])
        require(options,'No native match for source mesh '+str(i)+' labels='+str(chunk.labels))
        candidates.append(options);details.append(checks)
    solutions=[]
    def search(done,used):
        if len(solutions)>1:return
        if len(done)==len(chunks):solutions.append(done.copy());return
        choices=[(len([p for p in candidates[i]if p not in used]),i)for i in range(len(chunks))if i not in done]
        _,i=min(choices)
        for name in candidates[i]:
            if name not in used:done[i]=name;search(done,used|{name});done.pop(i)
    search({},set());require(len(solutions)==1,'Ambiguous or incomplete native matching; refusing to guess part identity')
    return solutions[0],details

def decimal_text(q):
    with localcontext()as ctx:
        ctx.prec=max(50,len(str(abs(q.numerator)))+len(str(q.denominator))+10)
        text=format(Decimal(q.numerator)/Decimal(q.denominator),'f')
    require(F(text)==q,'Transform produced nonterminating decimal coordinate')
    if '.'in text:text=text.rstrip('0').rstrip('.')
    return text or'0'

def write_3mf(path,mesh,label):
    ET.register_namespace('',NS)
    root=ET.Element('{'+NS+'}model',{'unit':'millimeter'})
    ET.SubElement(root,'{'+NS+'}metadata',{'name':'Title'}).text=label
    resources=ET.SubElement(root,'{'+NS+'}resources')
    obj=ET.SubElement(resources,'{'+NS+'}object',{'id':'1','type':'model','name':label})
    m=ET.SubElement(obj,'{'+NS+'}mesh');vertices=ET.SubElement(m,'{'+NS+'}vertices')
    for p in mesh.vertices:ET.SubElement(vertices,'{'+NS+'}vertex',dict(zip(('x','y','z'),map(decimal_text,p))))
    faces=ET.SubElement(m,'{'+NS+'}triangles')
    for f in mesh.faces:ET.SubElement(faces,'{'+NS+'}triangle',dict(zip(('v1','v2','v3'),map(str,f))))
    build=ET.SubElement(root,'{'+NS+'}build');ET.SubElement(build,'{'+NS+'}item',{'objectid':'1'})
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED)as z:
        z.writestr('[Content_Types].xml','<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        z.writestr('_rels/.rels','<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        z.writestr('3D/3dmodel.model',ET.tostring(root,encoding='utf-8',xml_declaration=True))
    reread=read_master(path)
    require(len(reread)==1 and reread[0].vertices==mesh.vertices and reread[0].faces==mesh.faces,'3MF exact coordinate/connectivity round trip failed')
    return {'exact_fraction_coordinate_round_trip':True,'oriented_connectivity_preserved':True}

def write_stl(path,mesh,label,validator):
    data=bytearray(('C5 R7 | '+label+' | millimetres | scale1').encode('ascii')[:80].ljust(80,b' '));data+=struct.pack('<I',len(mesh.faces))
    verts=[tuple(struct.unpack('<f',struct.pack('<f',float(x)))[0]for x in p)for p in mesh.vertices]
    error=max(abs(F.from_float(v)-x)for p,q in zip(mesh.vertices,verts)for x,v in zip(p,q))
    require(error<F(1,10000),'STL float32 error exceeds0.0001mm')
    for face in mesh.faces:
        a,b,c=[verts[i]for i in face]
        n=validator.cross(validator.subtract(b,a),validator.subtract(c,a));length=math.sqrt(validator.dot(n,n))
        require(length>0,'STL serialization collapsed triangle')
        data+=struct.pack('<12fH',*(x/length for x in n),*(v for p in(a,b,c)for v in p),0)
    path.write_bytes(data)
    _,read=validator.read_stl(path)
    require(read==[tuple(verts[i]for i in f)for f in mesh.faces],'STL binary round trip differs')
    validation=validator.validate_mesh(path)
    require(validation['ok']and validation['signed_volume_mm3']>0,'STL topology failed')
    return {'max_coordinate_round_trip_error_mm':float(error),'oriented_connectivity_preserved':True,'topology':validation}

def main():
    report={'ok':False,'scope':'Approved3MF master decomposition; exact3MF and checkedfloat32 STL; translation-only ordering files','failures':[]}
    staged=[]
    try:
        for path in [MASTER,NATIVE,PLAN,AUDIT]:require(path.is_file(),'Required approved/audited input missing: '+str(path))
        source_hashes={str(p):sha(p)for p in[MASTER,NATIVE,PLAN,AUDIT]}
        plan=json.loads(PLAN.read_text());audit=json.loads(AUDIT.read_text())
        require(audit.get('ok')is True,'Saved native audit must pass first')
        native_hash=audit.get('native_sha256')or audit.get('files',{}).get('native',{}).get('sha256')
        require(native_hash==source_hashes[str(NATIVE)],'Native audit hash does not match savedFCStd')
        entries,native=expected_parts(plan,audit)
        leaves=read_master(MASTER);chunks=[c for leaf in leaves for c in split_connected(leaf)]
        require(len(chunks)==8,'Master doesnot contain exactly8 uniquelyseparable closed parts')
        validator=load_validator();topologies=[topology(c,MASTER,validator)for c in chunks]
        assignment,matches=unique_assignment(chunks,entries,native,topologies)
        report.update({'source_hashes':source_hashes,'source_leaf_count':len(leaves),'connected_part_count':len(chunks),'parts':{},'installed_part_count':7,'optional_coupon_count':1,'order_placed':False})
        entries_by_name={p['name']:p for p in entries};manifest=[]
        staging_parent=ROOT/'printing';staging_parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.r7-derive-',dir=staging_parent)as tmp:
            stage=Path(tmp).resolve();require(stage.is_relative_to(ROOT.resolve()),'Staging directory escaped revision directory')
            for i,chunk in enumerate(chunks):
                name=assignment[i];entry=entries_by_name[name];stem='C5-R7-'+entry['stem']+'-mm'
                bb=bounds(chunk);offset=tuple(-bb[j]for j in range(3))
                normalized=Chunk([tuple(v[j]+offset[j]for j in range(3))for v in chunk.vertices],chunk.faces,chunk.labels,chunk.provenance)
                require(all(v>=0 for p in normalized.vertices for v in p),'Normalization produced negative coordinates')
                native_match=matches[i][name]
                rec={'name':name,'stem':entry['stem'],'optional':bool(entry.get('optional',False)),'source_labels':chunk.labels,'source_mesh':chunk.provenance,'native_comparison':native_match,'source_topology':topologies[i],'translation_from_assembly_mm':list(map(float,offset)),'files':{}}
                for category,mesh,folder in [('assembly',chunk,Path('printing')),('order',normalized,Path('craftcloud/optional-coupon'if rec['optional']else'craftcloud/upload'))]:
                    for extension in ['3mf','stl']:
                        relative=folder/(stem+'.'+extension);temp=stage/relative;temp.parent.mkdir(parents=True,exist_ok=True)
                        check=write_3mf(temp,mesh,name)if extension=='3mf'else write_stl(temp,mesh,name,validator)
                        if extension=='3mf':check['topology']=topology(read_master(temp)[0],temp,validator)
                        # Bounds/volume remain consistent with native after reversing only order-origin translation.
                        topo=check['topology'];translated=topo['bbox_mm']['min']+topo['bbox_mm']['max']
                        if category=='order':translated=[v-float(offset[j%3])for j,v in enumerate(translated)]
                        check['native_bounds_error_mm']=max(abs(a-b)for a,b in zip(translated,native[name]['bounds_mm']))
                        check['native_relative_volume_error']=abs(topo['absolute_volume_mm3']-native[name]['volume_mm3'])/native[name]['volume_mm3']
                        require(check['native_bounds_error_mm']<.05 and check['native_relative_volume_error']<.005,'Derived mesh differs from native bounds/volume')
                        rec['files'][category+'.'+extension]={'path':relative.as_posix(),'sha256':sha(temp),'bytes':temp.stat().st_size,'validation':check}
                        staged.append((temp,ROOT/relative))
                report['parts'][name]=rec
                manifest.append({'part':entry['stem'],'native_object':name,'optional':rec['optional'],'quantity':1,'units':'mm','scale':1,'geometry_change':'translation only','translation_from_assembly_mm':list(map(float,offset)),'dimensions_mm':[float(bb[j+3]-bb[j])for j in range(3)],'stl':rec['files']['order.stl']['path'],'stl_sha256':rec['files']['order.stl']['sha256'],'3mf':rec['files']['order.3mf']['path'],'3mf_sha256':rec['files']['order.3mf']['sha256'],'3mf_round_trip_verified':True,'stl_round_trip_verified':True})
            require(all(sha(Path(p))==h for p,h in source_hashes.items()),'Inputchanged during derivation')
            # Commit only after every part and format has passed. No source is overwritten.
            for src,dest in staged:dest.parent.mkdir(parents=True,exist_ok=True);os.replace(src,dest)
        report['source_files_unchanged']={p:sha(Path(p))==h for p,h in source_hashes.items()}
        require(all(report['source_files_unchanged'].values()),'Inputchanged at completion')
        order={'revision':'C5-R7','installed_parts':7,'optional_coupon_parts':1,'files':manifest,'source_master':str(MASTER),'source_master_sha256':source_hashes[str(MASTER)],'upload_instruction':'Upload one format per installed part from upload/ (seven STL OR seven 3MF). Optional coupon is separate. Units mm, 100% scale, quantity 1. Do not upload the multipart master as one printable object.','order_placed':False}
        (ROOT/'craftcloud/upload-manifest.json').write_text(json.dumps(order,indent=2)+'\n')
        report['ok']=True
    except Exception as e:
        report['failures'].append(str(e))
    REPORT.parent.mkdir(parents=True,exist_ok=True);REPORT.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'ok':report['ok'],'parts':len(report.get('parts',{})),'failures':report['failures'],'report':str(REPORT)}))
    if not report['ok']:raise SystemExit(1)

if __name__=='__main__':main()
