"""LEDs, diodes, transistors, level shifting, regulation and simple logic ICs."""
from __future__ import annotations

from .base import Part
from ..doctor import finding, series_resistor, ohms

LED_VF = {'red': 1.9, 'yellow': 2.0, 'orange': 2.0, 'green': 2.1, 'blue': 3.0, 'white': 3.0, 'ir': 1.3}


def led_finding(part, tag, current, i_max=0.020, i_abs=0.030):
    if current <= i_max * 1.05:
        return []
    severity = 'damage-risk' if current > i_abs else 'stress'
    value, i = series_resistor(3.3, part.vf(), 0.008)
    return [finding(f'led-current:{part.id}:{tag}', severity, f'{part.label}: {current * 1000:.0f} mA',
                    f'The LED carries {current * 1000:.0f} mA; it is rated {i_max * 1000:.0f} mA '
                    f'continuous, {i_abs * 1000:.0f} mA absolute.',
                    'Nothing in the circuit limits the current enough.',
                    'The LED burns out (goes open) if this continues.' if severity == 'damage-risk'
                    else 'It runs hot and its life shortens.',
                    [{'label': f'Add or increase the series resistor (≥ {ohms(value)})',
                      'steps': [f'{ohms(value)} gives about {i * 1000:.1f} mA from 3.3 V.']}],
                    parts=[part.id])]


class LED(Part):
    kind = 'led'
    prefix = 'led'
    pins = ('A', 'K')
    defaults = {'color': 'red'}
    choices = {'color': tuple(LED_VF)}
    damaged_behavior = 'A burnt-out LED is open circuit: it never lights again.'
    meta = {'name': 'LED (5 mm)', 'category': 'Outputs', 'aliases': ['light', 'diode', 'indicator', 'lamp'],
            'interfaces': ['gpio', 'pwm'], 'supply': '-', 'compat': 'direct', 'shape': 'led',
            'footprint': [[0, 0], [1, 0]],
            'description': 'Light-emitting diode. Long leg = anode (A). Always use a series resistor; '
                           'from an LPC1768 pin keep the current ≤ 4 mA (≥ 330 Ω).'}

    def vf(self, pin='A'):
        return LED_VF[self.props['color']]

    def diodes(self):
        return [('A', 'K')]

    def elements(self):
        if self.damaged:
            return []
        return [('D', '@A', '@K', self.vf(), 12.0, 'd')]

    def current(self):
        result = self.circuit.element_result(f'{self.id}:d')
        return result['i'] if result else 0.0

    def check(self, volts):
        return led_finding(self, 'd', self.current())

    def state(self):
        i = self.current()
        return {'current': i, 'brightness': min(1.0, i / 0.015), 'color': self.props['color']}


class RGBLed(Part):
    kind = 'rgb_led'
    prefix = 'rgb'
    pins = ('R', 'COM', 'G', 'B')
    defaults = {'common': 'cathode'}
    choices = {'common': ('cathode', 'anode')}
    damaged_behavior = 'The overdriven colour die is open circuit.'
    meta = {'name': 'RGB LED', 'category': 'Outputs', 'aliases': ['rgb', 'colour', 'color', 'tricolor'],
            'interfaces': ['pwm'], 'supply': '-', 'compat': 'direct', 'shape': 'led-rgb',
            'footprint': [[0, 0], [1, 0], [2, 0], [3, 0]],
            'description': 'Three LEDs in one package. Common cathode goes to GND; common anode to 3.3 V '
                           '(then a LOW pin lights the colour). One resistor per colour.'}
    VF = {'R': 1.9, 'G': 2.1, 'B': 3.0}

    def vf(self, pin='R'):
        return self.VF.get(pin, 2.0)

    def diodes(self):
        if self.props['common'] == 'cathode':
            return [(c, 'COM') for c in 'RGB']
        return [('COM', c) for c in 'RGB']

    def elements(self):
        if self.damaged:
            return []
        if self.props['common'] == 'cathode':
            return [('D', f'@{c}', '@COM', self.VF[c], 12.0, c) for c in 'RGB']
        return [('D', '@COM', f'@{c}', self.VF[c], 12.0, c) for c in 'RGB']

    def check(self, volts):
        found = []
        for c in 'RGB':
            result = self.circuit.element_result(f'{self.id}:{c}')
            if result:
                found += led_finding(self, c, result['i'])
        return found

    def state(self):
        out = {}
        for c in 'RGB':
            result = self.circuit.element_result(f'{self.id}:{c}') or {}
            out[c] = min(1.0, result.get('i', 0.0) / 0.015)
        return out


class Diode(Part):
    kind = 'diode'
    prefix = 'd'
    pins = ('A', 'K')
    defaults = {'model': '1N4007'}
    choices = {'model': ('1N4007', '1N4148', '1N5819')}
    VF = {'1N4007': 0.7, '1N4148': 0.65, '1N5819': 0.3}
    meta = {'name': 'Diode', 'category': 'Semiconductors', 'aliases': ['rectifier', 'flyback', 'schottky', '1n4007', '1n4148'],
            'interfaces': [], 'supply': '-', 'compat': 'direct', 'shape': 'axial-diode',
            'footprint': [[0, 0], [4, 0]],
            'description': 'Rectifier/signal/Schottky diode. Put one across every relay coil, motor or solenoid '
                           '(cathode band to the positive side).'}

    def elements(self):
        return [('D', '@A', '@K', self.VF[self.props['model']], 0.5, 'd')]


class Zener(Part):
    kind = 'zener'
    prefix = 'zd'
    pins = ('A', 'K')
    defaults = {'volts': 3.3}
    choices = {'volts': (3.3, 4.7, 5.1)}
    meta = {'name': 'Zener diode', 'category': 'Semiconductors', 'aliases': ['clamp', 'zener', 'protection'],
            'interfaces': [], 'supply': '-', 'compat': 'direct', 'shape': 'axial-diode',
            'footprint': [[0, 0], [4, 0]],
            'description': 'Clamps a signal at its Zener voltage (with a series resistor). A simple way to protect a 3.3 V input.'}

    def elements(self):
        return [('Z', '@A', '@K', 0.7, 2.0, float(self.props['volts']), 'z')]


class NPN(Part):
    kind = 'npn'
    prefix = 'q'
    pins = ('E', 'B', 'C')
    defaults = {'model': '2N2222'}
    choices = {'model': ('2N2222', 'BC547', '2N3904', 'TIP120')}
    BETA = {'2N2222': 150.0, 'BC547': 200.0, '2N3904': 150.0, 'TIP120': 1000.0}
    IMAX = {'2N2222': 0.8, 'BC547': 0.1, '2N3904': 0.2, 'TIP120': 5.0}
    meta = {'name': 'NPN transistor', 'category': 'Semiconductors', 'aliases': ['bjt', 'transistor', '2n2222', 'bc547', 'driver', 'switch'],
            'interfaces': ['gpio'], 'supply': '-', 'compat': 'direct', 'shape': 'to92',
            'footprint': [[0, 0], [1, 0], [2, 0]],
            'description': 'Low-side switch: emitter to GND, load between supply and collector, base through 1 kΩ from a pin.'}

    def elements(self):
        if self.damaged:
            return []
        return [('NPN', '@B', '@C', '@E', self.BETA[self.props['model']], 'q')]

    def check(self, volts):
        result = self.circuit.element_result(f'{self.id}:q') or {}
        limit = self.IMAX[self.props['model']]
        if result.get('i', 0) > limit:
            return [finding(f'bjt-current:{self.id}', 'damage-risk', f'{self.label} collector over current',
                            f'{result["i"]:.2f} A flows; the {self.props["model"]} is rated {limit} A.',
                            'The load needs more current than this transistor can carry.', 'It overheats and fails.',
                            [{'label': 'Use a bigger driver', 'steps': ['A logic-level MOSFET such as IRLZ44N, or a TIP120.']}],
                            parts=[self.id])]
        if result.get('ib', 0) > 0.02:
            return [finding(f'bjt-base:{self.id}', 'stress', f'{self.label} base current {result["ib"] * 1000:.0f} mA',
                            'The base has little or no series resistor.', 'Base current is limited only by the driving pin.',
                            'The MCU pin is overloaded.',
                            [{'label': 'Add a 1 kΩ base resistor', 'steps': ['About 2.6 mA base drive from 3.3 V.']}],
                            parts=[self.id])]
        return []

    def state(self):
        result = self.circuit.element_result(f'{self.id}:q') or {}
        return {'state': result.get('state', 'off'), 'current': result.get('i', 0.0)}


class PNP(NPN):
    kind = 'pnp'
    defaults = {'model': '2N3906'}
    choices = {'model': ('2N3906',)}
    BETA = {'2N3906': 150.0}
    IMAX = {'2N3906': 0.2}
    meta = {'name': 'PNP transistor', 'category': 'Semiconductors', 'aliases': ['bjt', 'transistor', '2n3906', 'high-side'],
            'interfaces': ['gpio'], 'supply': '-', 'compat': 'direct', 'shape': 'to92',
            'footprint': [[0, 0], [1, 0], [2, 0]],
            'description': 'High-side switch: emitter to the supply, load from collector to GND; pull the base LOW to turn on.'}

    def elements(self):
        if self.damaged:
            return []
        return [('PNP', '@B', '@C', '@E', self.BETA[self.props['model']], 'q')]


class MOSFET(Part):
    kind = 'nmos'
    prefix = 'q'
    pins = ('G', 'D', 'S')
    defaults = {'model': 'IRLZ44N'}
    choices = {'model': ('IRLZ44N', '2N7000', 'IRF540N')}
    VTH = {'IRLZ44N': 1.5, '2N7000': 2.1, 'IRF540N': 4.0}
    RON = {'IRLZ44N': 0.03, '2N7000': 2.0, 'IRF540N': 0.05}
    meta = {'name': 'N-channel MOSFET', 'category': 'Semiconductors', 'aliases': ['mosfet', 'fet', 'irlz44n', '2n7000', 'driver'],
            'interfaces': ['gpio', 'pwm'], 'supply': '-', 'compat': 'direct', 'shape': 'to220',
            'footprint': [[0, 0], [1, 0], [2, 0]],
            'description': 'Low-side switch for motors, LED strips and solenoids. Use a logic-level type (IRLZ44N) '
                           'with 3.3 V gate drive; IRF540N needs ~10 V to turn fully on.'}

    def elements(self):
        if self.damaged:
            return []
        model = self.props['model']
        return [('NMOS', '@G', '@D', '@S', self.VTH[model], self.RON[model], 'q'),
                ('D', '@S', '@D', 0.7, 0.5, 'body')]

    def check(self, volts):
        gate = self.v('G') - self.v('S')
        result = self.circuit.element_result(f'{self.id}:q') or {}
        if self.props['model'] == 'IRF540N' and 0 < gate < 6 and result.get('state') == 'on':
            return [finding(f'fet-gate:{self.id}', 'warning', f'{self.label} is barely on',
                            f'Gate drive is {gate:.1f} V; the IRF540N needs about 10 V to switch fully.',
                            'Standard MOSFETs are specified at Vgs = 10 V.', 'It runs hot and the load gets less voltage.',
                            [{'label': 'Use a logic-level MOSFET', 'steps': ['IRLZ44N is fully on at 3.3–5 V.']}],
                            parts=[self.id])]
        return []


class LevelShifter(Part):
    """Four BSS138 bidirectional channels with 10 kΩ pull-ups on each side."""
    kind = 'level_shifter'
    prefix = 'ls'
    pins = ('LV', 'HV', 'GND', 'LV1', 'LV2', 'LV3', 'LV4', 'HV1', 'HV2', 'HV3', 'HV4')
    meta = {'name': 'Logic level shifter (BSS138, 4-ch)', 'category': 'Semiconductors',
            'aliases': ['level converter', 'bss138', 'translator', '5v to 3.3v', 'bidirectional'],
            'interfaces': ['gpio', 'i2c', 'uart', 'spi'], 'supply': '3.3 V + 5 V', 'compat': 'direct', 'shape': 'module',
            'footprint': [[i, 0] for i in range(6)] + [[i, 3] for i in range(5)],
            'description': 'Connect LV to 3.3 V, HV to 5 V, GND to GND. Each LVn↔HVn pair translates in both '
                           'directions (I2C safe).'}

    def elements(self):
        els = []
        for n in range(1, 5):
            els += [('R', f'@LV{n}', '@LV', 10_000.0, f'lp{n}'), ('R', f'@HV{n}', '@HV', 10_000.0, f'hp{n}'),
                    ('NMOS', '@LV', f'@HV{n}', f'@LV{n}', 1.3, 5.0, f'q{n}'),
                    ('D', f'@LV{n}', f'@HV{n}', 0.7, 5.0, f'body{n}')]
        return els


class Regulator(Part):
    kind = 'regulator'
    prefix = 'reg'
    pins = ('IN', 'GND', 'OUT')
    defaults = {'model': 'AMS1117-3.3'}
    choices = {'model': ('AMS1117-3.3', 'LM7805')}
    source_pins = ('OUT',)
    meta = {'name': 'Voltage regulator', 'category': 'Power', 'aliases': ['ldo', 'ams1117', '7805', 'regulator', '3.3v'],
            'interfaces': [], 'supply': 'in 4.5–15 V', 'compat': 'supply', 'shape': 'to220',
            'footprint': [[0, 0], [1, 0], [2, 0]],
            'description': 'Linear regulator. AMS1117-3.3 makes 3.3 V from 5 V (1.1 V dropout); LM7805 makes 5 V from 7–35 V.'}

    def out_volts(self):
        target, dropout = (3.3, 1.1) if self.props['model'].startswith('AMS') else (5.0, 2.0)
        return max(0.0, min(target, self.v('IN') - self.v('GND') - dropout))

    def dynamic(self):
        return (round(self.out_volts(), 2),)

    def elements(self):
        return [('V', '@OUT', '@GND', self.out_volts(), 0.1, 'out'), ('R', '@IN', '@GND', 2_000.0, 'quiescent')]


class SevenSegment(Part):
    kind = 'seven_segment'
    prefix = 'seg'
    pins = ('a', 'b', 'c', 'd', 'e', 'f', 'g', 'dp', 'COM')
    defaults = {'common': 'cathode', 'color': 'red'}
    choices = {'common': ('cathode', 'anode'), 'color': ('red', 'green', 'blue')}
    damaged_behavior = 'Overdriven segments are open circuit.'
    meta = {'name': '7-segment display (single digit)', 'category': 'Displays', 'aliases': ['7seg', 'digit', 'numeric'],
            'interfaces': ['gpio'], 'supply': '-', 'compat': 'direct', 'shape': 'seven-segment',
            'footprint': [[0, 0], [1, 0], [2, 0], [3, 0], [4, 0], [0, 6], [1, 6], [2, 6], [3, 6]],
            'description': 'Eight LEDs (a–g, dp) sharing a common cathode (to GND) or anode (to 3.3 V). '
                           'One resistor per segment.'}

    def vf(self, pin='a'):
        return LED_VF[self.props['color']]

    def diodes(self):
        segments = self.pins[:8]
        return [(s, 'COM') for s in segments] if self.props['common'] == 'cathode' else [('COM', s) for s in segments]

    def elements(self):
        if self.damaged:
            return []
        return [('D', f'@{a}', f'@{k}', self.vf(), 15.0, a if a != 'COM' else k) for a, k in self.diodes()]

    def check(self, volts):
        found = []
        for s in self.pins[:8]:
            result = self.circuit.element_result(f'{self.id}:{s}')
            if result:
                found += led_finding(self, s, result['i'])
        return found

    def state(self):
        lit = {}
        for s in self.pins[:8]:
            result = self.circuit.element_result(f'{self.id}:{s}') or {}
            lit[s] = min(1.0, result.get('i', 0.0) / 0.01)
        return {'segments': lit, 'color': self.props['color']}


class ShiftRegister(Part):
    """74HC595: serial in, parallel out, clocked from SRCLK/RCLK rising edges."""
    kind = '74hc595'
    prefix = 'sr'
    pins = ('Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q6', 'Q7', 'GND', 'Q7S', 'MR', 'SHCP', 'STCP', 'OE', 'DS', 'Q0', 'VCC')
    inputs = ('DS', 'SHCP', 'STCP', 'MR', 'OE')
    supply = ('VCC', 'GND', 2.0, 6.0, 7.0)
    meta = {'name': '74HC595 shift register', 'category': 'Logic ICs', 'aliases': ['595', 'serial to parallel', 'shift', 'expander'],
            'interfaces': ['gpio', 'spi'], 'supply': '2–6 V', 'compat': 'direct', 'shape': 'dip16',
            'footprint': [[i, 0] for i in range(8)] + [[7 - i, -3] for i in range(8)],
            'description': 'Shift 8 bits in on DS with SHCP, latch them to Q0–Q7 with STCP. Tie MR to VCC and OE to GND. '
                           'Run it from 3.3 V so its inputs accept LPC1768 levels.'}

    def setup(self):
        self.shift = 0
        self.latch = 0
        self.last = {}

    def sense(self, volts, now):
        vcc = self.supply_voltage()
        if vcc < 1.5:
            return
        level = {pin: int(v - self.v('GND') >= 0.7 * vcc) for pin, v in volts.items()}
        rising = {pin for pin, l in level.items() if l and not self.last.get(pin, 1)}
        if not level['MR']:
            self.shift = 0
        if 'SHCP' in rising:
            self.shift = ((self.shift << 1) | level['DS']) & 0xFF
        if 'STCP' in rising:
            self.latch = self.shift
        self.last = level

    def dynamic(self):
        return (self.latch, self.shift >> 7, self.last.get('OE', 0))

    def elements(self):
        if not self.powered() or self.damaged:
            return []
        els = [self.output('Q7S', (self.shift >> 7) & 1, 50.0)]
        if not self.last.get('OE', 0):
            els += [self.output(f'Q{i}', (self.latch >> i) & 1, 50.0) for i in range(8)]
        return els

    def state(self):
        return {'outputs': self.latch}


class ULN2003(Part):
    """Seven Darlington low-side drivers with common flyback diodes (COM)."""
    kind = 'uln2003'
    prefix = 'u'
    pins = ('IN1', 'IN2', 'IN3', 'IN4', 'IN5', 'IN6', 'IN7', 'GND',
            'COM', 'OUT7', 'OUT6', 'OUT5', 'OUT4', 'OUT3', 'OUT2', 'OUT1')
    hidden = tuple(f'_b{n}' for n in range(1, 8))
    meta = {'name': 'ULN2003 Darlington driver', 'category': 'Drivers', 'aliases': ['darlington', 'uln2003', 'stepper driver', 'relay driver'],
            'interfaces': ['gpio'], 'supply': 'up to 50 V loads', 'compat': 'direct', 'shape': 'dip16',
            'footprint': [[i, 0] for i in range(8)] + [[7 - i, -3] for i in range(8)],
            'description': '500 mA sinks with built-in flyback diodes (tie COM to the load supply). '
                           'Inputs work from 3.3 V logic (2.7 kΩ base resistors).'}

    def elements(self):
        els = []
        for n in range(1, 8):
            els += [('R', f'@IN{n}', f'@_b{n}', 2_700.0, f'rs{n}'),
                    ('NPN', f'@_b{n}', f'@OUT{n}', '@GND', 1000.0, f'q{n}'),
                    ('D', f'@OUT{n}', '@COM', 0.7, 0.5, f'd{n}'),
                    ('R', f'@_b{n}', '@GND', 7_200.0, f'rb{n}')]
        return els
