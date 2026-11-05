"""Serial terminals: the PC end of a UART (USB serial on mbed, CN9 on the ALS kit, or a bridge part)."""
from __future__ import annotations

from collections import deque

from .uart import resample


class Terminal:
    def __init__(self, name, baud=9600, uart=0):
        self.name = name
        self.baud = baud
        self.uart = uart
        self.text = deque(maxlen=20_000)
        self.received = 0
        self.mismatch = False

    def attached(self, machine):
        """Built-in terminals listen on the UART's standard TXD pad (P0.2 for UART0)."""
        return machine.uarts[self.uart].pad('TXD') is not None

    def receive(self, byte, baud, bits=8, parity=False, stops=1):
        self.received += 1
        self.mismatch = abs(baud - self.baud) / self.baud > 0.03 if self.baud else True
        if self.mismatch:
            byte, _ = resample(byte, baud, self.baud, bits, parity, stops)
        self.text.append(chr(byte) if byte in (9, 10, 13) or 32 <= byte < 127 else f'\\x{byte:02x}')

    def frame_ns(self):
        return int(10 * 1e9 / self.baud)

    def send(self, machine, data, emit):
        """Queue bytes at this terminal's baud rate; `emit(byte)` delivers each frame."""
        for index, byte in enumerate(data[:4096]):
            machine.schedule_in(self.frame_ns() * (index + 1), lambda b=byte: emit(b))

    def clear(self):
        self.text.clear()

    def snapshot(self):
        return {'name': self.name, 'baud': self.baud, 'text': ''.join(self.text),
                'received': self.received, 'mismatch': self.mismatch}
