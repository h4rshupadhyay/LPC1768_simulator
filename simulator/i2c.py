"""I2C0-2 master mode, UM10360 chapter 19 status codes.

Devices respond at transaction level when their SDA and SCL pins share nets
with the selected pads. The bus works only if both lines actually rise when
released: without pull-ups a START never completes, as on real hardware.
"""
from __future__ import annotations

from .peripheral import Peripheral

AA, SI, STO, STA, I2EN = 4, 8, 16, 32, 64


class I2C(Peripheral):
    BASES = {0: 0x4001C000, 1: 0x4005C000, 2: 0x400A0000}
    IRQS = {0: 10, 1: 11, 2: 12}
    POWER = {0: 7, 1: 19, 2: 26}
    PCLK = {0: (0x1A8, 14), 1: (0x1AC, 6), 2: (0x1AC, 20)}

    def __init__(self, machine, index):
        super().__init__(machine)
        self.index = index
        self.name = f'I2C{index}'
        self.base, self.irq = self.BASES[index], self.IRQS[index]
        self.power_bit, self.pclk = self.POWER[index], self.PCLK[index]
        self.conset = 0
        self.stat = 0xF8
        self.dat = 0
        self.adr = [0, 0, 0, 0]
        self.masks = [0, 0, 0, 0]
        self.sclh, self.scll = 4, 4
        self.mmctrl = 0
        self.device = None
        self.reading = False
        self.active = False
        self.pending = False
        self.transactions = 0

    def hz(self):
        period = self.sclh + self.scll
        return self.pclk_hz() / period if period else 0.0

    def byte_ns(self):
        hz = self.hz()
        return int(9 * 1e9 / hz) if hz else 1000

    def read(self, offset):
        if offset not in (0, 4, 8, 0xC, 0x10, 0x14, 0x1C, 0x20, 0x24, 0x28, 0x2C, 0x30, 0x34, 0x38, 0x3C):
            self.unsupported(offset, False)
        if not self.powered():
            self.unpowered_access(False)
            return 0
        if offset == 0:
            return self.conset
        if offset == 4:
            return self.stat
        if offset in (8, 0x2C):
            return self.dat
        if offset == 0xC:
            return self.adr[0]
        if offset in (0x20, 0x24, 0x28):
            return self.adr[(offset - 0x1C) // 4]
        if offset >= 0x30:
            return self.masks[(offset - 0x30) // 4]
        return {0x10: self.sclh, 0x14: self.scll, 0x1C: self.mmctrl}[offset]

    def write(self, offset, value, mask):
        if offset not in (0, 8, 0xC, 0x10, 0x14, 0x18, 0x1C, 0x20, 0x24, 0x28, 0x30, 0x34, 0x38, 0x3C):
            self.unsupported(offset, True)
        if not self.powered():
            self.unpowered_access(True)
            return
        value &= mask
        if offset == 0:
            self.conset |= value & 0x7C
            self._step()
        elif offset == 0x18:
            clear_si = bool(value & SI) and self.conset & SI
            self.conset &= ~(value & 0x6C)
            if clear_si:
                self._continue()
        elif offset == 8:
            self.dat = value & 0xFF
        elif offset == 0xC:
            self.adr[0] = value & 0xFF
        elif offset in (0x20, 0x24, 0x28):
            self.adr[(offset - 0x1C) // 4] = value & 0xFF
        elif offset >= 0x30:
            self.masks[(offset - 0x30) // 4] = value & 0xFE
        elif offset == 0x10:
            self.sclh = value & 0xFFFF
        elif offset == 0x14:
            self.scll = value & 0xFFFF
        else:
            self.mmctrl = value & 15
        self.refresh_interrupts()

    # -- master state machine -----------------------------------------------------
    def _step(self):
        """STA may be set before SI is cleared; the START waits for SI clear."""
        if self.conset & I2EN and self.conset & STA and not self.conset & SI and not self.pending:
            self._schedule(self._start)

    def _schedule(self, action):
        self.pending = True
        def run():
            self.pending = False
            action()
        self.machine.schedule_in(self.byte_ns() if action is not self._start else self.byte_ns() // 9, run)

    def _bus_ok(self):
        sda, scl = self.machine.selected_pad(f'SDA{self.index}'), self.machine.selected_pad(f'SCL{self.index}')
        if sda is None or scl is None:
            self.note('pins', f'{self.name} is enabled but its SDA/SCL pins are not selected in PINSEL '
                      f'(SDA{self.index}: {"ok" if sda else "missing"}, SCL{self.index}: {"ok" if scl else "missing"}).')
            return False
        self.clear_note('pins')
        released = self.machine.bus_released_high(sda, scl)
        if not released:
            self.note('pullups', f'{self.name} SDA/SCL never rise when released. I2C needs pull-up '
                      'resistors (typically 4.7 kΩ to 3.3 V); the START condition cannot complete.')
            return False
        self.clear_note('pullups')
        return True

    def _start(self):
        if not self.conset & I2EN or not self.conset & STA:
            return
        if not self._bus_ok():
            return  # SI never sets: firmware waiting on the START hangs, as it would on a stuck bus
        repeated = self.active
        self.active = True
        self.device = None
        self._set(0x10 if repeated else 0x08)

    def _continue(self):
        if not self.conset & I2EN:
            return
        if self.conset & STO:
            self._schedule(self._stop)
            return
        if self.conset & STA:
            self._schedule(self._start)
            return
        status = self.stat
        if status in (0x08, 0x10):
            self._schedule(self._address)
        elif status in (0x18, 0x28):
            self._schedule(self._send)
        elif status in (0x40, 0x50):
            self._schedule(self._receive)

    def _address(self):
        address, self.reading = self.dat >> 1, bool(self.dat & 1)
        devices = self.machine.i2c_devices(self, address)
        if len(devices) > 1:
            self.note('conflict', f'{len(devices)} devices answer at I2C address 0x{address:02X} on '
                      f'{self.name}; their replies collide. Change one device address.')
        self.device = devices[0] if devices else None
        if self.device is not None:
            self.device.i2c_start()
            self.transactions += 1
        acked = self.device is not None and self.device.i2c_address(address, self.reading)
        if not acked:
            self.device = None
        self._set((0x40 if acked else 0x48) if self.reading else (0x18 if acked else 0x20))

    def _send(self):
        acked = self.device is not None and self.device.i2c_write(self.dat)
        self._set(0x28 if acked else 0x30)

    def _receive(self):
        ack = bool(self.conset & AA)
        self.dat = self.device.i2c_read(ack) if self.device is not None else 0xFF
        self._set(0x50 if ack else 0x58)

    def _stop(self):
        if self.device is not None:
            self.device.i2c_stop()
        self.device = None
        self.active = False
        self.conset &= ~STO
        self.stat = 0xF8
        if self.conset & STA:
            self._schedule(self._start)

    def _set(self, status):
        self.stat = status
        self.conset |= SI
        self.refresh_interrupts()

    def refresh_interrupts(self):
        if self.powered() and self.conset & SI and self.conset & I2EN:
            self.interrupt()

    def snapshot(self):
        return {'hz': round(self.hz()), 'status': self.stat, 'transactions': self.transactions}
