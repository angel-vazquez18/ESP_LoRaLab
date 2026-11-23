"""Import/verify the selected upstream Codec 2 subset without network access."""

import argparse
import hashlib
import json
import platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "firmware/lora_node/components/loralab_codec2"
COMMIT = "06d4c11e699b0351765f10398abb4f663a984f36"
SOURCES = (
    "codec2.c",
    "codec2_fft.c",
    "interp.c",
    "kiss_fft.c",
    "kiss_fftr.c",
    "lpc.c",
    "lsp.c",
    "nlp.c",
    "pack.c",
    "phase.c",
    "postfilter.c",
    "quantise.c",
    "sine.c",
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify():
    manifest = json.loads((DEST / "dependency.json").read_text())
    for name, expected in manifest["sha256"].items():
        path = DEST / name
        if not path.is_file() or sha(path) != expected:
            raise ValueError(f"Pinned Codec 2 resource differs: {name}")
    if manifest["source_commit"] != COMMIT:
        raise ValueError("Codec 2 source revision differs from the selected release")
    return manifest


def import_source(source):
    revision = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != COMMIT:
        raise ValueError("Source checkout must be the pinned Codec 2 1.2.0 release")
    subprocess.run(
        ["git", "-C", str(source), "diff", "--exit-code", "HEAD"],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    names = {"COPYING", "cmake/version.h.in", "src/generate_codebook.c"}
    pending = ["src/" + name for name in SOURCES]
    while pending:
        name = pending.pop()
        if name in names:
            continue
        names.add(name)
        for header in re.findall(
            r'^#include "([^"]+)"', (source / name).read_text(), re.MULTILINE
        ):
            candidate = "src/" + header
            if (source / candidate).is_file():
                pending.append(candidate)
    names.update(f"src/codebook/dlsp{i}.txt" for i in range(1, 11))
    for name in sorted(names):
        target = DEST / "vendor" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    patches = sorted((DEST / "patches").glob("*.patch"))
    for patch in patches:
        subprocess.run(
            [
                "patch",
                "--batch",
                "--forward",
                "-p1",
                "-d",
                str(DEST / "vendor"),
                "-i",
                str(patch),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    generated = DEST / "generated"
    (generated / "codec2").mkdir(parents=True, exist_ok=True)
    version = (source / "cmake/version.h.in").read_text()
    for key, value in {"MAJOR": "1", "MINOR": "2", "PATCH": "0"}.items():
        version = version.replace("@CODEC2_VERSION_" + key + "@", value)
    version = version.replace("@CODEC2_VERSION@", "1.2.0").replace(
        "#cmakedefine", "#define"
    )
    (generated / "codec2/version.h").write_text(version)
    compiler = (
        ["xcrun", "--sdk", "macosx", "clang"]
        if platform.system() == "Darwin"
        else ["cc"]
    )
    with tempfile.TemporaryDirectory(prefix="loralab-codebook-") as temporary:
        executable = str(Path(temporary) / "generate_codebook")
        subprocess.run(
            [
                *compiler,
                str(source / "src/generate_codebook.c"),
                "-lm",
                "-o",
                executable,
            ],
            check=True,
        )
        with (generated / "codebookd.c").open("wb") as output:
            subprocess.run(
                [
                    executable,
                    "lsp_cbd",
                    *[f"src/codebook/dlsp{i}.txt" for i in range(1, 11)],
                ],
                check=True,
                cwd=source,
                stdout=output,
            )
    resources = (
        sorted((DEST / "vendor").rglob("*")) + sorted(generated.rglob("*")) + patches
    )
    manifest = {
        "name": "Codec 2",
        "version": "1.2.0",
        "source_commit": COMMIT,
        "upstream_sha256": {name: sha(source / name) for name in sorted(names)},
        "local_patches": [str(p.relative_to(DEST)) for p in patches],
        "source": "https://github.com/drowe67/codec2",
        "tag": "1.2.0",
        "license": "LGPL-2.1-only",
        "additional_notice": "KISS FFT: BSD-3-Clause; see vendor/src/kiss_fft.c",
        "mode": 3200,
        "samples_per_frame": 160,
        "bits_per_frame": 64,
        "sample_rate_hz": 8000,
        "sources": list(SOURCES),
        "build_options": {
            "CODEC2_MODE_EN_DEFAULT": 0,
            "CODEC2_MODE_3200_EN": 1,
            "fft": "KISS FFT",
            "arithmetic": "float",
            "fast_math": False,
            "optimization": "O2",
            "tools_modems_freedv": False,
        },
        "generated_from": {
            "generated/codebookd.c": "upstream src/generate_codebook.c and src/codebook/dlsp1..10.txt",
            "generated/codec2/version.h": "upstream cmake/version.h.in",
        },
        "sha256": {str(p.relative_to(DEST)): sha(p) for p in resources if p.is_file()},
    }
    (DEST / "dependency.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--source",
        type=Path,
        help="Clean local checkout of the pinned official release",
    )
    group.add_argument(
        "--check", action="store_true", help="Verify retained resource hashes"
    )
    args = parser.parse_args()
    if args.source:
        import_source(args.source.resolve())
    manifest = verify()
    print(
        f"Codec 2 {manifest['version']} pinned resources match ({len(manifest['sha256'])} files)"
    )


if __name__ == "__main__":
    main()
