"""Render only the presentation boards built from saved R4 geometry."""
from pathlib import Path
import hashlib,json,os,subprocess

root=Path(__file__).resolve().parent
manifest=json.loads((root/'view-manifest.json').read_text())
exe=Path('C:/Program Files/KiCad/10.0/bin/kicad-cli.exe')
env=dict(os.environ,KICAD_CONFIG_HOME=str(root/'presentation/config'))
for view in manifest['views']:
    settings=view['render']
    target=root/(view['view']+'.png')
    # KiCad's CLI treats a leading-minus comma vector as a switch. Equivalent
    # positive rotations avoid that parser ambiguity without changing the pose.
    rotation=','.join(format(float(v)%360,'.8g') for v in settings['rotate'].split(','))
    args=[str(exe),'pcb','render','--output',str(target),'--width',str(settings['width']),
          '--height',str(settings['height']),'--side','top','--background','opaque',
          '--quality','high','--use-board-stackup-colors','--rotate',rotation,
          '--zoom',str(settings['zoom']),'--light-camera','.45','--light-top','.5',
          '--light-side','.4',view['board']]
    if settings.get('pan'):args[-1:-1]=['--pan',' '+settings['pan']]
    result=subprocess.run(args,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    (root/(view['view']+'-render.log')).write_text(result.stdout,encoding='utf-8')
    if result.returncode or not target.exists():
        raise RuntimeError('Render failed: '+view['view']+'; see log')
    view['render_output']=dict(file=str(target),sha256=hashlib.sha256(target.read_bytes()).hexdigest(),command=args)
    print('Rendered '+str(target),flush=True)
(root/'view-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
