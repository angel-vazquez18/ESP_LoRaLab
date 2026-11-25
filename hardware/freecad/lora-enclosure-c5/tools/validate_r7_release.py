"""Portable R7 publication checks; inspect saved evidence without CAD writes."""
from pathlib import Path,PurePosixPath
import hashlib,json
from rebuild_r7_viewer import reconstruct

R7='revision-r7-enclosure'
NATIVE=R7+'/cad/LoRa-Enclosure-C5-R7-Reinforced.FCStd'
STEP=R7+'/cad/LoRa-Enclosure-C5-R7-Reinforced.step'
MASTER=R7+'/printing/C5-R7-all-parts-mm.3mf'
PASS_FLAGS=[
 R7+'/PACKAGE-VALIDATION.json',R7+'/audit/saved-r7-validation.json',
 R7+'/audit/derived-print-validation.json',R7+'/audit/pcb-guard-verification.json',
 R7+'/documentation/DOCUMENT-VALIDATION.json',R7+'/audit/antenna/antenna-final-audit.json',
 R7+'/audit/lid/lid-candidate-audit.json',R7+'/interactive/BUILD-VALIDATION.json',
 R7+'/interactive/NATIVE-INPUT-VALIDATION.json',R7+'/interactive/mesh/MESH-VALIDATION.json',
 R7+'/interactive/focus/FOCUS-MESH-VALIDATION.json',R7+'/interactive/dimensions/DIMENSION-VALIDATION.json',
 R7+'/interactive/qa/R7-BROWSER-VALIDATION.json',
 R7+'/interactive/views/VIEWS-VALIDATION.json',
 R7+'/documentation/manufacturing/MANUFACTURING-DRAWING-VALIDATION.json',
 R7+'/documentation/bom/BOM-VALIDATION.json',
 R7+'/cnc-shop/CNC-SHOP-GEOMETRY-MANIFEST.json',
]
PARTS=['enclosure-base','enclosure-lid','ptt-plunger','ptt-stop-cup','battery-cover','speaker-retainer','sma-key']
REQUIRED=[NATIVE,STEP,MASTER,'R7-PUBLICATION-DEPENDENCIES.json','REPRODUCIBILITY-R7.md',
 R7+'/release-plan.json',R7+'/REVISION-NOTES.txt',R7+'/documentation/LoRa-C5-R7-Enclosure-Improvements.pdf',
 R7+'/documentation/R7-ASSEMBLY-AND-INSPECTION.txt',R7+'/craftcloud/ORDER-SPECIFICATION.txt',
 R7+'/craftcloud/upload-manifest.json',R7+'/interactive/r7-enclosure-viewer.html',
 R7+'/interactive/qa/r7-preview.html','tools/rebuild_r7_viewer.py','tools/validate_r7_release.py',
 R7+'/documentation/manufacturing/C5-R7-Manufacturing-Drawings.pdf',
 R7+'/documentation/manufacturing/manufacturing-geometry.json',
 R7+'/documentation/bom/LoRa-C5-R7-Complete-BOM.xlsx',R7+'/documentation/bom/LoRa-C5-R7-Complete-BOM.csv',
 R7+'/cnc-shop/CNC-SHOP-HANDOFF.txt',R7+'/cnc-shop/CNC-SHOP-GEOMETRY-MANIFEST.json',
 R7+'/cnc-shop/geometry/LoRa-Enclosure-C5-R7-Reinforced.step',
 *[R7+'/interactive/views/R7-'+mode+'.png'for mode in ['assembled','exploded','cutaway']],
 *[f'{R7}/craftcloud/upload/C5-R7-{part}-mm.{ext}'for part in PARTS for ext in ['stl','3mf']],
 *[f'{R7}/craftcloud/optional-coupon/C5-R7-fit-coupon-mm.{ext}'for ext in ['stl','3mf']],
]

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def validate(root):
    root=Path(root).resolve();failures=[];checks={}
    def require(condition,message):
        if not condition:raise ValueError(message)
    def path(name):
        p=PurePosixPath(name)
        require(not p.is_absolute() and '..'not in p.parts and '\\'not in name,'Unsafe release path')
        candidate=root/p;require(candidate.resolve().is_relative_to(root),'Release path escapes archive')
        return candidate
    def read(name):return json.loads(path(name).read_text(encoding='utf-8'))
    try:
        for name in REQUIRED+PASS_FLAGS:require(path(name).is_file(),'Missing R7 release input: '+name)
        for name in PASS_FLAGS:require(read(name).get('ok')is True,'Failed saved evidence: '+name)
        marker=read('CURRENT-RELEASE.json')
        require(marker.get('revision')=='R7' and marker.get('release_directory')==R7,'Wrong current revision')
        require(marker.get('print_part_count')==7,'Wrong installed part count in marker')
        plan=read(R7+'/release-plan.json');native=read(R7+'/audit/saved-r7-validation.json')
        require(native['native_sha256']==sha(path(NATIVE)),'Saved-native SHA mismatch')
        require(native['source_hashes']['step']==sha(path(STEP)),'STEP audit SHA mismatch')
        require(native['source_hashes']['prior_R6']==sha(path('revision-r6-speaker/cad/LoRa-Enclosure-C5-R6-Speaker.FCStd')),'R6 native reference audit mismatch')
        require(sha(path(STEP))==sha(path(R7+'/cnc-shop/geometry/LoRa-Enclosure-C5-R7-Reinforced.step')),'CNC-shop STEP differs from approved master')
        require(len(plan['parts'])==8 and len(native['parts'])==8,'Expected eight native parts including coupon')
        require(sum(bool(p['optional'])for p in plan['parts'])==1,'Expected one optional coupon')
        require(set(native['parts'])=={p['object']for p in plan['parts']},'Native plan mismatch')
        require(all(v['valid']and v['closed']and v['solids']==1 for v in native['parts'].values()),'Invalid native part evidence')
        require(not native['unchanged_electronics']['changed'] and native['unchanged_electronics']['objects_compared']>2900,'PCB/component preservation evidence failed')
        derived=read(R7+'/audit/derived-print-validation.json')
        require(derived['connected_part_count']==8 and derived['installed_part_count']==7 and derived['optional_coupon_count']==1,'Derived part counts')
        require(all(derived['source_files_unchanged'].values()),'Derivative input changed')
        checked=[]
        for original,expected in derived['source_hashes'].items():
            normalized=original.replace('\\','/');needle='/'+R7+'/'
            require(needle in normalized,'Unexpected derivative source path: '+original)
            relative=R7+'/'+normalized.split(needle,1)[1]
            require(sha(path(relative))==expected,'Derivative source hash mismatch: '+relative);checked.append(relative)
        for part in derived['parts'].values():
            require(set(part['files'])=={'assembly.3mf','assembly.stl','order.3mf','order.stl'},'Missing derived formats')
            for row in part['files'].values():
                require(sha(path(R7+'/'+row['path']))==row['sha256'],'Derived file SHA mismatch: '+row['path'])
                validation=row['validation']
                require(validation['topology']['ok'],'Failed derived topology')
                require(validation['native_bounds_error_mm']<.05 and validation['native_relative_volume_error']<.005,'Derived native comparison failed')
        order=read(R7+'/craftcloud/upload-manifest.json');require(order['order_placed']is False,'Unexpected order status')
        require(len(order['files'])==8 and sum(bool(p['optional'])for p in order['files'])==1,'Order manifest part count')
        for part in order['files']:
            require(part['quantity']==1 and part['units']=='mm' and part['scale']==1,'Ordering units/quantity/scale')
            folder='craftcloud/optional-coupon/'if part['optional']else'craftcloud/upload/'
            for ext in ['stl','3mf']:
                require(part[ext].startswith(folder),'Coupon/installed file separation failed')
                require(sha(path(R7+'/'+part[ext]))==part[ext+'_sha256'],'Order hash mismatch')
        guard=read(R7+'/audit/pcb-guard-verification.json')
        require(guard['files_checked']==367 and not any(guard[k]for k in ['added','missing','changed']),'Protected file evidence')
        require(guard['baseline_sha256']==sha(path(R7+'/audit/pcb-guard-baseline.json')),'Protected baseline hash')
        document=read(R7+'/documentation/DOCUMENT-VALIDATION.json')
        require(not document['visual_review_pending'] and document['reviewed_pdf_sha256']==sha(path(R7+'/documentation/LoRa-C5-R7-Enclosure-Improvements.pdf')),'Drawing visual review mismatch')
        viewer=read(R7+'/interactive/BUILD-VALIDATION.json');browser=read(R7+'/interactive/qa/R7-BROWSER-VALIDATION.json')
        fragment=path(R7+'/interactive/r7-enclosure-viewer.html')
        require(viewer['native_sha256']==sha(path(NATIVE)),'Viewer is not bound to saved R7 native')
        require(viewer['sha256']==sha(fragment)==browser['fragment_sha256'],'Viewer QA hash mismatch')
        preview=path(R7+'/interactive/qa/r7-preview.html')
        require(browser['preview_sha256']==sha(preview)and browser['preview_fragment_matches']is True,'Standalone preview browser QA mismatch')
        views=read(R7+'/interactive/views/VIEWS-VALIDATION.json')
        require(views['native_sha256']==sha(path(NATIVE))and views['fragment_sha256']==sha(fragment),'Final view source hash mismatch')
        require(views['preview_sha256']==sha(preview),'Final views standalone preview hash mismatch')
        require({row['mode']for row in views['images']}=={'assembled','exploded','cutaway'},'Final view set')
        for row in views['images']:
            require(sha(path(R7+'/interactive/views/R7-'+row['mode']+'.png'))==row['sha256'],'Final view image hash mismatch')
        bom=read(R7+'/documentation/bom/BOM-VALIDATION.json')
        require(not bom['visual_review_pending'],'BOM visual review pending')
        for extension in ['xlsx','csv']:
            require(sha(path(R7+'/documentation/bom/LoRa-C5-R7-Complete-BOM.'+extension))==bom['files'][extension],'BOM artifact hash mismatch')
        require(bom['reviewed_xlsx_sha256']==bom['files']['xlsx'],'BOM visual review hash mismatch')
        for original,expected in bom['source_hashes'].items():
            normalized=original.replace('\\','/');needle='/'+R7+'/'
            require(needle in normalized,'Unexpected current BOM source')
            require(sha(path(R7+'/'+normalized.split(needle,1)[1]))==expected,'BOM source hash mismatch')
        shop=read(R7+'/cnc-shop/CNC-SHOP-GEOMETRY-MANIFEST.json')
        require(shop['native_sha256']==sha(path(NATIVE))and shop['step_sha256']==sha(path(STEP)),'CNC handoff source hash mismatch')
        require(shop['native_validation_sha256']==sha(path(R7+'/audit/saved-r7-validation.json')),'CNC handoff native validation mismatch')
        require(shop['geometry_copy']['sha256']==sha(path(R7+'/'+shop['geometry_copy']['path']))==sha(path(STEP)),'CNC handoff copy hash mismatch')
        require(shop['machine_program_supplied']is False and shop['units']=='mm'and shop['installed_parts']==7 and shop['optional_coupon_parts']==1,'CNC handoff scope mismatch')
        geometry=read(R7+'/documentation/manufacturing/manufacturing-geometry.json')
        require(geometry['ok']and geometry['release_ready']and all(geometry['source_unchanged'].values()),'Manufacturing drawing geometry is still preflight')
        for original,expected in geometry['source_hashes'].items():
            normalized=original.replace('\\','/');needle='/'+R7+'/'
            require(needle in normalized,'Unexpected final drawing source')
            relative=R7+'/'+normalized.split(needle,1)[1]
            require(sha(path(relative))==expected,'Manufacturing geometry source hash mismatch')
        manufacturing=read(R7+'/documentation/manufacturing/MANUFACTURING-DRAWING-VALIDATION.json')
        require(manufacturing['release_ready']and manufacturing['pages']==9 and not manufacturing['visual_review_pending'],'Manufacturing drawing release/review gate')
        pdf=path(R7+'/documentation/manufacturing/C5-R7-Manufacturing-Drawings.pdf')
        require(manufacturing['pdf']=='C5-R7-Manufacturing-Drawings.pdf','Unexpected manufacturing drawing artifact')
        require(manufacturing['pdf_sha256']==manufacturing['reviewed_pdf_sha256']==sha(pdf),'Manufacturing PDF visual-review hash mismatch')
        require(manufacturing['geometry_sha256']==sha(path(R7+'/documentation/manufacturing/manufacturing-geometry.json')),'Manufacturing drawing geometry hash mismatch')
        require(manufacturing['native_sha256']==sha(path(NATIVE))and manufacturing['step_sha256']==sha(path(STEP)),'Manufacturing drawing CAD hashes mismatch')
        for original,expected in manufacturing['source_hashes'].items():
            normalized=original.replace('\\','/');needle='/'+R7+'/'
            require(needle in normalized,'Unexpected manufacturing drawing source')
            require(sha(path(R7+'/'+normalized.split(needle,1)[1]))==expected,'Manufacturing drawing source hash mismatch')
        _,checks['viewer_reconstruction']=reconstruct(path(R7+'/interactive'))
        dependencies=read('R7-PUBLICATION-DEPENDENCIES.json')
        allowed={'README.md','CURRENT-RELEASE.json','SOURCE-NOTICES.md','tools/validate_archive.py'}
        for name,expected in dependencies['baseline_files'].items():
            require(path(name).is_file(),'Historical archive file dropped: '+name)
            if name=='.gitattributes':
                raw=path(name).read_bytes();addition=b'*.brep binary\n'
                require(raw.endswith(addition)and hashlib.sha256(raw[:-len(addition)]).hexdigest()==expected,'Historical attributes differ beyond the exact BREP binary addition')
            elif name not in allowed:require(sha(path(name))==expected,'Historical bytes changed: '+name)
        for row in dependencies['portable_viewer_inputs']:
            require(sha(path(row['path']))==row['sha256'],'Portable viewer input changed')
        for p in root.rglob('*'):
            if not p.is_file():continue
            rel=p.relative_to(root).as_posix()
            require(not p.name.lower().startswith(('user-supplied-','codex-clipboard-')),'Product artwork in archive: '+rel)
            require(not any(piece.startswith('.')for piece in p.relative_to(root).parts[:-1]),'Hidden runtime folder: '+rel)
        checks.update(native_parts=8,installed_parts=7,optional_coupon_parts=1,unchanged_components=native['unchanged_electronics']['objects_compared'],derivative_inputs=checked,historical_files_retained=len(dependencies['baseline_files']),order_placed=False)
    except (ValueError,OSError,KeyError,TypeError)as error:failures.append(str(error))
    return {'ok':not failures,'checks':checks,'failures':failures}
