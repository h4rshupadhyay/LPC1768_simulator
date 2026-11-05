"""10-bit DAC on AOUT (P0.26 function 2), UM10360 chapter 30.

The output is an analog source for the circuit solver: VALUE/1024 x VREFP
behind the buffer's output resistance. DMA/timeout registers are stored only.
"""
from __future__ import annotations

from .peripheral import Peripheral

VREFP = 3.3


class DAC(Peripheral):
    name = 'DAC'
    base = 0x4008C000
    size = 0x4000
    pclk = (0x1A8, 22)

    def __init__(self, machine):
        super().__init__(machine)
        self.dacr = 0
        self.ctrl = 0
        self.count = 0

    def value(self):
        return (self.dacr >> 6) & 0x3FF

    def voltage(self):
        return self.value() * VREFP / 1024

    def max_current(self):
        # BIAS=0: 700 uA, 1 us settling; BIAS=1: 350 uA, 2.5 us (data sheet Table 21).
        return 350e-6 if self.dacr & (1 << 16) else 700e-6

    def read(self, offset):
        if offset == 0:
            return self.dacr
        if offset == 4:
            return self.ctrl
        if offset == 8:
            return self.count
        self.unsupported(offset, False)

    def write(self, offset, value, mask):
        value &= mask
        if offset == 0:
            self.dacr = (self.dacr & ~mask | value) & 0x1FFC0
            self.machine.observe()
        elif offset == 4:
            self.ctrl = value & 15
        elif offset == 8:
            self.count = value & 0xFFFF
        else:
            self.unsupported(offset, True)

    def snapshot(self):
        return {'value': self.value(), 'volts': round(self.voltage(), 4)}
