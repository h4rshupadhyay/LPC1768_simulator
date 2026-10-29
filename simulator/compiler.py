"""Freestanding Cortex-M3 compilation with portable LLVM/GCC or optional Keil.

The bundled register header, startup and linker script have no Keil dependency.
Only the Keil adapter uses a user-installed proprietary SDK.
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from importlib.util import find_spec
from io import StringIO
from pathlib import Path

from intelhex import IntelHex

ROOT = Path(__file__).resolve().parents[1]
TOOLCHAIN = ROOT / "toolchain"


class CompileError(ValueError):
    pass


@dataclass
class Compilation:
    hex: str
    diagnostics: str
    elf: bytes = b""
    backend: str = ""


def elf_to_hex(elf: bytes, *, allow_sram: bool = False) -> str:
    """Convert loadable ELF32 little-endian physical segments to Intel HEX.

    The data segment's flash load address is important: SRAM initializers must
    live in flash for startup's copy loop. NOBITS zero-fill belongs to startup.
    """
    if len(elf) < 52 or elf[:7] != b"\x7fELF\x01\x01\x01":
        raise CompileError("Compiler did not produce a little-endian ELF32 file.")
    if struct.unpack_from("<H", elf, 18)[0] != 40:
        raise CompileError("Compiler did not produce an ARM ELF file.")
    phoff = struct.unpack_from("<I", elf, 28)[0]
    phentsize, phnum = struct.unpack_from("<HH", elf, 42)
    if phentsize < 32 or phoff + phentsize * phnum > len(elf):
        raise CompileError("Malformed ELF program header table.")
    image = IntelHex()
    for i in range(phnum):
        kind, offset, _, physical, size, _, _, _ = struct.unpack_from(
            "<8I", elf, phoff + i * phentsize
        )
        if kind != 1 or not size:
            continue
        if offset + size > len(elf):
            raise CompileError("ELF load segment extends beyond the file.")
        if not (0 <= physical < physical + size <= 0x80000 or allow_sram and 0x10000000 <= physical < physical + size <= 0x10008000):
            raise CompileError("ELF initialized data must fit the LPC1768 flash.")
        image.frombytes(elf[offset : offset + size], offset=physical)
    if not image.addresses():
        raise CompileError("ELF has no loadable flash data.")
    output = StringIO()
    image.write_hex_file(output)
    return output.getvalue()


class Compiler:
    def __init__(
        self, keil_root: str | Path | None = None, *, optimization=0, backend=None
    ):
        if type(optimization) is not int or optimization not in range(4):
            raise ValueError("Optimization must be an integer from 0 through 3.")
        self.optimization = optimization
        self.root = Path(keil_root or os.environ.get("KEIL_ARM_ROOT", "C:/Keil/ARM"))
        self.bin = self.root / "ARMCC/bin"
        requested = backend or os.environ.get(
            "LPC_COMPILER", "keil" if keil_root else "auto"
        )
        if requested not in ("auto", "zig", "clang", "gcc", "keil"):
            raise ValueError("LPC_COMPILER must be auto, zig, clang, gcc, or keil.")
        choices = self._candidates()
        self.backend = (
            next(
                (name for name in ("zig", "clang", "gcc", "keil") if name in choices),
                None,
            )
            if requested == "auto"
            else requested
        )
        self.command = choices.get(self.backend)

    def _candidates(self):
        choices = {}
        zig = os.environ.get("LPC_ZIG") or shutil.which("zig")
        if not zig:
            spec = find_spec("ziglang")
            if spec and spec.origin:
                bundled = Path(spec.origin).parent / (
                    "zig.exe" if os.name == "nt" else "zig"
                )
                if bundled.is_file():
                    zig = str(bundled)
        if zig:
            choices["zig"] = [zig, "cc"]
        clang = os.environ.get("LPC_CLANG") or shutil.which("clang")
        if clang:
            # LLVM's ARM backend and ELF linker are both required. System Apple
            # Clang alone does not provide ld.lld, so do not advertise it ready.
            sibling = Path(clang).parent / (
                "ld.lld.exe" if os.name == "nt" else "ld.lld"
            )
            if sibling.is_file() or shutil.which("ld.lld"):
                choices["clang"] = [clang]
        gcc = os.environ.get("LPC_GCC") or shutil.which("arm-none-eabi-gcc")
        if gcc:
            choices["gcc"] = [gcc]
        if (self.bin / "armcc.exe").is_file():
            choices["keil"] = [str(self.bin / "armcc.exe")]
        return choices

    def info(self) -> dict:
        names = {
            "zig": "Bundled Zig/LLVM Cortex-M3 compiler",
            "clang": "LLVM Clang/LLD Cortex-M3 compiler",
            "gcc": "GNU Arm Embedded compiler",
            "keil": "Installed Keil ARM Compiler (microlib)",
        }
        return {
            "available": self.command is not None,
            "backend": self.backend or "unavailable",
            "path": self.command[0] if self.command else "",
            "name": names.get(self.backend, "No Cortex-M3 compiler installed"),
            "note": (
                "Uses installed Keil CMSIS/microlib; MDK Lite has a 32 KB limit."
                if self.backend == "keil"
                else "Bundled open register header/startup; real Thumb firmware and DWARF debug data. No Keil required."
            ),
        }

    def compile(self, source: str, language: str = "c") -> Compilation:
        if language not in ("c", "asm"):
            raise CompileError("Language must be c or asm.")
        if (
            not isinstance(source, str)
            or not source.strip()
            or len(source.encode("utf-8")) > 256_000
        ):
            raise CompileError("C source must be nonempty and at most 256 KB.")
        if not self.command:
            raise CompileError(
                "No Cortex-M3 compiler found. Install the project requirements including ziglang, set LPC_CLANG/LPC_GCC/LPC_ZIG, or upload HEX."
            )
        # Bundled applications can live in read-only installation directories.
        # Compiler intermediates belong in the user's OS temporary directory.
        with tempfile.TemporaryDirectory(prefix="lpc1768-compile-") as td:
            out = Path(td)
            if language == "asm":
                from .assembly import translate
                (out / "main.s").write_text(translate(source), encoding="utf-8")
            else:
                (out / "main.c").write_text(source, encoding="utf-8")
            diagnostics = []

            def run(command):
                try:
                    p = subprocess.run(
                        list(map(str, command)),
                        check=False,
                        cwd=out,
                        capture_output=True,
                        text=True,
                        errors="replace",
                        timeout=60,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                except (OSError, subprocess.TimeoutExpired) as e:
                    raise CompileError(f"{command[0]}: {e}") from e
                diagnostics.append(p.stdout + p.stderr)
                if p.returncode:
                    raise CompileError("\n".join(diagnostics).strip())

            if language == "asm":
                if self.backend == "keil":
                    raise CompileError("Assembly requires the portable LLVM or GCC backend.")
                flags = ["-mcpu=cortex_m3" if self.backend == "zig" else "-mcpu=cortex-m3", "-mthumb", "-g"]
                if self.backend == "zig":
                    flags = ["-target", "thumb-freestanding-eabi", *flags]
                elif self.backend == "clang":
                    flags = ["--target=arm-none-eabi", "-fuse-ld=lld", *flags]
                run([*self.command, *flags, "-Wa,-mimplicit-it=always", "-nostdlib", "main.s", "-Wl,-T," + str(TOOLCHAIN / "assembly.ld"), "-o", "firmware.elf"])
                elf = (out / "firmware.elf").read_bytes()
                return Compilation(elf_to_hex(elf, allow_sram=True), "\n".join(diagnostics).strip() or "Assembly compiled and linked.", elf, self.backend)
            if self.backend == "keil":
                return self._compile_keil(out, run, diagnostics)
            common = [
                "-mcpu=cortex_m3" if self.backend == "zig" else "-mcpu=cortex-m3",
                "-mthumb",
                "-mfloat-abi=soft",
                "-std=c11",
                f"-O{self.optimization}",
                "-g",
                "-gdwarf-4",
                "-ffreestanding",
                "-fno-builtin",
                "-fno-stack-protector",
                "-fno-sanitize=all",
                "-ffunction-sections",
                "-fdata-sections",
                "-fno-unwind-tables",
                "-fno-asynchronous-unwind-tables",
                "-I",
                TOOLCHAIN,
                "-isystem",
                TOOLCHAIN / "sysroot/include",
            ]
            if self.backend == "zig":
                common = ["-target", "thumb-freestanding-eabi", *common]
            elif self.backend == "clang":
                common = ["--target=arm-none-eabi", "-fuse-ld=lld", *common]
            files = [
                "main.c",
                *(
                    TOOLCHAIN / name
                    for name in ("startup.c", "system.c", "runtime.c", "syscalls.c")
                ),
            ]
            run(
                [
                    *self.command,
                    *common,
                    *files,
                    "-nostdlib",
                    "-Wl,-T," + str(TOOLCHAIN / "lpc1768.ld"),
                    "-Wl,--gc-sections",
                    "-Wl,--entry=Reset_Handler",
                    "-Wl,--build-id=none",
                    "-Wl,--start-group",
                    TOOLCHAIN / "sysroot/lib/libc.a",
                    TOOLCHAIN / "sysroot/lib/libm.a",
                    TOOLCHAIN / "libcompiler_rt.a",
                    "-Wl,--end-group",
                    "-o",
                    "firmware.elf",
                ]
            )
            elf = (out / "firmware.elf").read_bytes()
            return Compilation(
                elf_to_hex(elf),
                "\n".join(diagnostics).strip()
                or f"{self.info()['name']}: compile and link succeeded.",
                elf,
                self.backend,
            )

    def _compile_keil(self, out, run, diagnostics):
        flags = [
            "--cpu",
            "Cortex-M3",
            "--thumb",
            "--c99",
            f"-O{self.optimization}",
            "-g",
            "--library_type=microlib",
            "-I",
            self.root / "INC/NXP/LPC17xx",
            "-I",
            self.root / "CMSIS/Include",
            "-c",
        ]
        run([self.bin / "armcc.exe", *flags, "main.c", "-o", "main.o"])
        run(
            [
                self.bin / "armcc.exe",
                *flags,
                self.root / "Startup/NXP/LPC17xx/system_LPC17xx.c",
                "-o",
                "system.o",
            ]
        )
        run(
            [
                self.bin / "armasm.exe",
                "--cpu",
                "Cortex-M3",
                "-g",
                "--pd",
                "__MICROLIB SETA 1",
                self.root / "Startup/NXP/LPC17xx/startup_LPC17xx.s",
                "-o",
                "startup.o",
            ]
        )
        run(
            [
                self.bin / "armlink.exe",
                "--cpu",
                "Cortex-M3",
                "--ro_base",
                "0",
                "--rw_base",
                "0x10000000",
                "--first",
                "startup.o(RESET)",
                "--entry",
                "Reset_Handler",
                "--library_type=microlib",
                "startup.o",
                "system.o",
                "main.o",
                "-o",
                "firmware.axf",
            ]
        )
        run(
            [
                self.bin / "fromelf.exe",
                "--i32combined",
                "--output",
                "firmware.hex",
                "firmware.axf",
            ]
        )
        return Compilation(
            (out / "firmware.hex").read_text(),
            "\n".join(diagnostics).strip() or "Keil compile and link succeeded.",
            (out / "firmware.axf").read_bytes(),
            "keil",
        )
