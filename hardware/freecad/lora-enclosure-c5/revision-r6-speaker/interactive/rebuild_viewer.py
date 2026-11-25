"""Rebuild the derived R6 viewer from audited inputs, then check browser behavior."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import argparse,subprocess
ROOT=Path(__file__).resolve().parent
P=argparse.ArgumentParser();P.add_argument('--preflight',action='store_true');P.add_argument('--skip-browser',action='store_true');args=P.parse_args()
FC='C:/Program Files/FreeCAD 1.1/bin/python.exe'
PY='C:/Users/Homar/AppData/Local/Programs/FreeCAD-MCP/.venv/Scripts/python.exe'
NODE='C:/Users/Homar/AppData/Local/OpenAI/Codex/runtimes/cua_node/5c41f77a7900391c/bin/node.exe'
RENDER='C:/Users/Homar/.codex/plugins/cache/openai-curated-remote/visualize/1.0.109/skills/visualize/scripts/render.py'
def run(command):
 print('Running '+str(command[1]),flush=True)
 subprocess.run([str(c)for c in command],cwd=ROOT,check=True)
run([FC,ROOT/'prepare_inputs.py']+(['--preflight']if args.preflight else[]))
with ThreadPoolExecutor(max_workers=2)as pool:
 jobs=[pool.submit(run,[FC,ROOT/script])for script in ('mesh/export_r6_meshes.py','focus/export_focus_meshes.py')]
 for job in jobs:job.result()
run([PY,ROOT/'focus/verify_focus_pack.py'])
run([PY,ROOT/'build_viewer.py'])
run([PY,RENDER,ROOT/'r6-enclosure-viewer.html',ROOT/'qa/r6-preview.html','--force'])
if not args.skip_browser:run([NODE,ROOT/'qa/r6-viewer-qa.cjs',ROOT/'qa/r6-preview.html'])
