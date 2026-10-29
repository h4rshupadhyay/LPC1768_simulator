"""Unicorn Cortex-M3 plus only the LPC1768 register subset used by the labs.

No instruction decoding: Unicorn executes all ARM/Thumb instructions. MMIO
callbacks see every peripheral access. Live peripherals use elapsed monotonic time;
offline probes can use deterministic instruction-derived time.
"""
from __future__ import annotations
from dataclasses import dataclass
from io import StringIO
import struct
import time

from intelhex import IntelHex
from unicorn import (Uc, UcError, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS,
                     UC_HOOK_BLOCK, UC_HOOK_INTR)
from unicorn.arm_const import (UC_ARM_REG_SP, UC_ARM_REG_PC, UC_ARM_REG_LR,
    UC_ARM_REG_XPSR, UC_ARM_REG_PRIMASK, UC_ARM_REG_R0, UC_ARM_REG_R1,
    UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R12, UC_ARM_REG_IPSR)

from .board import Board
from .displays import LCD, SevenSegment
from .adc import ADCPeripheral
from .systick import SysTick


class FirmwareError(ValueError):
    pass


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
    TIMERS = {0x40004000: (1, 1), 0x40008000: (2, 2),
              0x40090000: (3, 22), 0x40094000: (4, 23)}

    def __init__(self, hex_text: str, *, realtime=False, clock_ns=None):
        self.hex_text = hex_text
        self.realtime = realtime
        self._clock_ns = clock_ns or time.perf_counter_ns
        self._clock_anchor = None
        self.elapsed_ns = 0
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
        self.lcd = LCD()
        self.seven = SevenSegment(window=50_000_000 if realtime else 300_000)
        self.enabled_irq = 0
        self.pending_irq = 0
        self.pending_system = 0
        self.active_irq = None
        self.irq_frame = None
        self._defer_irq_stop = False
        self.last_timer_tick = 0
        self.timer_fraction = {}
        self.adc_last = [0] * 8
        self.adc_global = 0
        self.pwm_latched = {i: 0 for i in range(7)}
        self.board = Board(self)
        self.adc = ADCPeripheral(self)
        self.systick = SysTick(self)
        self.systick_last_tick = 0
        self.systick_fraction = 0
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        self.uc.mem_map(0, self.FLASH_SIZE)
        self.uc.mem_map(0x10000000, 0x8000)
        self.uc.mem_map(0x2007C000, 0x8000)
        for start, data in self.segments:
            self.uc.mem_write(start, data)
        for base, size in [(0x40000000, 0x100000), (0x2009C000, 0x1000), (0xE000E000, 0x2000)]:
            self.uc.mmio_map(base, size, self._read, base, self._write, base)
        # Deterministic probes count every translated block. Live execution
        # can synchronize wall-clock peripherals at MMIO and bounded slices,
        # avoiding a Python callback on every iteration of a pure delay loop.
        self._block_hook = None
        if not self.realtime:
            self._block_hook = self.uc.hook_add(UC_HOOK_BLOCK, self._block)
        self.uc.hook_add(UC_HOOK_INTR, self._interrupt)
        self.uc.reg_write(UC_ARM_REG_SP, self.initial_sp)
        self.uc.reg_write(UC_ARM_REG_PC, self.entry)
        self.uc.reg_write(UC_ARM_REG_XPSR, 1 << 24)
        self._last_switch = 1
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

    def _fail(self, message):
        if self.error is None:
            self.error = message
        self.uc.emu_stop()

    def _block(self, uc, address, size, _):
        self.ticks += max(1, size // 2)
        self._tick_adc_now()
        self._tick_timers_now()
        # IRQs are delivered only between emulator slices. No nested interrupts.
        if not self._defer_irq_stop and (self.pending_system or self.pending_irq & self.enabled_irq) and self.active_irq is None and not uc.reg_read(UC_ARM_REG_PRIMASK):
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

    def function(self, port, pin):
        index = port * 2 + pin // 16
        return (self.regs.get(self.PIN + index * 4, 0) >> (2 * (pin % 16))) & 3

    def pin_pull(self, port, pin):
        index = port * 2 + pin // 16
        mode = (self.regs.get(self.PIN + 0x40 + index * 4, 0) >> (2 * (pin % 16))) & 3
        return 1 if mode == 0 else 0 if mode == 3 else None

    def pin_output(self, port, pin):
        if (port, pin) == (1, 23) and self.function(port, pin) == 2:
            level = self.pwm_level()
        elif self.function(port, pin) == 0 and self.gpio[port].direction & (1 << pin):
            level = int(bool(self.gpio[port].latch & (1 << pin)))
        else:
            return None
        if (self.regs.get(self.PIN + 0x68 + port * 4, 0) & (1 << pin)
                and level == 1):
            return None
        return level

    def gpio_value(self, port):
        g = self.gpio[port]
        external_mask, external_value = self.board.sampled_gpio(port)
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
        if port == 1 and self.function(1, 23) == 2:
            pwm = self.pin_output(1, 23)
            if pwm is not None:
                value = (value & ~(1 << 23)) | (pwm << 23)
        value = (value & ~external_mask) | external_value
        return value & ~g.mask & 0xFFFFFFFF

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
        switch = signals.get('SW2', 1)
        if hasattr(self, '_last_switch'):
            self._external_interrupt(switch)
        self._last_switch = switch

    def _external_interrupt(self, level):
        for group in self.board.groups():
            if 'SW2' not in group:
                continue
            for n in range(4):
                if f'P2.{10+n}' not in group or self.function(2, 10+n) != 1:
                    continue
                polarity = (self.regs.get(self.SC+0x14C, 0) >> n) & 1
                edge = bool(self.regs.get(self.SC+0x148, 0) & (1 << n))
                trigger = level == polarity and (not edge or level != self._last_switch)
                if trigger:
                    self.regs[self.SC+0x140] = self.regs.get(self.SC+0x140, 0) | (1 << n)
                    self.pending_irq |= 1 << (18+n)

    def _gpio_addr(self, address):
        off = address - 0x2009C000
        port, reg = divmod(off, 0x20)
        return (port, reg) if 0 <= port < 5 and reg in (0, 0x10, 0x14, 0x18, 0x1C) else None

    def read_word(self, address):
        gaddr = self._gpio_addr(address)
        if gaddr:
            p, r = gaddr
            g = self.gpio[p]
            return {0: g.direction, 0x10: g.mask, 0x14: lambda: self.gpio_value(p),
                    0x18: g.latch, 0x1C: 0}[r]() if r == 0x14 else {0:g.direction,0x10:g.mask,0x18:g.latch,0x1C:0}[r]
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
        if 0xE000E010 <= address <= 0xE000E01C:
            self._tick_timers_now()
            return self.systick.read(address - 0xE000E010)
        if address == 0xE000ED04:
            return self.regs.get(address, 0) | (int(bool(self.pending_system & (1 << 15))) << 26)
        if address == 0xE000E100 or address == 0xE000E180:
            return self.enabled_irq
        if address in (0xE000E200,0xE000E280):
            return self.pending_irq
        if address == 0xE000E300:
            return 0 if self.active_irq is None or self.active_irq < 0 else 1 << self.active_irq
        if address == 0xE000ED00:
            return 0x410FC231
        if address in (0xE000ED04,0xE000ED08,0xE000ED0C,0xE000ED10,0xE000ED14) or 0xE000E400 <= address <= 0xE000E420:
            return self.regs.get(address, 0)
        for base in (*self.TIMERS, self.PWM):
            if base <= address <= base + (0x74 if base == self.PWM else 0x70):
                if address-base not in self._timer_offsets(base):
                    break
                self._tick_timers_now()
                return self.regs.get(address, 0)
        raise FirmwareError(f'Unsupported register read at 0x{address:08X}.')

    @staticmethod
    def _sc_offsets():
        return {0,0x80,0x84,0x88,0x8C,0xA0,0xA4,0xA8,0xAC,0xC0,0xC4,0x104,
                0x108,0x10C,0x110,0x118,0x140,0x148,0x14C,0x180,0x184,0x188,
                0x1A0,0x1A8,0x1AC,0x1B0,0x1B8,0x1C0,0x1C4,0x1C8}

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
            self.observe()
            return
        if address in (self.ADC,self.ADC+0xC,self.ADC+0x34):
            self.adc.write(address - self.ADC, value, mask)
            return
        if 0xE000E010 <= address <= 0xE000E01C:
            self._tick_timers_now()
            self.systick.write(address - 0xE000E010, value, mask)
            return
        if address == 0xE000ED04:
            if value & (1 << 25):
                self.pending_system &= ~(1 << 15)
            if value & (1 << 26):
                self.pending_system |= 1 << 15
            return
        if address == 0xE000E100:
            self.enabled_irq |= value
            return
        if address == 0xE000E180:
            self.enabled_irq &= ~value
            return
        if address == 0xE000E200:
            self.pending_irq |= value
            return
        if address == 0xE000E280:
            self.pending_irq &= ~value
            return
        if address in (0xE000ED08,0xE000ED0C,0xE000ED10,0xE000ED14) or 0xE000E400 <= address <= 0xE000E420:
            store()
            return
        for base in (*self.TIMERS, self.PWM):
            if base <= address <= base + (0x74 if base == self.PWM else 0x70):
                off = address-base
                if off not in self._timer_offsets(base):
                    break
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
                return
        raise FirmwareError(f'Unsupported register write at 0x{address:08X}.')

    @staticmethod
    def _timer_offsets(base):
        common = {0,4,8,0xC,0x10,0x14,0x18,0x1C,0x20,0x24,0x28,0x2C,0x30,0x34,0x38,0x3C}
        return common | ({0x40,0x44,0x48,0x4C,0x50,0x70} if base == Machine.PWM else {0x70})

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

    def core_clock_hz(self):
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
        if self.realtime:
            if self._clock_anchor is None:
                return
            now = self._clock_ns()
            delta = max(0, now - self._clock_anchor)
            self._clock_anchor = now
            self.elapsed_ns += delta
            total = self.systick_fraction + delta * self.core_clock_hz()
            core_ticks, self.systick_fraction = divmod(total, 1_000_000_000)
            self.systick.advance(core_ticks)
            for base in (*self.TIMERS, self.PWM):
                if not delta or not self._timer_running(base):
                    continue
                total = self.pclk_fraction.get(base, 0) + delta * self.peripheral_clock_hz(base)
                clocks, self.pclk_fraction[base] = divmod(total, 1_000_000_000)
                self._advance_prescaler(base, clocks)
        else:
            self.systick.advance(self.ticks - self.systick_last_tick)
            self.systick_last_tick = self.ticks
            delta = self.ticks - self.last_timer_tick
            if delta:
                self._advance_timers(delta)
                self.last_timer_tick = self.ticks

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
        for base in (*self.TIMERS, self.PWM):
            if not self._timer_running(base):
                continue
            # Offline ticks represent deterministic core-clock progress. The
            # same PCLK selection and readable PR/PC prescaler still apply.
            divider = max(1, self.core_clock_hz() // self.peripheral_clock_hz(base))
            count = self.timer_fraction.get(base,0) + delta
            clocks, self.timer_fraction[base] = divmod(count, divider)
            self._advance_prescaler(base, clocks)

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

        def configured_matches():
            return [(self.pwm_latched[i] if pwm_mode else self.regs.get(base+off,0),
                     (mcr>>(3*i))&7, i) for i,off in enumerate(offsets)
                    if (mcr>>(3*i))&7 or (pwm_mode and i == 0)]

        matches = configured_matches()
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
            if reset:
                period = min((v for v, action, _ in matches if action & 2 and v), default=0)
                stop_in_period = any(0 < v <= period and action & 4 for v, action, _ in matches)
                if period and not stop_in_period and steps >= period:
                    for match, action, i in matches:
                        if 0 < match <= period and action & 1:
                            self.regs[base] = self.regs.get(base, 0) | (1 << self._match_ir_bit(base, i))
                            self.pending_irq |= 1 << irq
                    steps %= period
        self.regs[base+8] = (counter + int(pwm_mode)) & 0xFFFFFFFF

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

    def _pwm_enabled(self):
        return bool(self.function(1,23) == 2 and self.regs.get(self.SC+0xC4,0) & (1<<6)
                and self.regs.get(self.PWM+4,0) & 9 == 9
                and not self.regs.get(self.PWM+4,0) & 2
                and self.regs.get(self.PWM+0x4C,0) & (1<<12)
                and not self.regs.get(self.PWM+0x4C,0) & (1<<4)
                and not self.regs.get(self.PWM+0x70,0) & 3)

    def pwm_level(self):
        """Instantaneous single-edge PWM1.4 electrical output (not brightness)."""
        self._tick_timers_now()
        if not self._pwm_enabled():
            return None
        phase = (self.regs.get(self.PWM+8, 0) - 1) & 0xFFFFFFFF
        return int(phase < self.pwm_latched[4])

    def pwm_duty(self):
        self._tick_timers_now()
        good = self._pwm_enabled()
        # An open-drain pad cannot source current into LD10's grounded load.
        if self.regs.get(self.PIN + 0x6C, 0) & (1 << 23):
            return 0.0
        top = self.pwm_latched[0]
        periodic = bool(top and self.regs.get(self.PWM+0x14, 0) & 2)
        return (min(1.0, self.pwm_latched[4]/top) if periodic else float(self.pwm_level() or 0)) if good else 0.0

    def _deliver_irq(self):
        pending = self.pending_irq & self.enabled_irq
        if not (pending or self.pending_system) or self.active_irq is not None or self.uc.reg_read(UC_ARM_REG_PRIMASK):
            return
        irq = -1 if self.pending_system & (1 << 15) else (pending & -pending).bit_length()-1
        vtor = self.regs.get(0xE000ED08,0) & 0xFFFFFF80
        handler = int.from_bytes(self.uc.mem_read(vtor+(16+irq)*4,4),'little')
        if not handler & 1:
            raise FirmwareError(f'IRQ {irq} has no valid Thumb handler in the vector table.')
        regs = [UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,
                UC_ARM_REG_R12,UC_ARM_REG_LR,UC_ARM_REG_PC,UC_ARM_REG_XPSR]
        original_sp = self.uc.reg_read(UC_ARM_REG_SP)
        padding = 4 if self.regs.get(0xE000ED14, 0) & (1 << 9) and original_sp & 4 else 0
        sp = original_sp - 32 - padding
        values = [self.uc.reg_read(r) for r in regs]
        values[-1] = (values[-1] & ~(1 << 9)) | (int(bool(padding)) << 9)
        self.uc.mem_write(sp, struct.pack('<8I', *values))
        self.irq_frame = sp
        self.uc.reg_write(UC_ARM_REG_SP, sp)
        self.uc.reg_write(UC_ARM_REG_LR, 0xFFFFFFF9)
        self.uc.reg_write(UC_ARM_REG_XPSR, (self.uc.reg_read(UC_ARM_REG_XPSR) & ~511) | (16+irq))
        self.uc.reg_write(UC_ARM_REG_PC, handler)
        if irq == -1:
            self.pending_system &= ~(1 << 15)
        else:
            self.pending_irq &= ~(1<<irq)
        self.active_irq = irq
        self.irq_count += 1

    def _refresh_interrupts(self):
        # NVIC pending is cleared on entry, but a peripheral whose flag remains
        # asserted must request service again after exception return.
        self._tick_adc_now()
        self.observe()
        self.pending_irq |= (self.regs.get(self.SC+0x140,0)&15)<<18
        for base in (*self.TIMERS,self.PWM):
            irq=9 if base==self.PWM else self.TIMERS[base][0]
            ir=self.regs.get(base,0)
            mcr=self.regs.get(base+0x14,0)
            if any(ir&(1<<self._match_ir_bit(base, i)) and mcr&(1<<(3*i))
                   for i in range(7 if base == self.PWM else 4)):
                self.pending_irq|=1<<irq

    def _interrupt(self, uc, intno, _):
        # Unicorn reports ARM exception-return (BX LR to EXC_RETURN) as interrupt 8.
        if intno == 8 and self.active_irq is not None:
            sp = self.irq_frame
            vals = struct.unpack('<8I', bytes(uc.mem_read(sp,32)))
            regs = [UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,
                    UC_ARM_REG_R12,UC_ARM_REG_LR,UC_ARM_REG_PC,UC_ARM_REG_XPSR]
            for r,v in zip(regs,vals):
                uc.reg_write(r, v & ~(1 << 9) if r == UC_ARM_REG_XPSR else v)
            uc.reg_write(UC_ARM_REG_SP,sp+32+(4 if vals[-1] & (1 << 9) else 0))
            self.active_irq = None
            self.irq_frame = None
            uc.emu_stop()
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
            if self.error:
                raise FirmwareError(self.error)
        except UcError as e:
            self.error = f'Firmware execution failed at PC 0x{self.uc.reg_read(UC_ARM_REG_PC):08X}: {e}'
            raise FirmwareError(self.error) from e

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
                'gpioEvents':self.gpio_events,'lcdEdges':self.lcd.edges,
                'interrupts':self.irq_count,'pc':f'0x{self.uc.reg_read(UC_ARM_REG_PC):08X}',
                'warnings':self.board.warnings[:], 'error':self.error,
                'gpio':[{'direction':f'0x{g.direction:08X}','latch':f'0x{g.latch:08X}'} for g in self.gpio]}
