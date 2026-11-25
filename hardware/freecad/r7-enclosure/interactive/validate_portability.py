"""Read-only verification of the consolidated viewer and retained evidence."""
from pathlib import Path
import argparse,ast,hashlib,json,runpy,subprocess
ROOT=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--freecad-python',type=Path)
 parser.add_argument('--output',type=Path)
 args=parser.parse_args()
 baseline=json.loads((ROOT/'CONSOLIDATION-BASELINE.json').read_text())['files']
 for relative,expected in baseline.items():
  assert sha(ROOT/relative)==expected,relative
 refs=json.loads((ROOT/'PORTABLE-REFERENCES.json').read_text())['references']
 for record in refs.values():
  path=(ROOT/record['path']).resolve()
  assert path.is_relative_to(ROOT.resolve()),path
  assert sha(path)==record['sha256'],path
 for path in ROOT.rglob('*.py'):
  ast.parse(path.read_text(encoding='utf-8'),filename=str(path))
 helper=runpy.run_path(str(ROOT.parent/'tools/rebuild_r7_viewer.py'))
 _,reconstruction=helper['reconstruct'](ROOT)
 report={'ok':True,'original_files_unchanged':len(baseline),'portable_reference_inputs':len(refs),'reconstruction':reconstruction,'fresh_CAD_mesh_generation':False}
 if args.freecad_python:
  run=subprocess.run([str(args.freecad_python),'-B',str(ROOT/'prepare_inputs.py')],capture_output=True,text=True,check=True)
  native=json.loads(run.stdout)
  assert native['ok'] and native['actual_component_count']==2949 and native['global_placement_applied']
  report['native_inspection']={key:native[key]for key in ['ok','native_sha256','actual_component_count','global_placement_applied','first_component_bounds_mm','all_components_bounds_mm','source_hashes']}
 if args.output:
  with args.output.open('x',encoding='utf-8')as stream:
   stream.write(json.dumps(report,indent=2)+'\n')
 print(json.dumps(report,indent=2))
if __name__=='__main__':main()
