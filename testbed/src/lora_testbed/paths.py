"""Locations in the source checkout; keep layout knowledge out of runners."""
from pathlib import Path

TESTBED_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = TESTBED_ROOT.parent
