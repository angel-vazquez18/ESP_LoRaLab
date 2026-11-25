"""Read-only manifest, file-scope and stored-evidence validation for this archive."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import zipfile

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 100_000_000
MANIFEST = "ARCHIVE-MANIFEST.json"
EXTRACTED = "detailed-import/C5-detailed-assembly.step"
REFERENCE_SHA256 = "65143fecb376c40ac75cf7b3b2ffdf477c9ff656706a80c1fda63717d1041a19"
REFERENCE_BYTES = 76_201_161
NATIVE = [
    "LoRa-Enclosure-C5.FCStd",
    "LoRa-Enclosure-C5-Detailed-Exploded.FCStd",
    "fit-checked/LoRa-Enclosure-C5-Fit-Checked.FCStd",
    "fit-checked/exploded-view/LoRa-Enclosure-C5-Exploded-With-Hardware.FCStd",
    "fit-checked/cutaway-view/LoRa-Enclosure-C5-Assembled-Cutaway.FCStd",
    "final-design/cad/LoRa-Enclosure-C5-R1.FCStd",
    "revision-r2-oled/cad/LoRa-Enclosure-C5-R2-OLED.FCStd",
    "revision-r3-oled-gap/cad/LoRa-Enclosure-C5-R3-OLED.FCStd",
    "revision-r4-battery/cad/LoRa-Enclosure-C5-R4-Battery.FCStd",
]
FINAL_PASS_FLAGS = [
    "final-design/audit/final-export-validation.json",
    "final-design/audit/final-actual-clearance.json",
    "final-design/documentation/DOCUMENT-VALIDATION.json",
    "revision-r4-battery/audit/r4-battery-fit-validation.json",
    "revision-r4-battery/audit/r4-export-validation.json",
    "revision-r4-battery/documentation/DOCUMENT-VALIDATION.json",
    "revision-r4-battery/craftcloud/UPLOAD-VALIDATION.json",
    "revision-r4-battery/manufacturing/MANUFACTURING-VALIDATION.json",
    "revision-r4-battery/bom/BOM-VALIDATION.json",
]
PARTS = ["enclosure-base", "enclosure-lid", "ptt-plunger", "ptt-stop-cup"]
REQUIRED = NATIVE + FINAL_PASS_FLAGS + [
    "README.md", "SOURCE-NOTICES.md", ".gitattributes", ".gitignore", "CURRENT-RELEASE.json",
    "revision-r4-battery/cad/LoRa-Enclosure-C5-R4-Battery.step",
    "revision-r4-battery/documentation/C5-R4-Battery-Integration.pdf",
    "revision-r4-battery/craftcloud/CRAFTCLOUD-ORDER-SPECIFICATION.txt",
    "revision-r4-battery/research/BATTERY-CONNECTION-REVIEW.txt",
    *[f"revision-r4-battery/craftcloud/upload/C5-R4-{p}-mm.{ext}"
      for p in ("enclosure-base","enclosure-lid","ptt-plunger","ptt-stop-cup","battery-cover")
      for ext in ("stl","3mf")],
    "tools/extract_reference_assembly.py", "tools/validate_archive.py",
    "detailed-import/C5-detailed-assembly.step.zip",
    "final-design/cad/LoRa-Enclosure-C5-R1.step",
    "final-design/documentation/Enclosure-Technical-Drawings.pdf",
    "final-design/documentation/Enclosure-Engineering-Dossier.pdf",
    "final-design/views/C5-R1-assembly-views.png",
    "final-design/bom/LoRa-C5-R1-Complete-BOM.xlsx",
    "final-design/craftcloud/CRAFTCLOUD-ORDER-SPECIFICATION.txt",
    "fit-checked/verify_exports.py",
    *["fit-checked/ptt-motion/" + n for n in [
        "build_animation_fragment.cjs", "ptt-cutaway-animation.html",
        "ptt-cutaway-animation.template.html", "ptt-cutaway-meshes.json",
        "ptt-contact-patch.json", "ptt-load-path.json"]],
    *[f"final-design/printing/{p}.stl" for p in PARTS],
    *[f"final-design/cnc/C5-R1-{p}.step" for p in PARTS],
    *[f"final-design/craftcloud/upload/C5-R1-{p}-mm.{ext}" for p in PARTS for ext in ["stl", "3mf"]],
]
FORBIDDEN_DIRS = {"pcb-fabrication", "node_modules", "__pycache__", ".venv", "venv", ".git", ".pio", "python-packages"}
FORBIDDEN_SUFFIXES = {".kicad_pcb", ".kicad_sch", ".kicad_pro", ".kicad_prl", ".kicad_mod", ".kicad_sym", ".kicad_dru", ".gbr", ".gtl", ".gbl", ".gts", ".gbs", ".gto", ".gbo", ".gm1", ".g1", ".g2", ".gbrjob", ".drl", ".pyc", ".pyo", ".exe", ".dll", ".fcbak", ".fcstd1", ".log"}


import sys
sys.dont_write_bytecode = True
from validate_r7_release import REQUIRED as R7_REQUIRED, PASS_FLAGS as R7_FLAGS, validate as validate_r7
NATIVE += [
    'revision-r5-sma/cad/LoRa-Enclosure-C5-R5-SMA.FCStd',
    'revision-r6-speaker/cad/LoRa-Enclosure-C5-R6-Speaker.FCStd',
    'revision-r7-enclosure/cad/LoRa-Enclosure-C5-R7-Reinforced.FCStd',
]
FINAL_PASS_FLAGS += R7_FLAGS
REQUIRED += NATIVE[-3:] + R7_REQUIRED + R7_FLAGS

def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def safe_path(root, name):
    if not isinstance(name, str) or not name or "\\" in name:
        raise ValueError("Manifest paths must be nonempty POSIX-relative strings")
    posix, windows = PurePosixPath(name), PureWindowsPath(name)
    if posix.is_absolute() or windows.drive or any(p in (".", "..") for p in name.split("/")):
        raise ValueError("Absolute, drive-qualified or traversing manifest path: " + name)
    if str(posix) != name:
        raise ValueError("Manifest path is not canonical: " + name)
    candidate = root / posix
    if not candidate.resolve().is_relative_to(root):
        raise ValueError("Manifest path resolves outside root: " + name)
    return candidate


def validate(root):
    root = root.resolve(strict=True)
    failures, checks = [], {}
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    entries = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(entries, list):
        raise ValueError("Manifest must contain a files array")
    names, folded = set(), set()
    for entry in entries:
        if not isinstance(entry, dict):
            failures.append("Manifest row is not an object")
            continue
        name = entry.get("path")
        try:
            path = safe_path(root, name)
        except ValueError as error:
            failures.append(str(error))
            continue
        if name in names or name.casefold() in folded:
            failures.append("Duplicate/case-colliding manifest path: " + name)
        names.add(name)
        folded.add(name.casefold())
        if name in (MANIFEST, EXTRACTED):
            failures.append("Manifest must omit itself and the ignored reconstructed STEP: " + name)
        expected = entry.get("sha256", "")
        size = entry.get("bytes", entry.get("size_bytes", entry.get("size")))
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
            failures.append("Invalid SHA-256 field: " + name)
        elif not path.is_file() or path.is_symlink():
            failures.append("Missing or symlinked file: " + name)
        else:
            if digest(path) != expected.lower():
                failures.append("SHA-256 mismatch: " + name)
            if not isinstance(size, int) or isinstance(size, bool) or size != path.stat().st_size:
                failures.append("Byte-count mismatch/missing: " + name)

    observed = set()
    largest = {"path": None, "bytes": 0}
    for path in root.rglob("*"):
        name = path.relative_to(root).as_posix()
        parts = {p.lower() for p in path.relative_to(root).parts}
        if path.is_symlink():
            failures.append("Symlink in payload: " + name)
            continue
        if parts & FORBIDDEN_DIRS or any(p.startswith(".preview-browser-") for p in parts):
            failures.append("Runtime/cache/PCB directory in payload: " + name)
        if not path.is_file():
            continue
        size = path.stat().st_size
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            failures.append("Excluded source/runtime/backup file: " + name)
        if path.suffix.lower() == ".zip" and name != "detailed-import/C5-detailed-assembly.step.zip":
            failures.append("Unexpected bundled ZIP: " + name)
        if size >= MAX_BYTES:
            failures.append("File reaches/exceeds 100 MB: " + name)
        if size > largest["bytes"]:
            largest = {"path": name, "bytes": size}
        if name == EXTRACTED:
            if size != REFERENCE_BYTES or digest(path) != REFERENCE_SHA256:
                failures.append("Ignored reconstructed STEP differs from the recorded reference")
        elif name != MANIFEST:
            observed.add(name)
    for name in sorted(observed - names):
        failures.append("Unmanifested payload file: " + name)
    for name in sorted(names - observed):
        failures.append("Manifest entry not present as a regular payload file: " + name)
    for name in REQUIRED:
        if not (root / name).is_file():
            failures.append("Required artifact missing: " + name)

    native_found = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".fcstd"}
    if native_found != set(NATIVE):
        failures.append("Native FCStd milestone set is not exactly the expected twelve documents")
    checks["native_fcstd"] = []
    for name in NATIVE:
        try:
            with zipfile.ZipFile(root / name) as archive:
                corrupt = archive.testzip()
                ok = corrupt is None and "Document.xml" in archive.namelist()
                if not ok:
                    failures.append("FCStd ZIP CRC/Document.xml check failed: " + name)
                checks["native_fcstd"].append({"path": name, "ok": ok})
        except (OSError, zipfile.BadZipFile) as error:
            failures.append("FCStd cannot be read: " + name + ": " + str(error))

    checks["saved_final_pass_flags"] = {}
    for name in FINAL_PASS_FLAGS:
        try:
            saved = json.loads((root / name).read_text(encoding="utf-8"))
            ok = saved.get("ok") is True
            checks["saved_final_pass_flags"][name] = ok
            if not ok:
                failures.append("Saved final evidence is not ok:true: " + name)
        except (OSError, ValueError) as error:
            failures.append("Cannot parse saved final evidence: " + name + ": " + str(error))
    checks["manifest_entries"] = len(entries)
    checks["payload_files"] = len(observed)
    checks["largest_file"] = largest
    return {"ok": not failures, "root": str(root), "checks": checks, "failures": failures,
            "scope": "Archive integrity and recorded evidence only; no CAD recomputation or physical qualification."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="Archive root; defaults to the parent of tools/")
    args = parser.parse_args()
    try:
        report = validate(args.root)
    except (OSError, ValueError, TypeError, zipfile.BadZipFile) as error:
        report = {"ok": False, "error": str(error)}
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1



_base_validate = validate
def validate(root):
    report = _base_validate(root)
    extra = validate_r7(root)
    report['checks']['r7_release'] = extra['checks']
    report['failures'].extend(extra['failures'])
    report['ok'] = not report['failures']
    return report

if __name__ == "__main__":
    raise SystemExit(main())
