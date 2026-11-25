from pathlib import Path
import hashlib,json,struct
root=Path(__file__).resolve().parent
manifest=root/'cutaway-manifest.json'
data=json.loads(manifest.read_text())
png=root/'assembled-cutaway-top-angled.png'
raw=png.read_bytes()
width,height=struct.unpack('>II',raw[16:24])
assert hashlib.sha256(Path(data['render']['file']).read_bytes()).hexdigest()==data['render']['sha256']
data['alternate_render']=dict(file=str(png),sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),width=width,height=height,requested_dimensions=[1800,1400],rotation_degrees=[-45,0,-45],zoom=.7,quality='high',background='opaque',lights=dict(camera=.45,top=.5,side=.4),geometry_changed=False,comparison='45-degree tilt shows more microphone top and both amplifier terminal screws;54.7356-degree view shows more section depth. The lid rail still partly occludes the microphone with either camera.')
manifest.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
print(json.dumps(data['alternate_render']))
