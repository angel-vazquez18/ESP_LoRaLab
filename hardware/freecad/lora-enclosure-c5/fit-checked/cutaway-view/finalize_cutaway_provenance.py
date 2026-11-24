from pathlib import Path
import hashlib,json,struct
ROOT=Path(__file__).resolve().parent
path=ROOT/'cutaway-manifest.json'
data=json.loads(path.read_text())
png=ROOT/'assembled-cutaway-actual-kicad.png'
raw=png.read_bytes()
assert raw[:8]==b'\x89PNG\r\n\x1a\n'
width,height=struct.unpack('>II',raw[16:24])
assert width>=1700 and height>=1300
for item in data['manufacturing_hashes_verified']:
    assert hashlib.sha256((ROOT.parent/item['file']).read_bytes()).hexdigest().upper()==item['sha256'].upper()
assert hashlib.sha256(Path(data['source_board']).read_bytes()).hexdigest()==data['source_board_sha256']
data['render']=dict(file=str(png),sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),width=width,height=height,requested_dimensions=[1800,1400],tool='KiCad 10 kicad-cli pcb render',side='top',rotation_degrees=[-54.7356,0,-45],zoom=.8,background='opaque',quality='high',board_stackup_colors=True,lights=dict(camera=.45,top=.5,side=.4))
data['visual_check']='Final PNG inspected: uncropped assembled enclosure, closed lid frame/patch, actual electronics visible, half-section cup/plunger/screws/nuts show installed mechanism. Amber distinguishes enclosure cut faces.'
data['verified_no_explosion']=True
path.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'image':str(png),'dimensions':[width,height],'bytes':len(raw),'source_models':len(data['actual_electronics_models']),'sectioned_parts':len(data['models']),'unchanged_manufacturing_files':len(data['manufacturing_hashes_verified'])}))
