# Usage and wiring guide

A local, firmware-driven simulator of the ALS-SDA-ARMCTXM3-01 board. **A bundled
Zig/LLVM toolchain compiles the C (Keil, Clang or Arm GCC can be selected instead);
Unicorn executes real Cortex-M3 instructions.** Manual 10-pin
ribbon cables and jumper positions determine which signals reach the board.
There are no source-driven animations or exercise-specific simulation handlers.

The hardware audit is documented in [TEST_REPORT.md](../TEST_REPORT.md),
[HARDWARE_SPEC.md](../HARDWARE_SPEC.md), [COVERAGE_MATRIX.md](../COVERAGE_MATRIX.md)
and [HARDWARE_FIDELITY_GAPS.md](../HARDWARE_FIDELITY_GAPS.md). Run the backend,
frontend build and browser checks against an isolated service with:

```powershell
.\.venv\Scripts\python.exe tools/run_hardware_audit.py
```

The tested digital subset includes timed ADC conversion, PWM pin levels and
deferred latches, keypad row diodes, decoder pullups, and retained external LCD
state over MCU reset. LCD busy timing, analog effects and several other chip
features remain outside the model; see the gaps report before relying on an
unfamiliar program for an examination.
If the app is already running, use `stop.bat` and then `start.bat` to load the
updated Python peripheral models; recompiling C alone does not reload the server.

## Start on this machine

Double-click **`start.bat`**, or run:

```powershell
python tools\launch.py
```

Open **http://127.0.0.1:8765**. The launcher starts a hidden local service and
opens your browser. `stop.bat` stops a service started by this launcher.
The app works without internet after dependencies and the frontend are built.
No accounts or cloud services are needed.

First-run prerequisites: Python 3.10+ and Node.js 20.19+ (or Node 22.12+).
The launcher installs dependencies into `.venv`, builds the frontend if absent,
and logs the service to `build/server.log`.
C compilation uses the bundled **Zig/LLVM** toolchain with the project's own
`toolchain/LPC17xx.h` (CMSIS-compatible names for every LPC1768 peripheral),
startup code and newlib. Set `LPC_COMPILER=keil` (with `KEIL_ARM_ROOT`), `clang`
or `gcc` to use another installed compiler; see [native runtime setup](NATIVE_RUNTIME.md).
No Keil binaries or headers are redistributed in this project. HEX upload works
independently of the compiler.

## Workspace screens

**Board**, **IDE**, and **Lab exercises** are separate full-width screens,
accessible from the compact title-bar tabs.
The navigation supports browser Back and direct links (`#board`, `#ide`,
`#labs`). Switching screens preserves source, compiled firmware and wiring.

Select a task on **Lab exercises**, write or upload your C/HEX on **IDE**,
and use **Board** for physical connections and outputs. Compile on the IDE
screen; Run, Pause/Resume, Stop and Reset are available on both IDE and Board.
The editor retains line numbers and saves your source in this browser.
Both the editor and solution viewer highlight C keywords, comments, strings,
numbers, preprocessor directives, ARM compiler extensions and LPC register names.

Lab exercises shows the selected task's corrected C solution in a read-only,
numbered viewer. **Download C** saves that solution; **Open in IDE** explicitly
replaces your current source and requires compilation before running. Selecting
an exercise or viewing its solution preserves your source, firmware and wiring.
The interface omits wiring hints, pinout tooltips, connection checks and technical
help panels. The original manuals, corrected C files in `examples/`, and mapping
notes remain available separately. Compiler errors and runtime faults stay visible.

Jumpers start **open**. Clicking a jumper cycles its shunt positions; dropdowns
below the board offer the same control. Reset retains physical wiring and
potentiometers. Leaving the board screen releases held switches and keys.
JP4 and JP18 have three pins; JP5 and JP16 have two. JP18 is in the USB device
section. JP7, JP8, JP12, JP13 and JP17 also have movable three-pin shunts.
Their positions are saved in this browser across navigation and reloads; the
associated UART, CAN, SPI, RS485 and graphic LCD interfaces remain unmodeled.

Hold SW2 or keypad buttons to press; release to release. Keyboard Space/Enter
also works on focused controls. Keycodes are row-major **0–F**, with SW3–SW18
shown in tooltips. Calculator keys: **A = +**, **B = −**, **E = equals**,
**F = clear**. The two voltage sliders represent **POT4/AD0.4** and
**POT1/AD0.5**, from 0 to 3.3 V. POT5 has no verified route and is omitted.

For a standalone calculator using **F = equals, E = restart**, use
[calculator_timer.c](../examples/calculator_timer.c). It uses Timer0 delays instead
of long software loops and configures keypad rows/columns for this board.

For keypad-selected PWM brightness, use
[pwm_keypad_timer.c](../examples/pwm_keypad_timer.c): **CNB → CNB1**, **CND → CNB3**,
and **JP5 closed**. Keys **0/1/2/3** select **10/25/50/75%** on LD10. On CND,
P0.23–26 are keypad columns and P0.27 is row 0; JP4/JP18 are not needed.

To display LCD text: connect **CND → CNAD**, close **JP5 and JP16**, then run
the LCD reference. LCD initialization performed while disconnected is lost;
reset after connecting, just as on the physical board. Disconnecting the data
cable stops new writes while the LCD retains its contents. Opening JP16 hides
the display. For keypad, also connect **CNB → CNB3** and set **JP4 to 1–2**.
For POT4, set **JP18 to 2–3**.

## Your own firmware

Paste or upload `.c`, compile, then run; errors appear below the editor. The
compiler uses the installed `LPC17xx.h` and Keil microlib, and supports normal
direct memory-mapped register access. Download C or the compiled HEX if desired.
Alternatively, upload a Keil-generated Intel `.hex` file directly. There is no
ELF upload step. HEX must contain a valid reset vector at flash address zero,
with a valid SRAM stack pointer; checksums, memory ranges and EOF are validated.
A failed compilation/upload preserves the previously loaded firmware.

Compiler warnings are retained. Unsupported MMIO and execution errors show the
address/reason and stop execution. Reset before retrying after a runtime error.
The C editor is saved in this browser; the running machine and wiring live in
the service's memory and reset when the service is restarted.

## Verified scope and limits

Supported board models: eight GPIO LEDs, SW2 polling/EINT, four BCD-addressed
seven-segment digits, 4-bit HD44780 text, 4×4 GPIO-scanned keypad, ADC0.4/0.5,
basic timers and PWM1.4 duty on LD10. A bounded worker keeps infinite loops
off the UI thread. Every relevant GPIO write is observed; UI polling every
50 ms (up to 20 updates per second) does not determine LCD/segment decoding.

This is a tested subset, **not full LPC1768 compatibility**. Live Timer0–3 and
PWM counters follow monotonic elapsed time and the configured oscillator,
PLL0, CCLK divider, PCLKSEL and prescaler registers. Pause freezes this clock;
resume excludes paused time. A timer-driven 1 ms multiplex scan can therefore
count at approximately one-second intervals. Faster UI polling improves visual
feedback without changing the emulated CPU or peripheral clock rates.
CPU throughput, software delay loops and high-rate interrupt service remain
host-limited; execution is not cycle accurate. ADC conversions follow the configured ADC clock and conversion timing.
See [timing behavior and measured checks](TIMING.md).
NVIC supports flat external IRQ delivery and exception return, without nested
preemption, priority scheduling, PSP-based RTOS contexts, or SysTick. Bit-band
aliases, boot-ROM/IAP, USB/Ethernet/CAN and unrelated peripherals are unsupported.
LCD custom-character graphics/busy reads are not modeled.

SW2's physical manual is inconsistent: the lab uses **CNB1 pin 7 → P2.12**;
the board table calls pin 9 both NC and interrupt. The default follows the lab.
An explicit alternative pin-9 profile remains available through the local API.
See the evidence and corrections in [BOARD_NOTES](BOARD_NOTES.md).
When the display uses CNB, switch counter references use **CNC → CNB1** and
poll **P0.21** so that each header still has only one cable.

The complete board is drawn in SVG, using the supplied uncabled JPEG as the
visual reference. Component arrangement, connector orientation, silkscreen,
displays, switches and the metal MCU module are represented as vectors.
Tiny component markings and copper traces are illustrative rather than an
electrically verified PCB reproduction. Drawn Ethernet, USB, serial, motor,
relay and other interfaces do not extend the supported emulation listed above.
The board automatically fits the available window width and height. Use Zoom
to inspect details and Fit to restore the complete board without scrolling.
Connections and messages sit below the board alongside the voltage controls.
They wrap on narrow windows; long messages scroll independently of the board.

`board/board.svg` is a standalone vector snapshot. To export the current board
state again while the local service is running, use `npm.cmd run export:board`
(requires Playwright Chromium). The interactive artwork is in
`web/BoardArtwork.tsx`; shared control positions are in `board/layout.json`.

[Architecture evidence and backend comparison](ARCHITECTURE.md) ·
[Lab coverage and verification detail](LAB_COVERAGE.md)

## Development and tests

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm.cmd ci
npm.cmd run build
.\.venv\Scripts\python.exe -m simulator.server
```

For development, run `npm.cmd run dev` in another terminal. Vite proxies the
local API, reference photo and coordinate file to port 8765. For another backend
port, set `LPC_LAB_PORT` and update the development proxy configuration.

```powershell
.\.venv\Scripts\python.exe tools\probe_backend.py
.\.venv\Scripts\python.exe -m pytest -q
npx.cmd playwright install chromium
npm.cmd run test:browser
```

Backend integration tests require the installed Keil ARM5 toolchain. Each
peripheral integration test builds and runs genuine ARM firmware. Browser tests
require a running local server and a frontend build; they reset that local
simulator's state, so do not run them during your own lab session.

`tools/generate_examples.py` regenerates the 18 standalone corrected C examples
and their catalog. The original PDFs and photographs remain untouched.

Files: `simulator/engine.py` owns MMIO/CPU, `simulator/board.py` owns physical
routing, `simulator/displays.py` decodes events, `board/mapping.json` records pin
maps, and `board/layout.json` positions overlays. `web/` contains the React UI.
