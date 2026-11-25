"""Build the self-contained R6 interactive fragment from audited source meshes."""
from pathlib import Path
import base64,gzip,hashlib,json,struct

root=Path(__file__).resolve().parent
template=root/'r6-enclosure-viewer.template.html'
encoded=(root/'mesh/mesh-data.b64').read_text().strip()
mesh_report=json.loads((root/'mesh/MESH-VALIDATION.json').read_text())
assert mesh_report['ok'] and mesh_report['packed_round_trip_exact']
assert not mesh_report['geometric_decimation_applied']
assert all(mesh_report['source_files_unchanged'].values())
packed=gzip.decompress(base64.b64decode(encoded))
header_length=struct.unpack_from('<I',packed)[0]
header=json.loads(packed[4:4+header_length])
data=json.loads((root/'mesh/mesh-data.json').read_text())
assert len(data['parts'])==len(header['parts'])
assert header['schema']==2
assert data['units']=='mm'
required={'base','lid','cover','plunger','cup','pcb','heltec','oled','microphone','amplifier','switch','resistor','battery','sma_body','sma_washer','sma_nut','antenna','coax','coax_plug','speaker','speaker_retainer','speaker_lead_a','speaker_lead_b'}
assert required<={p.get('part',p['id'].removesuffix('_cut'))for p in data['parts']}
for part in ('base','lid','cover'):
    assert any(p.get('part',p['id'].removesuffix('_cut'))==part and p.get('variant')=='cut'for p in data['parts'])
text=template.read_text(encoding='utf-8')
source_config=json.loads((root/'SOURCE-INPUTS.json').read_text())
assert text.count('__R6_SOURCE_LABEL__')==1
text=text.replace('__R6_SOURCE_LABEL__','Draft R6 design' if 'preflight' in source_config['source_status'] else 'R6 design')
assert text.count('__R6_MESH_BASE64__')==1
text=text.replace('__R6_MESH_BASE64__',encoded)
dimensions=json.loads((root/'dimensions/dimensions.json').read_text(encoding='utf-8'))
dimension_report=json.loads((root/'dimensions/DIMENSION-VALIDATION.json').read_text(encoding='utf-8'))
assert dimension_report['ok'] and all(dimension_report['source_files_unchanged'].values())
assert text.count('__R6_DIMENSIONS_JSON__')==1
assert {'battery','pcb','oled'}<={d['category']for d in dimensions['dimensions']}
for d in dimensions['dimensions']:
    assert len(d['start_mm'])==len(d['end_mm'])==3
    distance=sum((b-a)**2 for a,b in zip(d['start_mm'],d['end_mm']))**.5
    assert abs(distance-d['value_mm'])<1e-6,d['id']
text=text.replace('__R6_DIMENSIONS_JSON__',json.dumps(dimensions,separators=(',',':')).replace('</','<\\/'))
focus_encoded=(root/'focus/focus-mesh-data.b64').read_text().strip()
focus_report=json.loads((root/'focus/FOCUS-MESH-VALIDATION.json').read_text())
assert focus_report['ok'] and all(focus_report['source_files_unchanged'].values())
focus_views={'views':json.loads((root/'focus/focus-views.json').read_text())}
assert {v['id']for v in focus_views['views']}=={d['id']for d in dimensions['dimensions']}
assert text.count('__R6_FOCUS_MESH_BASE64__')==text.count('__R6_FOCUS_JSON__')==1
text=text.replace('__R6_FOCUS_MESH_BASE64__',focus_encoded)
text=text.replace('__R6_FOCUS_JSON__',json.dumps(focus_views,separators=(',',':')).replace('</','<\\/'))
assert len(text.encode())<1_000_000,'Inline viewer exceeds 1MB'
assert not any(tag in text.lower()for tag in ('<!doctype','<html','<head>','<body>'))
output=root/'r6-enclosure-viewer.html';output.write_text(text,encoding='utf-8')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
report=dict(ok=True,fragment=str(output),bytes=output.stat().st_size,sha256=sha(output),
            source_status=source_config['source_status'],
            mesh_gzip_sha256=hashlib.sha256(base64.b64decode(encoded)).hexdigest(),
            template_sha256=sha(template),mesh_count=len(data['parts'])+focus_report['parts'],
            overview_mesh_count=len(data['parts']),focus_mesh_count=focus_report['parts'],
            mesh_validation_sha256=sha(root/'mesh/MESH-VALIDATION.json'),
            dimension_data_sha256=sha(root/'dimensions/dimensions.json'),
            focus_mesh_sha256=sha(root/'focus/focus-mesh-data.b64'),
            focus_views_sha256=sha(root/'focus/focus-views.json'),
            focus_validation_sha256=sha(root/'focus/FOCUS-MESH-VALIDATION.json'),
            overview_triangles=sum(len(p['indices'])//3 for p in data['parts']),focus_triangles=focus_report['triangles'],
            triangles=sum(len(p['indices'])//3 for p in data['parts'])+focus_report['triangles'],network_requests_required=False,
            cad_files_modified=False)
(root/'BUILD-VALIDATION.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
