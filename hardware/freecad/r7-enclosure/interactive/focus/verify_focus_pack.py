"""Read-only structural verification of the retained packed focus geometry."""
from pathlib import Path
import json,runpy
root=Path(__file__).resolve().parents[1]
helper=runpy.run_path(str(root.parent/'tools/rebuild_r7_viewer.py'))
print(json.dumps({'ok':True,**helper['decode'](root/'focus/focus-mesh-data.b64')},indent=2))
