"""SSP0/SSP1 (UM10360 chapter 18) and the legacy SPI block (chapter 17).

Master-mode frames are exchanged with devices whose SCK/MOSI pins share nets
with the selected pads; a device takes part only while its chip select is LOW.
Each frame takes its real bit time, so BSY/RNE polling behaves as on hardware.
"""
from __future__ import annotations

from collections import deque

from .peripheral import Peripheral

FIFO = 8


class SSP(Peripheral):
    BASES = {0: 0x40088000, 1: 0x40030000}
    IRQS = {0: 14, 1: 15}
    POWER = {0: 21, 1: 10}
    PCLK = {0: (0x1AC, 10), 1: (0x1A8, 20)}

    def __init__(self, machine, index):
        super().__init__(machine)
        self.index = index
        self.name = f'SSP{index}'
        self.base, self.irq = self.BASES[index], self.IRQS[index]
        self.power_bit, self.pclk = self.POWER[index], self.PCLK[index]
        self.cr0 = self.cr1 = self.cpsr = self.imsc = self.dmacr = 0
        self.overrun = self.timeout = False
        self.tx, self.rx = deque(), deque()
        self.busy = False
        self.frames = 0

    def bits(self):
        return (self.cr0 & 15) + 1

    def mode(self):
        return ((self.cr0 >> 6) & 1) << 1 | ((self.cr0 >> 7) & 1)

    def hz(self):
        divisor = self.cpsr & 0xFE
        if not divisor:
            return 0.0
        return self.pclk_hz() / (divisor * (((self.cr0 >> 8) & 0xFF) + 1))

    def enabled(self):
        return bool(self.cr1 & 2)

    def sr(self):
        return (int(not self.tx) | int(len(self.tx) < FIFO) << 1 | int(bool(self.rx)) << 2
                | int(len(self.rx) >= FIFO) << 3 | int(self.busy or bool(self.tx)) << 4)

    def ris(self):
        return (int(self.overrun) | int(self.timeout) << 1 | int(len(self.rx) >= FIFO // 2) << 2
                | int(len(self.tx) <= FIFO // 2) << 3)

    def read(self, offset):
        if offset not in (0, 4, 8, 0xC, 0x10, 0x14, 0x18, 0x1C, 0x24):
            self.unsupported(offset, False)
        if not self.powered():
            self.unpowered_access(False)
            return 0
        if offset == 8:
            value = self.rx.popleft() if self.rx else 0
            self.timeout = False
            return value
        if offset == 0xC:
            return self.sr()
        if offset == 0x18:
            return self.ris()
        if offset == 0x1C:
            return self.ris() & self.imsc
        return {0: self.cr0, 4: self.cr1, 0x10: self.cpsr, 0x14: self.imsc, 0x24: self.dmacr}[offset]

    def write(self, offset, value, mask):
        if offset not in (0, 4, 8, 0x10, 0x14, 0x20, 0x24):
            self.unsupported(offset, True)
        if not self.powered():
            self.unpowered_access(True)
            return
        value &= mask
        if offset == 0:
            self.cr0 = value & 0xFFFF
        elif offset == 4:
            self.cr1 = value & 15
            if self.cr1 & 4:
                self.note('slave', f'{self.name} slave mode is accepted but no external master is modeled.')
        elif offset == 8:
            if len(self.tx) < FIFO:
                self.tx.append(value & ((1 << self.bits()) - 1))
            if not self.busy:
                self._start()
        elif offset == 0x10:
            self.cpsr = value & 0xFF
            if self.cpsr & 1 or self.cpsr < 2:
                self.note('cpsr', f'{self.name} CPSR must be an even value from 2 to 254 (got {self.cpsr}).')
            else:
                self.clear_note('cpsr')
        elif offset == 0x14:
            self.imsc = value & 15
        elif offset == 0x20:
            if value & 1:
                self.overrun = False
            if value & 2:
                self.timeout = False
        else:
            self.dmacr = value & 3
        self.refresh_interrupts()

    def _start(self):
        if not self.tx or not self.enabled() or self.cr1 & 4:
            self.busy = False
            return
        hz = self.hz()
        if not hz:
            self.note('clock', f'{self.name} has no bit clock (CPSR is 0); nothing is transferred.')
            self.busy = False
            return
        self.busy = True
        value = self.tx.popleft()
        self.machine.observe()  # SSEL asserts for the frame
        self.machine.schedule_in(int(self.bits() * 1e9 / hz), lambda: self._finish(value))

    def _finish(self, value):
        self.frames += 1
        if self.cr1 & 1:
            received = value
        else:
            received = self.machine.spi_exchange(self, value, self.bits(), self.mode(), self.hz())
        if len(self.rx) >= FIFO:
            self.overrun = True
        else:
            self.rx.append(received)
        self.busy = False
        self._start()
        if not self.busy:
            self.machine.observe()
        self.refresh_interrupts()

    def pads(self):
        m, n = self.machine, self.index
        return {role: m.selected_pad(f'{role}{n}') for role in ('SCK', 'MOSI', 'MISO', 'SSEL')}

    def signal_level(self, role):
        """Idle-state levels of master outputs; frames are exchanged as wholes."""
        if not self.enabled() or self.cr1 & 4:
            return None
        if role == 'SCK':
            return (self.cr0 >> 6) & 1
        if role == 'MOSI':
            return 1
        if role == 'SSEL':
            return 0 if self.busy or self.tx else 1
        return None

    def refresh_interrupts(self):
        if self.powered() and self.ris() & self.imsc:
            self.interrupt()

    def snapshot(self):
        return {'hz': round(self.hz()), 'bits': self.bits(), 'mode': self.mode(), 'frames': self.frames}


class SPI(Peripheral):
    """Legacy SPI0 on P0.15-P0.18 function 3, master mode."""
    name = 'SPI'
    base = 0x40020000
    irq = 13
    power_bit = 8
    pclk = (0x1A8, 16)

    def __init__(self, machine):
        super().__init__(machine)
        self.spcr = self.spsr = self.spdr = 0
        self.spccr = 0
        self.spint = 0
        self.busy = False
        self.status_read = False
        self.frames = 0

    def bits(self):
        return ((self.spcr >> 8) & 15 or 16) if self.spcr & 4 else 8

    def mode(self):
        return ((self.spcr >> 4) & 1) << 1 | ((self.spcr >> 3) & 1)

    def hz(self):
        return self.pclk_hz() / self.spccr if self.spccr >= 8 else 0.0

    def read(self, offset):
        if offset not in (0, 4, 8, 0xC, 0x1C):
            self.unsupported(offset, False)
        if not self.powered():
            self.unpowered_access(False)
            return 0
        if offset == 4:
            self.status_read = bool(self.spsr & 0x80)
            return self.spsr
        if offset == 8:
            if self.status_read:
                self.spsr &= ~0x80
                self.status_read = False
            return self.spdr
        return {0: self.spcr, 0xC: self.spccr, 0x1C: self.spint}[offset]

    def write(self, offset, value, mask):
        if offset not in (0, 8, 0xC, 0x1C):
            self.unsupported(offset, True)
        if not self.powered():
            self.unpowered_access(True)
            return
        value &= mask
        if offset == 0:
            self.spcr = value & 0xFFC
        elif offset == 8:
            if self.busy:
                self.spsr |= 0x40  # WCOL
                return
            if self.status_read:
                self.spsr &= ~0x80
                self.status_read = False
            if not self.spcr & 0x20:
                self.note('slave', 'SPI slave mode is accepted but no external master is modeled.')
                return
            hz = self.hz()
            if not hz:
                self.note('clock', 'SPI S0SPCCR must be an even value of at least 8; nothing is transferred.')
                return
            self.clear_note('clock')
            self.busy = True
            bits = self.bits()
            out = value & ((1 << bits) - 1)
            self.machine.schedule_in(int(bits * 1e9 / hz), lambda: self._finish(out, bits))
        elif offset == 0xC:
            self.spccr = value & 0xFF
        else:
            if value & 1:
                self.spint = 0

    def _finish(self, value, bits):
        self.frames += 1
        self.spdr = self.machine.spi_exchange(self, value, bits, self.mode(), self.hz())
        self.busy = False
        self.spsr |= 0x80
        if self.spcr & 0x80:
            self.spint = 1
        self.refresh_interrupts()

    def pads(self):
        m = self.machine
        return {role: m.selected_pad(role) for role in ('SCK', 'MOSI', 'MISO', 'SSEL')}

    def signal_level(self, role):
        if not self.spcr & 0x20:
            return None
        return {'SCK': (self.spcr >> 4) & 1, 'MOSI': 1}.get(role)

    def refresh_interrupts(self):
        if self.powered() and self.spint:
            self.interrupt()
