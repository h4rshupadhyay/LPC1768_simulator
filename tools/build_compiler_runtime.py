"""Rebuild the browser/native Cortex-M3 arithmetic runtime from pinned Zig.

Run with `uv run python tools/build_compiler_runtime.py`. The generated archive
contains Thumb/M3 software floating point and integer helper routines, not host
machine code. End users of the built web app never run this build tool.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from importlib.util import find_spec
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    spec = find_spec("ziglang")
    if spec is None or spec.origin is None:
        raise SystemExit("Install the project-pinned ziglang==0.15.2 dependency first.")
    package = Path(spec.origin).parent
    zig = package / ("zig.exe" if (package / "zig.exe").is_file() else "zig")
    version = subprocess.run(
        [str(zig), "version"], check=True, capture_output=True, text=True
    ).stdout.strip()
    if version != "0.15.2":
        raise SystemExit(f"Expected Zig 0.15.2, found {version}.")
    source = package / "lib/compiler_rt.zig"
    archive = ROOT / "toolchain/libcompiler_rt.a"
    subprocess.run(
        [
            str(zig),
            "build-lib",
            str(source),
            "-target",
            "thumb-freestanding-eabi",
            "-mcpu",
            "cortex_m3",
            "-O",
            "ReleaseSmall",
            "-ffunction-sections",
            "-fdata-sections",
            "-fno-unwind-tables",
            "--name",
            "compiler_rt",
            f"-femit-bin={archive}",
        ],
        check=True,
        cwd=ROOT,
    )
    (ROOT / "toolchain/compiler-rt.LICENSE").write_bytes(
        (package / "LICENSE").read_bytes()
    )
    manifest = {
        "zig_version": version,
        "source_url": "https://github.com/ziglang/zig/tree/0.15.2/lib/compiler_rt",
        "entry_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "target": "thumb-freestanding-eabi",
        "cpu": "cortex_m3",
        "optimization": "ReleaseSmall",
        "function_sections": True,
        "data_sections": True,
        "unwind_tables": False,
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "license": "compiler-rt.LICENSE",
    }
    (ROOT / "toolchain/compiler-rt.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    print(f"Built {archive.relative_to(ROOT)} ({archive.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
