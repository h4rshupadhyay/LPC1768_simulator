"""Fetch and verify the free Cortex-M3 newlib C/math library and matching headers.

No apt/dpkg installation is performed. Only target archives, headers, and notices
are extracted from pinned Ubuntu packages. Python 3.12/3.13 builds use the
Bun's bundled Zstandard decoder for Debian's compressed archives; Python 3.14
has it built in. The zstandard Python wheel is also supported when installed.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tarfile
import urllib.request
from io import BytesIO
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".tools/newlib"
TARGET = ROOT / "toolchain/sysroot"
VERSION = "4.4.0.20231231-2"
BASE = "https://archive.ubuntu.com/ubuntu/pool/universe/n/newlib/"
PACKAGES = {
    f"libnewlib-arm-none-eabi_{VERSION}_all.deb": "9af508599193d07c9460897d01a36af46a2707765bd6941e27c6d0747859b0eb",
    f"libnewlib-dev_{VERSION}_all.deb": "f945b12c3abc844e76eebc28cf7d99e9aefd7caec39583116ef29556b3c52414",
}


def deb_data(package: bytes) -> bytes:
    if package[:8] != b"!<arch>\n":
        raise ValueError("Invalid Debian package archive")
    offset = 8
    while offset + 60 <= len(package):
        header = package[offset : offset + 60]
        if header[58:60] != b"`\n":
            raise ValueError("Invalid ar member header")
        name = header[:16].decode("ascii").strip().rstrip("/")
        size = int(header[48:58])
        start = offset + 60
        if size < 0 or start + size > len(package):
            raise ValueError("Truncated Debian package archive")
        if name.startswith("data.tar"):
            return package[start : start + size]
        offset = start + size + size % 2
    raise ValueError("Debian package has no data archive")


def destination(name: str) -> str | None:
    path = str(PurePosixPath(name)).lstrip("./")
    headers = "usr/include/newlib/"
    libraries = "usr/lib/arm-none-eabi/newlib/thumb/v7-m/nofp/"
    if path.startswith(headers):
        return "include/" + path[len(headers) :]
    if path.startswith(libraries) and path[len(libraries) :] in ("libc.a", "libm.a"):
        return "lib/" + path[len(libraries) :]
    if path == "usr/share/doc/libnewlib-arm-none-eabi/copyright":
        return "NEWLIB-COPYRIGHT"
    return None


def main() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    TARGET.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, checksum in PACKAGES.items():
        cached = CACHE / name
        if cached.exists():
            package = cached.read_bytes()
        else:
            with urllib.request.urlopen(BASE + name, timeout=120) as response:
                package = response.read()
        if hashlib.sha256(package).hexdigest() != checksum:
            raise ValueError(f"Integrity mismatch for {name}")
        cached.write_bytes(package)
        data = deb_data(package)
        if data[:4] == bytes.fromhex("28b52ffd"):
            try:
                from compression import zstd

                data = zstd.decompress(data)
            except ImportError:
                try:
                    import zstandard
                except ImportError as error:
                    bun = shutil.which("bun")
                    if not bun:
                        raise SystemExit(
                            "Install Bun, use Python 3.14, or run with --with zstandard==0.25.0."
                        ) from error
                    data = subprocess.run(
                        [
                            bun,
                            "--eval",
                            "process.stdout.write(Bun.zstdDecompressSync(new Uint8Array(await Bun.stdin.arrayBuffer())))",
                        ],
                        input=data,
                        capture_output=True,
                        check=True,
                    ).stdout
                else:
                    with zstandard.ZstdDecompressor().stream_reader(
                        BytesIO(data)
                    ) as reader:
                        data = reader.read()
        with tarfile.open(fileobj=BytesIO(data), mode="r:*") as archive:
            for member in archive:
                dest = destination(member.name)
                if not dest or not member.isfile():
                    continue
                parts = PurePosixPath(dest).parts
                if ".." in parts or PurePosixPath(dest).is_absolute():
                    raise ValueError("Unsafe library archive path")
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError(f"Missing archive data: {member.name}")
                data = stream.read()
                output = TARGET.joinpath(*parts)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(data)
                files[dest] = {
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
    for required in (
        "lib/libc.a",
        "lib/libm.a",
        "include/stdio.h",
        "include/math.h",
        "NEWLIB-COPYRIGHT",
    ):
        if required not in files:
            raise ValueError(f"Required newlib asset absent: {required}")
    manifest = {
        "name": "newlib",
        "version": VERSION,
        "target": "thumb/v7-m/nofp, ARMv7-M Cortex-M3 soft-float",
        "upstream": "https://sourceware.org/newlib/",
        "packages": {BASE + name: digest for name, digest in PACKAGES.items()},
        "licenses": ["NEWLIB-COPYRIGHT"],
        "files": files,
    }
    (TARGET / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        f"Bundled Cortex-M3 newlib {VERSION}: {len(files)} files, "
        f"{sum(item['bytes'] for item in files.values()) / 1048576:.1f} MiB"
    )


if __name__ == "__main__":
    main()
