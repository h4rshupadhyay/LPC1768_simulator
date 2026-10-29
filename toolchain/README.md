# Portable firmware toolchain

These sources replace the original dependency on the local Keil installation.
The native and browser compilers use the same Cortex-M3 startup, vector table,
register definitions, default clock configuration, and memory layout.

* `LPC17xx.h` defines the registers modeled by this lab at the offsets in NXP
  UM10360. It is an independently authored subset, not a complete vendor SDK.
* `startup.c` copies initialized data from flash, clears BSS, sets the default
  clock, and calls `main`. Weak vector handlers can be replaced by firmware.
* `system.c` defaults to 100 MHz, matching the original Keil lab configuration.
  `SystemCoreClockUpdate` derives frequency from the modeled clock registers.
* `runtime.c` supplies freestanding memory routines.
* `syscalls.c` supplies newlib's bare-metal hooks. Standard output and standard
  error append to `lpc_console_buffer`; there is no host filesystem or process
  access. The heap stops 8 KiB below the SRAM top to reserve stack space.
* `sysroot/` contains matching newlib 4.4.0 headers and the exact Cortex-M3
  `thumb/v7-m/nofp` C and math libraries. Its redistribution notices and package
  hashes are included. This supplies formatting, string operations, allocation,
  and standard mathematics without a Keil library or host libc.
* `libcompiler_rt.a` supplies M3 software floating point and 64-bit arithmetic.
  `uv run python tools/build_compiler_runtime.py` regenerates it from Zig 0.15.2.
  Its manifest records the source version, target and archive hash, and
  `compiler-rt.LICENSE` contains the upstream MIT notice.
* `lpc1768.ld` defines 512 KiB flash and 32 KiB main SRAM, leaving the other
  SRAM banks available to firmware through explicit addresses.

The lab-authored source files are MIT licensed. Newlib and compiler-rt retain
their included upstream notices. No Keil binary, header, startup file, or library
is redistributed. LLVM, Zig and browser runtime licenses are separate.

The default native compiler finds the `ziglang` Python package or `zig` on PATH,
then Clang/LLD, Arm GCC, and finally an installed Keil compiler. Set
`LPC_COMPILER` to `zig`, `clang`, `gcc`, or `keil` to select one explicitly.
`LPC_ZIG`, `LPC_CLANG` and `LPC_GCC` override executable paths.
`KEIL_ARM_ROOT` retains its original meaning.

Portable compilation produces real Thumb ELF with DWARF4 debug information and
Intel HEX. A freestanding program does not automatically gain an operating
system, host filesystem, terminal, or unsupported MCU peripherals. Legacy Keil
inline assembly and ARMCC-specific language extensions may require translation.

The startup clock writes implement the simulator's clock-register subset.
They do not implement the complete hardware oscillator and PLL lock/feed
sequence. Use a board vendor's complete startup and SDK before flashing code
onto real silicon.
