"""Actuators, character/LED displays and supplies."""
from __future__ import annotations

from .base import Part
from ..doctor import finding


class Buzzer(Part):
    kind = 'buzzer'
    prefix = 'bz'
    pins = ('+', '-')
    inputs = ('+',)
    defaults = {'type': 'active'}
    choices = {'type': ('active', 'passive')}
    inductive = None
    meta = {'name': 'Buzzer (active / passive)', 'category': 'Outputs', 'aliases': ['beeper', 'piezo', 'alarm', 'sound', 'speaker', 'tone'],
            'interfaces': ['gpio', 'pwm'], 'supply': '3–5 V', 'compat': 'driver', 'shape': 'buzzer',
            'footprint': [[0, 0], [3, 0]],
            'description': 'Active buzzers beep on DC but draw ~25 mA: drive them with a transistor. '
                           'Passive piezos need a square wave (PWM) and play its frequency.'}

    def setup(self):
        self.rise = None
        self.frequency = 0.0
        self.high = 0

    def sense(self, volts, now):
        level = volts['+'] - self.v('-') > 1.5
        if level and not self.high:
            if self.rise is not None and now > self.rise:
                self.frequency = 1e9 / (now - self.rise)
            self.rise = now
        self.high = level

    def elements(self):
        return [('R', '@+', '@-', 130.0 if self.props['type'] == 'active' else 12_000.0, 'coil')]

    def state(self):
        result = self.circuit.element_result(f'{self.id}:coil') or {}
        if self.props['type'] == 'active':
            return {'sounding': result.get('i', 0) > 0.008, 'current': result.get('i', 0)}
        recent = self.rise is not None and self.now() - self.rise < 100_000_000
        return {'sounding': recent and self.frequency > 20, 'frequency': round(self.frequency) if recent else 0}


class Servo(Part):
    kind = 'servo'
    prefix = 'servo'
    pins = ('GND', 'VCC', 'SIG')
    inputs = ('SIG',)
    supply = ('VCC', 'GND', 4.4, 6.0, 7.2)
    meta = {'name': 'Servo motor (SG90)', 'category': 'Actuators', 'aliases': ['servo', 'sg90', 'mg996r', 'rc servo', 'angle'],
            'interfaces': ['pwm'], 'supply': '4.8–6 V (up to ~700 mA stall)', 'compat': 'supply', 'shape': 'servo',
            'footprint': [[0, 0], [1, 0], [2, 0]],
            'description': '50 Hz PWM: 1 ms pulse = 0°, 1.5 ms = 90°, 2 ms = 180°. The 3.3 V signal is fine; '
                           'power it from 5 V, not from the 3.3 V pin.'}

    def setup(self):
        self.rise = None
        self.high = False
        self.angle = 90.0
        self.width = 0
        self.period = 0
        self.last_rise = None

    def sense(self, volts, now):
        level = volts['SIG'] - self.v('GND') >= 2.0
        if level and not self.high:
            if self.last_rise is not None:
                self.period = now - self.last_rise
            self.last_rise = self.rise = now
        elif not level and self.high and self.rise is not None:
            self.width = now - self.rise
            if self.operational() and 400_000 <= self.width <= 2_600_000:
                self.angle = max(0.0, min(180.0, (self.width - 1_000_000) / 1_000_000 * 180))
        self.high = level

    def elements(self):
        return [('R', '@VCC', '@GND', 500.0, 'idle'), ('R', '@SIG', '@GND', 20_000.0, 'sig')]

    def check(self, volts):
        if self.period and not 10_000_000 <= self.period <= 40_000_000 and self.width:
            return [finding(f'servo-period:{self.id}', 'warning', f'{self.label}: pulse period {self.period / 1e6:.1f} ms',
                            'Hobby servos expect a pulse every 20 ms (50 Hz).',
                            'Much faster or slower frames make the servo jitter or ignore commands.',
                            'Erratic motion.', [{'label': 'Use a 20 ms PWM period', 'steps': [
                                'Set MR0 for 20 ms and MRn for 1–2 ms pulses.']}], parts=[self.id])]
        return []

    def state(self):
        return {'angle': round(self.angle, 1), 'pulse_us': round(self.width / 1000), 'period_ms': round(self.period / 1e6, 2)}


class DCMotor(Part):
    kind = 'dc_motor'
    prefix = 'm'
    pins = ('+', '-')
    inductive = ('+', '-')
    defaults = {'rated_volts': 5.0}
    meta = {'name': 'DC motor (small hobby)', 'category': 'Actuators', 'aliases': ['motor', 'fan', 'rotation', 'dc motor', 'vibration'],
            'interfaces': ['pwm'], 'supply': '3–6 V, 100–300 mA', 'compat': 'driver', 'shape': 'motor',
            'footprint': [[0, 0], [2, 0]],
            'description': 'Never drive a motor from a GPIO pin: use a MOSFET/transistor (or L293D/L298N) and a '
                           'flyback diode across the motor.'}

    def elements(self):
        return [('R', '@+', '@-', 10.0, 'winding')]

    def state(self):
        result = self.circuit.element_result(f'{self.id}:winding') or {}
        current = result.get('i', 0.0)
        volts = current * 10
        speed = max(-1.0, min(1.0, (abs(volts) - 0.8) / self.props['rated_volts'])) if abs(volts) > 0.8 else 0.0
        return {'speed': speed if volts >= 0 else -speed, 'current': current}


class RelayModule(Part):
    kind = 'relay'
    prefix = 'k'
    pins = ('VCC', 'GND', 'IN', 'COM', 'NO', 'NC')
    supply = ('VCC', 'GND', 4.5, 5.5, 7.0)
    hidden = ('_opto',)
    defaults = {'trigger': 'low'}
    choices = {'trigger': ('low', 'high')}
    has_flyback = True
    meta = {'name': 'Relay module (5 V, 1 channel)', 'category': 'Actuators',
            'aliases': ['relay', 'switch mains', 'contactor', 'srd-05vdc', 'load switch'],
            'interfaces': ['gpio'], 'supply': '5 V (~70 mA coil)', 'compat': 'supply', 'shape': 'relay',
            'footprint': [[i, 0] for i in range(3)],
            'description': 'Module with driver transistor and flyback diode. Most are active-LOW with an opto LED '
                           'from VCC to IN: a 3.3 V HIGH may not fully release it.'}

    def setup(self):
        self.energized = False

    def opto_current(self):
        result = self.circuit.element_result(f'{self.id}:opto')
        return result['i'] if result else 0.0

    def dynamic(self):
        if self.props['trigger'] == 'low':
            on = self.opto_current() > 0.0012
        else:
            on = self.v('IN') - self.v('GND') > 1.8
        self.energized = bool(on and self.operational())
        return (self.energized,)

    def elements(self):
        els = []
        if self.props['trigger'] == 'low':
            els += [('R', '@VCC', '@_opto', 1_000.0, 'opto-r'), ('D', '@_opto', '@IN', 1.2, 10.0, 'opto')]
        else:
            els.append(('R', '@IN', '@GND', 4_700.0, 'in'))
        if self.energized:
            els.append(('R', '@VCC', '@GND', 70.0, 'coil'))
        els += [('SW', '@COM', '@NO', self.energized, 0.05, 'no'), ('SW', '@COM', '@NC', not self.energized, 0.05, 'nc')]
        return els

    def check(self, volts):
        current = self.opto_current()
        if self.props['trigger'] == 'low' and 0.0002 < current < 0.0012 and self.v('IN') > 2.5:
            return [finding(f'relay-half:{self.id}', 'warning', f'{self.label} input is half-on',
                            f'IN is HIGH at {self.v("IN"):.1f} V but the opto LED still conducts {current * 1000:.2f} mA '
                            'from the 5 V supply.',
                            'Active-LOW 5 V modules turn off only when IN reaches about 5 V.',
                            'The relay may chatter or stay energized.',
                            [{'label': 'Drive IN with open drain or a transistor',
                              'steps': ['Set the pin open-drain (PINMODE_OD) so HIGH releases fully, '
                                        'or use an NPN to pull IN LOW.']}], parts=[self.id])]
        return []

    def state(self):
        return {'energized': self.energized}


class StepperBoard(Part):
    """28BYJ-48 stepper on a ULN2003 driver board."""
    kind = 'stepper'
    prefix = 'stp'
    pins = ('IN1', 'IN2', 'IN3', 'IN4', 'VCC', 'GND')
    inputs = ('IN1', 'IN2', 'IN3', 'IN4')
    supply = ('VCC', 'GND', 4.5, 5.5, 7.0)
    has_flyback = True
    meta = {'name': '28BYJ-48 stepper + ULN2003 board', 'category': 'Actuators',
            'aliases': ['stepper', 'step motor', '28byj-48', 'uln2003', 'position'],
            'interfaces': ['gpio'], 'supply': '5 V (~240 mA)', 'compat': 'supply', 'shape': 'stepper',
            'footprint': [[i, 0] for i in range(6)],
            'description': 'Energize IN1–IN4 in the half-step sequence 1,12,2,23,3,34,4,41. 4096 half-steps per turn.'}
    SEQUENCE = [0b0001, 0b0011, 0b0010, 0b0110, 0b0100, 0b1100, 0b1000, 0b1001]

    def setup(self):
        self.pattern = 0
        self.position = 0
        self.index = None

    def sense(self, volts, now):
        pattern = sum(int(volts[f'IN{n + 1}'] - self.v('GND') >= 2.0) << n for n in range(4))
        if pattern == self.pattern:
            return
        self.pattern = pattern
        if pattern in self.SEQUENCE and self.operational():
            index = self.SEQUENCE.index(pattern)
            if self.index is not None:
                step = (index - self.index) % 8
                if step in (1, 2):
                    self.position += step
                elif step in (6, 7):
                    self.position -= 8 - step
            self.index = index

    def dynamic(self):
        return (self.pattern,)

    def elements(self):
        els = [('R', f'@IN{n}', '@GND', 4_000.0, f'in{n}') for n in range(1, 5)]
        coils = bin(self.pattern).count('1')
        if coils:
            els.append(('R', '@VCC', '@GND', 50.0 / coils, 'coils'))
        return els

    def state(self):
        return {'angle': round(self.position * 360 / 4096, 2) % 360, 'steps': self.position}


class LCD1602(Part):
    kind = 'lcd1602'
    prefix = 'lcd'
    pins = ('VSS', 'VDD', 'V0', 'RS', 'RW', 'E', 'D0', 'D1', 'D2', 'D3', 'D4', 'D5', 'D6', 'D7', 'A', 'K')
    inputs = ('RS', 'E', 'D0', 'D1', 'D2', 'D3', 'D4', 'D5', 'D6', 'D7')
    supply = ('VDD', 'VSS', 4.5, 5.5, 7.0)
    meta = {'name': 'LCD 16×2 (HD44780, parallel)', 'category': 'Displays',
            'aliases': ['lcd', '1602', 'hd44780', 'character display', 'text', 'alphanumeric'],
            'interfaces': ['gpio'], 'supply': '5 V', 'compat': 'direct', 'shape': 'lcd1602',
            'footprint': [[i, 0] for i in range(16)],
            'description': '4-bit mode uses D4–D7 + RS + E (RW to GND). V0 sets contrast: wire it to a 10 kΩ pot '
                           'wiper (≈0.5 V); at 0 V or floating the text may be invisible or solid blocks.'}

    def setup(self):
        from ..displays import LCD
        self.lcd = LCD()
        self.last_e = 0

    def sense(self, volts, now):
        if not self.operational():
            self.lcd.observe(False, 0, 0, 0)
            return
        threshold = 0.5 * self.supply_voltage()
        level = {pin: int(v - self.v('VSS') >= threshold * 0.88) for pin, v in volts.items()}
        net = self.circuit.board.net_of
        eight_bit = all(len(net(self.node(f'D{i}')).nodes) > 1 for i in range(4))
        if eight_bit and self.last_e and not level['E']:
            byte = sum(level[f'D{i}'] << i for i in range(8))
            self.lcd.edges += 1
            self.lcd.write(byte, level['RS'])
            self.lcd.enable = 0
        elif not eight_bit:
            self.lcd.observe(True, level['E'], level['RS'], sum(level[f'D{i + 4}'] << i for i in range(4)))
        self.last_e = level['E']

    def elements(self):
        return [('R', '@VDD', '@VSS', 3_000.0, 'iq'), ('R', '@V0', '@VSS', 1e6, 'v0'),
                ('D', '@A', '@K', 3.0, 100.0, 'backlight')]

    def state(self):
        contrast = self.v('V0') - self.v('VSS')
        floating = len(self.circuit.board.net_of(self.node('V0')).nodes) <= 1
        visible = self.operational() and not floating and contrast < 1.6
        result = self.circuit.element_result(f'{self.id}:backlight') or {}
        return {'lines': self.lcd.lines(self.operational()), 'visible': visible,
                'contrast': round(contrast, 2), 'backlight': min(1.0, result.get('i', 0) / 0.015)}


class NeoPixel(Part):
    kind = 'ws2812'
    prefix = 'px'
    pins = ('DIN', 'VCC', 'GND', 'DOUT')
    inputs = ('DIN',)
    supply = ('VCC', 'GND', 3.5, 5.3, 6.0)
    defaults = {'count': 8}
    meta = {'name': 'WS2812B RGB LED strip (NeoPixel)', 'category': 'Outputs',
            'aliases': ['neopixel', 'ws2812', 'addressable', 'rgb strip', 'led strip'],
            'interfaces': ['single-wire'], 'supply': '5 V (60 mA per LED at full white)', 'compat': 'level-shift',
            'shape': 'strip', 'footprint': [[0, 0], [1, 0], [2, 0]],
            'description': '800 kHz one-wire timing: 0.4 µs HIGH = 0, 0.8 µs HIGH = 1, GRB order, >50 µs LOW latches. '
                           'Needs the Precise timing mode. At 5 V its input needs 3.5 V: 3.3 V data is marginal.'}

    def configured(self):
        if not 1 <= int(self.props['count']) <= 64:
            raise ValueError('count must be 1–64.')

    transient = {'bits': [], 'rise': None, 'fall': None, 'high': False}

    def setup(self):
        self.colors = [(0, 0, 0)] * int(self.props['count'])
        self.bits = []
        self.rise = None
        self.fall = None
        self.high = False
        self.errors = 0

    def sense(self, volts, now):
        vcc = self.supply_voltage()
        v = volts['DIN'] - self.v('GND')
        level = v >= 0.5 * vcc if vcc else False
        if level and not self.high:
            if self.fall is not None and now - self.fall > 50_000:
                self._latch()
            self.rise = now
            self.peak = v
        elif not level and self.high and self.rise is not None:
            width = now - self.rise
            bit = int(width > 550)
            # A HIGH below 0.7 x VCC is outside the input spec: some bits flip.
            if getattr(self, 'peak', vcc) < 0.7 * vcc and self.machine.rng.random() < 0.1:
                bit ^= 1
                self.errors += 1
            if width < 5_000:
                self.bits.append(bit)
            self.fall = now
        self.high = level

    def _latch(self):
        count = int(self.props['count'])
        colors = list(self.colors)
        for i in range(min(count, len(self.bits) // 24)):
            word = self.bits[i * 24:(i + 1) * 24]
            g, r, b = (sum(bit << (7 - k) for k, bit in enumerate(word[j * 8:(j + 1) * 8])) for j in range(3))
            colors[i] = (r, g, b)
        self.colors = colors
        self.bits = []

    def elements(self):
        lit = sum(sum(c) for c in self.colors) / 765 * 0.06
        return [('R', '@VCC', '@GND', 1 / max(0.001, lit + 0.0005 * len(self.colors)), 'load'),
                ('R', '@DIN', '@GND', 100_000.0, 'din')]

    def check(self, volts):
        vcc = self.supply_voltage()
        high = max(self.v('DIN'), 0)
        if vcc > 4.5 and self.errors:
            return [finding(f'ws-level:{self.id}', 'warning', f'{self.label}: data HIGH below 0.7×VCC',
                            f'At {vcc:.1f} V supply the strip needs {0.7 * vcc:.1f} V for HIGH; the 3.3 V MCU '
                            f'output gives about {max(high, 3.3):.1f} V. {self.errors} bits were misread.',
                            'WS2812 inputs are CMOS with thresholds relative to VDD.', 'Wrong or flickering colours.',
                            [{'label': 'Add a 74AHCT125 level shifter', 'steps': ['Or power the strip at 3.7–4 V.']}],
                            parts=[self.id])]
        return []

    def state(self):
        return {'colors': [f'#{r:02x}{g:02x}{b:02x}' for r, g, b in self.colors]}


class PowerModule(Part):
    kind = 'power_module'
    prefix = 'psu'
    pins = ('5V', '3V3', 'GND')
    source_pins = ('5V', '3V3')
    meta = {'name': 'Breadboard power supply (MB102)', 'category': 'Power',
            'aliases': ['power', 'supply', 'mb102', '5v', '3.3v', 'rails'],
            'interfaces': [], 'supply': 'outputs 5 V / 3.3 V', 'compat': 'supply', 'shape': 'module-psu',
            'footprint': [[0, 0], [1, 0], [3, 0]],
            'description': 'Plugs onto the breadboard rails and supplies 5 V and 3.3 V (~700 mA). '
                           'Join its GND to the board GND.'}

    def elements(self):
        return [('V', '@5V', '@GND', 5.0, 0.2, '5v'), ('V', '@3V3', '@GND', 3.3, 0.3, '3v3')]


class Battery(Part):
    kind = 'battery'
    prefix = 'bat'
    pins = ('+', '-')
    source_pins = ('+',)
    defaults = {'volts': 9.0}
    choices = {'volts': (1.5, 3.0, 3.7, 4.5, 6.0, 9.0, 12.0)}
    meta = {'name': 'Battery / pack', 'category': 'Power', 'aliases': ['battery', 'cell', 'aa', '9v', 'li-ion', 'lipo'],
            'interfaces': [], 'supply': '1.5–12 V', 'compat': 'supply', 'shape': 'battery',
            'footprint': [[0, 0], [1, 0]],
            'description': 'AA packs, 9 V and Li-ion cells, with internal resistance.'}

    def elements(self):
        volts = float(self.props['volts'])
        return [('V', '@+', '@-', volts, 1.5 if volts == 9.0 else 0.3, 'cell')]


class BenchSupply(Part):
    kind = 'bench_supply'
    prefix = 'bench'
    pins = ('+', '-')
    source_pins = ('+',)
    defaults = {'limit': 1.0}
    stimuli_spec = {'volts': (0.0, 15.0, 5.0, 'V', 'Output voltage')}
    meta = {'name': 'Bench power supply', 'category': 'Power', 'aliases': ['psu', 'lab supply', 'adjustable', 'power'],
            'interfaces': [], 'supply': '0–15 V', 'compat': 'supply', 'shape': 'module-psu',
            'footprint': [[0, 0], [1, 0]],
            'description': 'Adjustable voltage with a current limit indicator.'}

    def elements(self):
        return [('V', '@+', '@-', self.stimuli['volts'], 0.05, 'out')]

    def state(self):
        result = self.circuit.element_result(f'{self.id}:out') or {}
        current = result.get('i', 0.0)
        return {'current': current, 'limited': current > self.props['limit']}
