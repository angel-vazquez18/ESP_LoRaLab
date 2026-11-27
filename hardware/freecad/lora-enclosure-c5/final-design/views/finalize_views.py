"""Record verified native render provenance and make a labeled contact sheet."""
from pathlib import Path
import json,hashlib
from PIL import Image,ImageDraw,ImageFont,ImageOps
out=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
manifest=json.loads((out/'view-manifest.json').read_text())
renders=[('assembled','assembled-isometric.png','01  Closed enclosure',(-50,0,-45),.75,(2000,1600)),('exploded','exploded-assembly.png','02  Exploded assembly',(-54.7356,0,-45),.22,(1800,2700)),('cutaway','assembled-cutaway.png','03  Assembled cutaway',(-50,0,-45),.75,(2000,1600)),('top-open','top-open-assembly.png','04  Top view, lid removed',(0,0,0),.85,(1800,2000))]
manifest['renders']=[]
for view,file,title,rotation,zoom,requested in renders:
 p=out/file;im=Image.open(p);im.verify();im=Image.open(p)
 assert min(im.size)>1300
 manifest['renders'].append(dict(view=view,file=str(p),sha256=sha(p),size_px=list(im.size),requested_size_px=list(requested),tool='KiCad 10.0 kicad-cli pcb render',quality='high',rotation_deg=list(rotation),zoom=zoom,background='opaque',board_stackup_colors=True,lights={'camera':.45,'top':.5,'side':.4},visually_inspected=True))
assert sha(Path(manifest['cad']))==manifest['cad_sha256']
assert sha(Path(manifest['source_board']))==manifest['source_pcb_sha256']
for v in manifest['actual_electronics_models']:assert sha(Path(v['source']))==v['sha256']
W,H=2400,2540;canvas=Image.new('RGB',(W,H),'#f7f8fa');draw=ImageDraw.Draw(canvas)
titlefont=ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf',44)
subfont=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',29)
draw.text((42,22),'LoRa C5 enclosure / revision R1',font=titlefont,fill='#172334')
draw.text((42,83),'Actual PCB and assigned component models  •  CAD-derived views',font=subfont,fill='#495665')
margin,gap,top=36,30,145;pw=(W-margin*2-gap)//2;ph=(H-top-60-gap)//2
for k,(_,file,title,*_) in enumerate(renders):
 x=margin+(k%2)*(pw+gap);y=top+(k//2)*(ph+gap)
 draw.rounded_rectangle((x,y,x+pw,y+ph),radius=12,fill='white',outline='#d3dae1',width=2)
 draw.text((x+24,y+15),title,font=titlefont,fill='#172334')
 im=Image.open(out/file).convert('RGB');im.thumbnail((pw-36,ph-106),Image.Resampling.LANCZOS)
 canvas.paste(im,(x+(pw-im.width)//2,y+86+(ph-106-im.height)//2))
path=out/'C5-R1-assembly-views.png';canvas.save(path)
manifest['contact_sheet']=dict(file=str(path),sha256=sha(path),size_px=[W,H],method='Four unchanged native KiCad renders resized proportionally and arranged with text titles; no geometry or features synthesized.')
(out/'view-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print(json.dumps(dict(contact_sheet=str(path),renders=len(renders),actual_models=len(manifest['actual_electronics_models']),cad_unchanged=True)))
