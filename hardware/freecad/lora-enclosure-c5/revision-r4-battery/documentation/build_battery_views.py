"""Read saved R4 CAD and create presentation-only views and exact section data.

Run with the FreeCAD bundled Python. Never saves native CAD or manufacturing
exports. The presentation boards retain the six actual assigned KiCad models.
"""
from pathlib import Path
import argparse, hashlib, json, math, os, re, uuid
import FreeCAD as App
import Part

out = Path(__file__).resolve().parent
root = out.parent
enclosure = root.parent
p = argparse.ArgumentParser()
p.add_argument('--config', default=str(out/'view-config.json'))
a = p.parse_args()
cfg = json.loads(Path(a.config).read_text(encoding='utf-8-sig'))
cad = Path(cfg['native_file'])
source = enclosure/'final-design/pcb-fabrication/source/heltec_v4_audio_carrier.kicad_pcb'
assembly = enclosure/'detailed-import/C5-detailed-assembly.step'
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
initial = {str(path): sha(path) for path in (cad, source, assembly)}
presentation = out/'presentation'
models = presentation/'models'
models.mkdir(parents=True, exist_ok=True)

def bounds(s):
    b=s.optimalBoundingBox(False,False)
    return [b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]

def box(bb):
    x0,y0,z0,x1,y1,z1=bb
    return Part.makeBox(x1-x0,y1-y0,z1-z0,App.Vector(x0,y0,z0))

doc=App.openDocument(str(cad))
parts={name: doc.getObject(name).Shape.copy() for name in cfg['printed_objects']}
for name in cfg.get('reference_objects',[]):
    parts[name]=doc.getObject(name).Shape.copy()
battery_name=cfg.get('battery_object','BatteryEnvelope')
if battery_name not in parts:
    obj=doc.getObject(battery_name)
    if obj and hasattr(obj,'Shape'):
        parts[battery_name]=obj.Shape.copy()
    else:
        # Explicit user-photo-derived packaging envelope, never a manufacturer model.
        parts[battery_name]=box(cfg['battery_bounds_mm'])
colors={name:tuple(color) for name,color in cfg['colors'].items()}
colors.setdefault(battery_name,(.13,.63,.39))
if cfg.get('padding_bounds_mm'):
    parts['ReferenceSoftPad']=box(cfg['padding_bounds_mm'])
    colors['ReferenceSoftPad']=(.34,.38,.40)
actual_battery=bounds(parts[battery_name])
assert max(abs(a-b) for a,b in zip(actual_battery,cfg['battery_bounds_mm']))<1e-6
assert abs(bounds(parts['EnclosureBase'])[4]-cfg['dimensions']['case_ymax'])<1e-6
actual_height=bounds(parts['EnclosureLid'])[5]-bounds(parts['BatteryCover'])[2]
assert abs(actual_height-cfg['dimensions']['overall_height_mm'])<1e-6
reference_sources=[]
if cfg.get('harness_reference'):
    hp=Path(cfg['harness_reference'])
    harness=json.loads(hp.read_text())
    reference_sources.append(dict(file=str(hp),sha256=sha(hp),purpose='Provisional plug and harness packaging envelopes; not purchased connector CAD.'))
    parts['ReferenceBatteryPlug']=box(harness['plug_assumed_bounds_mm'])
    colors['ReferenceBatteryPlug']=(.82,.83,.79)
    for name,dx,color in [('ReferenceLeadPositive',-.4,(.82,.06,.025)),('ReferenceLeadNegative',.4,(.08,.08,.08))]:
        points=[App.Vector(x+dx,y,z) for x,y,z in harness['lead_centerline_mm']]
        segments=[]
        for start,end in zip(points,points[1:]):
            delta=end-start
            if delta.Length>1e-8:
                segments.append(Part.makeCylinder(.35,delta.Length,start,delta.normalize()))
        segments.extend(Part.makeSphere(.35,v) for v in points[1:-1])
        parts[name]=segments[0].multiFuse(segments[1:]).removeSplitter()
        colors[name]=color

def export_wrl(path,shape,color,cut_planes=()):
    lines=['#VRML V2.0 utf8','# Presentation only; 1 VRML unit = 2.54 mm.']
    count=0
    for f in shape.Faces:
        b=f.BoundBox
        cut=any(abs(getattr(b,axis+'Min')-v)<1e-6 and abs(getattr(b,axis+'Max')-v)<1e-6 for axis,v in cut_planes)
        c=(.88,.64,.31) if cut else color
        vs,fs=f.tessellate(.03)
        count+=len(fs)
        lines+=['Shape { appearance Appearance { material Material { diffuseColor %s specularColor .16 .16 .16 shininess .25 } } geometry IndexedFaceSet { solid TRUE creaseAngle .7 coord Coordinate { point ['%' '.join(map(str,c))]
        lines+=['%.9f %.9f %.9f,'%tuple(vv/2.54 for vv in (v.x,v.y,v.z)) for v in vs]
        lines+=['] } coordIndex [']+['%d,%d,%d,-1,'%tuple(t) for t in fs]+['] } }']
    path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return dict(file=str(path),sha256=sha(path),triangles=count)

source_text=source.read_text(encoding='utf-8')
actual_models=[]
for model in re.findall(r'\(model\s+"([^"]+)"',source_text):
    path=source.parent/model.replace('${KIPRJMOD}/','')
    actual_models.append(dict(path=str(path),sha256=sha(path)))
assert len(actual_models)==6
model_rel=Path(os.path.relpath(source.parent,presentation)).as_posix()
template=source_text.replace('${KIPRJMOD}/','${KIPRJMOD}/'+model_rel+'/')
manifest=dict(native_file=str(cad),native_sha256=sha(cad),source_board=str(source),source_board_sha256=sha(source),actual_component_models=actual_models,battery_description=cfg['battery_description'],hardware_and_routing=cfg.get('hardware_and_routing','Reference geometry only.'),reference_sources=reference_sources,views=[])

for view,settings in cfg['views'].items():
    extras=[]
    entries=[]
    for name,original in parts.items():
        if name in settings.get('hide',[]):
            continue
        shape=original.copy()
        planes=[]
        for cut in settings.get('cuts',[]):
            if name in cut['objects']:
                shape=shape.cut(box(cut['bounds_mm'])).removeSplitter()
                planes.extend((axis,float(value)) for axis,value in cut.get('planes',[]))
        if shape.isNull():
            continue
        assert shape.isValid(),name
        offset=float(settings.get('z_offsets',{}).get(name,0))
        path=models/(view+'-'+name+'.wrl')
        entry=export_wrl(path,shape,colors.get(name,(.55,.60,.64)),planes)
        uid=uuid.uuid5(uuid.NAMESPACE_URL,'R4'+view+name)
        extras.append(f'''\n  (footprint "Presentation:{name}" (layer "F.Cu")
    (uuid "{uid}") (at 100 190)
    (property "Reference" "VIEW_{name.upper()}" (at 0 0) (layer "F.Fab") (hide yes) (effects (font (size 1 1) (thickness .15))))
    (property "Value" "Presentation only" (at 0 0) (layer "F.Fab") (hide yes) (effects (font (size 1 1) (thickness .15))))
    (attr exclude_from_pos_files exclude_from_bom)
    (model "${{KIPRJMOD}}/models/{path.name}" (offset (xyz 0 0 {offset-8})) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))
  )\n''')
        entries.append(dict(name=name,source_bounds_mm=bounds(original),shown_bounds_mm=bounds(shape),presentation_z_offset_mm=offset,**entry))
    board=presentation/(view+'.kicad_pcb')
    i=template.rfind(')')
    board.write_text(template[:i]+''.join(extras)+template[i:],encoding='utf-8')
    manifest['views'].append(dict(view=view,board=str(board),sha256=sha(board),objects=entries,render=settings['render']))

# Exact longitudinal section at X23 includes the OLED, Heltec and battery.
section_x=float(cfg.get('section_x_mm',23))
def section(shapes):
    lines=[]
    for s in shapes:
        b=s.BoundBox
        if b.XMin-1e-7<=section_x<=b.XMax+1e-7:
            for w in s.slice(App.Vector(1,0,0),section_x):
                points=[[round(v.y,7),round(v.z,7)] for v in w.discretize(Deflection=.025)]
                if w.isClosed() and points[-1]!=points[0]:points.append(points[0])
                lines.append(dict(points=points,closed=w.isClosed()))
    return lines
sections={name:section([shape]) for name,shape in parts.items()}
cache=json.loads((out/'electronics-section-cache.json').read_text())
assert cache['reference_sha256']==sha(assembly) and abs(cache['section_x_mm']-section_x)<1e-9
sections.update(cache['sections'])
geometry=dict(units='mm',section_plane=dict(axis='X',value_mm=section_x,drawing_axes=['Y','Z']),method='Actual B-rep planar slices, discretized to 0.025 mm deflection.',native_file=str(cad),native_sha256=sha(cad),reference_sha256=sha(assembly),sections=sections,dimensions=cfg['dimensions'],battery_description=cfg['battery_description'])
(out/'battery-section-geometry.json').write_text(json.dumps(geometry,indent=2)+'\n',encoding='utf-8')
manifest['source_hashes_unchanged']={path:sha(Path(path))==value for path,value in initial.items()}
assert all(manifest['source_hashes_unchanged'].values())
(out/'view-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
App.closeDocument(doc.Name)
print(json.dumps(dict(ok=True,views=[v['board'] for v in manifest['views']],sections={n:len(w) for n,w in sections.items()},source_files_unchanged=True)))
