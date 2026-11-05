"""Repetitive interrupt timer, watchdog and real-time clock (UM10360 ch. 24, 28, 27).

All three advance from simulated time. The RTC calendar starts from the host
date when the simulator starts and then counts simulated seconds.
"""
from __future__ import annotations

import calendar
import datetime

from .peripheral import Peripheral


class RIT(Peripheral):
    name = 'RIT'
    base = 0x400B0000
    irq = 29
    power_bit = 16
    pclk = (0x1AC, 26)

    def __init__(self, machine):
        super().__init__(machine)
        self.compval = 0xFFFFFFFF
        self.mask = 0
        self.ctrl = 0x0C
        self.counter = 0
        self.fraction = 0

    def read(self, offset):
        if offset not in (0, 4, 8, 0xC):
            self.unsupported(offset, False)
        return {0: self.compval, 4: self.mask, 8: self.ctrl, 0xC: self.counter}[offset]

    def write(self, offset, value, mask):
        if offset not in (0, 4, 8, 0xC):
            self.unsupported(offset, True)
        value &= mask
        if offset == 0:
            self.compval = value
        elif offset == 4:
            self.mask = value
        elif offset == 8:
            if value & 1:
                self.ctrl &= ~1
            self.ctrl = (self.ctrl & 1) | (value & 0x0E)
        else:
            self.counter = value
        self.refresh_interrupts()

    def advance(self, delta_ns):
        if not self.ctrl & 8 or not self.powered() or not delta_ns:
            return
        total = self.fraction + delta_ns * self.pclk_hz()
        clocks, self.fraction = divmod(total, 1_000_000_000)
        if not clocks:
            return
        keep = ~self.mask & 0xFFFFFFFF
        if self.mask == 0:
            # States cycle with period compval+1 when the counter clears on
            # match, otherwise through the full 32-bit range.
            clear = self.ctrl & 2 and self.counter <= self.compval
            period = self.compval + 1 if clear else 1 << 32
            pos = self.counter
            if clocks >= (self.compval - pos - 1) % period + 1:
                self.ctrl |= 1
            self.counter = (pos + clocks) % period
        else:
            target = self.compval & keep
            for _ in range(min(clocks, 1 << 16)):
                self.counter = (self.counter + 1) & 0xFFFFFFFF
                if self.counter & keep == target:
                    self.ctrl |= 1
                    if self.ctrl & 2:
                        self.counter = 0
            self.counter = (self.counter + max(0, clocks - (1 << 16))) & 0xFFFFFFFF
        self.refresh_interrupts()

    def refresh_interrupts(self):
        if self.ctrl & 1:
            self.interrupt()


class WDT(Peripheral):
    name = 'WDT'
    base = 0x40000000
    irq = 0
    pclk = (0x1A8, 0)

    def __init__(self, machine):
        super().__init__(machine)
        self.mod = 0
        self.tc = 0xFF
        self.tv = 0xFF
        self.clksel = 0
        self.feed_state = 0
        self.started = False
        self.fraction = 0

    def clock_hz(self):
        source = self.clksel & 3
        return {0: 4_000_000, 1: self.pclk_hz(), 2: 32_768}.get(source, 4_000_000)

    def read(self, offset):
        if offset not in (0, 4, 0xC, 0x10):
            self.unsupported(offset, False)
        return {0: self.mod, 4: self.tc, 0xC: self.tv, 0x10: self.clksel}[offset]

    def write(self, offset, value, mask):
        if offset not in (0, 4, 8, 0x10):
            self.unsupported(offset, True)
        value &= mask
        if offset == 0:
            # WDEN and WDRESET can only be set by software; WDTOF/WDINT clear by writing 0.
            self.mod = (self.mod & 3) | (value & 3) | (self.mod & value & 0x0C)
        elif offset == 4:
            self.tc = max(0xFF, value)
        elif offset == 8:
            byte = value & 0xFF
            if byte == 0xAA:
                self.feed_state = 1
            elif byte == 0x55 and self.feed_state == 1:
                self.feed_state = 0
                self.tv = self.tc
                if self.mod & 1:
                    self.started = True
            else:
                self.feed_state = 0
                if self.started:
                    self._timeout('invalid feed sequence')
        else:
            if not self.clksel & (1 << 31):
                self.clksel = value & 0x80000003

    def advance(self, delta_ns):
        if not self.started or not delta_ns:
            return
        total = self.fraction + delta_ns * self.clock_hz()
        clocks, self.fraction = divmod(total, 4_000_000_000)  # fixed /4 prescaler
        if clocks >= self.tv:
            self.tv = 0
            self._timeout('counter reached zero')
        else:
            self.tv -= clocks

    def _timeout(self, reason):
        self.mod |= 4
        if self.mod & 2:
            self.machine.request_reset(f'Watchdog reset: {reason}.')
        else:
            self.mod |= 8
            self.interrupt()
            self.tv = self.tc

    def refresh_interrupts(self):
        if self.mod & 8 and not self.mod & 2:
            self.interrupt()


class RTC(Peripheral):
    name = 'RTC'
    base = 0x40024000
    irq = 17
    power_bit = 9

    FIELDS = {0x20: ('SEC', 63), 0x24: ('MIN', 63), 0x28: ('HOUR', 31), 0x2C: ('DOM', 31),
              0x30: ('DOW', 7), 0x34: ('DOY', 511), 0x38: ('MONTH', 15), 0x3C: ('YEAR', 4095)}

    def __init__(self, machine):
        super().__init__(machine)
        now = datetime.datetime.now()
        self.time = {'SEC': now.second, 'MIN': now.minute, 'HOUR': now.hour, 'DOM': now.day,
                     'DOW': now.isoweekday() % 7, 'DOY': now.timetuple().tm_yday,
                     'MONTH': now.month, 'YEAR': now.year}
        self.alarm = {k: 0 for k in self.time}
        self.ilr = self.ccr = self.ciir = self.amr = 0
        self.calibration = self.auxen = self.aux = 0
        self.gpreg = [0] * 5
        self.fraction = 0

    def read(self, offset):
        if offset in self.FIELDS:
            return self.time[self.FIELDS[offset][0]]
        if 0x60 <= offset <= 0x7C:
            return self.alarm[self.FIELDS[offset - 0x40][0]]
        if 0x44 <= offset <= 0x54:
            return self.gpreg[(offset - 0x44) // 4]
        t = self.time
        values = {0: self.ilr, 8: self.ccr, 0xC: self.ciir, 0x10: self.amr,
                  0x14: t['SEC'] | t['MIN'] << 8 | t['HOUR'] << 16 | t['DOW'] << 24,
                  0x18: t['DOM'] | t['MONTH'] << 8 | t['YEAR'] << 16, 0x1C: t['DOY'],
                  0x40: self.calibration, 0x58: self.auxen, 0x5C: self.aux}
        if offset not in values:
            self.unsupported(offset, False)
        return values[offset]

    def write(self, offset, value, mask):
        value &= mask
        if offset in self.FIELDS:
            name, limit = self.FIELDS[offset]
            self.time[name] = value & limit
        elif 0x60 <= offset <= 0x7C:
            name, limit = self.FIELDS[offset - 0x40]
            self.alarm[name] = value & limit
        elif 0x44 <= offset <= 0x54:
            self.gpreg[(offset - 0x44) // 4] = value
        elif offset == 0:
            self.ilr &= ~(value & 3)
        elif offset == 8:
            self.ccr = value & 0x13
            if value & 2:
                self.fraction = 0
        elif offset == 0xC:
            self.ciir = value & 0xFF
        elif offset == 0x10:
            self.amr = value & 0xFF
        elif offset == 0x40:
            self.calibration = value & 0x3FFFF
        elif offset == 0x58:
            self.auxen = value & 0x10
        elif offset == 0x5C:
            self.aux &= ~(value & 0x10)
        else:
            self.unsupported(offset, True)
        self.refresh_interrupts()

    def advance(self, delta_ns):
        if not self.ccr & 1 or self.ccr & 2 or not delta_ns:
            return
        self.fraction += delta_ns
        seconds, self.fraction = divmod(self.fraction, 1_000_000_000)
        for _ in range(min(seconds, 86400)):
            self._tick()
        self.refresh_interrupts()

    def _tick(self):
        t = self.time
        changed = 1
        t['SEC'] += 1
        if t['SEC'] >= 60:
            t['SEC'] = 0; t['MIN'] += 1; changed |= 2
            if t['MIN'] >= 60:
                t['MIN'] = 0; t['HOUR'] += 1; changed |= 4
                if t['HOUR'] >= 24:
                    t['HOUR'] = 0; changed |= 8 | 16 | 32
                    t['DOW'] = (t['DOW'] + 1) % 7
                    t['DOY'] += 1
                    t['DOM'] += 1
                    year = t['YEAR'] or 2000
                    days = calendar.monthrange(year, min(12, max(1, t['MONTH'])))[1]
                    if t['DOM'] > days:
                        t['DOM'] = 1; t['MONTH'] += 1; changed |= 64
                        if t['MONTH'] > 12:
                            t['MONTH'] = 1; t['YEAR'] += 1; t['DOY'] = 1; changed |= 128
        if self.ciir & changed:
            self.ilr |= 1
        masked = self.amr
        keys = ('SEC', 'MIN', 'HOUR', 'DOM', 'DOW', 'DOY', 'MONTH', 'YEAR')
        if masked != 0xFF and all(masked & (1 << i) or t[k] == self.alarm[k] for i, k in enumerate(keys)):
            self.ilr |= 2

    def refresh_interrupts(self):
        if self.ilr & 3:
            self.interrupt()

    def snapshot(self):
        t = self.time
        return {'running': bool(self.ccr & 1), 'time': f"{t['YEAR']:04}-{t['MONTH']:02}-{t['DOM']:02} "
                f"{t['HOUR']:02}:{t['MIN']:02}:{t['SEC']:02}"}


class QEI(Peripheral):
    """Quadrature position counting from MCI0/MCI1 (PhA/PhB) and MCI2 (index) pads."""
    name = 'QEI'
    base = 0x400BC000
    size = 0x1000
    irq = 31
    power_bit = 18
    pclk = (0x1AC, 0)

    def __init__(self, machine):
        super().__init__(machine)
        self.conf = 0
        self.pos = 0
        self.maxpos = 0
        self.direction = 0
        self.index_count = 0
        self.cmpos = [0, 0, 0]
        self.inxcmp = self.load = self.velcomp = self.filter = 0
        self.ie = 0
        self.intstat = 0
        self.last = None

    def read(self, offset):
        values = {4: self.direction, 8: self.conf, 0xC: self.pos, 0x10: self.maxpos,
                  0x14: self.cmpos[0], 0x18: self.cmpos[1], 0x1C: self.cmpos[2],
                  0x20: self.index_count, 0x24: self.inxcmp, 0x28: self.load,
                  0x2C: 0, 0x30: 0, 0x34: 0, 0x38: self.velcomp, 0x3C: self.filter,
                  0xFE0: self.intstat, 0xFE4: self.ie}
        if offset not in values:
            self.unsupported(offset, False)
        return values[offset]

    def write(self, offset, value, mask):
        value &= mask
        if offset == 0:
            if value & 1:
                self.pos = 0
            if value & 2:
                self.index_count = 0
        elif offset == 8:
            self.conf = value & 15
        elif offset == 0x10:
            self.maxpos = value
        elif offset in (0x14, 0x18, 0x1C):
            self.cmpos[(offset - 0x14) // 4] = value
        elif offset == 0x24:
            self.inxcmp = value
        elif offset == 0x28:
            self.load = value
        elif offset == 0x38:
            self.velcomp = value
        elif offset == 0x3C:
            self.filter = value
        elif offset == 0xFD8:
            self.ie &= ~value
        elif offset == 0xFDC:
            self.ie |= value
        elif offset == 0xFE8:
            self.intstat &= ~value
        elif offset == 0xFEC:
            self.intstat |= value
        else:
            self.unsupported(offset, True)
        self.refresh_interrupts()

    def phases(self, a, b, index):
        """Called with resolved PhA/PhB/IDX levels whenever pads change."""
        if not self.powered():
            return
        state = (a, b)
        if self.conf & 2:  # SIGMODE: PhA is direction, PhB is the clock
            if self.last is not None and b and not self.last[1]:
                self._count(-1 if a else 1)
        elif self.last is not None and state != self.last:
            sequence = [(0, 0), (1, 0), (1, 1), (0, 1)]
            if state in sequence and self.last in sequence:
                step = (sequence.index(state) - sequence.index(self.last)) % 4
                if step in (1, 3):
                    forward = step == 1
                    if self.conf & 4 or a != self.last[0]:  # CAPMODE: count both phases
                        self._count(1 if forward else -1)
        if index and not getattr(self, '_last_index', 0):
            self.index_count += 1
            self.intstat |= 1
        self._last_index = index
        self.last = state

    def _count(self, step):
        if self.conf & 1:
            step = -step
        direction = int(step < 0)
        if direction != self.direction:
            self.intstat |= 1 << 2
        self.direction = direction
        self.pos += step
        if self.maxpos and self.pos > self.maxpos:
            self.pos = 0
            self.intstat |= 1 << 6
        elif self.pos < 0:
            self.pos = self.maxpos
            self.intstat |= 1 << 6
        self.refresh_interrupts()

    def refresh_interrupts(self):
        if self.intstat & self.ie:
            self.interrupt()

    def snapshot(self):
        return {'position': self.pos, 'direction': self.direction}


class StoredRegisters(Peripheral):
    """Register storage for MCPWM: writes are accepted, outputs are not modeled."""

    def __init__(self, machine, name, base, size, offsets, power_bit=None):
        super().__init__(machine)
        self.name, self.base, self.size = name, base, size
        self.offsets = set(offsets)
        self.power_bit = power_bit
        self.values = {}

    def read(self, offset):
        if offset not in self.offsets:
            self.unsupported(offset, False)
        return self.values.get(offset, 0)

    def write(self, offset, value, mask):
        if offset not in self.offsets:
            self.unsupported(offset, True)
        self.values[offset] = (self.values.get(offset, 0) & ~mask) | (value & mask)
        self.note('outputs', f'{self.name} registers are accepted, but its output waveforms are not modeled.')
