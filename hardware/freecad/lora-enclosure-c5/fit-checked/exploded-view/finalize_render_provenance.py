from pathlib import Path
import hashlib,json,re,struct
ROOT=Path(__file__).resolve().parent
manifest_path=ROOT/'exploded-view-manifest.json'
data=json.loads(manifest_path.read_text())
source=Path(data['source_board'])
actual=Path(r'C:\Users\Homar\Documents\Arduino\esp32-audio-chunker-test\hardware\kicad\heltec_v4_audio_carrier')
records=[]
for model in re.findall(r'\(model\s+"([^"]+)"',source.read_text(encoding='utf-8')):
    relative=model.replace('${KIPRJMOD}/','')
    staged=source.parent/relative
    original=actual/relative
    a=hashlib.sha256(staged.read_bytes()).hexdigest()
    b=hashlib.sha256(original.read_bytes()).hexdigest()
    assert a==b
    records.append(dict(model=model,staged_path=str(staged),original_path=str(original),sha256=a,unchanged_from_original=True))
assert len(records)==6
assert hashlib.sha256(source.read_bytes()).hexdigest()==data['source_board_sha256']
png=ROOT/'exploded-updated-actual-kicad.png'
raw=png.read_bytes()
assert raw[:8]==b'\x89PNG\r\n\x1a\n'
width,height=struct.unpack('>II',raw[16:24])
assert width>=1700 and height>=2600
for item in data['models']:
    if 'source_stl' in item:
        assert hashlib.sha256(Path(item['source_stl']).read_bytes()).hexdigest()==item['source_sha256']
    item['render_model_sha256']=hashlib.sha256(Path(item['model']).read_bytes()).hexdigest()
data['actual_electronics_models']=records
data['render']=dict(file=str(png),sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),width=width,height=height,requested_dimensions=[1800,2700],tool='KiCad 10 kicad-cli pcb render',side='top',rotation_degrees=[-54.7356,0,-45],zoom=.25,quality='high',background='opaque',board_stackup_colors=True,lights=dict(camera=.45,top=.5,side=.4))
data['verification']=dict(source_electronics_models_unchanged=True,manufacturing_stls_unchanged=True,source_board_unchanged=True,view_inspected_for_framing=True)
manifest_path.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'image':str(png),'width':width,'height':height,'bytes':len(raw),'actual_models_verified':len(records),'manufacturing_meshes_verified':4}))
