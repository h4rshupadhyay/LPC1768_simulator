"""LPC1768 ADC subset, from UM10360 chapter 29 and datasheet Fig.28.

Analog accuracy is idealized. Inputs disconnected by PINSEL or JP18 resolve
to zero by simulator convention, not by an assertion about floating hardware.
"""
from __future__ import annotations

import math


class ADCPeripheral:
    DONE = 1 << 31
    OVERRUN = 1 << 30
    BURST = 1 << 16
    PDN = 1 << 21
    CONTROL_MASK = 0x0F21FFFF

    def __init__(self, machine):
        self.machine = machine
        self.last_time = 0
        self.remaining = 0
        self.period = 0
        self.channel = None
        self.sample = 0
        self.conversion_burst = False
        self.last_channel = -1
        self.machine.regs.update({machine.ADC: 1,
                                  machine.ADC + 0xC: 0x100,
                                  machine.ADC + 0x34: 0xF00})

    def _now(self):
        m = self.machine
        if not m.realtime:
            return m.ticks
        # Clock stops on pause. Include time not yet folded into elapsed_ns by
        # the timer subsystem; this also permits a read before a timer update.
        return m.elapsed_ns + (max(0, m._clock_ns() - m._clock_anchor)
                               if m._clock_anchor is not None else 0)

    def _powered(self):
        m = self.machine
        return bool(m.regs.get(m.SC + 0xC4, 0) & (1 << 12)
                    and m.regs[m.ADC] & self.PDN)

    def _burst(self):
        cr = self.machine.regs[self.machine.ADC]
        return bool(cr & self.BURST and not cr & (7 << 24))

    def _period(self):
        m = self.machine
        cr = m.regs[m.ADC]
        pclk_div = (4, 1, 2, 8)[(m.regs.get(m.SC + 0x1A8, 0) >> 24) & 3]
        # One conversion needs 65 ADC clocks. Keep all arithmetic integral:
        # offline budget is core clocks, realtime budget is ns * core Hz.
        return 65 * (((cr >> 8) & 255) + 1) * pclk_div * (1_000_000_000 if m.realtime else 1)

    def _begin(self, channel):
        m = self.machine
        if channel not in (4, 5):
            m._fail(f'Unsupported ADC channel {channel}; only AD0.4 and AD0.5 are wired.')
            return
        self.channel = channel
        self.period = self._period()
        self.remaining = self.period
        self.conversion_burst = self._burst()
        valid = m.function(1, 26 + channel) == 3 and (
            channel != 4 or m.board.jumpers['JP18'] == '2-3')
        voltage = m.board.pots[channel] if valid else 0.0
        # Fig.28 places the first ideal transition at half an LSB and defines
        # 1 LSB=(VREFP-VREFN)/4096. Equality uses the upper code by convention.
        self.sample = min(4095, max(0, math.floor(voltage * 4096 / 3.3 + 0.5)))

    def _complete(self):
        m = self.machine
        channel = self.channel
        result = self.DONE | (self.sample << 4)
        channel_overrun = m.adc_last[channel] & self.OVERRUN
        global_overrun = m.adc_global & self.OVERRUN
        if self.conversion_burst:
            channel_overrun |= self.OVERRUN if m.adc_last[channel] & self.DONE else 0
            global_overrun |= self.OVERRUN if m.adc_global & self.DONE else 0
        m.adc_last[channel] = result | channel_overrun
        m.adc_global = result | global_overrun | (channel << 24)
        self.last_channel = channel
        self.channel = None
        self.remaining = 0
        self._request_interrupt(new_conversion=True)

    def _interrupt_asserted(self):
        m = self.machine
        inten = m.regs[m.ADC + 0xC]
        if inten & 0x100:
            return bool(m.adc_global & self.DONE)
        return any(inten & (1 << channel) and raw & self.DONE
                   for channel, raw in enumerate(m.adc_last))

    def _request_interrupt(self, *, new_conversion=False):
        # The active ISR gets a chance to acknowledge its level source.
        # A genuinely new completion can pend another IRQ during service;
        # merely revisiting the same DONE flag at each basic block cannot.
        if self._interrupt_asserted() and (new_conversion or self.machine.active_irq != 22):
            self.machine.pending_irq |= 1 << 22

    def sync(self):
        now = self._now()
        delta = max(0, now - self.last_time)
        self.last_time = now
        if not self._powered():
            self.channel = None
            self.remaining = 0
            return
        m = self.machine
        if self.channel is not None:
            period = self._period()
            if period != self.period:
                # A live divider change preserves conversion progress rather
                # than retaining the former clock rate for the entire sample.
                self.remaining = (self.remaining * period + self.period - 1) // self.period
                self.period = period
        budget = delta * (m.core_clock_hz() if m.realtime else 1)
        completed = 0
        while self.channel is not None and budget >= self.remaining:
            budget -= self.remaining
            self._complete()
            completed += 1
            if self._burst():
                selected = m.regs[m.ADC] & 255 or 1
                channels = [i for i in range(8) if selected & (1 << i)]
                self._begin(next((i for i in channels if i > self.last_channel), channels[0]))
                if completed >= 2 * len(channels):
                    # No firmware/input events occur inside sync(). Two scans
                    # establish the current static samples and sticky overrun
                    # flags. Whole further scans have the same register state
                    # and phase, so skip them without billions of iterations.
                    budget %= self._period() * len(channels)
        if self.channel is not None:
            self.remaining -= budget
        self._request_interrupt()

    def read(self, offset):
        self.sync()
        m = self.machine
        if offset == 4:
            raw = m.adc_global
            m.adc_global &= ~(self.DONE | self.OVERRUN)
            return raw
        if 0x10 <= offset <= 0x2C and offset % 4 == 0:
            channel = (offset - 0x10) // 4
            raw = m.adc_last[channel]
            m.adc_last[channel] &= ~(self.DONE | self.OVERRUN)
            return raw
        if offset == 0x30:
            done = sum(bool(raw & self.DONE) << i for i, raw in enumerate(m.adc_last))
            overrun = sum(bool(raw & self.OVERRUN) << (i + 8) for i, raw in enumerate(m.adc_last))
            return done | overrun | (int(self._interrupt_asserted()) << 16)
        return m.regs.get(m.ADC + offset, 0)

    def write(self, offset, value, mask):
        self.sync()
        m = self.machine
        address = m.ADC + offset
        if offset == 0x34:
            # TRIM[11:8] is locked by boot ROM; offset[7:4] remains writable.
            mask &= 0xF0
        elif offset == 0xC:
            mask &= 0x1FF
        else:
            mask &= self.CONTROL_MASK
        m.regs[address] = (m.regs.get(address, 0) & ~mask) | (value & mask)
        if offset != 0:
            self._request_interrupt()
            return
        m.adc_global &= ~self.DONE
        if not self._powered():
            self.channel = None
            self.remaining = 0
            return
        # UM10360 29.6: a launch while busy is ignored. Table532 has a
        # contradictory sentence about ADCR writes; the operation section is
        # followed here (see docs/ADC_AUDIT.md).
        if self.channel is not None:
            return
        cr = m.regs[address]
        if self._burst() or not cr & self.BURST and (cr >> 24) & 7 == 1:
            selected = cr & 255 or 1
            self._begin((selected & -selected).bit_length() - 1)
