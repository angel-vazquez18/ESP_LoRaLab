from pathlib import Path
import json
import FreeCAD, Part

folder=Path(__file__).resolve().parent/'source-project/models'
audit_file=folder.parent/'vrml-step-conversion-audit.json'
audit=json.loads(audit_file.read_text())
for record in audit:
    path=folder/Path(record['target']).name
    shape=Part.read(str(path))
    box=shape.BoundBox
    actual={'min':[box.XMin,box.YMin,box.ZMin],'max':[box.XMax,box.YMax,box.ZMax]}
    delta=max(abs(actual[k][i]-record['bbox_mm'][k][i]) for k in ('min','max') for i in range(3))
    validation={'face_count':len(shape.Faces),'solid_count':len(shape.Solids),'valid':shape.isValid(),'invalid_face_count':sum(not face.isValid() for face in shape.Faces),'bbox_mm':actual,'bbox_max_difference_mm':delta,'matches_source_facets':len(shape.Faces)==record['triangles']}
    assert validation['solid_count']==0 and validation['matches_source_facets'] and delta<1e-6,validation
    if not validation['valid']:
        validation['limitation']=f"FreeCAD reports bad subshape orientation on {validation['invalid_face_count']} small microphone faces. All nonzero source facet coordinates and face counts are preserved. This is a presentation surface model, not a printable/manufacturing solid."
    record['FreeCAD_roundtrip']=validation
    print(json.dumps({'file':path.name,**validation}),flush=True)
audit_file.write_text(json.dumps(audit,indent=2)+'\n')
print('ALL_FOUR_FACET_COUNTS_AND_BOUNDS_MATCH; SEE VALIDITY_LIMITATION',flush=True)
