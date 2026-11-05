"""Common base for memory-mapped peripherals registered on the machine bus.

A peripheral owns a register window, advances with simulated time and may
request interrupts. Accesses to offsets it does not implement are errors, so a
program never silently depends on unmodeled behavior.
"""
from __future__ import annotations

from .errors import FirmwareError

PCLK_DIVIDERS = (4, 1, 2, 8)


class Peripheral:
    name = ''
    base = 0
    size = 0x4000
    irq = None
    # (PCONP bit, PCLKSEL register offset from SC, shift)
    power_bit = None
    pclk = None

    def __init__(self, machine):
        self.machine = machine

    # -- helpers -------------------------------------------------------------
    def powered(self):
        if self.power_bit is None:
            return True
        m = self.machine
        return bool(m.regs.get(m.SC + 0xC4, 0) & (1 << self.power_bit))

    def pclk_hz(self):
        m = self.machine
        if self.pclk is None:
            return m.core_clock_hz()
        register, shift = self.pclk
        selection = (m.regs.get(m.SC + register, 0) >> shift) & 3
        return m.core_clock_hz() // PCLK_DIVIDERS[selection]

    def unsupported(self, offset, write):
        raise FirmwareError(f'Unsupported register {"write" if write else "read"} at '
                            f'0x{self.base + offset:08X} ({self.name} offset 0x{offset:02X}).')

    def interrupt(self):
        if self.irq is not None:
            self.machine.pending_irq |= 1 << self.irq

    def note(self, key, message):
        self.machine.note(f'{self.name}:{key}', message)

    def clear_note(self, key):
        self.machine.notes.pop(f'{self.name}:{key}', None)

    def unpowered_access(self, write):
        bit = self.power_bit
        self.note('power', f'{self.name} was accessed while unpowered (PCONP bit {bit} is 0). '
                  f'Real hardware ignores the {"write" if write else "read"}; '
                  f'set LPC_SC->PCONP |= 1 << {bit} first.')

    # -- interface -----------------------------------------------------------
    def read(self, offset):
        self.unsupported(offset, False)

    def write(self, offset, value, mask):
        self.unsupported(offset, True)

    def advance(self, delta_ns):
        pass

    def refresh_interrupts(self):
        pass

    def snapshot(self):
        return None
