# LPC1768 Virtual Embedded Systems Lab

A local simulator of the ALS-SDA-ARMCTXM3-01 board for Labs 6–11. Run real
Cortex-M3 firmware with Unicorn, connect ribbon cables and jumpers, and experiment
with LEDs, switches, LCD, keypad, seven-segment displays, ADC and PWM.

## Screenshots

| Interactive board | C editor |
| --- | --- |
| ![Virtual board with connectors, jumpers and peripherals](docs/screenshots/board.png) | ![C editor with line numbers, compile and execution controls](docs/screenshots/ide.png) |

## Build and run

Requires **uv**, **Python 3.11–3.13** and **Bun**. The locked Zig/LLVM package
compiles Cortex-M3 firmware on Linux, macOS and Windows. Keil is optional;
existing Keil ARM5 installations can still be selected with `LPC_COMPILER=keil`
and `KEIL_ARM_ROOT`. Clang/LLD and Arm GCC are additional optional backends.

```sh
uv sync --frozen
bun install --frozen-lockfile
bun run build
uv run python -m simulator.server
```

Open **http://127.0.0.1:8765**. On Windows, `start.bat` synchronizes missing
Python dependencies and builds the frontend if needed. `stop.bat` stops a
service launched that way. Compilation uses temporary output directories;
no separately installed host compiler is needed for the default Zig backend.
The checked-in ARM target libraries have pinned manifests and regeneration tools.
See [native runtime setup](docs/NATIVE_RUNTIME.md).

Choose a lab, write or upload C/HEX in **IDE**, and connect the required cables
and jumpers on **Board** before running. See the [usage and wiring guide](docs/USAGE.md).

## Development and checks

Develop in an isolated checkout with its own environment and build output.
Use port **8879** and set `LPC_LAB_URL=http://127.0.0.1:8879` for browser checks;
do not run tests against the practice session on port 8765. On Windows,
`start-isolated.bat` and `test-isolated.bat` set the development port.

```sh
uv run python -m pytest -ra
bun run build
```

Functional tests cover compiled firmware, GPIO and wiring, timers, ADC, PWM,
SysTick, debugging, error recovery and resource disposal. The host-dependent
millisecond throughput benchmark is retained as an explicit performance run,
with its current failure documented in [functional timing and host throughput](docs/REALTIME_PERFORMANCE.md).
Windows/macOS CI is defined; a local Linux result does not certify those hosts.
Frozen application packaging is deferred from this source contribution.

## Scope

Timers, PWM and ADC use modeled peripheral timing; CPU execution and software
delays depend on host speed. This is a tested digital subset, not a cycle-accurate
or complete LPC1768 replacement. No physical-board equivalence is claimed.

[Lab coverage](docs/LAB_COVERAGE.md) · [Hardware specification](HARDWARE_SPEC.md) ·
[Test report](TEST_REPORT.md) · [Known limitations](HARDWARE_FIDELITY_GAPS.md)
