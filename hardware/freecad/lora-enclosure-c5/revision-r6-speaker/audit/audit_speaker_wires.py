from pathlib import Path
import FreeCAD as A,Part,MeshPart,json,math,hashlib
OUT=Path(__file__).resolve().parent;ENC=OUT.parents[1]
src=(OUT/'audit_candidate.py').read_text();helpers=src[:src.index('d=A.openDocument')];scope={'__file__':str(OUT/'audit_candidate.py')};exec(compile(helpers,'helpers','exec'),scope)
audit=scope['audit'];bb=scope['bb'];compare=scope['compare']
V=lambda p:A.Vector(*p)
def unit(p):return p/p.Length
def wire(points,r=1.8):
 edges=[];last=V(points[0]);arcs=[]
 for i in range(1,len(points)-1):
  a,b,c=map(V,points[i-1:i+2]);u=unit(b-a);v=unit(c-b);ang=math.acos(max(-1,min(1,u.dot(v))));trim=r*math.tan(ang/2);p=b-u*trim;q=b+v*trim;n=unit(u.cross(v));center=p+n.cross(u)*r;rv=p-center
  assert(p-last).dot(b-a)>0
  edges.append(Part.makeLine(last,p));mid=center+rv*math.cos(ang/2)+n.cross(rv)*math.sin(ang/2);edges.append(Part.Arc(p,mid,q).toShape());last=q
 edges.append(Part.makeLine(last,V(points[-1])));path=Part.Wire(edges);normal=unit(V(points[1])-V(points[0]));profile=Part.Wire([Part.makeCircle(.4,V(points[0]),normal)]);s=path.makePipeShell([profile],True,False);assert s.isValid();return s,path.Length
paths={
 'ReferenceSpeakerLeadA':[[62,46.8,18.5],[67.4,46.8,18.5],[67.4,79,16.4],[52.75,79,14.3],[52.75,75.7,14.3]],
 'ReferenceSpeakerLeadB':[[62,47.7,18.5],[66.3,47.7,18.5],[66.3,77.8,16.4],[56.25,77.8,14.3],[56.25,75.7,14.3]]}
shapes={};lengths={}
for name,pts in paths.items():shapes[name],lengths[name]=wire(pts)
ref=A.newDocument('R6WireAudit');Part.insert(str(ENC/'detailed-import/C5-detailed-assembly.step'),ref.Name);objects=[o for o in ref.Objects if hasattr(o,'Shape')and not o.Shape.isNull()];comps=[]
for i,o in enumerate(objects):
 s=o.Shape.copy();s.translate(A.Vector(0,0,6.4814));comps.append((i,s,bb(s)))
def load(p):s=Part.Shape();s.read(str(p));return s
others={name:load(OUT/(name+'.brep'))for name in ['EnclosureBase','EnclosureLid','SpeakerRetainer','ReferenceSpeakerEnvelope','ReferenceSpeakerScrewShafts']}
others['Coax']=load(ENC/'revision-r5-sma/interactive/routing/coax.brep')
r={'provisional':True,'assumed_wire_od_mm':.8,'assumed_centerline_bend_mm':1.8,'paths':paths,'lengths_mm':lengths,'actual_electronics':{},'native_pairs':{}}
for n,s in shapes.items():
 r['actual_electronics'][n]=audit(s,comps);r['native_pairs'][n]={p:compare(s,t)for p,t in others.items()};print(n,r['actual_electronics'][n],r['native_pairs'][n],flush=True)
r['lead_to_lead']=compare(*shapes.values());r['ok']=all(not a['hits']for a in r['actual_electronics'].values())and all(p['intersection_mm3']<1e-6 for v in r['native_pairs'].values()for p in v.values())and r['lead_to_lead']['intersection_mm3']<1e-6
r['terminal_note']='Assigned terminal block has no modeled wire cavities. Reference endpoints stop just outside +Y face Y75.3; terminal holes/polarity and exact entry height are not qualified. Read SPK+ and SPK- markings on actual module.'
r['slack_note']='Listing gives approximately80mm leads before connector removal. Only proposed routed sections are drawn; surplus/service slack and opening movement not modeled. Disconnect speaker wires before separating lid fully.'
(OUT/'speaker-wire-audit.json').write_text(json.dumps(r,indent=2))
for n,s in shapes.items():s.exportBrep(str(OUT/(n+'.brep')))
print(json.dumps({'ok':r['ok'],'lengths':lengths,'lead_to_lead':r['lead_to_lead']}),flush=True)
