# ADR 001 — Keil compiler + Unicorn CPU, local board models

Status: selected after passing the firmware execution gate. Inspection performed
2026-10-28/29 on this Windows machine.

## Evidence before UI

`python tools/probe_backend.py` compiled Embedded C with the installed Keil tools,
linked the installed LPC17xx startup and `system_LPC17xx.c`, emitted Intel HEX,
loaded the flash vectors into Unicorn and observed real writes to `0x2009C018`
and `0x2009C01C`. Reset vector `0xE1`, initial SP `0x10000208`. This passed before
the main interface was built. No source interpretation or exercise animations.

Installed µVision: `C:/Keil/UV4/Uv4.exe`, file version 4.70.0.0;
`TOOLS.INI` identifies MDK 4.70a. `armcc --vsn` and `armlink --vsn`: ARM 5.03
build 24, MDK-ARM Lite. SarmCM3.dll, DARMP1 and UVSC/UVSC64/UVSCWrapper exist.
No installed UVSOCK or ARM AGSI SDK headers/examples were found in inspected
tool folders. The existing MCB1700 Blinky project specifies LPC1768 simulation
using SARMCM3 and DARMP1, confirming a simulator configuration is installed.

## Alternatives and exact limits of the investigation

* **Keil simulator:** officially supports CPU/peripheral simulation and debugger
  stimulus functions. UVSOCK supports project/build/debug automation; scripts
  can run, log and dump memory. Those facts do **not** prove a stream of every
  GPIO edge to an external frontend. AGSI is the relevant extension mechanism,
  but the ARM application note 196 has been withdrawn; an Arm employee confirms
  that legacy Cortex-M simulators supported it. Current public app-note 198
  download URLs could not be retrieved. We did not patch binaries, inspect
  proprietary implementations, or invent a wire protocol. We did not verify a
  live µVision debugger session, analog stimulus, SW2 injection, or a complete
  GPIO stream. Thus this is an integration uncertainty, **not** a claim that
  Keil is incapable. Continuing on that route would add undocumented bridge
  work before the essential edge capture could be tested.
* **Renode:** its inspected platform tree contains LPC2294, not an LPC1768
  model. It provides a richer machine/interrupt framework but requires adapting
  several LPC peripherals and adding a bridge. Useful future backend if the
  subset here grows substantially.
* **QEMU system mode:** requires an appropriate board model; the official ARM
  board list does not list LPC1768. Adding a board and peripherals in QEMU C is
  more work than the required small Python MMIO model.
* **Existing mbed-simulator project:** scoped to mbed rather than this board's
  direct-register firmware and pin/cable learning workflow. Not used as proof
  of arbitrary Keil HEX compatibility.
* **Unicorn 2.1.4:** prebuilt Windows package, Thumb/MCLASS CPU, direct MMIO
  callbacks and bounded execution. Verified with actual Keil startup, polling
  and interrupt handlers. Chosen because it makes every GPIO write visible
  without a binary SDK bridge. No ARM instruction decoding is written here.

## Design

React + TypeScript/SVG is served by a loopback Flask service. A single worker
owns a machine under a lock; execution slices release the lock so UI requests
and input changes remain responsive. A fixed board graph routes ten parallel
conductors by pin index. Manual cables and jumpers persist over firmware loads
and resets. Peripherals observe MMIO events; UI polling is only presentation.

The frontend uses hash navigation for separate Board, IDE and Lab exercises
screens. `web/App.tsx` keeps source, compilation and physical state above the
screen views, so switching does not recreate the simulated machine or discard
code. Leaving Board queues release of held inputs. Technical help, setup
answers and reference-code loading are intentionally absent from the UI.

Unicorn supplies CPU execution, not a complete LPC1768. The application supplies
FIO/PINCON, the clock registers needed by installed SystemInit, 65-clock ADC
conversions on two channels, timer/PWM counters with deferred PWM latches and flat NVIC interrupt
delivery. Interrupts use actual vector table entries, an exception stack frame
and Unicorn's exception-return callback. No nested interrupt/preemption support.
Live timer/PWM counters advance from monotonic elapsed time using oscillator,
PLL0, CCLK divider, PCLKSEL and prescaler settings. Pause/resume excludes paused
time; worker slices have no fixed 2 ms sleep. Offline Machine probes retain
deterministic instruction-derived timing. CPU execution is host-limited and not
cycle accurate; software delays and high-rate IRQ service cannot be promised at
full MCU speed. See [TIMING](TIMING.md). Unknown MMIO stops with an address.

Wokwi Elements was evaluated as a presentation library. The board now uses
native SVG geometry in `web/BoardArtwork.tsx`, reconstructed from the supplied
photograph, with firmware-driven controls and displays in `web/Board.tsx`.
Layout JSON supplies control positions and connector orientations. The drawing
requires no raster image or additional component library. Static artwork is
memoized and does not intercept pointer input. No visual rendering is used as
a simulation source; electrical routing remains in `board/mapping.json`.

## Complexity and compatibility boundary

This is a moderate board-specific subset, not a full chip implementation.
Adding CPU instructions costs no application code; adding a peripheral requires
a tested MMIO model. Full nested NVIC, SysTick, DMA, bit-band aliases, boot-ROM
IAP and arbitrary vendor drivers remain unsupported. Keil Lite's 32 KB linker
limit still applies. The installed headers/startup are used in place; no Keil
binary redistribution. The local compiler is Windows/Keil-specific; HEX execution
uses Python and Unicorn and can be ported independently.

## Sources

* [Keil remote control and UVSOCK](https://www.keil.com/support/docs/2636.htm)
* [Keil simulator and debug functions](https://www.keil.com/support/man/docs/uv4cl/uv4cl_db_cpusimulation.htm)
* [Arm employee on legacy AGSI and withdrawn note](https://community.arm.com/forums/f/keil-forum/54632/adding-more-peripherals-to-the-simulator/181165)
* [QEMU ARM board selection](https://www.qemu.org/docs/master/system/target-arm)
* [Renode source/platforms](https://github.com/renode/renode)
* [Unicorn Python MMIO implementation](https://github.com/unicorn-engine/unicorn/blob/master/bindings/python/unicorn/unicorn_py3/unicorn.py)
* [Wokwi Elements presentation scope](https://github.com/wokwi/wokwi-elements)

# ADR 002 — Open Workbench: external circuits, full peripheral set, 3D bench

Status: implemented on branch `worktree-open-workbench` (plan:
[2026-11-04-open-workbench](superpowers/plans/2026-11-04-open-workbench.md)).

## Layers added

* **Peripheral bus** (`simulator/peripheral.py`): UART0–3 (`uart.py`), SSP0/1 and legacy
  SPI (`ssp.py`), I2C0–2 master (`i2c.py`), DAC (`dac.py`), RIT/WDT/RTC/QEI and stored MCPWM
  registers (`clocks.py`) register windows on the machine. Unknown offsets still stop the
  program with an address and region name.
* **Pin functions** (`pins.py`): the full PINSEL table and pad electrical classes. Pads drive
  PWM1.1–1.6 and timer MATn outputs on any selected pin; capture inputs, counter mode, EINT0–3
  from any source and port 0/2 GPIO interrupts react to pad edges.
* **Core**: nested, prioritized NVIC (IP/SHPR, PRIGROUP), PendSV, SVC, IRQ32+, AIRCR reset,
  STIR, DWT CYCCNT, bit-band aliases, unmapped-access BusFault messages, PLL feed/limit notes.
* **Scheduler and time**: devices schedule events in simulated nanoseconds; live mode
  interleaves them with timer advance at their exact instant, offline/Precise mode derives
  time from instruction ticks. Precise timing throttles virtual time to the wall clock.
* **Circuit** (`circuit.py`, `solver.py`, `doctor.py`, `parts/`): targets (ALS kit, mbed
  module, bare chip), endpoint naming, breadboards, wires, mounts; DC nodal analysis of every
  net that contains a part or rail; Circuit Doctor findings, damage and fix patches.
  Nets without parts use the original digital resolution, so lab behavior is unchanged.
* **Frontend**: `web/workbench/` (three.js via @react-three/fiber/drei, lazy-loaded): 3D
  bench, catalogue search, inspector, Doctor, serial monitor and logic analyzer;
  `web/DebugPanel.tsx` exposes the existing debugger and printf console in the IDE.

## Trade-offs

Buses are transaction level rather than bit level: firmware sees correct register behavior
and timing per byte, and parts exchange whole frames. This keeps Python MMIO overhead bounded
while still teaching pin muxing, baud rates and pull-ups. Bit-banged protocols use timed edges
and need Precise timing for instruction-accurate delays. The solver is DC only; parts expose
simplified transfer functions with data-sheet ratings so that the Doctor can reason with
real numbers.
