# LPC1768 Open Workbench: extension plan

**Status:** proposal. Nothing in this plan has been implemented yet.
**Date:** 2026-11-04. **Baseline:** `main` @ `b48c67a`.

**Goal:** grow the ALS-kit lab simulator into a general LPC1768 workbench:
- an LPC1768 with or without the ALS kit,
- external parts on a breadboard,
- a searchable component catalogue,
- electrical diagnostics that explain what failed, why it failed and how to fix it,
- a realistic 3D bench view.

Exam practice on the ALS kit must keep working exactly as it does today.

The plan has five parts:
- Part A: how the current project works.
- Part B: the bugs and edge cases found during the review.
- Parts C and D: the revised requirements and the target architecture.
- Parts E to H: the phased work, the component research, testing and risks.

---

## Part A — How the project works today

### A1. Runtime pipeline

```
Browser (React 19 + SVG, polls every 50 ms)
   │  /api/compile, /api/firmware, /api/control, /api/physical, /api/debug, /api/state
   ▼
Flask loopback server (simulator/server.py) ── same-origin + localhost guard
   ▼
Runtime (simulator/runtime.py): one worker thread and an RLock.
   It runs bounded slices of 20 000 instructions / 1 ms.
   ▼
Machine (simulator/engine.py): Unicorn Cortex-M3 (Thumb, MCLASS).
   ├─ flash 0x0 (512 KB), SRAM 0x10000000 (32 KB) and 0x2007C000 (32 KB)
   ├─ MMIO hooks on 0x4000_0000–0x400F_FFFF, GPIO 0x2009_C000 and SCS 0xE000_E000
   ├─ GPIO/FIO (5 ports), PINCON (PINSEL/PINMODE/OD), SC (clock, PLL, PCONP, PCLKSEL, EXTINT)
   ├─ TIM0–3 and PWM1 (match/reset/stop/IRQ, PWM shadow latches), SysTick, flat NVIC
   ├─ ADC (simulator/adc.py): 65-clock conversions, burst, DONE/OVERRUN, AD0.4/AD0.5 only
   ├─ LCD (HD44780 4-bit, logical) and seven-segment persistence (simulator/displays.py)
   └─ Board (simulator/board.py): union-find nets over the 10-pin FRC headers,
      ribbons, patch wires and jumpers, then digital level resolution
```

- **Compiler.** `simulator/compiler.py` builds firmware with bundled Zig/LLVM by default; Clang, Arm GCC and Keil are optional backends.
- **Toolchain files.** `toolchain/` provides a minimal `LPC17xx.h`, startup, `SystemInit`, newlib syscalls and linker scripts.
- **printf output.** `printf` goes to `lpc_console_buffer` in SRAM. The debugger snapshot reads it from there.
- **Assembly.** Assembly is supported through `simulator/assembly.py`.
- **Debugger.** `simulator/debugger.py` parses ELF/DWARF for line breakpoints, symbols and memory reads. It also handles stepping.
- **Board model.** `board/mapping.json` is the only electrical description: 10 FRC headers with 10 pins each, 4 modeled jumpers and fixed peripheral nodes (`LED*`, `SEG*`, `DIG*`, `COL*`, `ROW*`, `LCD*`, `SW2`, `PWM_LED`).
- **Artwork.** `board/layout.json` and `web/BoardArtwork.tsx` are drawing only. No simulation reads them.
- **Signal resolution.** Resolution is purely digital:
  - Each net is the minimum of its strong drivers (wired-AND, LOW wins on a conflict).
  - If there are no strong drivers, internal pulls or documented external pulls apply.
  - Otherwise the net is floating. The model reads a floating net as 0 and flags it to the UI as `level: None`.
  - Keypad row diodes D6–D9 are modeled directionally.
- **Timing.**
  - In live mode, timers, PWM, ADC and SysTick run from host monotonic time scaled by the configured clocks.
  - The CPU runs as fast as the host allows.
  - Offline tests count basic-block halfwords.
- **Frontend.**
  - Three hash-routed screens: Board, IDE and Lab exercises.
  - On the board you can click header-to-header to add or remove ribbons, click jumpers to cycle them, hold keys and SW2, and use two POT sliders.
  - By design, the board screen shows no wiring hints. It is used for exam practice.

### A2. What is solid

- The test suite is broad: 37 pytest modules and 13 Playwright specs. They cover GPIO byte/halfword access and masking, every LED and segment state, keypad scan orders, ADC transfer and timing, PWM latches, timers, SysTick, debugger, disposal and portability.
- Unknown MMIO fails loudly with an address. Nothing is faked.
- Wiring persists across reset and reload. A failed compile keeps the previous firmware.

### A3. What blocks the new goals

| Area | Current limit | Why it matters for the goals |
|---|---|---|
| Electrical model | Digital only: no voltages, currents, ratings or supply rails | Requirement 4 cannot be built without one |
| Connectivity | Only the 100 FRC contacts exist (`ENDPOINT` regex). No 3.3 V/5 V taps, no MCU pins outside the headers | External parts have nowhere to plug in |
| Peripherals | UART, SSP/SPI, I2C, DAC, GPIO interrupts, RIT, WDT, RTC, QEI, MCPWM, capture/match pins, CAN, I2S, USB and Ethernet are all missing. Any access stops the CPU | Most sensors, displays and modules use these |
| PWM pins | Only PWM1.4 on P1.23 drives a pad | Servos and motor drivers on P2.0–P2.5 get nothing, silently |
| ADC | Only AD0.4 and AD0.5. Other channels are a hard runtime error | AD0.0–AD0.3 sit on P0.23–P0.26, which are on CND |
| EINT | Only the SW2 net can raise EINT0–3 | An external button or sensor on P2.10–P2.13 can't interrupt |
| Header file | `toolchain/LPC17xx.h` defines only GPIO, PINCON, SC, ADC, PWM1, TIM0–3 and SysTick | `LPC_UART0` and similar don't compile |
| Timing | Host-speed CPU; peripherals on wall-clock time | Bit-banged protocols (DHT11, WS2812, 1-Wire) need µs-accurate virtual time |
| Frontend | One fixed SVG board. The backend's patch wires, debugger, console and assembly have no UI | No way to place or wire external parts |
| Transport | Full-state polling every 50 ms | Won't scale to many components or a live 3D scene |

---

## Part B — Bugs and edge cases found during the review

I confirmed the "probe" findings by running `Machine`/`Runtime` directly in a scratch venv (unicorn 2.1.4) outside the repo. The other findings come from reading the code. I did **not** run the project test suite: this checkout has no `.venv`, `uv` or `bun`, and `AGENTS.md` forbids running tests in the practice checkout.

| # | Severity | Finding | Evidence |
|---|---|---|---|
| B1 | **High** | Firmware built with Keil's CMSIS `core_cm3.h` crashes on `SysTick_Config()`. That function writes `SCB->SHP[11]` (0xE000ED20), which isn't an accepted address. The Keil backend and uploaded Keil HEX files are both advertised paths. | probe: `Unsupported register write at 0xE000ED20` |
| B2 | High | NVIC only covers ISER0/ICER0/ISPR0/ICPR0. `NVIC_EnableIRQ` for IRQ 32–34 fails. SHPR1–3, AIRCR reset, PendSV, SVC and fault handlers are absent (`_interrupt` fails on any exception except EXC_RETURN). | probe: write 0xE000E104 fails |
| B3 | High | PWM1.1–1.6 on P2.0–P2.5, and PWM1.x on other pins, produce **no output and no warning**. Only P1.23 is routed. | probe: PWM1.1 on P2.0 via CND→CNA1 → LEDs off, `warnings: []` |
| B4 | Medium | An output driven HIGH that is patched to GND only produces a sidebar text warning, and the net resolves LOW. On real hardware this is ~45–50 mA of short-circuit current, well above the 4 mA rating. Nothing marks the pin as stressed. | probe |
| B5 | Medium | The PLL is accepted with no 0xAA/0x55 feed sequence and no frequency limits. With CCLKCFG=0, the core runs at **400 MHz** (the LPC1768 maximum is 100 MHz) and timers scale to it. | probe: `core_clock_hz() == 400_000_000` |
| B6 | Medium | A floating input (PINMODE "neither", no driver) always reads 0. The UI shows `level: None`, but firmware gets a stable 0, which hides bugs that would appear on real hardware. | probe |
| B7 | Medium | ADC channels other than 4 and 5 are a hard fault instead of "pin not routed / floating". This blocks AD0.0–AD0.3 on CND for external sensors. | probe |
| B8 | Medium | EINT0–3 only fire when the `SW2` node is in the net (`_external_interrupt` only checks groups containing `SW2`). | code: `engine.py` `_external_interrupt` |
| B9 | Low | `docs/USAGE.md` still says that Keil compiles the C and that GCC adapters are "not implemented". The default is now bundled Zig/LLVM. | doc vs `compiler.py` |
| B10 | Low | `AGENTS.md` names `C:\Users\harsh\Downloads\lpc_simulator` (practice) and `...-performance` (dev), and neither exists on this machine. The isolation rules need this machine's paths. | path check |
| B11 | Low | The local-only guard rejects IPv6 loopback: `request.host.split(':')[0]` of `[::1]:8765` is `[`. | code: `server.py` |
| B12 | Low | A patch wire to an NC pin is accepted silently and connects nothing. | probe: `CNA.9↔CNA1.9` accepted, no warning |
| B13 | Low | The frontend `State` type has no `wires`/`headerPins`, and there is no UI for patch wires, the debugger, the `printf` console or the assembly language mode, even though the backend supports all four. | `web/types.ts`, `web/App.tsx` |
| B14 | Info | A UART/SSP/I2C/DAC/RIT/WDT/GPIOINT access stops the whole run with "Unsupported register write". That is correct per the design, but it ends any program that touches those peripherals. | probe |
| B15 | Info | Known modeling gaps from `HARDWARE_FIDELITY_GAPS.md` still apply: no LCD busy timing, CGRAM glyphs, nested NVIC, DMA, bit-band or capture. They become more visible once external parts exist. | doc |

Phase 0 below fixes B1, B2, B5–B13. B3, B4, B14 and B15 are addressed by the architecture work.

---

## Part C — Requirements (refined and extended)

The numbers R1–R7 match the original request. R8–R14 are additions I'm proposing under item 6.

| ID | Requirement | Acceptance |
|---|---|---|
| R1 | **Kit-independent use.** Choosable targets: *ALS kit* (current), *mbed LPC1768 module* (DIP-40) and *bare LPC1768 breakout* (all 70 GPIO). The full pin-mux table drives every pin. | A blink, a UART echo and an I2C sensor program run on each target. |
| R2 | **External components.** Breadboards, jumper wires, passives, semiconductors, modules, sensors, displays, actuators and power sources. On the ALS kit they connect through FRC header pins, a ribbon-to-breadboard adapter and power taps. | Example circuits in Part F run with unmodified firmware. |
| R3 | **Findability.** A searchable, filterable catalogue: by name, alias, part number, function ("temperature", "distance"), interface, supply voltage, kit/external and difficulty. | The right part is reachable in ≤ 2 interactions for 20 scripted search tasks. |
| R4 | **Diagnostics with cause and fix.** An electrical rule check (static) and electrical monitoring (live). Findings: what happened, the physics with numbers, the consequence (stressed or **damaged** part with changed behavior) and a concrete fix with computed values and an optional "apply fix". | The HC-SR04 5 V echo into a 3.3 V pin, a BMP280 on 5 V and a 5 V signal into an ADC pin each produce the expected finding, damage behavior and divider/level-shift fix. |
| R5 | **Realistic 3D bench.** The board, breadboard, parts, wires and ribbons in a 3D scene. Orbit, pan and zoom, plus preset views. A top-down orthographic mode is used for precise wiring. Live LEDs, displays, motors and servos. | Every catalogue part has a 3D representation. 60 fps target with 50 parts on a mid-range laptop iGPU. |
| R7 | **Broad LPC1768 compatibility.** Every on-chip peripheral that external parts use is modeled. A *generic* part exists for each interface class (analog source, digital I/O, I2C register device, SPI device, UART device, 1-Wire). A component SDK makes adding parts routine. | The Part F catalogue is delivered in waves. The generic parts cover anything not modeled by name. |
| R8 | **Modes.** *Exam practice*: today's no-hints kit UI, unchanged and the default for the kit. *Learn*: diagnostics and hints on. *Sandbox*: anything goes, with damage optional. | The existing browser tests still pass in exam mode. |
| R9 | **Project files.** Save, load, export and import the circuit, firmware source and target as JSON. Undo/redo. Autosave to the browser. | Round-trip test. |
| R10 | **Virtual instruments.** Serial monitor (UART), multimeter (V/I/Ω), logic analyzer (GPIO/bus decode, VCD export), oscilloscope (PWM/DAC/analog) and a bench power supply. | Each instrument is exercised by a browser test. |
| R11 | **Debugger UI.** Expose the existing breakpoints, stepping, registers, memory, source line and `printf` console. | Uses the existing `/api/debug`. |
| R12 | **Push transport.** WebSocket/SSE state deltas replace the 50 ms full polling. | Bandwidth falls proportionally. Same visible behavior. |
| R13 | **Virtual time.** Deterministic, µs-resolution simulated time for protocol devices. It can run real-time (throttled) or as-fast-as-possible. | DHT22, WS2812 and DS18B20 decode correctly under host load. |
| R14 | **Guided examples.** About 30 "external component" examples, each with firmware, circuit and expected behavior, extending `examples/catalog.json`. | Each has a backend test and a browser test. |

---

## Part D — Target architecture

### D1. Layering

```
web/  (React 19)
 ├─ workbench/   3D scene (three.js via @react-three/fiber + drei), placement, wiring
 ├─ catalog/     component browser, search index, part detail pages
 ├─ doctor/      diagnostics panel, explanations, "apply fix"
 ├─ instruments/ serial monitor, multimeter, logic analyzer, scope, PSU
 ├─ ide/         existing editor, plus debugger and console panels
 └─ kit2d/       existing SVG ALS board, kept for exam mode and low-end devices
        ▲ WebSocket (state deltas, events) + REST (commands)
simulator/
 ├─ core/        machine.py (Unicorn, memory map), bus.py (MMIO registry),
 │               scheduler.py (virtual time event queue), nvic.py, scb.py
 ├─ chip/        lpc1768 peripheral models: gpio, pincon, sc, timer, pwm, adc,
 │               dac, uart, ssp, spi, i2c, gpioint, rit, wdt, rtc, qei, mcpwm
 │               pins.json (full PINSEL function table, pad types, ratings)
 ├─ circuit/     netlist.py (union-find over all endpoints),
 │               solver.py (DC operating point, MNA + Newton),
 │               erc.py (static rules), monitor.py (live rules), damage.py
 ├─ parts/       one module per part (behavior), all registered through the SDK
 ├─ targets/     als_kit/ (mapping.json moves here), mbed_lpc1768/, bare_lqfp100/
 └─ runtime.py, server.py, compiler.py, debugger.py (existing, adapted)
parts/  (data)   <part-id>/part.json, model.glb or procedural spec, doc.md, example.c
```

The current `engine.py` (727 lines) gets split along the existing seams:
- `read_word`/`write_word` become a bus that dispatches to peripheral objects.
- Each peripheral object owns its registers and `sync(now)`.

This is the main refactor. Every existing test must pass through it unchanged before any new behavior lands.

### D2. Virtual time (R13)

- **Master clock.** Replace the dual live/offline clocks with one **virtual time** in CPU cycles, with ns derived from CCLK.
- **Cycle estimate.** Count retired instructions per translated block (the offline path already does this) and convert at ~1.25 CPI. That figure is configurable and gets calibrated against known delay loops.
- **Event scheduler.** Peripherals and parts schedule events in a heap: "UART byte done at t", "echo pin falls at t", "DHT bit edge at t". The run loop executes until the next event or the slice budget, then dispatches the event.
- **Pacing.**
  - *Real-time:* the run loop sleeps when virtual time is ahead of wall time.
  - *Max speed:* no sleeping.
  - *Lagging:* when the host is too slow, virtual time simply runs slower than wall time. A "simulation speed 63%" badge shows the lag, and protocols stay correct.
- **Unifies live and offline.** Offline tests become "max speed" runs, so the deterministic and live paths converge.
- **Cost.** The live fast path loses its no-block-hook speedup. Mitigations:
  - Keep the per-block hook in C-side Unicorn counting (`UC_HOOK_BLOCK` with minimal Python work).
  - Batch counting on `emu_start(count=…)` boundaries when no event is due within the slice.
  - Measure with `tools/benchmark_ui.mjs` and the existing throughput test.

### D3. Netlist and endpoints

- **Endpoint names.** Every connectable point is `<owner>.<pin>`:
  - `mcu.P0.4`
  - `kit.CNA.1`
  - `kit.PWR.3V3`
  - `bb1.A12`
  - `bb1.+L3`
  - `r1.1`
  - `hcsr04.ECHO`
- **Target pin maps.** A target supplies a pin map from its own endpoints to MCU pads plus fixed nodes. The ALS `mapping.json` becomes one such target, so its semantics are unchanged.
- **Breadboard.** A breadboard part declares internal buses: 5-hole terminal strips per column-half and the split or continuous power rails.
- **Wires.** A wire joins two endpoints, with a color and an optional length for 3D sag. Ribbons stay as 10-way wires.
- **Union-find.** The existing union-find generalizes directly. Net membership caching stays, keyed on the topology hash.

### D4. Electrical model (needed for R4)

Two tiers, so digital speed is preserved.

1. **Digital fast path (unchanged semantics).** Used when a net contains only MCU pads, digital part pins and ideal pulls. It covers most GPIO traffic.
2. **Analog DC solve.** Used for any net cluster that contains resistors, LEDs/diodes, pots, sensors with analog outputs, supply rails or a part pin with a rating. A small **Modified Nodal Analysis** system is solved with Newton iteration for diodes and LEDs.
   - **When:** on topology change, on driver change of a pad in that cluster, and when a part's output changes. It isn't solved per instruction.
   - **Cost:** clusters are small (typically < 20 nodes), so pure-Python dense solves are fast. numpy is optional.

Element models are deliberately simple, with documented parameters:

| Element | Model |
|---|---|
| MCU push-pull pad | Voltage source 0 / 3.3 V behind R_out ≈ 100 Ω. This matches V_OH ≥ V_DD−0.4 V at 4 mA. The short-circuit current is capped at the datasheet I_OHS ≤ 45 mA and I_OLS ≤ 50 mA. |
| MCU input | Threshold V_IH = 0.7·V_DD ≈ 2.31 V and V_IL = 0.3·V_DD ≈ 0.99 V. Between them it is *indeterminate*: a warning, and firmware gets a seeded random bit. Pull-up/pull-down is a current source of ~50 µA (I_pd typ 50 µA). Repeater mode is supported. |
| Open-drain pad | Sink only. P0.27/P0.28 are true open-drain I2C pads, 5 V tolerant. |
| Resistor / pot | Ohmic, with a wattage rating (P = I²R checked). |
| LED / diode | Shockley or piecewise-linear with V_f per color (red ≈ 1.9 V, green ≈ 2.1 V, blue/white ≈ 3.0 V). I_max ≈ 20 mA typ, 30 mA abs. Brightness ∝ current (feeds 3D emissive intensity and PWM averaging). |
| Supply rail | Ideal source with a current limit: the kit LDO, USB 5 V, a battery with internal resistance, or the PSU instrument. |
| Sensor analog output | Controlled source with output impedance, driven by the part's physical stimulus slider. |
| BJT / MOSFET | Switch-level: Vbe/Vgs threshold → on-resistance and saturation. That is enough for low-side drivers. |
| Inductive load | DC: a winding resistance. Turn-off event: a flyback spike check (no diode → finding). |

The ADC reads the solved node voltage, so the existing pots become ordinary pot parts on the kit target. Readings clamp at V_REFP (3.3 V on the kit).

### D5. Circuit Doctor (R4): rules, damage, fixes

Each rule produces a `Finding`:

```
{id, severity: info|warning|stress|damage, parts:[…], nets:[…],
 title, what, why (with numbers), consequence, fixes:[{label, steps, apply?:patch}]}
```

**Static ERC** runs on every wiring change, before Run. Examples:
- VCC shorted to GND
- part power pins unconnected or on the wrong rail
- two push-pull outputs on one net
- LED without a series resistor
- I2C without pull-ups
- I2C address conflicts
- UART TX↔TX
- MISO contention without CS
- a signal that can exceed a pin rating
- an inductive load without a flyback diode
- a motor or relay coil driven directly from a GPIO
- the firmware's PINSEL function doesn't match the wired pin (checked on first PINSEL write)

**Live monitor** checks the DC solution after each solve:
- pin current against 4 mA nominal and the ~45–50 mA short circuit
- the total I/O and supply current limits
- the voltage on each part pin against its recommended range and its absolute maximum
- LED current
- resistor power
- an ADC input above V_REFP or above the analog absolute maximum
- inputs left at an indeterminate level

**Severity and damage**, per part rating table:
- **within recommended:** ok
- **above recommended and below absolute max:** `stress`. The part keeps working, and the readings may be clamped (an ADC input above 3.3 V reads 4095).
- **above absolute max for longer than a hold-off (default 50 ms simulated):** `damage`. The part is **latched damaged** until the user clicks "Replace part", and its model switches to its damaged behavior:
  - BMP280: I2C NACKs, or returns 0x00/0xFF garbage
  - LED: open circuit and dark
  - MCU pad: stuck input, or output stuck low

  In 3D the part shows scorch marks and a brief smoke particle effect. Damage is configurable: *Realistic*, *Warn only* or *Off*.

**Fix generators** compute concrete values:
- **Voltage divider.** Pick E12/E24 pairs so that V_out ≤ the target with margin. Prefer total R between 3 kΩ and 30 kΩ so the input current is acceptable. Show the resulting voltage and tolerance band. Example: 5 V echo → 10 kΩ / 20 kΩ gives 3.33 V. The suggested fix is 10 kΩ / 18 kΩ, which gives 3.21 V, below V_DD.
- **Bidirectional level shifter.** BSS138 or TXS0108E, recommended for I2C or anything above ~100 kHz.
- **Series resistor for an LED.** R = (V_src − V_f)/I_target, rounded up to E12.
- **Transistor or MOSFET low-side driver plus flyback diode** for motors, relays and solenoids.
- **Move the supply to the 3V3 rail**, or add an LDO.
- **Add 4.7 kΩ pull-ups** for I2C.

*Apply fix* places the parts on free breadboard holes and rewires them. The change can be undone.

**Worked examples** (these become acceptance tests):

| Scenario | Finding shown | Consequence | Fix offered |
|---|---|---|---|
| HC-SR04 on 5 V, ECHO wired straight to P0.x (GPIO) | "ECHO swings to 5.0 V. The pin is 5 V tolerant in digital mode, so this is ok, but…" (info). If that pin is muxed as **AD0.x**: "5.0 V on an analog-mode pin exceeds 3.3 V, and the pad isn't 5 V tolerant in ADC mode." | Info, or **damage** to the ADC channel in analog mode | Divider of 10 kΩ / 18 kΩ, or keep the pin in GPIO mode |
| BMP280 VCC on the 5 V rail | "Supply 5.0 V exceeds the 3.6 V maximum (4.25 V absolute)." | **Damaged:** NACKs on I2C | Power it from 3V3. If it is a 5 V-ready breakout with an LDO, choose that variant. |
| MQ-2 analog out (0–5 V) to AD0.5 | "AO reaches 4.6 V at high gas concentration, above V_REFP 3.3 V." | Readings clip at 4095. **Damage** above the analog absolute max | Divider: 10 kΩ / 20 kΩ gives 3.33 V full-scale |
| LED from GPIO, no resistor | "Pin sources ≈ 14 mA at 1.9 V (rated 4 mA)." | Stress, LED dim, pad over-current | 330 Ω (≈ 4.2 mA) |
| DC motor directly on GPIO | "Motor needs ≈ 200 mA; the pin can supply 4 mA." | Motor doesn't turn. Pad stress or damage | 2N2222/IRLZ44N low-side driver + 1N4007 flyback |
| WS2812 data from 3.3 V GPIO, LEDs on 5 V | "V_IH(min) = 0.7·5 V = 3.5 V; a 3.3 V high is marginal." | Random colors (seeded bit errors) | 74AHCT125 level shifter, or power the first pixel through a diode |
| I2C without pull-ups (I2C0 open-drain) | "SDA/SCL never reach HIGH." | Bus hangs, firmware times out | 4.7 kΩ to 3V3 |

**Exam mode** hides the doctor panel and keeps today's UI. **Learn mode** shows the findings.

### D6. Component SDK

Each part is described by `part.json`:

```json
{
  "id": "hc-sr04", "name": "HC-SR04 Ultrasonic Distance Sensor",
  "aliases": ["ultrasonic", "sonar", "distance"], "category": "sensors/distance",
  "interfaces": ["gpio-pulse"], "kit": false, "difficulty": 2,
  "pins": [{"id":"VCC","type":"power","v":[4.5,5.5],"absMax":6.0},
           {"id":"TRIG","type":"in","vih":2.0,"absMax":5.5},
           {"id":"ECHO","type":"out","voh":5.0,"rOut":100},
           {"id":"GND","type":"ground"}],
  "stimuli": [{"id":"distance_cm","min":2,"max":400,"default":50}],
  "footprint": {"pitch":2.54, "pins":[[0,0],[1,0],[2,0],[3,0]]},
  "model3d": {"procedural":"module-pcb", "size":[45,20,15], "features":["2x-transducer"]},
  "docs": "doc.md", "example": "example.c", "datasheet": "url"
}
```

The behavior goes in a Python `Part` subclass with a small interface:
- `on_pin(pin, level, t)`
- `schedule(t, cb)`
- `drive(pin, v, r_out)`
- `i2c_*`, `spi_transfer`, `uart_rx`
- `state()` for the UI
- `damage(reason)`

**Generic parts** need no code:
- Generic I2C register device: a register map in JSON.
- Generic SPI device: a command table.
- Generic analog sensor: a transfer curve.
- Generic digital sensor.
- Generic UART device: scripted responses.

Each part ships with:
- a unit test of its model
- a compiled-firmware integration test
- a part page (pinout, ratings, wiring with the kit and the mbed module, sample code)

### D7. 3D workbench (R5)

- **Stack.** `three@0.169`, `@react-three/fiber@9` (React 19 compatible) and `@react-three/drei@10`. Pin the exact versions in `bun.lock`. The scene uses `frameloop="demand"`, so it renders only on state change or interaction.
- **ALS board model.**
  - Generated from `layout.json` coordinates mapped to mm: an extruded PCB with silkscreen texture, headers, ICs, LCD, keypad and pots.
  - Today's SVG artwork is rasterized to a canvas texture for the silkscreen, which reuses the existing drawing.
  - Live LEDs are emissive meshes with selective bloom. The LCD and seven-segment displays are `CanvasTexture`s updated from state.
- **Breadboard.**
  - An instanced hole mesh (830 holes in one draw call).
  - Rail markings.
  - Correct internal strips that light up on hover to show what is connected.
- **Parts.**
  - Procedural geometry where possible. Resistors get color bands computed from their value.
  - The 3D model is a real teaching aid: a 4.7 kΩ resistor shows yellow-violet-red.
  - LEDs, DIP ICs, TO-92/TO-220, headers and module PCBs are procedural.
  - Optional GLB assets come only from permissively licensed sources (CC0/MIT), recorded in `parts/LICENSES.md`.
- **Wires.** `TubeGeometry` along a catenary/Bezier path with realistic sag and Dupont housings. Ribbons are flat 10-conductor strips with a red pin-1 stripe, which mirrors the current SVG.
- **Interaction.**
  - Drag from the catalogue onto the bench. Snap to the 2.54 mm grid and breadboard holes. R rotates; Delete removes.
  - Click a pin, then click a pin to make a wire.
  - Hover a pin to see the endpoint name, net, live voltage and the mux function.
  - Selection outline. Pan/orbit/zoom.
  - **Preset views:** Top (orthographic, used for wiring), Isometric, Front, Board close-up, "Focus selected".
- **Mobile and low-end.**
  - Fall back to the 2D top view, which is the same scene graph with an orthographic camera.
  - The existing SVG kit view remains available.
- **Accessibility.** Every interactive object keeps a DOM proxy (listbox of parts/pins) for keyboard and screen readers, mirroring today's ARIA work.

### D8. Component finder (R3)

- **Left drawer.**
  - A search box with fuzzy matching over name, aliases, part number and function tags. I recommend a ~6 KB in-house index (trigram + tag boost) rather than a library.
  - Category tree.
  - Filter chips: interface (GPIO, ADC, PWM, I2C, SPI, UART, 1-Wire), supply (3.3 V, 5 V, either), "works directly with LPC1768" / "needs level shifting" / "needs driver" (computed from ratings), kit vs external, difficulty.
- **Intent search.** "measure distance" → HC-SR04, VL53L0X, Sharp IR. "show text" → 16×2 LCD, SSD1306, Nokia 5110.
- **Lists.** Recents and favorites.
- **Part detail pane.** 3D preview, pinout, ratings, "how to wire to: ALS kit / mbed / bare chip", sample firmware ("Open in IDE"), and the common mistakes taken from the Doctor rules for that part.

---

## Part E — Phased delivery

All work happens in an isolated worktree on port 8879, per `AGENTS.md` after B10 is fixed. Each phase ends with the full existing pytest and Playwright suites green in exam mode.

### Phase 0 — Groundwork and fixes (S, ~1 week)
- [ ] Update `AGENTS.md` paths for this machine (B10). Create the dev worktree and `.venv`, run `uv sync` and `bun install`. Record a baseline test run.
- [ ] B1/B2: accept SHPR1–3 (0xE000ED18–0xE000ED23), ISER1/ICER1/ISPR1/ICPR1 and AIRCR VECTKEY reset. Add tests with Keil-style `SysTick_Config`.
- [ ] B5: enforce the PLL feed sequence and lock status. Warn, then later make it a Doctor finding, when CCLK > 100 MHz or the PLL output is outside 275–550 MHz.
- [ ] B6: floating inputs read from a seeded PRNG with a warning, behind a "realistic floating inputs" flag. The flag defaults off in exam mode to keep current behavior.
- [ ] B7: unrouted ADC channels convert as floating, not as a fatal error.
- [ ] B8: EINT from any net that carries P2.10–P2.13 in function 1.
- [ ] B9, B11, B12 and B13 (types only).
- [ ] Extend `toolchain/LPC17xx.h` with complete CMSIS-compatible structs and base addresses for every LPC1768 peripheral (UART0–3, SSP0/1, SPI, I2C0–2, DAC, RIT, WDT, RTC, GPIOINT, QEI, MCPWM, CAN, I2S, GPDMA, USB, EMAC) and the core SCB/NVIC structs. Without this, user code can't even compile.

### Phase 1 — Core refactor (M, ~2 weeks)
- [ ] Split `engine.py` into a bus plus peripheral classes (D1). There is no behavior change, and all tests pass.
- [ ] Virtual-time scheduler (D2) with real-time throttle and max-speed modes. Port the timers, PWM, ADC and SysTick to it. Calibrate the CPI.
- [ ] Generalized netlist and endpoints (D3). Move the ALS mapping into `targets/als_kit/`.
- [ ] `pins.json`: the full LQFP100 pin and function table from UM10360 Tables 79–85 (PINSEL0–10) and pad types from datasheet notes [1]–[9]. Example: an ADC-capable pad isn't 5 V tolerant in analog mode; USB D+/D− are never 5 V tolerant. Unit-test the table against the header macros.
- [ ] WebSocket delta transport (R12). Keep `/api/state` for tests.

### Phase 2 — Chip peripherals (L, ~3–4 weeks)
Ordered by how many common parts each one unlocks:
1. GPIO interrupts (IO0/IO2 IntEn/Stat/Clr → EINT3), EINT0–3 from any source.
2. PWM1.1–1.6 on all mux pins, single- and double-edge. MCPWM later.
3. ADC AD0.0–AD0.7 on their real pads, reading solved voltages.
4. UART0–3: LCR/DLL/DLM/FDR baud check, FIFOs, THRE/RDA interrupts, RS485 bits accepted.
5. SSP0/1 and legacy SPI: frame formats, CPOL/CPHA, FIFOs, clock-rate check.
6. I2C0–2: the master state machine with the UM10360 status codes, plus a slave mode stub.
7. Timer capture inputs and external match outputs (needed by the HC-SR04, IR receivers and frequency counters).
8. DAC (AOUT on P0.26) feeding the solver.
9. RIT, WDT (reset and interrupt), RTC (with an accelerated-time option), QEI.
10. Full NVIC: priorities, preemption/nesting, tail-chaining approximation, PendSV/SVC, HardFault with a readable "fault explanation" (bus fault address and the faulting line from DWARF).
11. Bit-band aliases (0x2200_0000 and 0x4200_0000 regions).
12. Later or optional: GPDMA, CAN (with a two-node loopback), I2S. USB and Ethernet stay out of scope (document it).

Each peripheral gets the same register-accurate test style used today. Where firmware programs something that can't work, a Doctor finding explains it (for example a baud-rate error > 2 %, or I2C with no pull-ups).

### Phase 3 — Electrical solver and Circuit Doctor (L, ~3 weeks)
- [ ] MNA/Newton solver with the element models in D4. Unit tests against hand-calculated circuits: dividers, LED with resistor, pull-up versus driven, diode clamps.
- [ ] Rating tables for the MCU pads, the kit rails and the Wave-1 parts.
- [ ] Static ERC rules and the live monitor rules (D5). Severity, hold-off and latching damage. "Replace part".
- [ ] Fix generators (divider, level shifter, series R, driver + flyback, pull-ups, supply move) with E-series rounding, plus `apply` patches with undo.
- [ ] Doctor panel UI (Learn/Sandbox modes). Highlight the offending nets and parts in 2D and 3D.
- [ ] Golden tests: each worked example in D5 runs with real firmware and asserts the finding, the consequence and that the fix resolves it.

### Phase 4 — 3D workbench (L, ~4 weeks; can start in parallel after Phase 1)
- [ ] Scene scaffold, cameras, preset views, demand rendering, the orthographic top view.
- [ ] ALS board 3D model from the layout plus a silkscreen texture. Live LED, LCD, seven-segment and PWM brightness.
- [ ] Breadboard (instanced), part placement and snapping, wiring tool, ribbons, hover and inspect.
- [ ] mbed LPC1768 module and bare-chip breakout models.
- [ ] Project save/load, undo/redo (R9).
- [ ] Performance budget test (50 parts, 100 wires) and the visual-regression screenshots in Playwright.
- [ ] Keep `kit2d` (current SVG) as the exam-mode view until the 3D view reaches feature parity, then make the view selectable.

### Phase 5 — Component library, in waves (ongoing; see Part F)
- Wave 1 (with Phase 3): prototyping, passives, LEDs, buttons, basic analog sensors and drivers.
- Wave 2: I2C/SPI/UART sensors and displays.
- Wave 3: actuators, bit-banged protocol parts, communication modules.
- Wave 4: the long tail through generic parts and community contributions via the SDK.

### Phase 6 — Finder, instruments, examples (M, ~2–3 weeks)
- [ ] Catalogue drawer and search (D8), part pages.
- [ ] Serial monitor, multimeter, logic analyzer (with UART/I2C/SPI decode and VCD export), oscilloscope, PSU (R10).
- [ ] Debugger and console panels (R11).
- [ ] About 30 guided examples (R14).

### Phase 7 — Hardening and docs (S–M)
- [ ] Update the docs (README, USAGE, ARCHITECTURE, HARDWARE_FIDELITY_GAPS) for the new scope, with honest fidelity statements per part.
- [ ] Throughput benchmarks with virtual time. Measure the cost of per-byte SPI display traffic (for example an ILI9341 full frame ≈ 150 k MMIO writes) and add a fast path if needed.
- [ ] Promote to `main` only when the user requests it, per `AGENTS.md`.

The estimates assume one developer working full-time. Total ≈ 4–5 months; Phases 3 and 4 can overlap.

---

## Part F — Component research: what works with an LPC1768

### F1. The electrical facts every rule is based on

Source: NXP LPC1769/68/67/66/65/64/63 data sheet, Rev. 9.10, Tables 6 and 8 and pad notes.

| Fact | Value | Consequence for parts |
|---|---|---|
| I/O supply V_DD(3V3) | 2.4–3.6 V operating, 3.3 V typical | Logic HIGH out ≈ 3.3 V. 5 V parts with V_IH = 0.7·VCC (3.5 V) **won't** reliably read it (WS2812, many 5 V CMOS chips). TTL-input 5 V parts (V_IH 2.0 V: HC-SR04 TRIG, 74HCT, ULN2003) are fine. |
| Digital input on 5 V-tolerant pads | 0–5.0 V operating, 5.5 V absolute (only while V_DD is present; 3.6 V when unpowered) | 5 V outputs into digital-mode pins are acceptable, which makes them an *info* finding. Driving 5 V into an **unpowered** MCU is *damage*. |
| ADC-capable pads in analog mode | Not 5 V tolerant; the operating input is 0–V_DDA (3.3 V), and V_IA is 5.1 V absolute | 5 V analog sensors (MQ-x, LM35 at high temperature, ACS712) need dividers |
| V_REFP | 2.5 V to V_DDA | The ADC full scale is V_REFP; the kit uses 3.3 V |
| Output drive | I_OH/I_OL rated 4 mA at 0.4 V drop; short-circuit ≈ 45 mA / 50 mA | LEDs need ≥ 330 Ω for ~4 mA. Motors, relays, buzzers above a few mA and solenoids need drivers |
| Supply/ground pin current | 100 mA per pin (absolute) | Sum of I/O currents is checked against it |
| P0.27/P0.28 (I2C0) | Open-drain, 5 V tolerant, need external pull-ups, Fast-mode Plus 1 Mbit/s | Pull-ups may go to 5 V on I2C0 only. The other I2C pads are standard 5 V-tolerant pads |
| USB D+/D− pads | Not 5 V tolerant | Never wire 5 V signals there |
| Pull-ups/pull-downs | Internal, pulled to ~2.3–2.6 V, I_pd typical 50 µA | Weak; won't hold against modules with strong outputs |
| Peripherals | 4 UART, 2 SSP + 1 SPI, 3 I2C, I2S, 2 CAN, 8-ch 12-bit ADC (200 kHz), 10-bit DAC, 6-ch PWM, MCPWM, QEI, RTC, 4 timers (8 capture, 10 match), RIT, WDT, USB, Ethernet MAC, 70 GPIO | This list defines what "compatible" means |

### F2. Compatibility classes (shown as catalogue badges)

- **Direct:** 3.3 V parts, or 5 V-tolerant digital inputs within 4 mA.
- **Needs divider or level shifter:** 5 V outputs into analog pins or into 3.3 V-only parts. 5 V CMOS inputs that need V_IH > 3.3 V.
- **Needs driver:** loads above about 4 mA per pin, inductive loads, anything powered from 5–12 V.
- **Needs supply:** parts drawing more than the 3.3 V rail can give (ESP8266 peaks around 300 mA, servos and motors).

### F3. Catalogue

P0 is Wave 1/2 and P1 is Wave 3. P2 parts are covered by generic parts until modeled by name.

**Prototyping and power**

| Part | Interface | Supply | Class | Priority |
|---|---|---|---|---|
| Breadboard 830 / 400 / 170 | — | — | — | P0 |
| Jumper wires M-M / M-F / F-F, FRC 10-pin ribbon, FRC-to-breadboard adapter | — | — | — | P0 |
| Kit power tap (3V3/5V/GND); exact pins to be verified in the ALS manual (CN8 power) | — | — | — | P0 |
| MB102 breadboard PSU (3.3/5 V), USB 5 V, 2×AA / 4×AA / 9 V / Li-ion 1S, bench PSU instrument | — | — | needs supply | P0 |
| AMS1117-3.3 / LM1117, LM7805, LM2596 buck, MT3608 boost | — | — | — | P1 |
| Fuse / polyfuse | — | — | — | P2 |

**Passives**

| Part | Notes | Priority |
|---|---|---|
| Resistor (E12/E24, ¼ W), potentiometer 1 k–100 k, trimpot, slide pot | 3D color bands | P0 |
| Capacitors: ceramic, electrolytic (polarity and voltage rating checked) | DC only (open); decoupling advice | P1 |
| Inductor, crystal | Mostly visual | P2 |

**Discrete semiconductors and logic**

| Part | Interface | Class | Priority |
|---|---|---|---|
| LED (red/green/yellow/blue/white), RGB LED (common anode/cathode), bi-color LED, IR LED | GPIO/PWM | direct with resistor | P0 |
| 1N4148, 1N4007, 1N5819 Schottky, Zener 3.3 / 5.1 V | — | — | P0 |
| NPN 2N2222 / BC547 / 2N3904, PNP 2N3906, TIP120 | — | driver | P0 |
| MOSFET 2N7000, BS170, IRLZ44N | — | driver | P0 |
| PC817 optocoupler | GPIO | — | P1 |
| BSS138 4-ch level shifter, TXS0108E, 74AHCT125 | — | level shift | P0 |
| ULN2003, L293D, L298N, DRV8833, TB6612FNG, A4988 / DRV8825 | GPIO/PWM | driver | P0–P1 |
| 74HC595, 74HC165, 74HC138, 74HC14, CD4511, CD4051 | GPIO/SPI | direct (3.3 V) | P1 |

**Inputs**

| Part | Interface | Priority |
|---|---|---|
| Push button, tactile switch, slide/toggle switch, DIP switch, limit switch, reed switch, tilt switch | GPIO | P0 |
| 4×4 and 3×4 membrane keypad | GPIO matrix | P0 |
| Rotary encoder KY-040 | GPIO / QEI | P0 |
| Analog joystick (2× ADC + button) | ADC | P0 |
| TTP223 capacitive touch | GPIO | P1 |

**Analog sensors**

| Part | Supply | Output range | Class | Priority |
|---|---|---|---|---|
| LDR (with divider), NTC 10 k thermistor | — | ratiometric | direct | P0 |
| LM35 | 4–30 V | 10 mV/°C (≤ 1.5 V) | direct | P0 |
| TMP36 | 2.7–5.5 V | 0.1–2.0 V | direct | P0 |
| MQ-2 / MQ-135 gas (heater 5 V, ~150 mA) | 5 V | 0–5 V | divider + supply | P0 |
| Soil moisture (resistive/capacitive), rain sensor | 3.3–5 V | 0–VCC | divider if 5 V | P0 |
| KY-038 sound sensor, TCRT5000 IR reflectance, flame sensor | 3.3–5 V | AO 0–VCC + DO | divider if 5 V | P1 |
| Sharp GP2Y0A21 IR distance | 5 V | 0.4–3.1 V | direct signal, 5 V supply | P1 |
| ACS712 current sensor | 5 V | 2.5 V ± 185 mV/A | divider | P1 |
| SS49E hall (analog), A3144 hall (open-collector digital) | 3.3–5 V | — | direct | P1 |
| ADXL335 accelerometer | 3.3 V | 0–3.3 V | direct | P1 |
| Flex sensor, FSR | — | ratiometric | direct | P2 |

**Digital and protocol sensors**

| Part | Interface | Supply | Class | Priority |
|---|---|---|---|---|
| HC-SR04 ultrasonic | GPIO pulse (capture) | 5 V | ECHO 5 V: info in GPIO mode, divider if analog-muxed | P0 |
| HC-SR501 PIR | GPIO | 5–20 V (3.3 V out) | direct | P0 |
| DHT11 / DHT22 | bit-banged single wire | 3.3–5 V | direct (pull-up) | P0 |
| DS18B20 | 1-Wire | 3.0–5.5 V | direct (4.7 k pull-up) | P0 |
| TSOP38238 / VS1838B IR receiver (NEC remote stimulus) | GPIO + capture | 2.7–5.5 V | direct | P1 |
| BMP280 / BME280 | I2C / SPI | 1.71–3.6 V | **3.3 V only** | P0 |
| MPU6050 (GY-521 has an LDO) | I2C | 3.3 / 5 V module | direct | P0 |
| ADXL345, QMC5883L / HMC5883L, MPU9250 | I2C / SPI | 3.3 V | direct | P1 |
| BH1750 light, TSL2561 | I2C | 3.3 V | direct | P1 |
| LM75 / TMP102, SHT31, AHT20 | I2C | 3.3 V | direct | P0–P1 |
| VL53L0X ToF, APDS-9960, MAX30102 | I2C | 3.3 V | direct | P1 |
| INA219 current/power | I2C | 3.3–5 V | direct | P1 |
| HX711 load cell | 2-wire clocked | 2.6–5.5 V | direct | P1 |
| MAX6675 / MAX31855 thermocouple | SPI | 3.3 / 5 V | direct | P1 |
| TCS34725 color | I2C | 3.3 V | direct | P2 |

**Displays and indicators**

| Part | Interface | Supply | Class | Priority |
|---|---|---|---|---|
| Single 7-segment (CA/CC), 4-digit multiplexed | GPIO | — | resistors per segment | P0 |
| HD44780 16×2 / 20×4 (4- and 8-bit, R/W, busy flag) | GPIO | 5 V (VIH 2.2 V OK at 3.3 V) | direct; contrast pot | P0 |
| PCF8574 I2C LCD backpack | I2C | 5 V | direct (pull-ups to 3V3) | P0 |
| SSD1306 128×64 OLED | I2C / SPI | 3.3–5 V module | direct | P0 |
| TM1637 4-digit | 2-wire (not I2C) | 3.3–5 V | direct | P1 |
| MAX7219 8×8 matrix / 8-digit | SPI | 5 V (VIH 3.5 V) | **level shift** | P1 |
| Nokia 5110 (PCD8544) | SPI | 3.3 V | direct | P1 |
| ST7735 / ILI9341 TFT (+ XPT2046 touch) | SPI | 3.3 V | direct | P1 |
| KS0108 128×64 graphic LCD (the ALS kit's CND1 GLCD) | GPIO 8-bit | 5 V | direct | P1 |
| WS2812B / NeoPixel strip and ring | bit-banged 800 kHz | 5 V (VIH 3.5 V) | **level shift** | P1 |
| APA102 | SPI | 5 V | level shift | P2 |
| Active buzzer (~30 mA), passive buzzer/piezo, speaker via DAC + amp | GPIO / PWM / DAC | 3.3–5 V | driver | P0–P1 |

**Actuators**

| Part | Interface | Supply | Class | Priority |
|---|---|---|---|---|
| SG90 / MG996R servo (50 Hz, 1–2 ms) | PWM | 4.8–6 V, stall up to 0.7–2.5 A | direct signal, external supply | P0 |
| DC motor (with driver or transistor), vibration motor, fan | PWM | 3–12 V | driver + flyback | P0 |
| 28BYJ-48 + ULN2003 | GPIO | 5 V | driver | P0 |
| NEMA-17 + A4988 | GPIO step/dir | 8–35 V | driver | P1 |
| Relay module (often active-low, 5 V coil), solenoid, SSR | GPIO | 5–12 V | driver / flyback | P0 |

**Communication, storage and timekeeping**

| Part | Interface | Supply | Class | Priority |
|---|---|---|---|---|
| USB-UART bridge (CP2102 / FT232): the serial monitor endpoint | UART | — | direct | P0 |
| HC-05 / HC-06 Bluetooth (AT commands, phone-terminal stimulus) | UART | 3.6–6 V, RX 3.3 V | direct | P1 |
| ESP-01 / ESP8266 (AT subset, ~300 mA peaks) | UART | 3.3 V | needs supply | P1 |
| NEO-6M GPS (NMEA stream from a chosen location) | UART | 3.3–5 V | direct | P1 |
| AT24C02 / 24LC256 EEPROM (the kit has I2C RTC/EEPROM) | I2C | 1.8–5.5 V | direct | P0 |
| 25LC256 / W25Q32 flash, microSD (SPI mode, FAT image) | SPI | 3.3 V | direct | P1 |
| DS1307 (5 V), DS3231, PCF8563 RTC | I2C | — | direct | P0–P1 |
| MCP23017, PCF8574 I/O expanders | I2C | 3.3 V | direct | P1 |
| MCP3008 ADC, ADS1115 ADC, MCP4725 DAC, MCP4921 DAC | SPI / I2C | 3.3 V | direct | P1 |
| NRF24L01 (two-node link), RC522 RFID (virtual tag stimulus) | SPI | 3.3 V | direct | P1 |
| MAX485 RS-485, SN65HVD230 CAN transceiver, MCP2515 CAN | UART / CAN / SPI | 3.3 / 5 V | — | P2 |

**Out of scope, and documented as such**
- USB device/host enumeration, Ethernet PHY/TCP-IP, GSM/LTE modems, cameras, and audio codecs beyond the DAC.

**What "every compatible component" means here**
- Every *interface class* the LPC1768 exposes is modeled.
- Each class has a generic part.
- The SDK lets you add a specific device as a JSON register map, or as a small Python class with a test.

### F4. Targets

| Target | Pins exposed | Notes |
|---|---|---|
| ALS-SDA-ARMCTXM3-01 (existing) | 10 FRC headers, power taps | Unchanged exam mode. External parts connect via patch wires or the FRC-to-breadboard adapter |
| mbed LPC1768 (DIP-40) | p5–p30, VOUT 3.3 V, VU 5 V, GND; LED1–4 = P1.18/P1.20/P1.21/P1.23; USB serial = UART0 | The most common bare form. Verify the pin map against the mbed handbook before shipping |
| Bare LPC1768 LQFP100 breakout | All 70 GPIO | For full pin-mux freedom |

---

## Part G — Testing strategy

- **Regression gate.** Today's 37 pytest modules and 13 Playwright specs run unchanged in exam mode after every phase.
- **Peripheral tests.** Register-level tests per new peripheral, in the existing style: compiled C, real MMIO, no source interpretation.
- **Solver tests.** Analytic circuits with tolerance assertions.
- **Doctor golden tests.** One per rule and per D5 scenario: finding text keys, severity, damage state, and the fix-apply result.
- **Part tests.**
  - A model unit test.
  - Firmware integration (a sample `.c` that reads or drives the part).
  - For bit-banged and protocol parts, a timing-tolerance test in virtual time.
- **3D tests.** Playwright screenshot baselines for preset views, a pick/wire interaction test and a performance budget (frame time).
- **Finder tests.** About 20 scripted search tasks (R3 acceptance).

---

## Part H — Risks and decisions to confirm

1. **Virtual time versus raw speed.** Block counting slows pure-CPU loops compared with today's live fast path. Mitigation: a C-side counting hook and slice batching. Measure before committing.
2. **Python MMIO throughput** for SPI displays and fast UARTs. If a full TFT frame is too slow, add a peripheral fast path (batch FIFO writes) or document the frame rate.
3. **Accuracy honesty.** The solver is DC and simplified. Every part page states its fidelity tier, consistent with this project's existing "no hidden gaps" documentation culture.
4. **Exam mode must not drift.** Hints stay off and the SVG view stays available. Existing behavior tests guard this.
5. **3D asset licensing.** Prefer procedural geometry and accept CC0/MIT assets only. Record each source.
6. **Damage model pedagogy.** Latching damage could frustrate beginners. The default is *Realistic* in Learn mode with a one-click "Replace part", and *Warn only* in Sandbox. This is open for user confirmation.
7. **Scope.** USB, Ethernet and CAN networking are explicitly deferred.

## Sources

- NXP, *LPC1769/68/67/66/65/64/63 data sheet*, Rev. 9.10 (2020): limiting values (Table 6), static characteristics (Table 8), pad notes. <https://www.nxp.com/docs/en/data-sheet/LPC1769_68_67_66_65_64_63.pdf>
- NXP community, *LPC1768 ports 5V tolerant*: <https://community.nxp.com/thread/424970>
- mbed forum, *logic input pin electrical specs*: <https://os.mbed.com/forum/helloworld/post/16861/>
- mbed cookbook (component libraries used with the LPC1768): <https://os.mbed.com/cookbook/>
- Wokwi Custom Chips API (reference design for a part SDK: GPIO, analog, time, UART, I2C, SPI, framebuffer): <https://docs.wokwi.com/chips-api/getting-started>
- Repository documents: `HARDWARE_FIDELITY_GAPS.md`, `docs/ARCHITECTURE.md`, `docs/BOARD_NOTES.md`, `docs/PERIPHERAL_CONNECTIVITY_AUDIT.md`, `docs/TIMING.md`.
