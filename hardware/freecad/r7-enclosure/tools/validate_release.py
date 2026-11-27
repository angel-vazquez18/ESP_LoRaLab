"""Validate the current R7 release without any older enclosure directory.

Ordinary Python checks current artifacts and preserved audit bindings. Run with
FreeCAD's Python and --cad to refresh the read-only global-placement/STEP proof.
--cad-only writes only that proof. No CAD, mesh or source document is exported.
"""
from pathlib import Path,PurePosixPath
from datetime import datetime,timezone
import argparse,hashlib,importlib.util,json,math,struct,sys,zipfile
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
NATIVE='cad/LoRa-Enclosure-C5-R7-Reinforced.FCStd'
STEP='cad/LoRa-Enclosure-C5-R7-Reinforced.step'
MASTER='printing/C5-R7-all-parts-mm.3mf'
CAD_REPORT='audit/current-native-validation.json'

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb')as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
def require(condition,message):
    if not condition:raise ValueError(message)
def inside(name):
    p=PurePosixPath(name)
    require(not p.is_absolute()and '..'not in p.parts and '\\'not in name,'Unsafe release-relative path: '+name)
    target=ROOT/p;require(target.resolve().is_relative_to(ROOT.resolve()),'Path escaped current release')
    return target
def read(name):return json.loads(inside(name).read_text(encoding='utf-8'))
def resolve_source(name):
    normalized=str(name).replace('\\','/')
    for marker in ['/revision-r7-enclosure/','/r7-enclosure/']:
        if marker in normalized:return inside(normalized.split(marker,1)[1])
    if not normalized.startswith('/')and ':'not in normalized:return inside(normalized)
    raise ValueError('Historical external source is not a current file: '+str(name))
def source_hashes(record):
    for name,expected in record.get('source_hashes',{}).items():
        require(sha(resolve_source(name))==expected,'Source hash mismatch: '+str(name))
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec)
    sys.modules[name]=m;spec.loader.exec_module(m);return m
def write_report(name,record):
    p=inside(name);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')

def native_check():
    import FreeCAD as App,Part
    provenance=read('PROVENANCE.json');plan=read('release-plan.json');historical=read('audit/saved-r7-validation.json')
    before={NATIVE:sha(inside(NATIVE)),STEP:sha(inside(STEP))}
    require(before[NATIVE]==provenance['approved_geometry']['native']['sha256'],'Native differs from approved R7')
    require(before[STEP]==provenance['approved_geometry']['step']['sha256'],'STEP differs from approved R7')
    def world(obj):
        s=obj.Shape.copy()
        if hasattr(obj,'getGlobalPlacement'):
            parent=obj.getGlobalPlacement().multiply(obj.Placement.inverse())
            s.Placement=parent.multiply(s.Placement)
        return s
    def bounds(s):
        b=s.optimalBoundingBox(False,False);return[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
    def compare(a,b):
        bd=max(abs(x-y)for x,y in zip(bounds(a),bounds(b)))
        vd=abs(a.Volume-b.Volume);sd=abs(a.cut(b).Volume)+abs(b.cut(a).Volume)
        return {'matches':bd<1e-6 and vd<max(1e-5,abs(a.Volume)*1e-6)and sd<1e-5,
                'bounds_difference_mm':bd,'volume_difference_mm3':vd,'symmetric_difference_mm3':sd}
    result={'ok':False,'kind':'current-R7-native-STEP-global-placement','native_sha256':before[NATIVE],
            'step_sha256':before[STEP],'parts':{},'step':{},'source_hashes':before,'failures':[],
            'historical_R6_comparison_rerun':False,'native_saved':False}
    doc=App.openDocument(str(inside(NATIVE)))
    try:
        shapes={p['object']:world(doc.getObject(p['object']))for p in plan['parts']}
        for name,s in shapes.items():
            info={'valid':s.isValid(),'closed':s.isClosed(),'solids':len(s.Solids),'volume_mm3':s.Volume,'bounds_mm':bounds(s)}
            require(info['valid']and info['closed']and info['solids']==1,'Invalid current solid '+name)
            old=historical['parts'][name]
            require(max(abs(a-b)for a,b in zip(info['bounds_mm'],old['bounds_mm']))<1e-6,'Stored R7 bounds changed: '+name)
            require(abs(s.Volume-old['volume_mm3'])<max(1e-5,abs(s.Volume)*1e-6),'Stored R7 volume changed: '+name)
            result['parts'][name]=info
        imported=Part.read(str(inside(STEP))).Solids;require(len(imported)==8,'STEP must contain seven parts and coupon')
        used=set()
        for name,s in shapes.items():
            candidates=[i for i,t in enumerate(imported)if i not in used and max(abs(a-b)for a,b in zip(bounds(s),bounds(t)))<1e-5]
            require(len(candidates)==1,'Ambiguous current STEP identity: '+name);i=candidates[0];used.add(i)
            proof=compare(s,imported[i]);require(proof['matches'],'Global native/STEP mismatch: '+name);result['step'][name]=proof
        electronics=[o for o in doc.Objects if o.Name.startswith('C5_detailed_assembly')and hasattr(o,'Shape')]
        expected=provenance['component_reference'];require(len(electronics)==expected['assigned_component_objects'],'Assigned electronics count changed')
        delta=App.Vector(*expected['parent_registration_translation_mm']);records=[];minimum=[float('inf')]*3;maximum=[-float('inf')]*3
        for obj in electronics:
            parent=obj.getGlobalPlacement().multiply(obj.Placement.inverse())
            require((parent.Base-delta).Length<1e-7 and abs(parent.Rotation.Angle)<1e-7,'Unexpected electronics parent transform: '+obj.Name)
            s=world(obj);b=s.BoundBox
            lo=[b.XMin,b.YMin,b.ZMin];hi=[b.XMax,b.YMax,b.ZMax]
            minimum=[min(a,b)for a,b in zip(minimum,lo)];maximum=[max(a,b)for a,b in zip(maximum,hi)]
            matrix=obj.getGlobalPlacement().toMatrix()
            records.append([obj.Name,[getattr(matrix,'A'+str(i)+str(j))for i in range(1,5)for j in range(1,5)]])
        result['global_placement_correction']={'ok':True,'component_count':len(electronics),'parent_z_offsets_mm':[delta.z],
          'parent_translation_mm':[delta.x,delta.y,delta.z],'world_bounds_mm':minimum+maximum,
          'placement_records_sha256':hashlib.sha256(json.dumps(records,separators=(',',':')).encode()).hexdigest(),
          'method':'parent = getGlobalPlacement() * object.Placement.inverse(); parent applied once to Shape.Placement'}
        doc.recompute()
        result['recompute']={n:compare(s,world(doc.getObject(n)))for n,s in shapes.items()}
        require(all(p['matches']for p in result['recompute'].values()),'Recompute changed current geometry')
        require(all(sha(inside(p))==h for p,h in before.items()),'Read-only CAD inputs changed')
        result['ok']=True
    finally:App.closeDocument(doc.Name)
    write_report(CAD_REPORT,result);return result

def validate():
    result={'ok':False,'kind':'current-R7-release','checked_utc':datetime.now(timezone.utc).isoformat(),'checks':{},'failures':[],
      'scope':'Current artifact integrity, exact approved-mesh reconstruction and saved current global-placement CAD proof; no physical qualification or old-revision recomputation.'}
    def check(label,fn):
        try:result['checks'][label]=fn()
        except Exception as error:result['failures'].append(label+': '+str(error))
    def identities():
        provenance=read('PROVENANCE.json')
        require([p.relative_to(ROOT).as_posix()for p in ROOT.rglob('*.FCStd')]==[NATIVE],'Expected exactly the current R7 native document')
        for row in provenance['approved_geometry'].values():require(sha(inside(row['path']))==row['sha256'],'Approved geometry changed: '+row['path'])
        for name,row in provenance['historical_audits'].items():require(sha(inside(name))==row['sha256'],'Historical audit rewritten: '+name)
        native=read('audit/saved-r7-validation.json');require(native['source_hashes']['prior_R6']==provenance['historical_prior']['native_sha256'],'Historical R6 identity changed')
        current=read(CAD_REPORT);require(current['ok']and current['native_sha256']==sha(inside(NATIVE))and current['step_sha256']==sha(inside(STEP)),'Current native proof missing/stale')
        require(current['global_placement_correction']['ok']and current['global_placement_correction']['component_count']==2949,'Current global component proof failed')
        with zipfile.ZipFile(inside(NATIVE))as z:require(z.testzip()is None and 'Document.xml'in z.namelist(),'Native ZIP/container failure')
        ref=provenance['component_reference'];raw=inside(ref['relative_path']);compressed=inside(ref['zip_path'])
        require(raw.is_file()or compressed.is_file(),'Assigned component reference missing')
        if raw.is_file():require(raw.stat().st_size==ref['bytes']and sha(raw)==ref['sha256'],'Component reference changed')
        if compressed.is_file():
            with zipfile.ZipFile(compressed)as z:
                require(z.namelist()==[ref['member']]and z.testzip()is None,'Unexpected component ZIP contents')
                h=hashlib.sha256();size=0
                with z.open(ref['member'])as stream:
                    for block in iter(lambda:stream.read(1024*1024),b''):h.update(block);size+=len(block)
                require(size==ref['bytes']and h.hexdigest()==ref['sha256'],'Compressed component reference differs')
        return {'native_documents':1,'printed_parts':8,'global_component_objects':2949,'historical_sources_required':False,'component_reference_verified':True}
    check('identities_and_current_native',identities)
    def prints():
        d=module('r7_derivative',ROOT/'derive_print_files.py');validator=d.load_validator()
        plan=read('release-plan.json');native=read(CAD_REPORT)
        entries,parts=d.expected_parts(plan,native)
        chunks=[c for leaf in d.read_master(inside(MASTER))for c in d.split_connected(leaf)]
        require(len(chunks)==8,'Approved master islands differ')
        topology=[d.topology(c,inside(MASTER),validator)for c in chunks]
        assignment,_=d.unique_assignment(chunks,entries,parts,topology)
        proof_name='audit/current-print-validation.json'if inside('audit/current-print-validation.json').exists()else'audit/derived-print-validation.json'
        proof=read(proof_name);require(proof['ok'],'Print derivation proof failed');source_hashes(proof)
        checked=[]
        for i,chunk in enumerate(chunks):
            name=assignment[i];record=proof['parts'][name];bb=d.bounds(chunk);offset=tuple(-bb[k]for k in range(3))
            for kind in ['assembly','order']:
                expected=chunk if kind=='assembly'else d.Chunk([tuple(p[k]+offset[k]for k in range(3))for p in chunk.vertices],chunk.faces,chunk.labels,chunk.provenance)
                for extension in ['3mf','stl']:
                    entry=record['files'][kind+'.'+extension];p=inside(entry['path']);require(sha(p)==entry['sha256'],'Print SHA mismatch: '+entry['path'])
                    if extension=='3mf':
                        meshes=d.read_master(p);require(len(meshes)==1,'Expected one individual 3MF mesh')
                        require(meshes[0].vertices==expected.vertices and meshes[0].faces==expected.faces,'3MF differs from approved master geometry')
                        status=d.topology(meshes[0],p,validator)
                    else:
                        _,actual=validator.read_stl(p)
                        vertices=[tuple(struct.unpack('<f',struct.pack('<f',float(x)))[0]for x in point)for point in expected.vertices]
                        require(actual==[tuple(vertices[j]for j in face)for face in expected.faces],'STL differs from approved float32 geometry')
                        status=validator.validate_mesh(p);require(status['ok']and status['signed_volume_mm3']>0,'STL topology failure')
                    require(abs(status['absolute_volume_mm3']-parts[name]['volume_mm3'])/parts[name]['volume_mm3']<.005,'Print/native volume mismatch')
                    checked.append(entry['path'])
        order=read('craftcloud/upload-manifest.json');require(order['order_placed']is False and len(order['files'])==8,'Order manifest state/count')
        require(sum(bool(r['optional'])for r in order['files'])==1,'Optional coupon count')
        for row in order['files']:
            require(row['quantity']==1 and row['units']=='mm'and row['scale']==1,'Order units/scale/quantity')
            prefix='craftcloud/optional-coupon/'if row['optional']else'craftcloud/upload/'
            for extension in ['stl','3mf']:
                require(row[extension].startswith(prefix)and sha(inside(row[extension]))==row[extension+'_sha256'],'Order file binding/separation')
        return {'files_checked':len(checked),'exact_3mf_and_float32_stl_geometry':True,'installed_parts':7,'optional_coupon_parts':1,'order_placed':False}
    check('manufacturing_meshes',prints)
    def documentation():
        drawing=read('documentation/manufacturing/MANUFACTURING-DRAWING-VALIDATION.json')
        require(drawing['ok']and drawing['release_ready']and drawing['pages']==9 and not drawing['visual_review_pending'],'Manufacturing drawing release review')
        require(drawing['pdf_sha256']==drawing['reviewed_pdf_sha256']==sha(inside('documentation/manufacturing/'+drawing['pdf'])),'Manufacturing PDF binding')
        require(drawing['geometry_sha256']==sha(inside('documentation/manufacturing/manufacturing-geometry.json')),'Drawing geometry binding')
        require(drawing['native_sha256']==sha(inside(NATIVE))and drawing['step_sha256']==sha(inside(STEP)),'Drawing native/STEP binding')
        global_proof=drawing['global_placement_correction'];require(global_proof['ok']and global_proof['component_count']==2949 and global_proof['parent_z_offsets_mm']==[6.4814],'Drawing global placement correction absent')
        source_hashes(drawing)
        geometry=read('documentation/manufacturing/manufacturing-geometry.json');require(geometry['ok']and geometry['release_ready'],'Drawing geometry is preflight');source_hashes(geometry)
        bom=read('documentation/bom/BOM-VALIDATION.json');require(bom['ok']and not bom['visual_review_pending'],'BOM review gate');source_hashes(bom)
        for ext in ['xlsx','csv']:require(sha(inside('documentation/bom/LoRa-C5-R7-Complete-BOM.'+ext))==bom['files'][ext],'BOM artifact mismatch')
        require(bom['reviewed_xlsx_sha256']==bom['files']['xlsx'],'BOM reviewed XLSX differs')
        improvements=read('documentation/DOCUMENT-VALIDATION.json');require(improvements['ok']and not improvements['visual_review_pending'],'Improvement drawing review')
        require(improvements['reviewed_pdf_sha256']==sha(inside('documentation/LoRa-C5-R7-Enclosure-Improvements.pdf')),'Improvement PDF changed')
        shop=read('cnc-shop/CNC-SHOP-GEOMETRY-MANIFEST.json');require(shop['ok']and shop['native_sha256']==sha(inside(NATIVE))and shop['step_sha256']==sha(inside(STEP)),'CNC source binding')
        require(shop['geometry_copy']['sha256']==sha(inside(shop['geometry_copy']['path']))==sha(inside(STEP)),'CNC STEP copy differs')
        require(shop['native_validation_sha256']==sha(inside('audit/saved-r7-validation.json')),'CNC original validation binding')
        require(shop['machine_program_supplied']is False and shop['units']=='mm','CNC scope changed')
        return {'manufacturing_pages':9,'global_component_sections_corrected':True,'bom_reviewed':True,'cnc_geometry_exact':True,'machine_code_supplied':False}
    check('documentation_bom_cnc',documentation)
    def viewer():
        helper=module('r7_current_viewer',ROOT/'tools/rebuild_r7_viewer.py');_,proof=helper.reconstruct(ROOT/'interactive')
        require(proof['ok'],'Portable viewer reconstruction failed')
        build=read('interactive/BUILD-VALIDATION.json');browser=read('interactive/qa/R7-BROWSER-VALIDATION.json');views=read('interactive/views/VIEWS-VALIDATION.json')
        require(build['ok']and browser['ok']and views['ok'],'Viewer/QA/views release gate')
        require(build['native_sha256']==browser['native_sha256']==views['native_sha256']==sha(inside(NATIVE)),'Viewer native binding')
        require(build['sha256']==browser['fragment_sha256']==views['fragment_sha256']==proof['fragment_sha256'],'Viewer fragment binding')
        require(browser['preview_sha256']==views['preview_sha256']==proof['preview_sha256']and browser['preview_fragment_matches'],'Standalone wrapper binding')
        require(not views.get('visual_review_pending',True),'Final view visual review pending')
        for row in views['images']:require(sha(inside('interactive/views/R7-'+row['mode']+'.png'))==row['sha256'],'View image changed')
        return proof
    check('interactive_viewer',viewer)
    def pcb_evidence():
        baseline=sha(inside('audit/pcb-guard-baseline.json'));old=read('audit/pcb-guard-verification.json');relocation=read('audit/pcb-relocation-verification.json')
        for proof in [old,relocation]:require(proof['ok']and proof['files_checked']==367 and proof['baseline_sha256']==baseline and not any(proof[k]for k in ['added','missing','changed']),'Protected-file integrity evidence')
        local=inside('pcb-fabrication/R7-PRESERVED-PCB-MANIFEST.json')
        if local.exists():
            copy=read('pcb-fabrication/R7-PRESERVED-PCB-MANIFEST.json');require(copy['ok'],'Local PCB copy manifest failed')
            for row in copy['files']:require(sha(inside(row['path']))==row['sha256'],'Local PCB copy differs: '+row['path'])
        archived=inside('references/pcb-fabrication-baseline')
        if archived.exists():
            for key,row in read('audit/pcb-guard-baseline.json')['files'].items():
                if key.startswith('c5_fabrication_handoff/'):
                    require(sha(archived/key.split('/',1)[1])==row['sha256'],'Preserved complete PCB baseline differs')
        return {'protected_files_in_recorded_guard':367,'historical_reports_preserved':True,'local_pcb_payload_verified':local.exists(),'full_pcb_baseline_verified':archived.exists(),'firmware_external_files_reread':False}
    check('protected_pcb_evidence',pcb_evidence)
    result['ok']=not result['failures'];return result

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--cad',action='store_true');parser.add_argument('--cad-only',action='store_true');parser.add_argument('--report',default='VALIDATION.json');args=parser.parse_args()
    try:
        if args.cad or args.cad_only:
            proof=native_check()
            if args.cad_only:print(json.dumps({'ok':proof['ok'],'report':CAD_REPORT,'components':proof['global_placement_correction']['component_count']}));return 0
        result=validate();write_report(args.report,result)
        print(json.dumps({'ok':result['ok'],'checks':list(result['checks']),'failures':result['failures'],'report':args.report},indent=2))
        return 0 if result['ok']else 1
    except Exception as error:
        print(json.dumps({'ok':False,'error':str(error)}));return 1

if __name__=='__main__':raise SystemExit(main())
