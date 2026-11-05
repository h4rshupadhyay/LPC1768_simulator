# Remaining hardware-fidelity gaps

The audit verifies a documented digital subset. It does not certify physical
board equivalence. See HARDWARE_SPEC.md for source precedence and wiring,
COVERAGE_MATRIX.md for all 19 manual entries, and TEST_REPORT.md for executed
results. No gap below is hidden by a skipped or expected-failure test.

## Unverified physical behavior: eight evidence gaps

| ID | Status | Remaining uncertainty and examination risk |
|---|---|---|
| U01 | UNVERIFIED | No physical board, continuity measurements, oscilloscope captures, logic-analyzer traces, or hardware-in-the-loop fixture was available. Software results cannot establish physical equivalence. |
| U02 | UNVERIFIED | SW2 is CNB1 pin7 in ESD PDF p29; the ALS PDF p37 table lists pin9 as both NC and interrupt. The default pin7 profile reaches P2.12 through CNB. Confirm the actual board with continuity testing. The alternative pin9 profile does not invent a missing CNB conductor. |
| U03 | UNVERIFIED | ADC accuracy, reference voltage, gain/offset, nonlinearity, noise, potentiometer tolerance, source impedance, acquisition aperture and threshold equality are not measured. Tests establish the NXP ideal transfer only. |
| U04 | UNVERIFIED | Floating ADC inputs resolve to zero by convention; unpowered/floating segment inputs are suppressed in the renderer. These are not measured voltages. Strong conflicts resolve LOW with a warning; resistor competition and output contention are not physically predicted. |
| U05 | UNVERIFIED | Exact first-cycle PWM synchronization, APB read timing, ADC changes during acquisition and clock/power transition transients need silicon measurements. Steady single-edge PWM periods and counter reset-to-one are tested; see the source discussion below. |
| U06 | UNVERIFIED | JP16 gates LCD acceptance/visibility while retaining state. Exact LCD power sequencing, brownout behavior and module/controller identity are not established by the supplied wiring information. MCU reset correctly retains the external LCD's DDRAM and transaction phase. |
| U07 | UNVERIFIED | Contacts are ideal switches. There is no calibrated bounce waveform or minimum pulse duration. Controlled short-pulse, missed-scan and held-key tests are implemented; debounce success remains the executed firmware's responsibility. |
| U08 | UNVERIFIED | LED current, perceived brightness, seven-segment flicker/ghost current, buffer/decoder propagation, LCD contrast POT3 and backlight behavior have no physical or photometric calibration. |

## Unsupported behavior: nine capability gaps

| ID | Status | Boundary |
|---|---|---|
| S01 | UNSUPPORTED | LCD busy timing, minimum E width, setup/hold requirements, command delays and invalid rapid writes. Correct nibble order can appear to work despite physically insufficient delays. This is an important remaining false-positive risk. |
| S02 | UNSUPPORTED | Rendering custom CGRAM glyphs, controller-specific character ROM, visible cursor/blink and a complete 8-bit LCD interface. CGRAM addressing is tested without claiming custom glyph rendering. |
| S03 | PARTIAL | Priority preemption with PRIGROUP grouping, nesting, PendSV, SVC, IRQ32–34 and SHPR/AIRCR (including SYSRESETREQ) are modeled; tail chaining is approximated by return-then-deliver. BASEPRI/FAULTMASK, MSP/PSP switching and HardFault/MemManage/BusFault handlers are not (faults stop with an explanation and source line). |
| S04 | UNSUPPORTED | DMA, bit-band aliases, MPU/protection faults, faithful flash programming/IAP, boot-ROM/ISP behavior and SRAM power-cycle contents. Mapped flash/RAM is not a complete memory-system model. |
| S05 | PARTIAL | All eight channels sample their pads (kit POT1/POT4 on AD0.5/AD0.4; solved circuit voltages elsewhere). External START edges, trim effects and a variable VREF are absent. |
| S06 | PARTIAL | Timer capture, counter mode and EMR match outputs, PWM1.1–1.6 single/double edge on every PINSEL pad are modeled. The kit's JP14/RM4/TP4 loopback routes, MCPWM outputs, PWM external count and DMA are not. |
| S07 | PARTIAL | UART0–3, SSP0/1, legacy SPI, I2C0–2 master, DAC, RIT, WDT, RTC and QEI are modeled at register/transaction level and talk to Workbench parts. I2S, CAN, USB, Ethernet, slave modes and the kit's on-board UART/SPI/I2C devices, relay, buzzer and motors remain artwork only. |
| S08 | PARTIAL | Individual flying leads to header pins and the Workbench's breadboards are modeled, with DC voltages and currents for nets containing parts. Reversed/damaged ribbons, splitters, supply disconnection and most board jumpers are not; JP7/8/12/13/17 retain browser state only. |
| S09 | UNSUPPORTED | Complete PLL feed/lock sequencing, oscillator startup, illegal-frequency enforcement, PCGPIO gating of GPIO/PINCON accesses, sleep/power-down, brownout/reset causes, AIRCR system reset, and GPIO repeater retention. Startup-compatible register responses can accept a clock or power program that real hardware rejects. |

## Timing and execution approximations

The live clock advances timers, PWM and ADC from active monotonic time using
configured divisors. Pause excludes stopped time. CPU instructions and busy loops
still run at host throughput. Offline tests count basic-block halfwords as a
deterministic progress budget; this is not a cycle-accurate Cortex-M3 clock.
Fast polling and interrupt code can miss periods when the host cannot keep up.
Interrupt flags latch rather than queue every missed event.

Seven-segment rendering retains dominant patterns over 50 ms of active time and
weights dwell with instruction progress. This approximates persistence and avoids
Python MMIO overhead dominating brief blanking writes. It does not establish
physical refresh brightness or correct flicker for every slow scan program.

The board manual's suggested clock profile (PDF pp46-47) is PLL off, 12 MHz/4 =
3 MHz and PCLK=CCLK. The installed CMSIS startup used by the compiler defaults
to 100 MHz. Both derived rates are tested, but raw software-delay counts are not
portable between them. Reference timer dividers now derive from SystemCoreClock;
ADC examples choose a legal clock and disable analog-pin pulls.

NXP UM10360 Table447 says PWM resets TC to one. Its diagram can be misread as
losing a period clock. The model holds a 1..MR0 counter cycle with match actions
on the subsequent edge, retaining MR0 clocks per period. This agrees with the
[original reported register/LED experiment on NXP's forum](https://community.nxp.com/t5/LPCXpresso-IDE/LPC17xx-LPC1769-PWM-manual-unclear-help-appreciated/m-p/563867).
That is an independently published observation, not a measurement of this user's
board. Exact startup/bus-edge phase remains U05.

## Test coverage boundaries

The finite sweeps include all LED states on four headers, all segment masks on
four digits, all 24 row scan orders, all three-key rectangles, 200 calculator
expressions, both ADC channels' ideal centers and threshold sides, and all
requested PWM duty levels. The catalog's 16-position ring period is traced twice.
These do not enumerate every combination of 32-bit register values, all 65,536
multi-key sets, all analog input event histories or every instruction/input
interleaving. Full catalog 10,000/65,536-state counter cycles remain unverified;
documented carry/borrow/wrap boundaries and full underlying 8-bit cycles are tested.

Tests schedule events with injected clocks, SRAM handshakes and controlled CPU
advancement. There is no general instruction-accurate event scheduler and no
second-emulator or physical-board differential run. Mutation detection applies
only to the named, executed campaign, not every possible incorrect program.

## Before the examination

Confirm SW2 wiring and the startup clock on the actual lab board. Check LCD waits
on hardware even when text appears here. Use verified GPIO, ribbons/jumpers,
keypad coordinates, LCD transactions, ADC control/ideal codes, timer setup and
single-edge PWM within their tested scope. Treat the unsupported paths and
unmeasured electrical/timing behavior above as boundaries of this simulator.

## Workbench electrical model

Nets that contain an external part or a supply rail are solved at DC by nodal
analysis with piecewise-linear diodes, BJTs and MOSFETs (`simulator/solver.py`).
Pad drive (3.3 V behind ~70 Ω), pull-ups (~50 µA) and ratings come from the NXP
data sheet; part ratings come from their data sheets. There is no capacitance,
inductive transient, temperature dependence or noise. Damage is a teaching model:
an absolute maximum exceeded for 50 ms of simulated time. Transaction-level buses
mean pads do not toggle bit by bit during UART/SPI/I2C frames. The ALS power tap
position and on-board I2C pull-ups are assumptions. See [docs/WORKBENCH.md](docs/WORKBENCH.md).
