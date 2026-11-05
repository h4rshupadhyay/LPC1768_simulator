# Workbench: LPC1768 with external components

The **Workbench** screen (`#bench`) is a 3D bench for building circuits around an
LPC1768. The exam-practice **Board** screen is unchanged and stays the default.

## The kit is the main board

The ALS LPC1768 kit is always on the bench; every project builds around it. External
parts connect to the kit with jumper wires:

| Kit connection | Endpoint | Notes |
|---|---|---|
| Header pins | `kit.CNA.1` … `kit.CNAD.10` | Same MCU mapping as the manual, e.g. CNA.3 = P0.6, CNA.6 = P0.9, CNA.7/CNA.8 = P0.10/P0.11 (I2C2), CND.1 = P0.23 (AD0.0), CND.7 = P2.0 (PWM1.1). |
| Power tap | `kit.3V3`, `kit.5V`, `kit.GND` | Shown next to the CN8 power section. Its position is an assumption; check your board. Any number of wires may share it. |

A header that holds a ribbon cable cannot take jumper wires at the same time. Loading
an example unplugs only the ribbons on headers it needs, and says which.

The simulator core also models an mbed LPC1768 module (`mbed.p5` … `mbed.p30`,
`VOUT`, `VU`, `GND`) and a bare chip (`mcu.P0.0` …), reachable through the
`/api/settings` target option; the Workbench screen itself always returns to the kit.

## 3D view controls

Drag to orbit, scroll to zoom, right-drag to pan, or use the **View** panel in the
corner: sliders for **Rotate**, **Tilt**, **Zoom** and **Pan** (left/right, forward/back),
and presets **Bench** (kit and parts), **Kit**, **Top**, **Front**, **Parts** and
**Selected** (the selected part). Sliders and mouse stay in step.

## Building a circuit

* **Find parts**: search by name, alias, part number or intent ("distance", "show text",
  "5v relay"); typos are tolerated. Filter by category, interface, and whether the part
  works directly with a 3.3 V LPC1768. The **i** button shows ratings and wiring notes.
* **Place**: click a catalogue card, move the ghost, press **R** to rotate and click to
  drop. Pins that land on breadboard holes plug in; the rows a–e / f–j of a column are
  joined, rails run the full length. A hole takes one lead.
* **Wire**: click a pin or hole, then another. Pick the wire colour in the toolbar.
  Click a wire, then Delete (or the HUD button) removes it.
* **Probe**: hover any pin or hole to read its node, voltage and the selected pin function.
* **Inspect**: select a part to change its properties (resistance, colour, I2C address…),
  move environment sliders (temperature, distance, light, gas…) and read live pin voltages.
* **Undo/redo** (Ctrl+Z / Ctrl+Y), **Save project** / **Open…** (JSON with circuit and C source).
* **Examples** load a wired circuit and compile its firmware in one step.

## Circuit Doctor

The Doctor explains what is wrong, why, what it does to the hardware, and how to fix it:

* **Static rules**: unpowered or ungrounded parts, I2C/1-Wire buses without pull-ups,
  LEDs without series resistors, coils without flyback diodes.
* **Live electrical checks** on the solved operating point: LPC1768 pin current (4 mA
  rating, ~45–50 mA short circuit), pin voltage per pad class (5 V tolerant digital;
  analog-mode pads 0–3.3 V, 5.1 V absolute; USB pads never 5 V), part supply ranges and
  absolute maxima, LED current, resistor power, rail overload and shorts, undefined input levels.
* **Firmware observations**: pin not muxed (e.g. UART transmitting without TXD in PINSEL),
  baud-rate mismatch, unpowered peripheral (PCONP), missing PLL feed, CPU clock above 100 MHz,
  I2C address conflicts, SPI MISO contention, floating inputs read by firmware.

Fixes carry computed values: E12 voltage dividers that keep a signal at or below 3.3 V,
LED series resistors for a target current, level shifters, transistor drivers. Many have
**Apply fix**, which rewires the bench (undoable).

**Realistic damage**: an absolute maximum exceeded for more than 50 ms of simulated time
destroys the part. A damaged BMP280 stops acknowledging I2C, a burnt LED is open, an
overstressed MCU pin no longer drives or reads. **Replace part** repairs it once the cause
is fixed. Turn realistic damage off to get warnings only.

## Timing modes

* **Real-time** (default): peripherals follow the wall clock; the CPU runs as fast as the
  host allows. Right for human-scale behavior, UART, I2C, SPI, servos, ultrasonic timing
  measured with a timer.
* **Precise (µs)**: every peripheral and device runs on instruction-derived virtual time,
  throttled so it never runs ahead of real time. Use it for bit-banged protocols that depend
  on instruction timing (DHT11/22, 1-Wire DS18B20, WS2812). The toolbar shows the achieved speed.

## Serial monitor

The **Serial** tab shows the UART0 terminal (PC/USB serial) and the terminal of every
USB–serial adapter or Bluetooth module on the bench. Pick the baud rate: a mismatch garbles
text exactly as a real UART would, and the Doctor says which side is wrong.

## How the electrical model works

Nets containing a part pin or a supply rail are solved by nodal analysis
(`simulator/solver.py`): MCU outputs are 3.3 V behind 70 Ω, internal pull-ups ~50 µA,
LEDs/diodes/transistors/MOSFETs are piecewise linear. Nets with only kit wiring keep the
original digital model, so exam-practice behavior is unchanged. Devices that talk I2C, SPI
or UART exchange whole transactions with the modeled LPC1768 peripherals over the nets they
share; bit-banged parts react to timed edges.

## Adding a part

Create a class in `simulator/parts/` deriving from `Part` (`simulator/parts/base.py`):
declare `pins`, catalogue `meta` (name, category, aliases, interfaces, supply, compat,
footprint, shape), optional `supply`/`pin_limits` ratings and `stimuli_spec`, then implement
`elements()` (solver stamps using `@PIN` names) and, as needed, `sense()`, `dynamic()`,
`i2c_*`, `spi_transfer`, `uart_rx`, `check()` and `state()`. Register it in
`simulator/parts/__init__.py`. Register-map I2C chips can often use **Generic I2C register
device** with no code. Add a test beside `tests/test_new_peripherals.py`.

## Limits

* DC operating point only: no capacitance, inductance transients, switching noise or analog
  bandwidth. Motors are resistive; back-EMF and stall are not modeled.
* UART/SPI/I2C are transaction level; the pads do not toggle bit by bit, so a part cannot
  sniff a bus it is not addressed on. I2C slave mode, SPI slave mode, CAN, USB, Ethernet,
  I2S and GPDMA are not modeled (accesses stop with an explanation). MCPWM registers are
  stored without outputs.
* Ratings are data-sheet typical values. Damage thresholds are deliberately simple and do
  not predict real failure times.
* The ALS power tap location and the mbed `VOUT` current limit (~40 mA) are assumptions to
  verify on real hardware.
