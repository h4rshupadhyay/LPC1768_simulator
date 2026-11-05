"""UART0-3, UM10360 chapters 14-15: byte-level frames timed by the baud rate.

Frames are delivered whole to whatever is wired to the selected TXD pad, and
received from devices on the selected RXD pad. A receiver samples the sender's
waveform at its own bit timing, so mismatched baud rates garble data exactly
as a real UART would, rather than being silently corrected.
"""
from __future__ import annotations

from collections import deque

from .peripheral import Peripheral

FIFO = 16
TRIGGERS = (1, 4, 8, 14)


def resample(byte, sender, receiver, bits=8, parity=False, stops=1):
    """(received byte, framing error) when `receiver` samples a `sender` frame."""
    frame = [0] + [(byte >> i) & 1 for i in range(bits)]
    if parity:
        frame.append(bin(byte).count('1') & 1)
    frame += [1] * stops
    value = 0
    def level(t):
        index = int(t * sender / receiver)
        return frame[index] if index < len(frame) else 1
    for i in range(bits):
        value |= level(1.5 + i) << i
    stop_at = 1.5 + bits + int(parity)
    return value, not level(stop_at)


class UART(Peripheral):
    BASES = {0: 0x4000C000, 1: 0x40010000, 2: 0x40098000, 3: 0x4009C000}
    IRQS = {0: 5, 1: 6, 2: 7, 3: 8}
    POWER = {0: 3, 1: 4, 2: 24, 3: 25}
    PCLK = {0: (0x1A8, 6), 1: (0x1A8, 8), 2: (0x1AC, 16), 3: (0x1AC, 18)}

    def __init__(self, machine, index):
        super().__init__(machine)
        self.index = index
        self.name = f'UART{index}'
        self.base = self.BASES[index]
        self.irq = self.IRQS[index]
        self.power_bit = self.POWER[index]
        self.pclk = self.PCLK[index]
        self.dll, self.dlm, self.ier, self.lcr, self.mcr = 1, 0, 0, 0, 0
        self.fcr, self.scr, self.fdr, self.ter, self.acr, self.icr = 0, 0, 0x10, 0x80, 0, 0
        self.rs485 = [0, 0, 0]
        self.rx = deque()
        self.tx = deque()
        self.shifting = False
        self.thre_pending = False
        self.line_status = 0  # sticky OE/PE/FE/BI bits 1-4
        self.timeout_due = None
        self.sent = 0

    # -- configuration --------------------------------------------------------
    def divisor(self):
        return (self.dlm << 8) | self.dll

    def baud(self):
        divisor = self.divisor()
        if not divisor:
            return 0.0
        add, mul = self.fdr & 15, (self.fdr >> 4) & 15
        fraction = 1 + add / mul if mul and add < mul else 1
        return self.pclk_hz() / (16 * divisor * fraction)

    def frame(self):
        bits = 5 + (self.lcr & 3)
        parity = bool(self.lcr & 8)
        stops = 2 if self.lcr & 4 else 1
        return bits, parity, stops

    def frame_ns(self):
        baud = self.baud()
        bits, parity, stops = self.frame()
        return int((1 + bits + parity + stops) * 1e9 / baud) if baud else None

    def pad(self, direction):
        return self.machine.selected_pad(f'{direction}{self.index}')

    # -- registers --------------------------------------------------------------
    def lsr(self):
        value = int(bool(self.rx)) | self.line_status
        if not self.tx:
            value |= 0x20
            if not self.shifting:
                value |= 0x40
        return value

    def iir(self):
        fifo = 0xC0 if self.fcr & 1 else 0
        if self.ier & 4 and self.line_status & 0x1E:
            return fifo | 0x06
        if self.ier & 1 and self.rx:
            if len(self.rx) >= self.trigger():
                return fifo | 0x04
            if self.timeout_due is not None and self.machine.time_ns() >= self.timeout_due:
                return fifo | 0x0C
        if self.ier & 2 and self.thre_pending:
            return fifo | 0x02
        return fifo | 0x01

    def trigger(self):
        return TRIGGERS[(self.fcr >> 6) & 3] if self.fcr & 1 else 1

    def read(self, offset):
        if offset not in self._offsets():
            self.unsupported(offset, False)
        if not self.powered():
            self.unpowered_access(False)
            return 0
        dlab = self.lcr & 0x80
        if offset == 0:
            if dlab:
                return self.dll
            value = self.rx.popleft() if self.rx else 0
            self._restart_timeout()
            return value
        if offset == 4:
            return self.dlm if dlab else self.ier
        if offset == 8:
            value = self.iir()
            if value & 0x0F == 0x02:
                self.thre_pending = False
            return value
        if offset == 0x14:
            value = self.lsr()
            self.line_status = 0
            return value
        if offset == 0x58:
            return len(self.rx) | (len(self.tx) << 8)
        return {0xC: self.lcr, 0x10: self.mcr, 0x18: 0, 0x1C: self.scr, 0x20: self.acr,
                0x24: self.icr, 0x28: self.fdr, 0x30: self.ter, 0x4C: self.rs485[0],
                0x50: self.rs485[1], 0x54: self.rs485[2]}[offset]

    def write(self, offset, value, mask):
        if offset not in self._offsets() or offset in (0x14, 0x18, 0x58):
            self.unsupported(offset, True)
        if not self.powered():
            self.unpowered_access(True)
            return
        dlab = self.lcr & 0x80
        def merge(old):
            return ((old & ~mask) | (value & mask)) & 0xFF
        if offset == 0:
            if dlab:
                self.dll = merge(self.dll)
            else:
                self._transmit(value & 0xFF)
        elif offset == 4:
            if dlab:
                self.dlm = merge(self.dlm)
            else:
                was = self.ier
                self.ier = merge(self.ier) & 0x387
                if self.ier & 2 and not was & 2 and not self.tx:
                    self.thre_pending = True
        elif offset == 8:
            self.fcr = value & 0xC7
            if value & 2:
                self.rx.clear()
            if value & 4:
                self.tx.clear()
        elif offset == 0xC:
            self.lcr = merge(self.lcr)
        elif offset == 0x10:
            self.mcr = merge(self.mcr)
        elif offset == 0x1C:
            self.scr = merge(self.scr)
        elif offset == 0x20:
            self.acr = value & 0x307
        elif offset == 0x24:
            self.icr = merge(self.icr)
        elif offset == 0x28:
            self.fdr = merge(self.fdr)
        elif offset == 0x30:
            self.ter = value & 0x80
        else:
            self.rs485[(offset - 0x4C) // 4] = merge(self.rs485[(offset - 0x4C) // 4])
        self.refresh_interrupts()

    def _offsets(self):
        common = {0, 4, 8, 0xC, 0x14, 0x1C, 0x20, 0x28, 0x30, 0x58}
        if self.index == 1:
            return common | {0x10, 0x18, 0x4C, 0x50, 0x54}
        return common | {0x24}

    # -- transmission -------------------------------------------------------------
    def _transmit(self, byte):
        if len(self.tx) >= FIFO:
            return  # data written to a full THR FIFO is lost
        self.tx.append(byte)
        self.thre_pending = False
        if not self.shifting:
            self._start_next()

    def _start_next(self):
        duration = self.frame_ns()
        if not self.tx or not self.ter & 0x80:
            self.shifting = False
            return
        if duration is None:
            self.note('baud', f'{self.name} transmits with a zero divisor (DLL=DLM=0); no data leaves the pin.')
            self.shifting = False
            return
        self.shifting = True
        byte = self.tx.popleft()
        if not self.tx:
            self.thre_pending = True
        self.machine.schedule_in(duration, lambda: self._finish(byte))

    def _finish(self, byte):
        self.sent += 1
        pad = self.pad('TXD')
        bits, parity, stops = self.frame()
        if pad is None:
            self.note('pin', f'{self.name} is transmitting, but no pin is configured as TXD{self.index}. '
                      f'Select the TXD{self.index} function in PINSEL.')
        else:
            self.clear_note('pin')
            self.machine.deliver_serial(pad, byte, self.baud(), bits, parity, stops, source=self)
        self._start_next()
        self.refresh_interrupts()

    # -- reception ---------------------------------------------------------------
    def receive(self, byte, baud, bits=8, parity=False, stops=1, sender='device'):
        """A frame arriving on this UART's RXD pad, sent at `baud`."""
        if not self.powered():
            return
        own = self.baud()
        if not own:
            return
        my_bits = self.frame()[0]
        if abs(baud - own) / own > 0.03:
            byte, framing = resample(byte, baud, own, my_bits, parity, stops)
            self.note('baud', f'{sender} sends at {baud:.0f} baud but {self.name} is set to {own:.0f} baud; '
                      'received bytes are garbled. Match DLL/DLM/FDR to the device.')
            if framing:
                self.line_status |= 0x08
        else:
            self.clear_note('baud')
        if len(self.rx) >= FIFO:
            self.line_status |= 0x02
            return
        self.rx.append(byte & ((1 << my_bits) - 1))
        self._restart_timeout()
        self.refresh_interrupts()

    def _restart_timeout(self):
        duration = self.frame_ns()
        self.timeout_due = self.machine.time_ns() + 4 * duration if self.rx and duration else None
        if self.timeout_due is not None:
            self.machine.schedule_at(self.timeout_due, self.refresh_interrupts)

    def refresh_interrupts(self):
        if self.powered() and not self.iir() & 1:
            self.interrupt()

    def tx_level(self):
        return 1

    def snapshot(self):
        return {'baud': round(self.baud()), 'frame': self.frame(), 'sent': self.sent}
