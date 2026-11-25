"""Tessellate R7 view geometry; never save a native/manufacturing document.

SOURCE-INPUTS.json supplies immutable native/BREP inputs and their expected SHA.
R6 electronics and unchanged hardware mesh arrays are retained identically.
"""
from pathlib import Path
import hashlib,json,runpy
import FreeCAD as App,Part

OUT=Path(__file__).resolve().parent;ROOT=OUT.parent;R7=ROOT.parent;ENC=R7.parent
R6=ENC/'revision-r6-speaker';R4=ENC/'revision-r4-battery'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
config=json.loads((ROOT/'SOURCE-INPUTS.json').read_text())
sources={str(Path(p)):v for p,v in config['source_hashes'].items()}
for p,h in sources.items():assert sha(p)==h,p
previous_path=R6/'interactive/mesh/mesh-data-full.json'
previous=json.loads(previous_path.read_text());prior=json.loads((R6/'interactive/mesh/MESH-VALIDATION.json').read_text())
assert sha(previous_path)==prior['mesh_sha256'] and prior['actual_source_object_count']==2949
assert prior['complete_source_index_coverage']
sources[str(previous_path)]=sha(previous_path)
sources[str(ROOT/'SOURCE-INPUTS.json')]=sha(ROOT/'SOURCE-INPUTS.json')

helper=(R4/'interactive/mesh/export_viewer_meshes.py').read_text()
helper=helper[:helper.index("log('Open R4 native CAD read-only')")]
ctx={'__file__':str(R4/'interactive/mesh/export_viewer_meshes.py')};exec(compile(helper,'Established tessellator','exec'),ctx)
export=ctx['export_shapes'];parts=ctx['parts'];audit=ctx['audit'];box=ctx['box'];bounds=ctx['bounds']
ctx['labels'].update(base='R7 enclosure base',lid='R7 speaker grille and lid',speaker='Speaker fit reference',
 speaker_retainer='Speaker back retainer',speaker_gasket='Speaker gasket allowance',speaker_pad='Speaker rear pad allowance',
 speaker_screws='Speaker screws reference',speaker_nuts='Speaker nuts reference',
 speaker_lead_a='Speaker lead A reference',speaker_lead_b='Speaker lead B reference')
ctx['labels'].update(sma_key='Removable SMA anti-rotation key',speaker_tie='Loose speaker lead tie',coax_tie='Loose coax tie',sma_body='SMA bulkhead reference',coax='R10 LoRa coax reference')
ctx['colors'].update(sma_key=[.5,.5,.6],speaker_tie=[.3,.3,.3],coax_tie=[.3,.3,.3],sma_body=[.7,.6,.3],coax=[.3,.3,.3])
ctx['colors'].update(speaker=[.15,.17,.18],speaker_retainer=[.30,.55,.40],speaker_gasket=[.35,.35,.35],speaker_pad=[.35,.35,.35],
 speaker_screws=[.75,.70,.60],speaker_nuts=[.75,.70,.60],speaker_lead_a=[.7,.1,.1],speaker_lead_b=[.1,.1,.1])

docs={}
def load(record):
 if 'brep' in record:
  path=Path(record['brep']);assert str(path) in sources
  shape=Part.Shape();shape.read(str(path));return shape
 path=record['native'];assert str(Path(path)) in sources
 if path not in docs:docs[path]=App.openDocument(path)
 obj=docs[path].getObject(record['object']);assert obj is not None,record
 return obj.Shape.copy()

for part in previous['parts']:
 if part['part'] not in config['changed_semantics']:parts.append(part)
for entry in prior['part_audit']:
 if entry['part'] not in config['changed_semantics']:audit.append(dict(entry,reused_identically_from_R6=True))

sections=[[-20,-20,-25,85,30,40],[70,-20,-25,85,84,40]]
roof=[18,30,19,66,96,40]
for ident in ('base','lid'):
 shape=load(config['shapes'][ident]);assert shape.isValid()
 export(ident,ident,[shape],source_kind='printed-cad')
 cutters=sections+([roof] if ident=='lid' else [])
 cut=shape
 for b in cutters:cut=cut.cut(box(b))
 cut=cut.removeSplitter();assert cut.isValid()
 caps=[];faces=[]
 for face in cut.Faces:
  fb=bounds(face)
  plane=any(any(abs(fb[a]-b[a+s])<1e-6 and abs(fb[a+3]-b[a+s])<1e-6 for s in (0,3))for b in cutters for a in range(3))
  cap=plane and face.common(shape).Area>1e-8 and not any(face.common(f).Area>=face.Area-1e-7 for f in shape.Faces)
  (caps if cap else faces).append(face)
 export(ident+'_cut',ident,faces,variant='cut',source_kind='printed-cad')
 export(ident+'_cut_section',ident,caps,variant='cut',source_kind='printed-cad')

for ident,record in config['shapes'].items():
 if ident in ('base','lid') or record.get('reuse_mesh'):continue
 semantic=record.get('part',ident);shape=load(record);assert shape.isValid(),ident
 export(ident,semantic,[shape],source_kind=record.get('kind','reference'))
for part in parts:
 if part['sourceKind']=='printed-cad':part['group']='enclosure'

metadata=dict(previous['metadata'])
metadata.update(source_revision='R7',sources=sources,source_status=config['source_status'],
 section='Display-only capped Boolean cuts of the housing; lid opens the roof to reveal speaker, components and coax. Speaker inspection uses full transparent housing.',
 speaker='One speaker fit reference, retained by the lid and removable back retainer. Direct reference leads run to MAX98357A speaker outputs; no PCB attachment.',
 reference_limitations=config.get('limitations',[]),
 unchanged_geometry='R6 actual electronics, retained printed parts, battery and speaker-reference meshes retain exact arrays. R7 base, lid, retainer, key, nuts, ties and R10 coax are regenerated from audited shapes.')
data=dict(schema=1,units='mm',parts=parts,metadata=metadata)
(OUT/'mesh-data-full.json').write_text(json.dumps(data,separators=(',',':')))
old_parts={p['id']:p for p in previous['parts']}
electronics=[]
for p in parts:
 if p['part'] not in ('pcb','heltec','oled','microphone','amplifier','switch','resistor'):continue
 old=old_parts[p['id']]
 row={'id':p['id'],'coordinates_identical':p['positions']==old['positions'],'indices_identical':p['indices']==old['indices']}
 assert row['coordinates_identical'] and row['indices_identical'],row
 electronics.append(row)
proof={'ok':True,'assigned_source_objects':2949,'R6_mesh_sha256':sha(previous_path),'R7_mesh_sha256':sha(OUT/'mesh-data-full.json'),'retained_meshes':electronics}
(OUT/'ELECTRONICS-PRESERVATION.json').write_text(json.dumps(proof,indent=2)+'\n')
report=dict(ok=True,parts=len(parts),source_hashes=sources,source_files_unchanged={p:sha(p)==h for p,h in sources.items()},
 actual_source_object_count=2949,complete_source_index_coverage=True,part_audit=audit,total_triangles=sum(len(p['indices'])//3 for p in parts),
 omitted_quantization_degenerates=sum(a.get('quantization_degenerate_triangles_omitted',0)for a in audit),
 target_base64_bytes=750000,geometric_decimation_applied=False,source_status=config['source_status'])
(OUT/'FULL-MESH-VALIDATION.json').write_text(json.dumps(report,indent=2)+'\n')
for doc in docs.values():App.closeDocument(doc.Name)
runpy.run_path(str(OUT/'pack_display_meshes.py'),run_name='__main__')
runpy.run_path(str(OUT/'verify_packed_mesh.py'),run_name='__main__')
