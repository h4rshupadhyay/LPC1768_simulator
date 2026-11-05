"""Unicorn Cortex-M3 plus the LPC1768 register model.

No instruction decoding: Unicorn executes all ARM/Thumb instructions. MMIO
callbacks see every peripheral access. Live peripherals use elapsed monotonic time;
offline probes can use deterministic instruction-derived time. Peripherals beyond
the original lab subset (UART, SSP/SPI, I2C, DAC, RIT, WDT, RTC, QEI) register on
a small bus and exchange data with circuit parts through the board's nets.
"""
from __future__ import annotations
from dataclasses import dataclass
from io import StringIO
import heapq
import itertools
import random
import struct
import time

from intelhex import IntelHex
from unicorn import (Uc, UcError, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS,
                     UC_HOOK_BLOCK, UC_HOOK_INTR, UC_HOOK_MEM_UNMAPPED,
                     UC_MEM_WRITE_UNMAPPED, UC_MEM_FETCH_UNMAPPED)
from unicorn.arm_const import (UC_ARM_REG_SP, UC_ARM_REG_PC, UC_ARM_REG_LR,
    UC_ARM_REG_XPSR, UC_ARM_REG_PRIMASK, UC_ARM_REG_R0, UC_ARM_REG_R1,
    UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R12)

from . import pins
from .errors import FirmwareError
from .board import Board
from .displays import LCD, SevenSegment
from .adc import ADCPeripheral
from .systick import SysTick
from .uart import UART
from .ssp import SSP, SPI
from .i2c import I2C
from .dac import DAC
from .clocks import RIT, WDT, RTC, QEI, StoredRegisters

__all__ = ['Machine', 'FirmwareError', 'GPIO']

# Named windows used only to explain unsupported accesses.
REGIONS = [
    (0x40038000, 0x4004C000, 'CAN acceptance filter / CAN1 / CAN2 (not modeled)'),
    (0x400A8000, 0x400AC000, 'I2S (not modeled)'),
    (0x400FC000, 0x40100000, 'system control'),
    (0x50000000, 0x50004000, 'Ethernet MAC (not modeled)'),
    (0x50004000, 0x50008000, 'GPDMA (not modeled)'),
    (0x5000C000, 0x50010000, 'USB (not modeled)'),
    (0xE000E000, 0xE000F000, 'system control space'),
]
EXCEPTION_NAMES = {-14: 'NMI', -13: 'HardFault', -5: 'SVCall', -2: 'PendSV', -1: 'SysTick'}


@dataclass
class GPIO:
    direction: int = 0
    mask: int = 0
    latch: int = 0


class Machine:
    FLASH_SIZE = 0x80000
    SC = 0x400FC000
    PIN = 0x4002C000
    ADC = 0x40034000
    PWM = 0x40018000
    GPIOINT = 0x40028080
    TIMERS = {0x40004000: (1, 1), 0x40008000: (2, 2),
              0x40090000: (3, 22), 0x40094000: (4, 23)}
    TIMER_BASES = (0x40004000, 0x40008000, 0x40090000, 0x40094000)

    def __init__(self, hex_text: str, *, realtime=False, clock_ns=None, target='als'):
        self.hex_text = hex_text
        self.realtime = realtime
        self._clock_ns = clock_ns or time.perf_counter_ns
        self._clock_anchor = None
        self.elapsed_ns = 0
        self.virtual_ns = 0
        self._virtual_fraction = 0
        self._virtual_tick = 0
        self.core_cycles = 0
        self.pclk_fraction = {}
        self.segments, self.initial_sp, self.entry = self.validate_hex(hex_text)
        self.gpio = [GPIO() for _ in range(5)]
        # UM10360 tables 46 and 654: PWM1 is powered and exception entry
        # aligns the stack to eight bytes at reset.
        self.regs = {self.SC + 0xC4: 0x040882DE, 0xE000ED14: 0x200}
        self.ticks = 0
        self.gpio_events = 0
        self.irq_count = 0
        self.error = None
        self.notes = {}
        self.reset_requested = None
        self.fault = None
        self.floating_mode = 'low'
        self.rng = random.Random(0x1768)
        self.damaged_pads = set()
        self.ports_read = set()  # GPIO ports whose FIOPIN firmware has sampled
        self.lcd = LCD()
        self.seven = SevenSegment(window=50_000_000 if realtime else 300_000)
        self.enabled_irq = 0
        self.pending_irq = 0
        self.pending_system = 0
        self.active = []
        self._defer_irq_stop = False
        self._ticking = False
        self._events = []
        self._event_seq = itertools.count()
        self.last_timer_tick = 0
        self.timer_fraction = {}
        self.adc_last = [0] * 8
        self.adc_global = 0
        self.pwm_latched = {i: 0 for i in range(7)}
        self.gpioint = {'r0': 0, 'f0': 0, 'r2': 0, 'f2': 0, 'sr0': 0, 'sf0': 0, 'sr2': 0, 'sf2': 0}
        self._pll_unfed = False
        self._pll_feed = 0
        self._dwt_base = 0
        self._specials_key = None
        self._specials = []
        self._cclk_key = None
        self._cclk = 0
        self._last_pads = None
        self.board = Board(self, target=target)
        self.adc = ADCPeripheral(self)
        self.systick = SysTick(self)
        self.systick_last_tick = 0
        self.systick_fraction = 0
        self.uarts = [UART(self, i) for i in range(4)]
        self.ssps = [SSP(self, i) for i in range(2)]
        self.spi = SPI(self)
        self.i2cs = [I2C(self, i) for i in range(3)]
        self.dac = DAC(self)
        self.rit, self.wdt, self.rtc, self.qei = RIT(self), WDT(self), RTC(self), QEI(self)
        mcpwm = StoredRegisters(self, 'MCPWM', 0x400B8000, 0x4000, range(0, 0x78, 4), power_bit=17)
        self.peripherals = [*self.uarts, *self.ssps, self.spi, *self.i2cs, self.dac,
                            self.rit, self.wdt, self.rtc, self.qei, mcpwm]
        self.terminals = {}
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        self.uc.mem_map(0, self.FLASH_SIZE)
        self.uc.mem_map(0x10000000, 0x8000)
        self.uc.mem_map(0x2007C000, 0x8000)
        for start, data in self.segments:
            self.uc.mem_write(start, data)
        for base, size in [(0x40000000, 0x100000), (0x2009C000, 0x1000), (0xE000E000, 0x2000),
                           (0xE0001000, 0x1000), (0x50000000, 0x200000)]:
            self.uc.mmio_map(base, size, self._read, base, self._write, base)
        # Cortex-M3 bit-band aliases of the SRAM/GPIO and peripheral regions.
        for alias in (0x22000000, 0x42000000):
            self.uc.mmio_map(alias, 0x2000000, self._bitband_read, alias, self._bitband_write, alias)
        # Deterministic probes count every translated block. Live execution
        # can synchronize wall-clock peripherals at MMIO and bounded slices,
        # avoiding a Python callback on every iteration of a pure delay loop.
        self._block_hook = None
        if not self.realtime:
            self._block_hook = self.uc.hook_add(UC_HOOK_BLOCK, self._block)
        self.uc.hook_add(UC_HOOK_INTR, self._interrupt)
        self.uc.hook_add(UC_HOOK_MEM_UNMAPPED, self._unmapped)
        self.uc.reg_write(UC_ARM_REG_SP, self.initial_sp)
        self.uc.reg_write(UC_ARM_REG_PC, self.entry)
        self.uc.reg_write(UC_ARM_REG_XPSR, 1 << 24)
        self.observe()

    @classmethod
    def validate_hex(cls, text):
        if not isinstance(text, str) or len(text) > 3_000_000:
            raise FirmwareError('Intel HEX must be text, at most 3 MB.')
        lines = [s.strip() for s in text.splitlines() if s.strip()]
        if not lines or lines[-1].upper() != ':00000001FF':
            raise FirmwareError('Intel HEX is missing its end-of-file record.')
        try:
            ih = IntelHex(StringIO(text))
            segments = []
            for start, end in ih.segments():
                if not (0 <= start < end <= cls.FLASH_SIZE or
                        0x10000000 <= start < end <= 0x10008000 or
                        0x2007C000 <= start < end <= 0x20084000):
                    raise FirmwareError(f'HEX data outside LPC1768 flash/SRAM: 0x{start:08X}.')
                segments.append((start, ih.tobinarray(start=start, end=end - 1).tobytes()))
            if any(a not in ih.addresses() for a in range(8)):
                raise FirmwareError('HEX must contain a Cortex-M vector table at flash address 0.')
            sp, pc = struct.unpack('<II', ih.tobinarray(start=0, end=7).tobytes())
            if not ((0x10000000 < sp <= 0x10008000 or 0x2007C000 < sp <= 0x20084000) and sp % 8 == 0):
                raise FirmwareError(f'Invalid initial stack pointer 0x{sp:08X}.')
            if not pc & 1 or not 8 <= (pc & ~1) < cls.FLASH_SIZE or (pc & ~1) not in ih.addresses():
                raise FirmwareError(f'Invalid Thumb reset vector 0x{pc:08X}.')
            return segments, sp, pc
        except FirmwareError:
            raise
        except Exception as e:
            raise FirmwareError(f'Invalid Intel HEX: {e}') from e

    # -- diagnostics -----------------------------------------------------------
    def note(self, key, message):
        """Record a firmware/configuration observation for the Circuit Doctor."""
        self.notes[key] = message

    def _fail(self, message):
        if self.error is None:
            self.error = message
        self.uc.emu_stop()

    def request_reset(self, reason):
        self.reset_requested = reason
        self.uc.emu_stop()

    @staticmethod
    def region_name(address):
        return next((name for start, end, name in REGIONS if start <= address < end), None)

    def _unmapped(self, uc, access, address, size, value, _):
        kind = ('write to' if access == UC_MEM_WRITE_UNMAPPED else
                'instruction fetch from' if access == UC_MEM_FETCH_UNMAPPED else 'read from')
        self.fault = f'BusFault: {kind} unmapped address 0x{address:08X}'
        return False

    def _block(self, uc, address, size, _):
        self.ticks += max(1, size // 2)
        self._tick_adc_now()
        self._tick_timers_now()
        # IRQs are delivered between emulator slices; a higher-priority
        # pending exception stops the slice so it can preempt.
        if not self._defer_irq_stop and (self.pending_system or self.pending_irq & self.enabled_irq) \
                and self._preempt_ready():
            uc.emu_stop()

    def _read(self, uc, offset, size, base):
        address = base + offset
        try:
            value = self.read_word(address & ~3)
            return (value >> ((address & 3) * 8)) & ((1 << (size * 8)) - 1)
        except (FirmwareError, ValueError) as e:
            self._fail(str(e))
            return 0

    def _write(self, uc, offset, size, value, base):
        address = base + offset
        try:
            self.write_word(address & ~3, value << ((address & 3) * 8),
                            ((1 << (size * 8)) - 1) << ((address & 3) * 8))
        except (FirmwareError, ValueError) as e:
            self._fail(str(e))

    def _bitband_target(self, alias, offset):
        region = 0x20000000 if alias == 0x22000000 else 0x40000000
        byte = region + (offset >> 5)
        bit = (byte & 3) * 8 + ((offset >> 2) & 7)
        return byte & ~3, bit

    def _bitband_word(self, word):
        if 0x2007C000 <= word < 0x20084000:
            return int.from_bytes(self.uc.mem_read(word, 4), 'little'), True
        return self.read_word(word), False

    def _bitband_read(self, uc, offset, size, alias):
        try:
            word, bit = self._bitband_target(alias, offset)
            value, _ = self._bitband_word(word)
            return (value >> bit) & 1
        except (FirmwareError, ValueError) as e:
            self._fail(str(e))
            return 0

    def _bitband_write(self, uc, offset, size, value, alias):
        try:
            word, bit = self._bitband_target(alias, offset)
            old, ram = self._bitband_word(word)
            new = (old & ~(1 << bit)) | ((value & 1) << bit)
            if ram:
                self.uc.mem_write(word, new.to_bytes(4, 'little'))
            else:
                self.write_word(word, new)
        except (FirmwareError, ValueError) as e:
            self._fail(str(e))

    # -- pads -------------------------------------------------------------------
    def function(self, port, pin):
        index = port * 2 + pin // 16
        return (self.regs.get(self.PIN + index * 4, 0) >> (2 * (pin % 16))) & 3

    def _true_open_drain(self, port, pin):
        # P0.27/P0.28 are open-drain I2C pads. The ALS kit's documented GPIO use
        # of these pads (LCD RS/E) relies on its on-board pull-ups, so the kit
        # profile keeps the established push-pull digital model.
        return (port, pin) in pins.OPEN_DRAIN_I2C and self.board.target != 'als'

    def pin_pull(self, port, pin):
        if self._true_open_drain(port, pin):
            return None  # no internal pull resistors on the I2C0 pads
        index = port * 2 + pin // 16
        mode = (self.regs.get(self.PIN + 0x40 + index * 4, 0) >> (2 * (pin % 16))) & 3
        return 1 if mode == 0 else 0 if mode == 3 else None

    def pin_output(self, port, pin):
        if (port, pin) in self.damaged_pads:
            return None
        function = self.function(port, pin)
        if function == 0:
            if not self.gpio[port].direction & (1 << pin):
                return None
            level = int(bool(self.gpio[port].latch & (1 << pin)))
        else:
            level = self._signal_output(pins.name(port, pin, function))
            if level is None:
                return None
        if level == 1 and (self.regs.get(self.PIN + 0x68 + port * 4, 0) & (1 << pin)
                           or self._true_open_drain(port, pin)):
            return None
        return level

    def _signal_output(self, signal):
        """Digital level a selected peripheral function drives onto its pad."""
        if not signal:
            return None
        if signal.startswith('PWM1.'):
            return self.pwm_level(int(signal[5]))
        if signal.startswith('MAT'):
            timer, channel = int(signal[3]), int(signal[5])
            return (self.regs.get(self.TIMER_BASES[timer] + 0x3C, 0) >> channel) & 1
        return None

    def selected_pad(self, signal):
        """The (port, pin) currently muxed to `signal`, or None."""
        for port, pin, function in pins.pads_for(signal):
            if self.function(port, pin) == function:
                return port, pin
        return None

    def _special_pads(self):
        """Pads whose level is not the plain GPIO latch: alternate functions and I2C0."""
        key = tuple(self.regs.get(self.PIN + i * 4, 0) for i in range(11)) + (self.board.target,)
        if key != self._specials_key:
            self._specials = [(port, pin) for port in range(5) for pin in range(32)
                              if self.function(port, pin) or self._true_open_drain(port, pin)]
            self._specials_key = key
        return self._specials

    def _pad_word(self, port, external_mask, external_value):
        g = self.gpio[port]
        def zero_pairs(value):
            value = ~(value | (value >> 1)) & 0x55555555
            value = (value | (value >> 1)) & 0x33333333
            value = (value | (value >> 2)) & 0x0F0F0F0F
            value = (value | (value >> 4)) & 0x00FF00FF
            return (value | (value >> 8)) & 0xFFFF
        def pair_mask(offset):
            base = self.PIN + offset + port * 8
            return zero_pairs(self.regs.get(base, 0)) | (zero_pairs(self.regs.get(base + 4, 0)) << 16)
        gpio_functions = pair_mask(0)
        pullups = pair_mask(0x40)
        open_drain = self.regs.get(self.PIN + 0x68 + port * 4, 0)
        driven = g.direction & gpio_functions & ~(open_drain & g.latch)
        value = (g.latch & driven) | (pullups & ~driven)
        for p, n in self._special_pads():
            if p != port:
                continue
            level = self.pin_output(p, n)
            if level is None:
                level = self.pin_pull(p, n)
            value = (value & ~(1 << n)) | (int(bool(level)) << n)
        value = (value & ~external_mask) | external_value
        return value, driven

    def gpio_value(self, port):
        g = self.gpio[port]
        self.ports_read.add(port)
        self._tick_timers_now()
        external_mask, external_value = self.board.sampled_gpio(port)
        value, driven = self._pad_word(port, external_mask, external_value)
        floating = self._floating_bits(port, driven, external_mask) & ~g.mask & ~driven
        floating &= ~g.direction
        if floating:
            names = [f'P{port}.{n}' for n in range(32) if floating & (1 << n)][:8]
            self.note('floating-read', f'Firmware read floating input{"s" if len(names) > 1 else ""} '
                      f'{", ".join(names)} (no pull resistor and nothing driving). Real pins read '
                      'unpredictable values; enable a pull-up/down in PINMODE or connect a source.')
            if self.floating_mode == 'random':
                value = (value & ~floating) | (self.rng.getrandbits(32) & floating)
        return value & ~g.mask & 0xFFFFFFFF

    def _floating_bits(self, port, driven, external_mask):
        """Pads in PINMODE 'neither' (10b) that nothing external resolves."""
        bits = 0
        for half in range(2):
            modes = self.regs.get(self.PIN + 0x40 + (port * 2 + half) * 4, 0)
            neither = (modes >> 1) & ~modes & 0x55555555
            for shift in (1, 2, 4, 8):
                neither = (neither | (neither >> shift)) & (0x33333333, 0x0F0F0F0F, 0x00FF00FF, 0x0000FFFF)[
                    (1, 2, 4, 8).index(shift)]
            bits |= neither << (16 * half)
        return (bits & ~external_mask) | self.board.floating_mask(port)

    # -- observation and edge-driven inputs ------------------------------------
    def observe(self):
        if self.realtime:
            self._tick_timers_now()
        signals = self.board.signals()
        powered = self.board.jumpers['JP16'] == 'closed'
        lcd_connected = all(f'LCD{i}' in signals for i in range(4))
        nib = sum(signals.get(f'LCD{i}', 0) << i for i in range(4))
        self.lcd.observe(powered and lcd_connected and 'LCD_EN' in signals,
                         signals.get('LCD_EN', 0), signals.get('LCD_RS', 0), nib)
        selected = sum(signals.get(f'DIG{i}', 0) << i for i in range(4))
        pattern = sum(signals.get(f'SEG{i}', 0) << i for i in range(8))
        connected = self.board.has_signal_connection('DIG') and self.board.has_signal_connection('SEG')
        self.seven.observe(self.elapsed_ns if self.realtime else self.ticks,
                           selected if connected else -1, pattern, dwell_tick=self.ticks)
        self._watch_pads()
        if self.board.circuit.probes:
            self.board.circuit.record(self.time_ns())

    def _watching(self):
        r = self.regs
        pinsel4 = r.get(self.PIN + 0x10, 0)
        eint = any((pinsel4 >> (20 + 2 * n)) & 3 == 1 for n in range(4))
        gpioint = any(self.gpioint[k] for k in ('r0', 'f0', 'r2', 'f2'))
        capture = any(r.get(base + 0x28, 0) or r.get(base + 0x70, 0) & 3 for base in self.TIMER_BASES)
        return eint or gpioint or capture or self.qei.powered()

    def _watch_pads(self):
        if not self._watching():
            self._last_pads = None
            return
        masks, values = self.board._port_masks, self.board._port_values
        levels = [self._pad_word(port, masks[port], values[port])[0] for port in range(5)]
        last = self._last_pads
        self._last_pads = levels
        if last is None:
            return
        # External interrupts EINT0-3 on P2.10-P2.13, UM10360 section 3.6.
        for n in range(4):
            if self.function(2, 10 + n) != 1:
                continue
            level = (levels[2] >> (10 + n)) & 1
            previous = (last[2] >> (10 + n)) & 1
            polarity = (self.regs.get(self.SC + 0x14C, 0) >> n) & 1
            edge = bool(self.regs.get(self.SC + 0x148, 0) & (1 << n))
            if level == polarity and (not edge or level != previous):
                self.regs[self.SC + 0x140] = self.regs.get(self.SC + 0x140, 0) | (1 << n)
                self.pending_irq |= 1 << (18 + n)
        # GPIO interrupts on ports 0 and 2 share the EINT3 vector (section 9.5.6).
        for port in (0, 2):
            gpio_pins = ~self._non_gpio_mask(port)
            rising = levels[port] & ~last[port] & self.gpioint[f'r{port}'] & gpio_pins
            falling = last[port] & ~levels[port] & self.gpioint[f'f{port}'] & gpio_pins
            if rising or falling:
                self.gpioint[f'sr{port}'] |= rising
                self.gpioint[f'sf{port}'] |= falling
                self.pending_irq |= 1 << 21
        # Timer capture inputs and counter mode (sections 21.6.11-21.6.12).
        for timer, base in enumerate(self.TIMER_BASES):
            ccr, ctcr = self.regs.get(base + 0x28, 0), self.regs.get(base + 0x70, 0)
            if not ccr and not ctcr & 3:
                continue
            for channel in range(2):
                pad = self.selected_pad(f'CAP{timer}.{channel}')
                if pad is None:
                    continue
                port, pin = pad
                now, before = (levels[port] >> pin) & 1, (last[port] >> pin) & 1
                if now == before:
                    continue
                if ctcr & 3 and (ctcr >> 2) & 3 == channel and (ctcr & 3 == 3 or (ctcr & 3 == 1) == bool(now)):
                    self._advance_counter(base, 1)
                if (ccr >> (3 * channel)) & (1 if now else 2):
                    self.regs[base + 0x2C + 4 * channel] = self.regs.get(base + 8, 0)
                    if ccr & (4 << (3 * channel)):
                        self.regs[base] = self.regs.get(base, 0) | (1 << (4 + channel))
                        self.pending_irq |= 1 << self.TIMERS[base][0]
        if self.qei.powered():
            def level(signal):
                pad = self.selected_pad(signal)
                return (levels[pad[0]] >> pad[1]) & 1 if pad else 0
            self.qei.phases(level('MCI0'), level('MCI1'), level('MCI2'))

    def _non_gpio_mask(self, port):
        return sum(1 << pin for p, pin in self._special_pads() if p == port and self.function(p, pin))

    def _gpio_addr(self, address):
        off = address - 0x2009C000
        port, reg = divmod(off, 0x20)
        return (port, reg) if 0 <= port < 5 and reg in (0, 0x10, 0x14, 0x18, 0x1C) else None

    def _peripheral(self, address):
        for peripheral in self.peripherals:
            if peripheral.base <= address < peripheral.base + peripheral.size:
                return peripheral
        return None

    def _unsupported(self, address, write):
        region = self.region_name(address)
        suffix = f' ({region})' if region else ''
        raise FirmwareError(f'Unsupported register {"write" if write else "read"} at 0x{address:08X}{suffix}.')

    # -- register reads ----------------------------------------------------------
    def read_word(self, address):
        gaddr = self._gpio_addr(address)
        if gaddr:
            p, r = gaddr
            g = self.gpio[p]
            if r == 0x14:
                return self.gpio_value(p)
            return {0: g.direction, 0x10: g.mask, 0x18: g.latch, 0x1C: 0}[r]
        if self.PIN <= address <= self.PIN+0x7C:
            return self.regs.get(address, 0)
        if self.SC <= address <= self.SC+0x1C8 and address-self.SC in self._sc_offsets():
            off = address - self.SC
            if off == 0x1A0:
                v = self.regs.get(address, 0)
                return v | (0x40 if v & 0x20 else 0)
            if off in (0x88, 0xA8):
                base = self.SC + (0x80 if off == 0x88 else 0xA0)
                shift = 24 if off == 0x88 else 8
                control = self.regs.get(base, 0)
                return self.regs.get(base+4, 0) | (control<<shift) | ((1 << (shift+2)) if control & 1 else 0)
            return self.regs.get(address, 0)
        if self.ADC <= address <= self.ADC+0x34:
            off = address - self.ADC
            if off in (0, 4, 0xC, 0x30, 0x34) or 0x10 <= off <= 0x2C and off % 4 == 0:
                return self.adc.read(off)
        if self.GPIOINT <= address <= self.GPIOINT + 0x34:
            return self._gpioint_read(address - self.GPIOINT)
        if 0xE000E010 <= address <= 0xE000E01C:
            self._tick_timers_now()
            return self.systick.read(address - 0xE000E010)
        if 0xE000E000 <= address < 0xE000F000 or 0xE0001000 <= address < 0xE0002000:
            value = self._scs_read(address)
            if value is not None:
                return value
        for base in (*self.TIMERS, self.PWM):
            if base <= address <= base + (0x74 if base == self.PWM else 0x70):
                if address-base not in self._timer_offsets(base):
                    break
                self._tick_timers_now()
                return self.regs.get(address, 0)
        peripheral = self._peripheral(address)
        if peripheral is not None:
            self._tick_timers_now()
            return peripheral.read(address - peripheral.base)
        self._unsupported(address, False)

    def _scs_read(self, address):
        if address == 0xE000ED04:
            top = self.active[-1][0] + 16 if self.active else 0
            pending = self._best_pending()
            return (self.regs.get(address, 0) | top | (int(len(self.active) <= 1) << 11)
                    | ((pending + 16 if pending is not None else 0) << 12)
                    | (int(bool(self.pending_irq & self.enabled_irq)) << 22)
                    | (int(bool(self.pending_system & (1 << 15))) << 26)
                    | (int(bool(self.pending_system & (1 << 14))) << 28))
        bank = (address & 0x7F) // 4
        if 0xE000E100 <= address < 0xE000E120 or 0xE000E180 <= address < 0xE000E1A0:
            return (self.enabled_irq >> (32 * bank)) & 0xFFFFFFFF
        if 0xE000E200 <= address < 0xE000E220 or 0xE000E280 <= address < 0xE000E2A0:
            return (self.pending_irq >> (32 * bank)) & 0xFFFFFFFF
        if 0xE000E300 <= address < 0xE000E320:
            active = sum(1 << irq for irq, _ in self.active if irq >= 0)
            return (active >> (32 * bank)) & 0xFFFFFFFF
        if address == 0xE000ED00:
            return 0x410FC231
        if address == 0xE000ED0C:
            return 0xFA050000 | (self.regs.get(address, 0) & 0x700)
        if address == 0xE000E004:
            return 1  # ICTR: up to 64 interrupt lines
        if address == 0xE0001004:
            return (self._cycles() -self._dwt_base) & 0xFFFFFFFF if self.regs.get(0xE0001000, 0) & 1 \
                else self.regs.get(address, 0)
        if (address in (0xE000E008, 0xE000ED08, 0xE000ED10, 0xE000ED14, 0xE000EDFC, 0xE0001000)
                or 0xE000E400 <= address <= 0xE000E420 or 0xE000ED18 <= address <= 0xE000ED3C):
            return self.regs.get(address, 0)
        if 0xE000ED40 <= address <= 0xE000ED8C:
            return 0  # feature/ID registers and CPACR (no FPU)
        return None

    def _gpioint_read(self, off):
        g = self.gpioint
        values = {0: int(bool(g['sr0'] | g['sf0'])) | (int(bool(g['sr2'] | g['sf2'])) << 2),
                  4: g['sr0'], 8: g['sf0'], 0x10: g['r0'], 0x14: g['f0'],
                  0x24: g['sr2'], 0x28: g['sf2'], 0x30: g['r2'], 0x34: g['f2']}
        if off not in values:
            self._unsupported(self.GPIOINT + off, False)
        return values[off]

    @staticmethod
    def _sc_offsets():
        return {0,0x80,0x84,0x88,0x8C,0xA0,0xA4,0xA8,0xAC,0xC0,0xC4,0x104,
                0x108,0x10C,0x110,0x118,0x140,0x148,0x14C,0x180,0x184,0x188,
                0x1A0,0x1A8,0x1AC,0x1B0,0x1B8,0x1C0,0x1C4,0x1C8}

    # -- register writes --------------------------------------------------------
    def write_word(self, address, value, mask=0xFFFFFFFF):
        value &= mask
        def store():
            self.regs[address] = ((self.regs.get(address, 0) & ~mask) | value) & 0xFFFFFFFF
        ga = self._gpio_addr(address)
        if ga:
            p,r = ga
            g = self.gpio[p]
            if r == 0:
                g.direction = (g.direction & ~mask) | value
            elif r == 0x10:
                g.mask = (g.mask & ~mask) | value
            else:
                bits = mask & ~g.mask
                if r == 0x14:
                    g.latch = (g.latch & ~bits) | (value & bits)
                elif r == 0x18:
                    g.latch |= value & bits
                else:
                    g.latch &= ~(value & bits)
                self.gpio_events += 1
            self.observe()
            return
        if self.PIN <= address <= self.PIN+0x7C:
            store()
            self.observe()
            return
        if self.SC <= address <= self.SC+0x1C8 and address-self.SC in self._sc_offsets():
            self._tick_adc_now()
            # Account the preceding interval at the old clock/power settings
            # in both wall-clock and deterministic execution modes.
            self._tick_timers_now()
            if address == self.SC+0x140:
                self.regs[address] = self.regs.get(address, 0) & ~value
            else:
                store()
            self._clock_bookkeeping(address - self.SC, value)
            self.observe()
            return
        if address in (self.ADC,self.ADC+0xC,self.ADC+0x34):
            self.adc.write(address - self.ADC, value, mask)
            return
        if self.GPIOINT <= address <= self.GPIOINT + 0x34:
            self._gpioint_write(address - self.GPIOINT, value)
            return
        if 0xE000E010 <= address <= 0xE000E01C:
            self._tick_timers_now()
            self.systick.write(address - 0xE000E010, value, mask)
            return
        if (0xE000E000 <= address < 0xE000F000 or 0xE0001000 <= address < 0xE0002000) \
                and self._scs_write(address, value, mask, store):
            return
        for base in (*self.TIMERS, self.PWM):
            if base <= address <= base + (0x74 if base == self.PWM else 0x70):
                off = address-base
                if off not in self._timer_offsets(base):
                    break
                if off in (0x2C, 0x30) and base != self.PWM:
                    return  # capture registers are read-only
                self._tick_timers_now()
                previous_tcr = self.regs.get(base+4, 0)
                if off == 0:
                    self.regs[address] = self.regs.get(address, 0) & ~value
                else:
                    store()
                if off == 4 and value & 2:
                    self.regs[base+8] = int(base == self.PWM and bool(value & 8))
                    self.regs[base+0x10] = 0
                    self.timer_fraction[base] = 0
                    self.pclk_fraction[base] = 0
                if base == self.PWM:
                    if off == 4 and value & 8 and not previous_tcr & 8:
                        self.regs[base+8] = max(1, self.regs.get(base+8, 0))
                    # Match registers are direct in timer mode and shadowed in
                    # PWM mode. LER arms transfer at the next MR0 boundary.
                    if off in self._pwm_match_offsets() and not self.regs.get(base+4, 0) & 8:
                        channel = self._pwm_match_offsets().index(off)
                        self.pwm_latched[channel] = self.regs[address]
                if off == 0x3C or base == self.PWM and off == 0x4C:
                    self.observe()
                return
        peripheral = self._peripheral(address)
        if peripheral is not None:
            self._tick_timers_now()
            peripheral.write(address - peripheral.base, value, mask)
            return
        self._unsupported(address, True)

    def _scs_write(self, address, value, mask, store):
        bank = (address & 0x7F) // 4
        if 0xE000E100 <= address < 0xE000E120:
            self.enabled_irq |= value << (32 * bank)
        elif 0xE000E180 <= address < 0xE000E1A0:
            self.enabled_irq &= ~(value << (32 * bank))
        elif 0xE000E200 <= address < 0xE000E220:
            self.pending_irq |= value << (32 * bank)
        elif 0xE000E280 <= address < 0xE000E2A0:
            self.pending_irq &= ~(value << (32 * bank))
        elif address == 0xE000EF00:
            self.pending_irq |= 1 << (value & 0x1FF)  # STIR
        elif address == 0xE000ED04:
            if value & (1 << 25):
                self.pending_system &= ~(1 << 15)
            if value & (1 << 26):
                self.pending_system |= 1 << 15
            if value & (1 << 27):
                self.pending_system &= ~(1 << 14)
            if value & (1 << 28):
                self.pending_system |= 1 << 14
        elif address == 0xE000ED0C:
            # AIRCR writes need VECTKEY 0x05FA in the upper halfword.
            if mask & 0xFFFF0000 == 0xFFFF0000 and value >> 16 == 0x05FA:
                self.regs[address] = value & 0x700
                if value & 4:
                    self.request_reset('Software reset requested through SCB->AIRCR (NVIC_SystemReset).')
        elif address == 0xE0001004:
            self._dwt_base = (self._cycles() -value) & 0xFFFFFFFF
            store()
        elif address == 0xE000ED28 or address == 0xE000ED2C:
            self.regs[address] = self.regs.get(address, 0) & ~value  # write-one-to-clear fault status
        elif (address in (0xE000E008, 0xE000ED08, 0xE000ED10, 0xE000ED14, 0xE000EDFC, 0xE0001000)
              or 0xE000E400 <= address <= 0xE000E420 or 0xE000ED18 <= address <= 0xE000ED3C):
            if address == 0xE0001000 and value & 1 and not self.regs.get(address, 0) & 1:
                self._dwt_base = (self._cycles() -self.regs.get(0xE0001004, 0)) & 0xFFFFFFFF
            store()
        else:
            return False
        return True

    def _gpioint_write(self, off, value):
        g = self.gpioint
        if off == 0xC:
            g['sr0'] &= ~value
            g['sf0'] &= ~value
        elif off == 0x2C:
            g['sr2'] &= ~value
            g['sf2'] &= ~value
        elif off in (0x10, 0x14, 0x30, 0x34):
            g[{0x10: 'r0', 0x14: 'f0', 0x30: 'r2', 0x34: 'f2'}[off]] = value
            self._last_pads = None
            self.observe()
        else:
            self._unsupported(self.GPIOINT + off, True)

    def _clock_bookkeeping(self, off, value):
        """Track the PLL0 feed protocol and report clock settings real silicon rejects."""
        if off in (0x80, 0x84):
            self._pll_unfed = True
        elif off == 0x8C:
            byte = value & 0xFF
            if byte == 0xAA:
                self._pll_feed = 1
            elif byte == 0x55 and self._pll_feed == 1:
                self._pll_unfed = False
                self._pll_feed = 0
            else:
                self._pll_feed = 0
        if off not in (0x80, 0x84, 0x8C, 0x104, 0x10C):
            return
        pll = self.regs.get(self.SC + 0x84, 0)
        control = self.regs.get(self.SC + 0x80, 0) & 3
        if control and self._pll_unfed:
            self.note('clock:feed', 'PLL0CON/PLL0CFG changed without the 0xAA, 0x55 PLL0FEED sequence. '
                      'Real hardware ignores unfed PLL changes; the simulator applies them anyway.')
        elif not self._pll_unfed:
            self.notes.pop('clock:feed', None)
        if control & 1:
            source = self.regs.get(self.SC + 0x10C, 0) & 3
            oscillator = {0: 4_000_000, 1: 12_000_000, 2: 32_768}.get(source, 4_000_000)
            fcco = oscillator * 2 * ((pll & 0x7FFF) + 1) // (((pll >> 16) & 255) + 1)
            if not 275_000_000 <= fcco <= 550_000_000:
                self.note('clock:fcco', f'PLL0 output (FCCO) would be {fcco / 1e6:.1f} MHz; it must be '
                          '275–550 MHz. Adjust MSEL/NSEL in PLL0CFG.')
            else:
                self.notes.pop('clock:fcco', None)
        cclk = self.core_clock_hz()
        if cclk > 100_000_000:
            self.note('clock:cclk', f'CPU clock is {cclk / 1e6:.0f} MHz, above the LPC1768 maximum of '
                      '100 MHz. Increase CCLKCFG (divider) before connecting the PLL.')
        else:
            self.notes.pop('clock:cclk', None)

    @staticmethod
    def _timer_offsets(base):
        common = {0,4,8,0xC,0x10,0x14,0x18,0x1C,0x20,0x24,0x28,0x2C,0x30,0x34,0x38,0x3C}
        return common | ({0x40,0x44,0x48,0x4C,0x50,0x70} if base == Machine.PWM else {0x70})

    # -- time ----------------------------------------------------------------------
    def _tick_adc_now(self):
        self.adc.sync()

    def resume_clock(self):
        if self.realtime and self._clock_anchor is None:
            self._clock_anchor = self._clock_ns()

    def pause_clock(self):
        if self.realtime:
            self._tick_timers_now()
            self._tick_adc_now()
            self._clock_anchor = None

    def time_ns(self):
        """Current simulated time, in the clock domain of scheduled events."""
        if not self.realtime:
            if not self._ticking:
                self._sync_virtual()
            return self.virtual_ns
        return self.elapsed_ns + (max(0, self._clock_ns() - self._clock_anchor)
                                  if self._clock_anchor is not None and not self._ticking else 0)

    def _cycles(self):
        """Core clock cycles for DWT->CYCCNT: elapsed live, or instruction ticks offline."""
        if self.realtime:
            self._tick_timers_now()
            return self.core_cycles
        return self.ticks

    def schedule_at(self, t_ns, callback):
        heapq.heappush(self._events, (int(t_ns), next(self._event_seq), callback))

    def schedule_in(self, delay_ns, callback):
        self.schedule_at(self.time_ns() + max(0, int(delay_ns)), callback)

    def core_clock_hz(self):
        regs, sc = self.regs, self.SC
        key = (regs.get(sc + 0x10C, 0), regs.get(sc + 0x104, 0), regs.get(sc + 0x80, 0), regs.get(sc + 0x84, 0))
        if key != self._cclk_key:
            self._cclk_key, self._cclk = key, self._compute_core_clock()
        return self._cclk

    def _compute_core_clock(self):
        source = self.regs.get(self.SC + 0x10C, 0) & 3
        oscillator = {0: 4_000_000, 1: 12_000_000, 2: 32_768}.get(source, 4_000_000)
        divider = (self.regs.get(self.SC + 0x104, 0) & 255) + 1
        if self.regs.get(self.SC + 0x80, 0) & 3 == 3:
            pll = self.regs.get(self.SC + 0x84, 0)
            multiplier = (pll & 0x7FFF) + 1
            predivider = ((pll >> 16) & 255) + 1
            return oscillator * 2 * multiplier // (predivider * divider)
        return oscillator // divider

    def peripheral_clock_hz(self, base):
        register, shift = {
            0x40004000: (0x1A8, 2), 0x40008000: (0x1A8, 4),
            0x40090000: (0x1AC, 12), 0x40094000: (0x1AC, 14),
            self.PWM: (0x1A8, 12),
        }[base]
        selection = (self.regs.get(self.SC + register, 0) >> shift) & 3
        return self.core_clock_hz() // (4, 1, 2, 8)[selection]

    def _timer_running(self, base):
        power = 6 if base == self.PWM else self.TIMERS[base][1]
        tcr = self.regs.get(base + 4, 0)
        return bool(self.regs.get(self.SC + 0xC4, 0) & (1 << power)
                    and tcr & 1 and not tcr & 2
                    and not self.regs.get(base + 0x70, 0) & 3)

    def _tick_timers_now(self):
        if self._ticking:
            return
        self._ticking = True
        try:
            if self.realtime:
                if self._clock_anchor is None:
                    return
                now = self._clock_ns()
                target = self.elapsed_ns + max(0, now - self._clock_anchor)
                self._clock_anchor = now
                # Scheduled device events fire at their own instant, after the
                # counters have advanced exactly to it.
                while self._events and self._events[0][0] <= target:
                    moment = self._events[0][0]
                    if moment > self.elapsed_ns:
                        self._advance_live(moment - self.elapsed_ns)
                    heapq.heappop(self._events)[2]()
                if target > self.elapsed_ns:
                    self._advance_live(target - self.elapsed_ns)
            else:
                self.systick.advance(self.ticks - self.systick_last_tick)
                self.systick_last_tick = self.ticks
                delta = self.ticks - self.last_timer_tick
                if delta:
                    self._advance_timers(delta)
                    self.last_timer_tick = self.ticks
                # Virtual nanoseconds only matter to scheduled events and the
                # timekeeping peripherals; idle programs skip the conversion.
                if self._events or self.wdt.started or self.rtc.ccr & 1 or (
                        self.rit.ctrl & 8 and self.regs.get(self.SC + 0xC4, 0) & 0x10000):
                    self._sync_virtual()
        finally:
            self._ticking = False

    def _sync_virtual(self):
        ticks = self.ticks - self._virtual_tick
        if not ticks:
            return
        self._virtual_tick = self.ticks
        total = self._virtual_fraction + ticks * 1_000_000_000
        ns, self._virtual_fraction = divmod(total, max(1, self.core_clock_hz()))
        target = self.virtual_ns + ns
        while self._events and self._events[0][0] <= target:
            moment = max(self.virtual_ns, self._events[0][0])
            self._advance_peripherals(moment - self.virtual_ns)
            self.virtual_ns = moment
            heapq.heappop(self._events)[2]()
        self._advance_peripherals(target - self.virtual_ns)
        self.virtual_ns = target

    def _advance_live(self, delta):
        self.elapsed_ns += delta
        total = self.systick_fraction + delta * self.core_clock_hz()
        core_ticks, self.systick_fraction = divmod(total, 1_000_000_000)
        self.core_cycles += core_ticks
        self.systick.advance(core_ticks)
        for base in (*self.TIMERS, self.PWM):
            if not delta or not self._timer_running(base):
                continue
            total = self.pclk_fraction.get(base, 0) + delta * self.peripheral_clock_hz(base)
            clocks, self.pclk_fraction[base] = divmod(total, 1_000_000_000)
            self._advance_prescaler(base, clocks)
        self._advance_peripherals(delta)

    def _advance_peripherals(self, delta_ns):
        # Hot path: skip the idle timekeepers without method calls.
        if delta_ns <= 0:
            return
        if self.rit.ctrl & 8 and self.regs.get(self.SC + 0xC4, 0) & (1 << 16):
            self.rit.advance(delta_ns)
        if self.wdt.started:
            self.wdt.advance(delta_ns)
        if self.rtc.ccr & 1:
            self.rtc.advance(delta_ns)

    def _advance_prescaler(self, base, clocks):
        pc = self.regs.get(base + 0x10, 0)
        pr = self.regs.get(base + 0xC, 0)
        steps = 0
        if pc > pr:
            # Lowering PR or writing PC does not reinterpret past clocks. PC
            # must wrap and reach equality with PR before the next TC increment.
            until_reset = ((pr - pc) & 0xFFFFFFFF) + 1
            if clocks < until_reset:
                self.regs[base + 0x10] = (pc + clocks) & 0xFFFFFFFF
                return
            clocks -= until_reset
            steps, pc = 1, 0
        additional, self.regs[base + 0x10] = divmod(pc + clocks, pr + 1)
        self._advance_counter(base, steps + additional)

    def _advance_timers(self, delta):
        regs = self.regs
        for base in (*self.TIMERS, self.PWM):
            # Cheap TCR test first: this runs on every translated block.
            if regs.get(base + 4, 0) & 3 != 1 or not self._timer_running(base):
                continue
            # Offline ticks represent deterministic core-clock progress. The
            # same PCLK selection and readable PR/PC prescaler still apply.
            divider = max(1, self.core_clock_hz() // self.peripheral_clock_hz(base))
            count = self.timer_fraction.get(base,0) + delta
            clocks, self.timer_fraction[base] = divmod(count, divider)
            self._advance_prescaler(base, clocks)

    def _external_match(self, base, channel):
        """EMR action for a timer match, UM10360 table 433."""
        emr = self.regs.get(base + 0x3C, 0)
        action = (emr >> (4 + 2 * channel)) & 3
        if not action:
            return False
        bit = 1 << channel
        emr = emr & ~bit if action == 1 else emr | bit if action == 2 else emr ^ bit
        self.regs[base + 0x3C] = emr
        return True

    def _advance_counter(self, base, steps):
        if not steps:
            return
        irq = 9 if base == self.PWM else self.TIMERS[base][0]
        counter = self.regs.get(base+8,0)
        mcr = self.regs.get(base+0x14,0)
        pwm_mode = base == self.PWM and bool(self.regs.get(base+4, 0) & 8)
        if pwm_mode:
            # PWM holds TC=1..MR0, unlike Timer mode's zero-based count.
            # Work in elapsed cycle phase internally; Table447 resets TC to1.
            # Match actions occur on the edge after the held matching value,
            # so MR0 still specifies MR0 clocks rather than MR0-1 clocks.
            counter = (counter - 1) & 0xFFFFFFFF
        offsets = self._pwm_match_offsets() if base == self.PWM else (0x18,0x1C,0x20,0x24)
        emr = 0 if base == self.PWM else self.regs.get(base + 0x3C, 0) & 0xFF0

        def configured_matches():
            return [(self.pwm_latched[i] if pwm_mode else self.regs.get(base+off,0),
                     (mcr>>(3*i))&7, i) for i,off in enumerate(offsets)
                    if (mcr>>(3*i))&7 or (pwm_mode and i == 0) or emr >> (4 + 2*i) & 3]

        matches = configured_matches()
        pins_changed = False
        while steps:
            distances=[(((match-counter)&0xFFFFFFFF) or 0x100000000,action,i)
                       for match,action,i in matches]
            distance=min((d for d,_,_ in distances),default=steps+1)
            if distance>steps:
                counter=(counter+steps)&0xFFFFFFFF
                break
            counter=(counter+distance)&0xFFFFFFFF
            steps-=distance
            reset=stop=False
            for d,action,i in distances:
                if d!=distance:
                    continue
                if action&1:
                    self.regs[base]=self.regs.get(base,0)|(1<<self._match_ir_bit(base, i))
                    self.pending_irq|=1<<irq
                if emr:
                    pins_changed |= self._external_match(base, i)
                reset|=bool(action&2)
                stop|=bool(action&4)
                if pwm_mode and i == 0:
                    self._latch_pwm()
                    matches = configured_matches()
            if reset:
                counter=0
            if stop:
                self.regs[base+4]&=~1
                self.regs[base+0x10] = 0
                self.pclk_fraction[base] = 0
                self.timer_fraction[base] = 0
                break
            # IR flags latch rather than queue. Batch whole reset periods after
            # a host stall so a fast PWM cannot cause millions of Python loops.
            # EMR toggles depend on the parity of skipped periods, so keep it.
            if reset:
                period = min((v for v, action, _ in matches if action & 2 and v), default=0)
                stop_in_period = any(0 < v <= period and action & 4 for v, action, _ in matches)
                if period and not stop_in_period and steps >= period:
                    skipped = steps // period
                    for match, action, i in matches:
                        if 0 < match <= period and action & 1:
                            self.regs[base] = self.regs.get(base, 0) | (1 << self._match_ir_bit(base, i))
                            self.pending_irq |= 1 << irq
                        if emr and 0 < match <= period and (emr >> (4 + 2*i)) & 3 == 3 and skipped & 1:
                            self.regs[base + 0x3C] ^= 1 << i
                    steps %= period
        self.regs[base+8] = (counter + int(pwm_mode)) & 0xFFFFFFFF
        if pins_changed:
            self._pins_dirty = True

    @staticmethod
    def _pwm_match_offsets():
        return (0x18, 0x1C, 0x20, 0x24, 0x40, 0x44, 0x48)

    @staticmethod
    def _match_ir_bit(base, channel):
        return channel + 4 if base == Machine.PWM and channel >= 4 else channel

    def _latch_pwm(self):
        enabled = self.regs.get(self.PWM + 0x50, 0)
        for channel, offset in enumerate(self._pwm_match_offsets()):
            if enabled & (1 << channel):
                self.pwm_latched[channel] = self.regs.get(self.PWM + offset, 0)
        self.regs[self.PWM + 0x50] = 0

    def _pwm_counting(self):
        tcr = self.regs.get(self.PWM + 4, 0)
        return bool(self.regs.get(self.SC + 0xC4, 0) & (1 << 6) and tcr & 9 == 9
                    and not tcr & 2 and not self.regs.get(self.PWM + 0x70, 0) & 3)

    def _pwm_channel_enabled(self, channel):
        return self._pwm_counting() and bool(self.regs.get(self.PWM + 0x4C, 0) & (1 << (8 + channel)))

    def _pwm_enabled(self):
        return bool(self.function(1, 23) == 2 and self._pwm_channel_enabled(4)
                    and not self.regs.get(self.PWM + 0x4C, 0) & (1 << 4))

    def pwm_level(self, channel=4):
        """Instantaneous PWM1.n electrical output (not brightness)."""
        self._tick_timers_now()
        if not self._pwm_channel_enabled(channel):
            return None
        phase = (self.regs.get(self.PWM+8, 0) - 1) & 0xFFFFFFFF
        if channel >= 2 and self.regs.get(self.PWM + 0x4C, 0) & (1 << channel):
            # Double edge: set by MR(n-1), reset by MR(n), UM10360 table 445.
            start, stop = self.pwm_latched[channel - 1], self.pwm_latched[channel]
            return int(start <= phase < stop) if start <= stop else int(not stop <= phase < start)
        return int(phase < self.pwm_latched[channel])

    def pwm_duty(self, channel=4, pad=(1, 23)):
        self._tick_timers_now()
        good = self._pwm_channel_enabled(channel) and self.function(*pad) == (
            pins.FUNCTIONS[pad].index(f'PWM1.{channel}') if pad in pins.FUNCTIONS
            and f'PWM1.{channel}' in pins.FUNCTIONS[pad] else -1)
        double = channel >= 2 and self.regs.get(self.PWM + 0x4C, 0) & (1 << channel)
        if channel == 4 and pad == (1, 23):
            good = self._pwm_enabled()
        # An open-drain pad cannot source current into a grounded load.
        if self.regs.get(self.PIN + 0x68 + pad[0] * 4, 0) & (1 << pad[1]):
            return 0.0
        top = self.pwm_latched[0]
        periodic = bool(top and self.regs.get(self.PWM+0x14, 0) & 2)
        if not good:
            return 0.0
        if not periodic:
            return float(self.pwm_level(channel) or 0)
        if double:
            start, stop = self.pwm_latched[channel - 1], self.pwm_latched[channel]
            return min(1.0, ((stop - start) % top) / top) if start != stop else 0.0
        return min(1.0, self.pwm_latched[channel] / top)

    def pwm_period_ns(self):
        top = self.pwm_latched[0]
        rate = self.peripheral_clock_hz(self.PWM) / (self.regs.get(self.PWM + 0xC, 0) + 1)
        return top * 1e9 / rate if top and rate else None

    # -- exceptions --------------------------------------------------------------
    @property
    def active_irq(self):
        return self.active[-1][0] if self.active else None

    def _priority(self, irq):
        address = 0xE000E400 + irq if irq >= 0 else 0xE000ED18 + irq + 12
        return (self.regs.get(address & ~3, 0) >> (8 * (address & 3))) & 0xF8

    def _group(self, priority):
        prigroup = (self.regs.get(0xE000ED0C, 0) >> 8) & 7
        return priority & (0xFF << (prigroup + 1)) & 0xFF

    def _best_pending(self):
        candidates = [irq for bit, irq in ((15, -1), (14, -2), (11, -5)) if self.pending_system & (1 << bit)]
        pending = self.pending_irq & self.enabled_irq
        while pending:
            low = pending & -pending
            candidates.append(low.bit_length() - 1)
            pending ^= low
        if not candidates:
            return None
        return min(candidates, key=lambda irq: (self._priority(irq), irq))

    def _preempt_ready(self):
        if self.uc.reg_read(UC_ARM_REG_PRIMASK):
            return False
        best = self._best_pending()
        if best is None:
            return False
        if not self.active:
            return True
        running = min(self._group(self._priority(irq)) for irq, _ in self.active)
        return self._group(self._priority(best)) < running

    def _deliver_irq(self):
        if not (self.pending_irq & self.enabled_irq or self.pending_system) or not self._preempt_ready():
            return
        irq = self._best_pending()
        vtor = self.regs.get(0xE000ED08,0) & 0xFFFFFF80
        handler = int.from_bytes(self.uc.mem_read(vtor+(16+irq)*4,4),'little')
        if not handler & 1:
            raise FirmwareError(f'{EXCEPTION_NAMES.get(irq, f"IRQ {irq}")} has no valid Thumb handler in the vector table.')
        regs = [UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,
                UC_ARM_REG_R12,UC_ARM_REG_LR,UC_ARM_REG_PC,UC_ARM_REG_XPSR]
        original_sp = self.uc.reg_read(UC_ARM_REG_SP)
        padding = 4 if self.regs.get(0xE000ED14, 0) & (1 << 9) and original_sp & 4 else 0
        sp = original_sp - 32 - padding
        values = [self.uc.reg_read(r) for r in regs]
        values[-1] = (values[-1] & ~(1 << 9)) | (int(bool(padding)) << 9)
        self.uc.mem_write(sp, struct.pack('<8I', *values))
        self.uc.reg_write(UC_ARM_REG_SP, sp)
        self.uc.reg_write(UC_ARM_REG_LR, 0xFFFFFFF1 if self.active else 0xFFFFFFF9)
        self.uc.reg_write(UC_ARM_REG_XPSR, (self.uc.reg_read(UC_ARM_REG_XPSR) & ~511) | (16+irq))
        self.uc.reg_write(UC_ARM_REG_PC, handler)
        if irq < 0:
            self.pending_system &= ~(1 << (irq + 16))
        else:
            self.pending_irq &= ~(1<<irq)
        self.active.append((irq, sp))
        self.irq_count += 1

    def _refresh_interrupts(self):
        # NVIC pending is cleared on entry, but a peripheral whose flag remains
        # asserted must request service again after exception return.
        self._tick_adc_now()
        self.observe()
        self.pending_irq |= (self.regs.get(self.SC+0x140,0)&15)<<18
        g = self.gpioint
        if g['sr0'] | g['sf0'] | g['sr2'] | g['sf2']:
            self.pending_irq |= 1 << 21
        for base in (*self.TIMERS,self.PWM):
            irq=9 if base==self.PWM else self.TIMERS[base][0]
            ir=self.regs.get(base,0)
            mcr=self.regs.get(base+0x14,0)
            ccr=self.regs.get(base+0x28,0) if base != self.PWM else 0
            if any(ir&(1<<self._match_ir_bit(base, i)) and mcr&(1<<(3*i))
                   for i in range(7 if base == self.PWM else 4)) or \
                    any(ir & (1 << (4 + c)) and ccr & (4 << (3 * c)) for c in range(2)):
                self.pending_irq|=1<<irq
        for peripheral in self.peripherals:
            peripheral.refresh_interrupts()

    def _interrupt(self, uc, intno, _):
        # Unicorn reports ARM exception-return (BX LR to EXC_RETURN) as interrupt 8.
        if intno == 8 and self.active:
            _, sp = self.active[-1]
            vals = struct.unpack('<8I', bytes(uc.mem_read(sp,32)))
            regs = [UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,
                    UC_ARM_REG_R12,UC_ARM_REG_LR,UC_ARM_REG_PC,UC_ARM_REG_XPSR]
            for r,v in zip(regs,vals):
                uc.reg_write(r, v & ~(1 << 9) if r == UC_ARM_REG_XPSR else v)
            uc.reg_write(UC_ARM_REG_SP,sp+32+(4 if vals[-1] & (1 << 9) else 0))
            self.active.pop()
            uc.emu_stop()
        elif intno == 2:
            # SVC: the return address is the following instruction.
            self.pending_system |= 1 << 11
            uc.emu_stop()
        elif intno == 1:
            self._fail(f'UsageFault: undefined instruction at PC 0x{uc.reg_read(UC_ARM_REG_PC):08X}.')
        else:
            self._fail(f'Unsupported CPU exception {intno} at PC 0x{uc.reg_read(UC_ARM_REG_PC):08X}.')

    def invalidate_translations(self):
        # Native Unicorn does not retrofit newly added hooks into translated
        # loops. The WASM bridge instruments blocks from its first execution
        # and has no ctl_remove_cache API.
        invalidate = getattr(self.uc, 'ctl_remove_cache', None)
        if invalidate is not None:
            for start, end in ((0, self.FLASH_SIZE), (0x10000000, 0x10008000),
                               (0x2007C000, 0x20084000)):
                invalidate(start, end)

    def run(self, instructions=20000, *, timeout_us=None, until=None, fast=False):
        if self.error:
            raise FirmwareError(self.error)
        if timeout_us is None:
            # Offline instruction budgets must not be shortened by host load.
            # The live Runtime supplies its own short responsiveness deadline.
            timeout_us = 100_000 if self.realtime else 0
        try:
            if self._block_hook is None and not fast:
                self._block_hook = self.uc.hook_add(UC_HOOK_BLOCK, self._block)
                self.invalidate_translations()
            self._tick_timers_now()
            self._refresh_interrupts()
            self._deliver_irq()
            pc = self.uc.reg_read(UC_ARM_REG_PC)
            # EXC_RETURN stops Unicorn so we can restore the software frame.
            # In live mode, reserve part of this bounded slice for foreground
            # work after that return. Otherwise a 1 ms SysTick on a slower host
            # can become pending before every slice and starve main forever.
            live_irq = fast and self.realtime and self.active_irq is not None
            first_budget = max(1, instructions // 2) if live_irq else instructions
            self.uc.emu_start(pc | 1, self.FLASH_SIZE if until is None else until,
                              count=first_budget, timeout=timeout_us)
            remaining = instructions - first_budget
            if live_irq and self.active_irq is None and remaining and not self.error:
                pc = self.uc.reg_read(UC_ARM_REG_PC)
                # A retained precise hook still records dwell and pending
                # flags, but may not cancel this reserved foreground budget.
                self._defer_irq_stop = True
                try:
                    self.uc.emu_start(pc | 1, self.FLASH_SIZE if until is None else until,
                                      count=remaining, timeout=timeout_us)
                finally:
                    self._defer_irq_stop = False
            if self._block_hook is None:
                # This is a scheduling budget, not a cycle counter. A timeout
                # or exception return may retire fewer instructions.
                self.ticks += instructions
            self._tick_timers_now()
            self._tick_adc_now()
            if getattr(self, '_pins_dirty', False):
                self._pins_dirty = False
                self.observe()
            if self.error:
                raise FirmwareError(self.error)
        except UcError as e:
            pc = self.uc.reg_read(UC_ARM_REG_PC)
            detail = f'{self.fault} at PC 0x{pc:08X}' if self.fault else \
                f'Firmware execution failed at PC 0x{pc:08X}: {e}'
            self.error = detail
            raise FirmwareError(self.error) from e

    # -- device traffic over the board's nets ------------------------------------
    def deliver_serial(self, pad, byte, baud, bits, parity, stops, source=None):
        """A UART frame leaves `pad`: every receiver on that net gets it."""
        node = f'P{pad[0]}.{pad[1]}'
        for uart in self.uarts:
            rx = uart.pad('RXD')
            if uart is not source and rx and self.board.same_net(node, f'P{rx[0]}.{rx[1]}'):
                uart.receive(byte, baud, bits, parity, stops, sender=source.name if source else 'device')
        for part, pin in self.board.parts_on(node):
            if hasattr(part, 'uart_rx'):
                part.uart_rx(pin, byte, baud, bits, parity, stops)
        terminal = self.terminals.get(getattr(source, 'index', None))
        if terminal is not None and isinstance(source, UART) and terminal.attached(self):
            terminal.receive(byte, baud, bits, parity, stops)

    def send_serial_from_node(self, node, byte, baud, bits=8, parity=False, stops=1, sender='device'):
        """A device on `node` transmits one frame to UARTs whose RXD shares the net."""
        for uart in self.uarts:
            rx = uart.pad('RXD')
            if rx and self.board.same_net(node, f'P{rx[0]}.{rx[1]}'):
                uart.receive(byte, baud, bits, parity, stops, sender=sender)

    def spi_exchange(self, controller, value, bits, mode, hz):
        pads = controller.pads()
        sck, miso = pads.get('SCK'), pads.get('MISO')
        if sck is None:
            controller.note('pins', f'{controller.name} transfers data but no pin is configured as its SCK.')
            return (1 << bits) - 1
        controller.clear_note('pins')
        ssel = pads.get('SSEL')
        replies = []
        for part, pin in self.board.parts_on(f'P{sck[0]}.{sck[1]}'):
            if not hasattr(part, 'spi_transfer') or pin != getattr(part, 'spi_pins', {}).get('SCK'):
                continue
            if not part.spi_selected(ssel):
                continue
            reply = part.spi_transfer(value, bits, mode, hz)
            miso_pin = part.spi_pins.get('MISO')
            if reply is not None and miso_pin and miso and self.board.same_net(
                    f'{part.id}.{miso_pin}', f'P{miso[0]}.{miso[1]}'):
                replies.append(reply)
        if len(replies) > 1:
            controller.note('contention', f'{len(replies)} SPI devices drive MISO at once on '
                            f'{controller.name}; give each its own chip select and keep the others HIGH.')
        result = (1 << bits) - 1
        for reply in replies:
            result &= reply
        return result

    def i2c_devices(self, controller, address):
        sda = self.selected_pad(f'SDA{controller.index}')
        scl = self.selected_pad(f'SCL{controller.index}')
        if sda is None or scl is None:
            return []
        devices = []
        for part, pin in self.board.parts_on(f'P{sda[0]}.{sda[1]}'):
            names = getattr(part, 'i2c_pins', None)
            if not names or pin != names[0]:
                continue
            if self.board.same_net(f'{part.id}.{names[1]}', f'P{scl[0]}.{scl[1]}') \
                    and part.i2c_matches(address) and part.operational():
                devices.append(part)
        return devices

    def bus_released_high(self, *pads):
        return all(self.board.released_level(f'P{port}.{pin}') for port, pin in pads)

    # -- snapshot -------------------------------------------------------------------
    def snapshot(self):
        signals = self.board.signals()
        segments = self.seven.patterns(self.elapsed_ns if self.realtime else self.ticks,
                                      dwell_tick=self.ticks)
        if not (self.board.has_signal_connection('SEG') and self.board.has_signal_connection('DIG')):
            segments = [0]*4
        pwm = 0.0
        for group in self.board.groups():
            if 'PWM_LED' in group:
                pwm = self.pwm_duty() if 'P1.23' in group else float(signals.get('PWM_LED',0))
                if 'P1.23' in group and self.function(1,23) == 0:
                    pwm = float(signals.get('PWM_LED',0))
        return {'leds':[bool(signals.get(f'LED{i}',0)) for i in range(8)],
                'lcd':self.lcd.lines(self.board.jumpers['JP16'] == 'closed'),
                'segments':segments,'pwm':pwm,'cables':self.board.cables[:],
                **self.board.wiring_snapshot(signals),
                'jumpers':dict(self.board.jumpers),'pots':dict(self.board.pots),
                'keys':sorted(self.board.keys),'sw2':self.board.sw2,'sw2Pin':self.board.sw2_pin,
                'ticks':self.ticks,'elapsedSeconds':self.elapsed_ns / 1_000_000_000,
                'simSeconds': self.time_ns() / 1_000_000_000,
                'gpioEvents':self.gpio_events,'lcdEdges':self.lcd.edges,
                'interrupts':self.irq_count,'pc':f'0x{self.uc.reg_read(UC_ARM_REG_PC):08X}',
                'warnings':self.board.warnings[:], 'error':self.error,
                'notes': sorted(self.notes.items()),
                'target': self.board.target,
                'mbedLeds': [bool(signals.get(f'LED_M{i}', 0)) for i in range(1, 5)],
                'circuit': self.board.circuit_snapshot(),
                'peripherals': {p.name: s for p in self.peripherals if (s := p.snapshot()) is not None},
                'terminals': {str(k): t.snapshot() for k, t in self.terminals.items()},
                'gpio':[{'direction':f'0x{g.direction:08X}','latch':f'0x{g.latch:08X}'} for g in self.gpio]}
