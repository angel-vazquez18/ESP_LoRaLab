"""Read-only validation of approved R6 CAD/STEP/STL/3MF exports."""
from pathlib import Path
import hashlib, importlib.util, itertools, json, runpy, zipfile
from fractions import Fraction
import FreeCAD as A, Part

ROOT=Path(__file__).resolve().parent
ENC=ROOT.parent
STEMS={'EnclosureBase':'enclosure-base','EnclosureLid':'enclosure-lid',
       'PTTPlunger':'ptt-plunger','PTTStopCup':'ptt-stop-cup',
       'BatteryCover':'battery-cover','SpeakerRetainer':'speaker-retainer'}
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    out=importlib.util.module_from_spec(spec);spec.loader.exec_module(out);return out
h=module('r6_mesh_helpers',ENC/'revision-r4-battery/audit/validate_r4_exports.py')
v=module('r6_topology_helpers',ENC/'fit-checked/verify_exports.py')
native=ROOT/'cad/LoRa-Enclosure-C5-R6-Speaker.FCStd'
step=ROOT/'cad/LoRa-Enclosure-C5-R6-Speaker.step'
files={'native':native,'step':step}
for n,stem in STEMS.items():
    for ext in ['stl','3mf']:files[n+'.'+ext]=ROOT/f'printing/C5-R6-{stem}-mm.{ext}'
missing=[str(p)for p in files.values()if not p.is_file()]
if missing:raise SystemExit('Wait for approved exports: '+', '.join(missing))
initial={n:sha(p)for n,p in files.items()}
h.FILES=files
report={'ok':False,'files':{n:{'path':str(p),'sha256':initial[n]}for n,p in files.items()},'failures':[],'step':{},'meshes':{}}
def check(ok,label):
    if not ok:report['failures'].append(label)

def retainer_rounding_certificate(result):
    """Supplement the volume heuristic only for this independently proven pair.

    Re-run the exact rational proof against current files. All existing native,
    topology, winding, bounding-box and pointwise gates remain mandatory.
    """
    script=ROOT/'audit/verify_retainer_format_precision.py'
    runpy.run_path(str(script))
    path=ROOT/'audit/retainer-format-precision.json'
    proof=json.loads(path.read_text())
    s,m=result['stl'],result['three_mf']
    c=result['stl_three_mf_comparison']
    serial,corr,vol=proof['serialization'],proof['correspondence'],proof['volume_certificate']
    rational=lambda key:Fraction(int(vol[key]['numerator']),int(vol[key]['denominator']))
    delta=rational('absolute_volume_difference_mm3')
    bound=rational('exact_sum_absolute_per_triangle_volume_deltas_mm3')
    expansion=rational('exact_multilinear_coordinate_perturbation_bound_mm3')
    gates={
        'certificate_succeeded':proof['ok'],
        'certificate_hashes_match_current_exports':all(
            proof['source_hashes'].get(str(files['SpeakerRetainer.'+ext]))==sha(files['SpeakerRetainer.'+ext])
            for ext in ['stl','3mf']),
        'certificate_inputs_unchanged':all(proof['source_files_unchanged'].values()),
        'topology_and_positive_winding':all(x['topology']['ok'] and x['topology']['signed_volume_mm3']>0 for x in [s,m]),
        'native_comparisons':all(x['native_comparison']['matches']for x in [s,m]),
        'cross_format_bounds':c['max_bounds_difference_mm']<1e-4,
        'cross_format_pointwise':c['corresponding_triangle_max_vertex_difference_mm'] is not None and c['corresponding_triangle_max_vertex_difference_mm']<1e-4,
        'millimeter_rounding':serial['three_mf_unit']=='millimeter' and serial['xml_coordinate_grid_mm']==1e-4 and serial['all_xml_coordinates_are_nearest_0_0001_mm_rounding_of_corresponding_stl'],
        'certified_pointwise':serial['pointwise_1e_4_mm_gate_passed'] and serial['max_axis_coordinate_difference_mm']['value']<1e-4,
        'same_oriented_connectivity':corr['global_bijective_vertex_mapping'] and corr['identical_oriented_triangle_connectivity'],
        'closed_nondegenerate_connected':corr['every_edge_has_two_opposite_directed_owners'] and corr['exact_zero_area_triangles_in_either_mesh']==0 and corr['connected_components']==1,
        'volume_delta_within_exact_bounds':0<=delta<=bound<=expansion and vol['delta_is_within_exact_bounds'],
        'independent_volume_calculations_agree':abs(float(delta)-c['absolute_volume_difference_mm3'])<1e-9 and all(
            abs(vol[key]['value']-mesh['topology']['signed_volume_mm3'])<1e-9
            for key,mesh in [('stl_signed_volume_mm3',s),('three_mf_signed_volume_mm3',m)]),
    }
    result['legacy_relative_volume_heuristic_passed']=c['relative_volume_difference']<c['relative_volume_tolerance']
    result['serialization_certificate']={'path':str(path.relative_to(ROOT)),'sha256':sha(path),
        'script_sha256':sha(script),'gates':gates,
        'reason':'Exact coordinate-rounding proof supplements the failed 1 ppm volume heuristic; no dimensional or topology limit changed.'}
    result['ok']=all(gates.values())
    return result
with zipfile.ZipFile(native)as z:check(z.testzip() is None,'FCStd ZIP integrity')
doc=A.openDocument(str(native))
try:
    shapes={n:doc.getObject(n).Shape.copy()for n in STEMS}
    report['native']={n:h.info(s)for n,s in shapes.items()}
    check(all(s['valid']and s['closed']and s['solids']==1 for s in report['native'].values()),'Native solids')
    imported=Part.read(str(step)).Solids
    check(len(imported)==6,'STEP must contain six printable solids')
    if len(imported)==6:
        nb={n:h.bbox(s)for n,s in shapes.items()};sb=[h.bbox(s)for s in imported]
        cost={(n,i):sum(abs(a-b)for a,b in zip(nb[n],sb[i]))+abs(s.Volume-imported[i].Volume)/s.Volume for n,s in shapes.items()for i in range(6)}
        pairing=min(itertools.permutations(range(6)),key=lambda order:sum(cost[n,i]for n,i in zip(STEMS,order)))
        for n,i in zip(STEMS,pairing):
            result=h.compare(shapes[n],imported[i]);report['step'][n]=result;check(result['matches'],'STEP geometry '+n)
    doc.recompute()
    report['recompute']={n:h.compare(s,doc.getObject(n).Shape)for n,s in shapes.items()}
    check(all(r['matches']for r in report['recompute'].values()),'Recompute changed geometry')
    old_manifest=json.loads((ENC/'final-design/craftcloud/upload-manifest.json').read_text())
    old={r['part']:r for r in old_manifest['files']}
    for n,stem in STEMS.items():
        translation=[-float(x)for x in old[stem]['translation_from_assembly_mm']]if n in ['PTTPlunger','PTTStopCup']else[0,0,0]
        report['meshes'][n]=h.check_mesh_pair(n,shapes[n],v,translation)
        if n=='SpeakerRetainer' and not report['meshes'][n]['ok']:
            report['meshes'][n]=retainer_rounding_certificate(report['meshes'][n])
        check(report['meshes'][n]['ok'],'Mesh integrity '+n)
        print(n,'mesh ok',report['meshes'][n]['ok'],flush=True)
    report['source_files_unchanged']={n:sha(p)==initial[n]for n,p in files.items()}
    check(all(report['source_files_unchanged'].values()),'Source changed during verification')
    report['ok']=not report['failures']
finally:A.closeDocument(doc.Name)
(ROOT/'manufacturing-validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'ok':report['ok'],'failures':report['failures']}))
if not report['ok']:raise SystemExit(1)
