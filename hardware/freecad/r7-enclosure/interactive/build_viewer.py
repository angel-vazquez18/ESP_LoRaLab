"""Reconstruct the frozen R7 viewer exactly; use --output for a new file."""
from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).resolve().parents[1]/'tools/rebuild_r7_viewer.py'),run_name='__main__')
