"""Cortex-M3 SysTick register and counter state."""


class SysTick:
    BASE = 0xE000E010

    def __init__(self, machine):
        self.machine = machine
        self.ctrl = 4
        self.load = 0
        self.value = 0
        self.calib = 0x000F423F
        self.countflag = False

    def advance(self, core_ticks):
        if self.ctrl & 4:
            self._advance_edges(core_ticks)

    def external_edges(self, edges):
        """Apply STCLK/P3.26 edges, UM10360 section 23.4, not core/8."""
        if not isinstance(edges, int) or edges < 0:
            raise ValueError('STCLK edge count must be a non-negative integer.')
        if not self.ctrl & 4:
            self._advance_edges(edges)

    def _advance_edges(self, clocks):
        if not self.ctrl & 1 or not clocks:
            return
        if self.value == 0:
            self.value = self.load
            clocks -= 1
        if not self.value or not clocks:
            return
        if clocks < self.value:
            self.value -= clocks
            return
        clocks -= self.value
        self.value = 0
        self.countflag = True
        if self.ctrl & 2:
            self.machine.pending_system |= 1 << 15
        if self.load:
            clocks %= self.load + 1
            if clocks:
                self.value = self.load - (clocks - 1)

    def read(self, offset):
        if offset == 0:
            result = self.ctrl | (int(self.countflag) << 16)
            self.countflag = False
            return result
        return {4: self.load, 8: self.value, 12: self.calib}[offset]

    def write(self, offset, value, mask):
        if offset == 0:
            old = self.ctrl
            self.ctrl = ((old & ~mask) | value) & 7
        elif offset == 4:
            self.load = ((self.load & ~mask) | value) & 0xFFFFFF
        elif offset == 8:
            self.value = 0
            self.countflag = False
        # CALIB is read-only (ARM Cortex-M3 user guide table 674).
