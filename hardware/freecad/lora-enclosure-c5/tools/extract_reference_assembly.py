"""Verify and reconstruct the ignored corrected STEP without replacing local data."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import zipfile

MEMBER = "C5-detailed-assembly.step"
EXPECTED_BYTES = 76_201_161
EXPECTED_SHA256 = "65143fecb376c40ac75cf7b3b2ffdf477c9ff656706a80c1fda63717d1041a19"
DEFAULT_ROOT = Path(__file__).resolve().parents[1]


def hash_stream(stream):
    digest = hashlib.sha256()
    size = 0
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
        size += len(chunk)
        if size > EXPECTED_BYTES:
            raise ValueError("Reference member exceeds its recorded byte count")
    return size, digest.hexdigest()


def check_identity(size, sha256):
    if size != EXPECTED_BYTES or sha256 != EXPECTED_SHA256:
        raise ValueError("Reference assembly byte count or SHA-256 does not match the original")


def verify_zip(source):
    with zipfile.ZipFile(source) as archive:
        entries = archive.infolist()
        if len(entries) != 1 or entries[0].filename != MEMBER:
            raise ValueError("Reference ZIP must contain exactly the named STEP member")
        if entries[0].file_size != EXPECTED_BYTES or entries[0].is_dir():
            raise ValueError("Reference ZIP member has unexpected type or size")
        with archive.open(entries[0]) as stream:
            size, sha256 = hash_stream(stream)
        check_identity(size, sha256)
    return {"member": MEMBER, "bytes": size, "sha256": sha256}


def reconstruct(root, verify_only=False):
    root = Path(root).resolve(strict=True)
    source = root / "detailed-import" / (MEMBER + ".zip")
    target = root / "detailed-import" / MEMBER
    if not source.resolve(strict=True).is_relative_to(root):
        raise ValueError("Reference ZIP resolves outside the archive root")
    if target.is_symlink():
        raise ValueError("Refusing a symbolic-link extraction destination")
    result = verify_zip(source)
    if target.exists():
        if not target.is_file():
            raise FileExistsError("Extraction destination is not a regular file")
        with target.open("rb") as stream:
            size, sha256 = hash_stream(stream)
        try:
            check_identity(size, sha256)
        except ValueError as error:
            raise FileExistsError("Existing STEP differs; it was left untouched") from error
        return {**result, "status": "existing STEP verified", "path": str(target)}
    if verify_only:
        return {**result, "status": "compressed reference verified; no file written"}

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", prefix=".reference-", suffix=".tmp", dir=target.parent, delete=False) as output:
            temporary = Path(output.name)
            with zipfile.ZipFile(source) as archive, archive.open(MEMBER) as stream:
                digest = hashlib.sha256()
                size = 0
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    size += len(chunk)
                    if size > EXPECTED_BYTES:
                        raise ValueError("Reference member exceeds its recorded byte count")
                    digest.update(chunk)
                    output.write(chunk)
            check_identity(size, digest.hexdigest())
            output.flush()
            os.fsync(output.fileno())
        # Exclusive creation preserves any existing file, including a file created
        # concurrently. No replace or overwrite fallback is used. A failed copy
        # remains visible for inspection and is rejected on the next invocation.
        with target.open("xb") as destination, temporary.open("rb") as verified:
            for chunk in iter(lambda: verified.read(1024 * 1024), b""):
                destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        return {**result, "status": "STEP extracted and verified", "path": str(target)}
    finally:
        if temporary is not None and temporary.exists():
            if temporary.resolve().parent != target.parent.resolve():
                raise ValueError("Unexpected temporary-file location")
            temporary.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="Archive root; defaults to the parent of tools/")
    parser.add_argument("--verify-only", action="store_true", help="Verify compressed bytes without reconstructing a missing STEP")
    args = parser.parse_args()
    try:
        print(json.dumps({"ok": True, **reconstruct(args.root, args.verify_only)}, indent=2))
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
