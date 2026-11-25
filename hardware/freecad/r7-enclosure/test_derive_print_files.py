"""Synthetic checks for exact 3MF transforms, separation and STL round trips."""
from pathlib import Path
from fractions import Fraction as F
import json,tempfile,zipfile,xml.etree.ElementTree as ET
import derive_print_files as d

def cube(origin=(0,0,0)):
    pts=[(0,0,0),(1,0,0),(1,1,0),(0,1,0),(0,0,1),(1,0,1),(1,1,1),(0,1,1)]
    verts=[tuple(F(x)+F(y)for x,y in zip(p,origin))for p in pts]
    faces=[(0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),(3,7,6),(3,6,2),(0,4,7),(0,7,3),(1,2,6),(1,6,5)]
    return d.Chunk(verts,faces,[],{})

def main():
    checks=[];root=Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix='.derive-selftest-',dir=root)as tmp:
        out=Path(tmp).resolve();assert out.is_relative_to(root.resolve())
        original=cube((F(1,10),F(2,10),F(3,10)));path=out/'cube.3mf'
        d.write_3mf(path,original,'synthetic cube');checks.append('Exact rational3MF coordinate/connectivity round trip')
        validator=d.load_validator();topo=d.topology(d.read_master(path)[0],path,validator)
        assert abs(topo['absolute_volume_mm3']-1)<1e-12
        stl=d.write_stl(out/'cube.stl',original,'synthetic',validator)
        assert stl['topology']['ok']and stl['max_coordinate_round_trip_error_mm']<1e-4
        checks.append('STL float32 coordinate bound and closed positive winding')
        a=cube();b=cube((3,0,0));both=d.Chunk(a.vertices+b.vertices,a.faces+[tuple(i+8 for i in f)for f in b.faces],[],{})
        assert len(d.split_connected(both))==2;checks.append('Disconnected compound splits into separate closed meshes')
        touching=cube((1,0,0));pair=d.Chunk(a.vertices+touching.vertices,a.faces+[tuple(i+8 for i in f)for f in touching.faces],[],{})
        islands=d.split_connected(pair)
        assert len(islands)==2 and all(d.topology(c,path,validator)['ok']for c in islands)
        checks.append('Touching assembled parts preserve separate vertex-index islands')
        with zipfile.ZipFile(path)as z:members={n:z.read(n)for n in z.namelist()}
        xml=ET.fromstring(members['3D/3dmodel.model']);resources=xml.find('m:resources',d.M)
        group=ET.SubElement(resources,'{'+d.NS+'}object',{'id':'2','type':'model','name':'nested cube'})
        children=ET.SubElement(group,'{'+d.NS+'}components')
        ET.SubElement(children,'{'+d.NS+'}component',{'objectid':'1','transform':'1 0 0 0 1 0 0 0 1 1 2 3'})
        item=xml.find('m:build/m:item',d.M);item.set('objectid','2');item.set('transform','0 1 0 -1 0 0 0 0 1 10 20 30')
        transformed=out/'transformed.3mf';members['3D/3dmodel.model']=ET.tostring(xml)
        with zipfile.ZipFile(transformed,'w')as z:
            for n,data in members.items():z.writestr(n,data)
        leaf=d.read_master(transformed)[0]
        assert leaf.vertices[0]==(F(78,10),F(211,10),F(333,10))
        assert abs(d.topology(leaf,transformed,validator)['absolute_volume_mm3']-1)<1e-12
        checks.append('Nested component then build rotation/translation order')
        item.set('transform','-1 0 0 0 1 0 0 0 1 10 20 30');members['3D/3dmodel.model']=ET.tostring(xml)
        mirrored=out/'mirrored.3mf'
        with zipfile.ZipFile(mirrored,'w')as z:
            for n,data in members.items():z.writestr(n,data)
        mirrored_leaf=d.read_master(mirrored)[0]
        assert mirrored_leaf.provenance['reflection_winding_reversed']
        assert d.topology(mirrored_leaf,mirrored,validator)['signed_volume_mm3']>0
        checks.append('Reflected source transform preserves outward winding')
        entries=[{'name':'a','stem':'a'},{'name':'b','stem':'b'}]
        native={n:{'bounds_mm':[0,0,0,1,1,1],'volume_mm3':1}for n in ['a','b']}
        try:d.unique_assignment([a,a],entries,native,[{'absolute_volume_mm3':1}]*2)
        except ValueError as e:assert'Ambiguous'in str(e)
        else:raise AssertionError('Ambiguous identity was accepted')
        checks.append('Ambiguous geometry assignment fails rather than guessing')
        a.labels=['a'];b2=cube();b2.labels=['b'];matched,_=d.unique_assignment([a,b2],entries,native,[{'absolute_volume_mm3':1}]*2)
        assert matched=={0:'a',1:'b'};checks.append('Explicit labels consistently disambiguate matching geometry')
        # Exercise the whole eight-part pipeline in an isolated synthetic root.
        # These are unit cubes, not CAD or manufacturing files for the enclosure.
        fixture=out/'pipeline';fixture.mkdir()
        saved={key:getattr(d,key)for key in ['ROOT','MASTER','NATIVE','PLAN','AUDIT','REPORT','load_validator']}
        try:
            d.ROOT=fixture;d.MASTER=fixture/'synthetic-master.3mf';d.NATIVE=fixture/'synthetic-native.txt'
            d.PLAN=fixture/'plan.json';d.AUDIT=fixture/'native-audit.json';d.REPORT=fixture/'audit/derived-print-validation.json'
            d.load_validator=lambda:validator
            xml=ET.Element('{'+d.NS+'}model',{'unit':'millimeter'})
            resources=ET.SubElement(xml,'{'+d.NS+'}resources');build=ET.SubElement(xml,'{'+d.NS+'}build')
            entries=[];native={}
            for i in range(8):
                name='R7FitCoupon'if i==7 else'Part'+str(i);obj=cube((F(-3,10)+3*i,F(-1,10),F(-2,10)))
                component=fixture/('part'+str(i)+'.3mf');d.write_3mf(component,obj,name)
                with zipfile.ZipFile(component)as z:model=ET.fromstring(z.read('3D/3dmodel.model'))
                node=model.find('m:resources/m:object',d.M);node.set('id',str(i+1));resources.append(node)
                ET.SubElement(build,'{'+d.NS+'}item',{'objectid':str(i+1)})
                entries.append({'name':name,'stem':'part-'+str(i),'optional':i==7,'quantity':1})
                native[name]={'bounds_mm':list(map(float,d.bounds(obj))),'volume_mm3':1,'valid':True,'closed':True,'solids':1}
            with zipfile.ZipFile(d.MASTER,'w')as z:z.writestr('3D/master.model',ET.tostring(xml))
            d.NATIVE.write_text('Synthetic test fixture only.');d.PLAN.write_text(json.dumps({'parts':entries}))
            d.AUDIT.write_text(json.dumps({'ok':True,'native_sha256':d.sha(d.NATIVE),'parts':native}))
            d.main();report=json.loads(d.REPORT.read_text());manifest=json.loads((fixture/'craftcloud/upload-manifest.json').read_text())
            assert report['ok']and len(report['parts'])==8
            assert len(list((fixture/'printing').glob('*.stl')))==8
            assert len(list((fixture/'craftcloud/upload').glob('*.3mf')))==7
            assert len(list((fixture/'craftcloud/optional-coupon').glob('*.3mf')))==1
            assert len(manifest['files'])==8 and not manifest['order_placed']
            assert all(row['quantity']==1 and row['scale']==1 for row in manifest['files'])
            assert all(r['files']['order.3mf']['validation']['exact_fraction_coordinate_round_trip']for r in report['parts'].values())
            checks.append('Complete eight-part derivation, unique pairing, normalization, native checks and optional separation')
        finally:
            for key,value in saved.items():setattr(d,key,value)
    print({'ok':True,'checks':checks})

if __name__=='__main__':main()
