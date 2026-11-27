"""ASCII DXF top projections for a CNC shop's reference, never toolpaths.

Uses CAD-derived visible and hidden linework from extract_drawing_geometry.py.
All units are millimetres. STEP remains authoritative for 3D surfaces/depths.
"""
import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ap=argparse.ArgumentParser()
ap.add_argument("--geometry",default=str(HERE/"drawing-geometry.json"))
ap.add_argument("--output",default=str(HERE/"cnc-reference"))
args=ap.parse_args()
D=json.loads(Path(args.geometry).read_text(encoding="utf-8"))
out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
records=[]
for name,part in D["parts"].items():
    codes=[]
    def put(code,value):codes.extend([str(code),str(value)])
    put(0,"SECTION");put(2,"HEADER")
    put(9,"$ACADVER");put(1,"AC1015")
    put(9,"$INSUNITS");put(70,4)
    put(9,"$MEASUREMENT");put(70,1)
    put(0,"ENDSEC")
    put(0,"SECTION");put(2,"TABLES")
    put(0,"TABLE");put(2,"LTYPE");put(70,1)
    put(0,"LTYPE");put(2,"CONTINUOUS");put(70,0);put(3,"Solid line");put(72,65);put(73,0);put(40,0)
    put(0,"ENDTAB")
    put(0,"TABLE");put(2,"LAYER");put(70,3)
    for layer,color in [("TOP_VISIBLE",7),("TOP_HIDDEN_REFERENCE",8),("NOTES_NOT_GEOMETRY",3)]:
        put(0,"LAYER");put(2,layer);put(70,0);put(62,color);put(6,"CONTINUOUS")
    put(0,"ENDTAB");put(0,"ENDSEC")
    put(0,"SECTION");put(2,"ENTITIES")
    n=0
    for kind in ("visible","hidden"):
        for vertices in part["views"]["top"][kind]:
            if len(vertices)<2:continue
            closed=sum((vertices[0][i]-vertices[-1][i])**2 for i in (0,1))<1e-10
            if closed:vertices=vertices[:-1]
            put(0,"LWPOLYLINE");put(100,"AcDbEntity");put(8,"TOP_VISIBLE" if kind=="visible" else "TOP_HIDDEN_REFERENCE")
            put(100,"AcDbPolyline");put(90,len(vertices));put(70,1 if closed else 0)
            for x,y in vertices:put(10,f"{x:.6f}");put(20,f"{y:.6f}")
            n+=1
    x0,y0,_,x1,y1,_=part["bounds_mm"]
    notes=[name+" / TOP PROJECTION / mm", "REFERENCE ONLY - NO TOOLPATHS OR DEPTHS", "STEP controls 3D geometry. Curves sampled to 0.025 mm deflection.", "Origin: carrier PCB lower-left XY; do not rescale."]
    for i,note in enumerate(notes):
        put(0,"TEXT");put(100,"AcDbEntity");put(8,"NOTES_NOT_GEOMETRY")
        put(100,"AcDbText");put(10,x0);put(20,y0-5-i*2);put(30,0);put(40,1.3);put(1,note)
    put(0,"ENDSEC");put(0,"EOF")
    file=out/(name+"-top-reference.dxf")
    file.write_text("\n".join(codes)+"\n",encoding="ascii")
    records.append({"part":name,"file":str(file),"polyline_entities":n,"units":"mm","top_projection_bounds_mm":[x0,y0,x1,y1],"sha256":hashlib.sha256(file.read_bytes()).hexdigest()})
report={"source_cad":D["source"],"source_sha256":D["source_sha256"],"scope":"Top reference projections. Not machinable G-code; no stock, offsets, speeds, tooling, feeds, fixtures or depth commands.","geometry_method":D["method"],"records":records}
(out/"DXF-REFERENCE-MANIFEST.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
(out/"READ-ME.txt").write_text("CNC SHOP REFERENCE PROJECTIONS\n\nFour top-view DXFs, millimetres, carrier datum XY. STEP solids control the complete 3D parts.\nVisible and hidden reference lines occupy separate layers. Hide TOP_HIDDEN_REFERENCE before using a visible profile.\nCurves are polylines at 0.025 mm maximum sampling deflection, not original analytical arcs.\nThese files contain no toolpath, depth, work offset, compensation, feeds, speeds or machine-specific commands.\nThe shop must review features, choose material and fixture/setup strategy, and generate/simulate CAM for its equipment.\nUse the engineering dossier and technical drawings to interpret the fits and physical acceptance requirements.\n",encoding="utf-8")
print(json.dumps(report,indent=2))
