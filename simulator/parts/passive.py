"""Breadboards, passives, switches and other user inputs."""
from __future__ import annotations

from .base import Part
from ..doctor import finding, ohms


class Breadboard(Part):
    kind = 'breadboard'
    prefix = 'bb'
    defaults = {'size': 'full'}
    choices = {'size': ('full', 'half', 'mini')}
    COLUMNS = {'full': 63, 'half': 30, 'mini': 17}
    meta = {'name': 'Breadboard', 'category': 'Prototyping', 'aliases': ['protoboard', 'solderless', '830', '400'],
            'interfaces': [], 'supply': '-', 'compat': 'direct', 'shape': 'breadboard',
            'description': 'Solderless breadboard. Holes a–e and f–j of each column are joined; the '
                           'center channel separates them. The + and − rails run the full length.'}

    def columns(self):
        return self.COLUMNS[self.props['size']]

    def hole_node(self, hole):
        """Node for a hole such as 'a12' (terminal strip) or 'tp3'/'bn7' (power rails)."""
        hole = hole.lower()
        if hole[:2] in ('tp', 'tn', 'bp', 'bn'):
            if self.props['size'] == 'mini':
                raise ValueError('A mini breadboard has no power rails.')
            index = hole[2:]
            if not index.isdigit() or not 1 <= int(index) <= self.columns():
                raise ValueError(f'No rail hole {hole} on {self.id}.')
            return f'{self.id}:{hole[:2].upper()}'
        row, column = hole[:1], hole[1:]
        if row not in 'abcdefghij' or not row or not column.isdigit() or not 1 <= int(column) <= self.columns():
            raise ValueError(f'No hole {hole} on {self.id}; rows a–j, columns 1–{self.columns()}.')
        return f'{self.id}:{int(column)}{"L" if row in "abcde" else "R"}'


class Resistor(Part):
    kind = 'resistor'
    prefix = 'r'
    pins = ('1', '2')
    defaults = {'ohms': 220.0, 'watts': 0.25}
    damaged_behavior = 'An overheated resistor goes open circuit or drifts far from its value.'
    meta = {'name': 'Resistor', 'category': 'Passives', 'aliases': ['res', 'ohm', 'pull-up', 'pull-down', 'divider'],
            'interfaces': ['analog'], 'supply': '-', 'compat': 'direct', 'shape': 'axial',
            'footprint': [[0, 0], [4, 0]],
            'description': 'Carbon film resistor (¼ W). Colour bands show the value.'}

    def elements(self):
        if self.damaged:
            return []
        return [('R', '@1', '@2', max(0.01, float(self.props['ohms'])), 'r')]

    def check(self, volts):
        result = self.circuit.element_result(f'{self.id}:r')
        if not result:
            return []
        power = result['p']
        rating = float(self.props['watts'])
        if power <= rating:
            return []
        severity = 'damage-risk' if power > 2 * rating else 'stress'
        return [finding(f'res-power:{self.id}', severity, f'{self.label} dissipates {power:.2f} W',
                        f'{power:.2f} W in a {rating:g} W resistor ({ohms(self.props["ohms"])}).',
                        'P = I²R turns into heat in the resistor body.',
                        'It overheats, discolours and fails open.',
                        [{'label': 'Use a larger resistor or a higher power rating',
                          'steps': [f'Choose a resistor rated above {power * 2:.1f} W, or increase its value.']}],
                        parts=[self.id])]

    def state(self):
        result = self.circuit.element_result(f'{self.id}:r') or {}
        return {'current': result.get('i', 0.0), 'power': result.get('p', 0.0)}


class Capacitor(Part):
    kind = 'capacitor'
    prefix = 'c'
    pins = ('+', '-')
    defaults = {'farads': 1e-5, 'volts': 25.0, 'polarized': True}
    damaged_behavior = 'A reversed or over-voltage electrolytic vents and shorts.'
    meta = {'name': 'Capacitor', 'category': 'Passives', 'aliases': ['cap', 'decoupling', 'electrolytic', 'ceramic'],
            'interfaces': ['analog'], 'supply': '-', 'compat': 'direct', 'shape': 'capacitor',
            'footprint': [[0, 0], [1, 0]],
            'description': 'Capacitor. Open circuit at DC; polarity and voltage rating are checked.'}

    def elements(self):
        if self.damaged:
            return [('R', '@+', '@-', 1.0, 'short')]
        return []

    def check(self, volts):
        v = self.v('+') - self.v('-')
        if self.props['polarized'] and v < -0.5:
            return [finding(f'cap-reverse:{self.id}', 'damage-risk', f'{self.label} is reversed',
                            f'The negative lead is {-v:.1f} V above the positive lead.',
                            'Electrolytic capacitors only tolerate one polarity.',
                            'Reverse voltage destroys the oxide layer; the capacitor vents.',
                            [{'label': 'Turn it around', 'steps': ['The stripe marks the negative lead.']}],
                            parts=[self.id])]
        if abs(v) > float(self.props['volts']):
            return [finding(f'cap-volts:{self.id}', 'damage-risk', f'{self.label} over its voltage rating',
                            f'{abs(v):.1f} V across a {self.props["volts"]:g} V capacitor.',
                            'The dielectric breaks down above the rated voltage.', 'It shorts.',
                            [{'label': 'Use a higher voltage rating', 'steps': ['Pick at least 1.5× the circuit voltage.']}],
                            parts=[self.id])]
        return []


class Potentiometer(Part):
    kind = 'potentiometer'
    prefix = 'pot'
    pins = ('1', 'W', '3')
    defaults = {'ohms': 10_000.0}
    stimuli_spec = {'position': (0.0, 1.0, 0.5, '', 'Knob position')}
    meta = {'name': 'Potentiometer', 'category': 'Inputs', 'aliases': ['pot', 'knob', 'trimmer', 'variable resistor'],
            'interfaces': ['analog', 'adc'], 'supply': '-', 'compat': 'direct', 'shape': 'pot',
            'footprint': [[0, 0], [1, 0], [2, 0]],
            'description': 'Rotary potentiometer. Wire the ends to 3.3 V and GND and read the wiper with the ADC.'}

    def elements(self):
        total = max(1.0, float(self.props['ohms']))
        position = self.stimuli['position']
        return [('R', '@1', '@W', max(0.5, total * position), 'a'),
                ('R', '@W', '@3', max(0.5, total * (1 - position)), 'b')]


class PushButton(Part):
    kind = 'button'
    prefix = 'sw'
    pins = ('1', '2', '3', '4')
    internal = (('1', '2'), ('3', '4'))
    stimuli_spec = {'pressed': (0, 1, 0, '', 'Pressed')}
    meta = {'name': 'Push button', 'category': 'Inputs', 'aliases': ['tactile', 'switch', 'momentary', 'tact'],
            'interfaces': ['gpio'], 'supply': '-', 'compat': 'direct', 'shape': 'button',
            'footprint': [[0, 0], [0, 2], [3, 0], [3, 2]],
            'description': '6 mm tactile switch. Pins 1–2 and 3–4 are always joined; pressing joins both pairs. '
                           'Use a pull-up (PINMODE) and read LOW when pressed.'}

    def elements(self):
        return [('SW', '@2', '@3', bool(self.stimuli['pressed']), 0.05, 'contact')]

    def state(self):
        return {'pressed': bool(self.stimuli['pressed'])}


class Switch(Part):
    kind = 'switch'
    prefix = 'sw'
    pins = ('COM', 'A', 'B')
    defaults = {'style': 'slide'}
    choices = {'style': ('slide', 'toggle', 'reed', 'tilt', 'limit')}
    stimuli_spec = {'position': (0, 1, 0, '', 'Position (0 = A, 1 = B)')}
    meta = {'name': 'Switch (SPDT)', 'category': 'Inputs', 'aliases': ['slide', 'toggle', 'reed', 'tilt', 'limit', 'spdt'],
            'interfaces': ['gpio'], 'supply': '-', 'compat': 'direct', 'shape': 'switch',
            'footprint': [[0, 0], [1, 0], [2, 0]],
            'description': 'Single-pole double-throw switch: COM connects to A or B. Reed/tilt/limit styles '
                           'are actuated by a magnet, tilt or contact.'}

    def elements(self):
        b = bool(self.stimuli['position'])
        return [('SW', '@COM', '@A', not b, 0.05, 'a'), ('SW', '@COM', '@B', b, 0.05, 'b')]

    def state(self):
        return {'position': int(self.stimuli['position'])}


class Keypad(Part):
    kind = 'keypad'
    prefix = 'kp'
    pins = ('R1', 'R2', 'R3', 'R4', 'C1', 'C2', 'C3', 'C4')
    defaults = {'layout': '4x4'}
    choices = {'layout': ('4x4', '4x3')}
    stimuli_spec = {'key': (-1, 15, -1, '', 'Pressed key index (−1 = none)')}
    meta = {'name': 'Membrane keypad', 'category': 'Inputs', 'aliases': ['matrix', 'keyboard', '4x4', '4x3', 'keys'],
            'interfaces': ['gpio'], 'supply': '-', 'compat': 'direct', 'shape': 'keypad',
            'footprint': [[i, 0] for i in range(8)],
            'description': 'Row/column switch matrix. Drive one row LOW at a time and read the columns with pull-ups.'}
    LABELS = {'4x4': '123A456B789C*0#D', '4x3': '123456789*0#'}

    def elements(self):
        key = int(self.stimuli['key'])
        cols = 4 if self.props['layout'] == '4x4' else 3
        if key < 0 or key >= 4 * cols:
            return []
        return [('SW', f'@R{key // cols + 1}', f'@C{key % cols + 1}', True, 0.1, 'key')]

    def state(self):
        return {'key': int(self.stimuli['key']), 'labels': self.LABELS[self.props['layout']]}


class Joystick(Part):
    kind = 'joystick'
    prefix = 'js'
    pins = ('GND', 'VCC', 'VRX', 'VRY', 'SW')
    supply = ('VCC', 'GND', 0.0, 5.5, 6.0)
    stimuli_spec = {'x': (0.0, 1.0, 0.5, '', 'X axis'), 'y': (0.0, 1.0, 0.5, '', 'Y axis'),
                    'pressed': (0, 1, 0, '', 'Button')}
    meta = {'name': 'Analog joystick (KY-023)', 'category': 'Inputs', 'aliases': ['thumbstick', 'ky-023', 'xy'],
            'interfaces': ['adc', 'gpio'], 'supply': '3.3–5 V', 'compat': 'divider-if-5v', 'shape': 'module',
            'footprint': [[i, 0] for i in range(5)],
            'description': 'Two 10 kΩ pots and a push switch to GND. Power from 3.3 V so VRX/VRY stay inside the ADC range.'}

    def elements(self):
        els = []
        for axis, pin in (('x', 'VRX'), ('y', 'VRY')):
            p = self.stimuli[axis]
            els += [('R', '@VCC', f'@{pin}', max(1.0, 10_000 * (1 - p)), f'{axis}a'),
                    ('R', f'@{pin}', '@GND', max(1.0, 10_000 * p), f'{axis}b')]
        els.append(('SW', '@SW', '@GND', bool(self.stimuli['pressed']), 0.1, 'sw'))
        return els


class RotaryEncoder(Part):
    """KY-040 style incremental encoder with on-board pull-ups; quadrature on CLK/DT."""
    kind = 'encoder'
    prefix = 'enc'
    pins = ('GND', 'VCC', 'SW', 'DT', 'CLK')
    supply = ('VCC', 'GND', 3.0, 5.5, 6.0)
    stimuli_spec = {'step': (-1000, 1000, 0, 'detents', 'Position'), 'pressed': (0, 1, 0, '', 'Push')}
    meta = {'name': 'Rotary encoder (KY-040)', 'category': 'Inputs', 'aliases': ['knob', 'quadrature', 'ky-040', 'qei'],
            'interfaces': ['gpio', 'qei'], 'supply': '3.3–5 V', 'compat': 'direct', 'shape': 'module',
            'footprint': [[i, 0] for i in range(5)],
            'description': 'Each detent produces one full quadrature cycle on CLK and DT. Works with GPIO '
                           'interrupts or the LPC1768 QEI (MCI0/MCI1).'}

    def setup(self):
        self.phase = 0
        self.position = 0

    def stimulated(self, name):
        if name != 'step':
            return
        target = int(self.stimuli['step'])
        delta = target - self.position
        self.position = target
        direction = 1 if delta > 0 else -1
        for k in range(abs(delta) * 4):
            self.schedule_in(200_000 * (k + 1), lambda d=direction: self._advance(d))

    def _advance(self, direction):
        self.phase = (self.phase + direction) % 4
        self.changed()

    def dynamic(self):
        return (self.phase,)

    def elements(self):
        clk, dt = ((0, 0), (1, 0), (1, 1), (0, 1))[self.phase]
        els = [('R', '@CLK', '@VCC', 10_000.0, 'clk-pull'), ('R', '@DT', '@VCC', 10_000.0, 'dt-pull'),
               ('R', '@SW', '@VCC', 10_000.0, 'sw-pull')]
        if not clk:
            els.append(('R', '@CLK', '@GND', 10.0, 'clk'))
        if not dt:
            els.append(('R', '@DT', '@GND', 10.0, 'dt'))
        if self.stimuli['pressed']:
            els.append(('R', '@SW', '@GND', 10.0, 'sw'))
        return els

    def state(self):
        return {'position': self.position}
