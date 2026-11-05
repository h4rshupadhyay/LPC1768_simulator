"""Analog and digital sensors, and generic signal sources."""
from __future__ import annotations

import math

from .base import Part
from ..doctor import finding


class LDR(Part):
    kind = 'ldr'
    prefix = 'ldr'
    pins = ('1', '2')
    stimuli_spec = {'lux': (0.1, 100_000.0, 300.0, 'lx', 'Light')}
    meta = {'name': 'Photoresistor (LDR)', 'category': 'Sensors', 'aliases': ['light', 'ldr', 'photocell', 'gl5528', 'brightness'],
            'interfaces': ['adc'], 'supply': '-', 'compat': 'direct', 'shape': 'ldr', 'footprint': [[0, 0], [1, 0]],
            'description': 'Resistance falls with light (GL5528: ~10 kΩ at 10 lx, ~1 MΩ dark). '
                           'Put it in a divider with 10 kΩ and read the middle with the ADC.'}

    def ohms(self):
        return min(1_000_000.0, 10_000.0 * (max(self.stimuli['lux'], 0.1) / 10) ** -0.7)

    def elements(self):
        return [('R', '@1', '@2', self.ohms(), 'r')]

    def state(self):
        return {'ohms': self.ohms()}


class Thermistor(Part):
    kind = 'thermistor'
    prefix = 'th'
    pins = ('1', '2')
    defaults = {'r25': 10_000.0, 'beta': 3950.0}
    stimuli_spec = {'celsius': (-40.0, 125.0, 25.0, '°C', 'Temperature')}
    meta = {'name': 'NTC thermistor 10 kΩ', 'category': 'Sensors', 'aliases': ['ntc', 'temperature', 'thermistor'],
            'interfaces': ['adc'], 'supply': '-', 'compat': 'direct', 'shape': 'thermistor', 'footprint': [[0, 0], [1, 0]],
            'description': 'Resistance falls as it warms (B = 3950). Use a 10 kΩ divider; convert with the Beta equation.'}

    def ohms(self):
        t = self.stimuli['celsius'] + 273.15
        return self.props['r25'] * math.exp(self.props['beta'] * (1 / t - 1 / 298.15))

    def elements(self):
        return [('R', '@1', '@2', self.ohms(), 'r')]


class LM35(Part):
    kind = 'lm35'
    prefix = 'lm'
    pins = ('VS', 'VOUT', 'GND')
    supply = ('VS', 'GND', 4.0, 30.0, 35.0)
    stimuli_spec = {'celsius': (-55.0, 150.0, 25.0, '°C', 'Temperature')}
    damaged_behavior = 'Output stuck near 0 V.'
    meta = {'name': 'LM35 temperature sensor', 'category': 'Sensors', 'aliases': ['temperature', 'lm35', 'thermometer'],
            'interfaces': ['adc'], 'supply': '4–30 V', 'compat': 'direct', 'shape': 'to92', 'footprint': [[0, 0], [1, 0], [2, 0]],
            'description': '10 mV/°C, 0 V at 0 °C. Needs at least 4 V supply: from 3.3 V it does not work properly. '
                           'Output stays below 1.5 V, safe for the ADC.'}

    def elements(self):
        if self.damaged or not self.powered():
            return [('R', '@VOUT', '@GND', 1e6, 'idle')]
        return [('V', '@VOUT', '@GND', max(0.0, 0.01 * self.stimuli['celsius']), 1.0, 'out'),
                ('R', '@VS', '@GND', 60_000.0, 'iq')]


class TMP36(LM35):
    kind = 'tmp36'
    prefix = 'tmp'
    supply = ('VS', 'GND', 2.7, 5.5, 6.0)
    stimuli_spec = {'celsius': (-40.0, 125.0, 25.0, '°C', 'Temperature')}
    meta = {'name': 'TMP36 temperature sensor', 'category': 'Sensors', 'aliases': ['temperature', 'tmp36', 'thermometer'],
            'interfaces': ['adc'], 'supply': '2.7–5.5 V', 'compat': 'direct', 'shape': 'to92', 'footprint': [[0, 0], [1, 0], [2, 0]],
            'description': '0.5 V at 0 °C, 10 mV/°C. Runs from 3.3 V.'}

    def elements(self):
        if self.damaged or not self.powered():
            return [('R', '@VOUT', '@GND', 1e6, 'idle')]
        return [('V', '@VOUT', '@GND', 0.5 + 0.01 * self.stimuli['celsius'], 1.0, 'out'),
                ('R', '@VS', '@GND', 60_000.0, 'iq')]


class AnalogModule(Part):
    """Sensor board with an analog output and an LM393 comparator output (active LOW)."""
    kind = 'analog_module'
    prefix = 'mod'
    pins = ('VCC', 'GND', 'DO', 'AO')
    supply = ('VCC', 'GND', 3.3, 5.5, 6.0)
    stimulus = 'level'
    stimuli_spec = {'level': (0.0, 1.0, 0.2, '', 'Sensed level'), 'threshold': (0.0, 1.0, 0.5, '', 'Trim pot')}
    heater_ohms = None
    meta = {'name': 'Analog sensor module', 'category': 'Sensors', 'aliases': ['module', 'lm393'], 'interfaces': ['adc', 'gpio'],
            'supply': '3.3–5 V', 'compat': 'divider-if-5v', 'shape': 'module', 'footprint': [[i, 0] for i in range(4)],
            'description': 'AO swings 0–VCC: from a 5 V supply it needs a divider before an ADC pin. '
                           'DO goes LOW when the level passes the trim-pot threshold.'}

    def fraction(self):
        return self.stimuli[self.stimulus]

    def elements(self):
        els = [('R', '@DO', '@VCC', 10_000.0, 'do-pull')]
        if self.heater_ohms:
            els.append(('R', '@VCC', '@GND', self.heater_ohms, 'heater'))
        if self.damaged or not self.powered():
            return els
        level = self.fraction()
        vcc = self.supply_voltage()
        els.append(('V', '@AO', '@GND', min(vcc, max(0.0, level * vcc)), 1_000.0, 'ao'))
        if level >= self.stimuli['threshold']:
            els.append(('R', '@DO', '@GND', 20.0, 'do'))
        return els

    def dynamic(self):
        return (round(self.supply_voltage(), 2),)

    def state(self):
        return {'triggered': self.fraction() >= self.stimuli['threshold']}


class GasSensor(AnalogModule):
    kind = 'mq2'
    prefix = 'mq'
    supply = ('VCC', 'GND', 4.5, 5.5, 6.0)
    heater_ohms = 33.0
    stimuli_spec = {'ppm': (200.0, 10_000.0, 300.0, 'ppm', 'Gas concentration'),
                    'threshold': (0.0, 1.0, 0.5, '', 'Trim pot')}
    meta = {'name': 'MQ-2 gas sensor module', 'category': 'Sensors', 'aliases': ['gas', 'smoke', 'lpg', 'mq2', 'mq-135', 'air quality'],
            'interfaces': ['adc', 'gpio'], 'supply': '5 V (heater ~150 mA)', 'compat': 'divider', 'shape': 'module-gas',
            'footprint': [[i, 0] for i in range(4)],
            'description': 'Heated sensor: needs 5 V and ~150 mA. AO rises toward 5 V with gas, so put a divider '
                           '(e.g. 10 kΩ / 20 kΩ) between AO and an ADC pin.'}

    def fraction(self):
        ppm = self.stimuli['ppm']
        return min(0.95, 0.08 + 0.87 * math.log10(ppm / 200) / math.log10(50))


class SoilMoisture(AnalogModule):
    kind = 'soil_moisture'
    prefix = 'soil'
    stimuli_spec = {'moisture': (0.0, 1.0, 0.4, '', 'Moisture'), 'threshold': (0.0, 1.0, 0.5, '', 'Trim pot')}
    stimulus = 'moisture'
    meta = {'name': 'Soil moisture sensor', 'category': 'Sensors', 'aliases': ['soil', 'moisture', 'water', 'humidity', 'rain'],
            'interfaces': ['adc', 'gpio'], 'supply': '3.3–5 V', 'compat': 'divider-if-5v', 'shape': 'module',
            'footprint': [[i, 0] for i in range(4)],
            'description': 'Resistive probe with comparator board. Power it from 3.3 V for a direct ADC connection.'}

    def fraction(self):
        return 1 - self.stimuli['moisture']


class SoundSensor(AnalogModule):
    kind = 'sound_sensor'
    prefix = 'mic'
    stimuli_spec = {'loudness': (0.0, 1.0, 0.1, '', 'Loudness'), 'threshold': (0.0, 1.0, 0.5, '', 'Trim pot')}
    stimulus = 'loudness'
    meta = {'name': 'Sound sensor (KY-038)', 'category': 'Sensors', 'aliases': ['microphone', 'sound', 'clap', 'noise', 'ky-038'],
            'interfaces': ['adc', 'gpio'], 'supply': '3.3–5 V', 'compat': 'divider-if-5v', 'shape': 'module',
            'footprint': [[i, 0] for i in range(4)], 'description': 'Electret microphone with a comparator output.'}


class FlameSensor(AnalogModule):
    kind = 'flame_sensor'
    prefix = 'fl'
    stimuli_spec = {'flame': (0.0, 1.0, 0.0, '', 'IR intensity'), 'threshold': (0.0, 1.0, 0.5, '', 'Trim pot')}
    stimulus = 'flame'
    meta = {'name': 'Flame sensor (IR)', 'category': 'Sensors', 'aliases': ['fire', 'flame', 'ir'],
            'interfaces': ['adc', 'gpio'], 'supply': '3.3–5 V', 'compat': 'divider-if-5v', 'shape': 'module',
            'footprint': [[i, 0] for i in range(4)], 'description': 'IR photodiode with a comparator output.'}


class SharpIR(Part):
    kind = 'sharp_ir'
    prefix = 'ir'
    pins = ('VO', 'GND', 'VCC')
    supply = ('VCC', 'GND', 4.5, 5.5, 7.0)
    stimuli_spec = {'distance_cm': (5.0, 100.0, 30.0, 'cm', 'Distance')}
    meta = {'name': 'Sharp GP2Y0A21 IR distance', 'category': 'Sensors', 'aliases': ['distance', 'proximity', 'infrared', 'range'],
            'interfaces': ['adc'], 'supply': '5 V', 'compat': 'direct', 'shape': 'module-sharp',
            'footprint': [[0, 0], [1, 0], [2, 0]],
            'description': '10–80 cm. Output 0.4–3.1 V (inversely related to distance), so it is ADC-safe even on a 5 V supply.'}

    def volts(self):
        d = max(self.stimuli['distance_cm'], 6.0)
        return min(3.1, max(0.4, (27.86 / d) ** (1 / 1.15)))

    def elements(self):
        els = [('R', '@VCC', '@GND', 165.0, 'iq')]
        if self.powered() and not self.damaged:
            els.append(('V', '@VO', '@GND', self.volts(), 100.0, 'out'))
        return els


class CurrentSensor(Part):
    kind = 'acs712'
    prefix = 'cs'
    pins = ('IP+', 'IP-', 'VCC', 'OUT', 'GND')
    supply = ('VCC', 'GND', 4.5, 5.5, 8.0)
    meta = {'name': 'ACS712 current sensor (5 A)', 'category': 'Sensors', 'aliases': ['current', 'amps', 'hall', 'acs712', 'power'],
            'interfaces': ['adc'], 'supply': '5 V', 'compat': 'divider', 'shape': 'module',
            'footprint': [[i, 0] for i in range(5)],
            'description': 'Measures current through IP+→IP−: OUT = VCC/2 + 185 mV/A. The 2.5 V midpoint and '
                           'swing up to 5 V need a divider for the ADC.'}

    def amps(self):
        result = self.circuit.element_result(f'{self.id}:shunt')
        return result['i'] if result else 0.0

    def dynamic(self):
        return (round(self.amps(), 3),)

    def elements(self):
        els = [('R', '@IP+', '@IP-', 0.0012, 'shunt'), ('R', '@VCC', '@GND', 500.0, 'iq')]
        if self.powered():
            v = self.supply_voltage()
            els.append(('V', '@OUT', '@GND', min(v, max(0.0, v / 2 + 0.185 * self.amps())), 100.0, 'out'))
        return els


class Accelerometer(Part):
    kind = 'adxl335'
    prefix = 'acc'
    pins = ('VCC', 'X', 'Y', 'Z', 'GND')
    supply = ('VCC', 'GND', 1.8, 3.6, 3.9)
    stimuli_spec = {'x': (-3.0, 3.0, 0.0, 'g', 'X'), 'y': (-3.0, 3.0, 0.0, 'g', 'Y'), 'z': (-3.0, 3.0, 1.0, 'g', 'Z')}
    damaged_behavior = 'All outputs stuck at 0 V.'
    meta = {'name': 'ADXL335 accelerometer', 'category': 'Sensors', 'aliases': ['accelerometer', 'tilt', 'motion', 'gyro', 'adxl335'],
            'interfaces': ['adc'], 'supply': '1.8–3.6 V', 'compat': 'direct', 'shape': 'module',
            'footprint': [[i, 0] for i in range(5)],
            'description': 'Three ratiometric analog axes: VCC/2 at 0 g, ~300 mV/g at 3 V. 3.3 V only.'}

    def elements(self):
        if self.damaged or not self.powered():
            return [('R', '@VCC', '@GND', 10_000.0, 'iq')]
        v = self.supply_voltage()
        return [('R', '@VCC', '@GND', 10_000.0, 'iq')] + [
            ('V', f'@{axis.upper()}', '@GND', min(v, max(0.0, v / 2 + self.stimuli[axis] * 0.1 * v)), 32_000.0, axis)
            for axis in 'xyz']


class AnalogSource(Part):
    kind = 'analog_source'
    prefix = 'src'
    pins = ('OUT', 'GND')
    defaults = {'ohms': 100.0}
    stimuli_spec = {'volts': (0.0, 12.0, 1.0, 'V', 'Output voltage')}
    source_pins = ('OUT',)
    meta = {'name': 'Generic analog source', 'category': 'Generic', 'aliases': ['voltage', 'analog', 'generic sensor', 'signal', 'source'],
            'interfaces': ['adc'], 'supply': '-', 'compat': 'divider-if-5v', 'shape': 'module',
            'footprint': [[0, 0], [1, 0]],
            'description': 'Stands in for any analog sensor: a set voltage behind an output resistance.'}

    def elements(self):
        return [('V', '@OUT', '@GND', self.stimuli['volts'], max(0.01, float(self.props['ohms'])), 'out')]


class SignalGenerator(Part):
    kind = 'signal_generator'
    prefix = 'gen'
    pins = ('OUT', 'GND')
    defaults = {'high': 3.3}
    stimuli_spec = {'hz': (0.0, 20_000.0, 1.0, 'Hz', 'Frequency (0 = steady)'), 'duty': (0.0, 1.0, 0.5, '', 'Duty'),
                    'level': (0, 1, 0, '', 'Steady level')}
    meta = {'name': 'Signal generator', 'category': 'Generic', 'aliases': ['clock', 'square wave', 'pulse', 'generic digital', 'frequency'],
            'interfaces': ['gpio', 'capture'], 'supply': '-', 'compat': 'direct', 'shape': 'module',
            'footprint': [[0, 0], [1, 0]],
            'description': 'Square wave or steady logic level for testing capture, counters and interrupts.'}

    def setup(self):
        self.out = 0
        self.epoch = 0

    def reset_transient(self):
        self.stimulated('hz')

    def stimulated(self, name):
        self.epoch += 1
        self.out = int(self.stimuli['level']) if not self.stimuli['hz'] else 1
        if self.stimuli['hz']:
            self._toggle(self.epoch)

    def _toggle(self, epoch):
        if epoch != self.epoch or not self.stimuli['hz']:
            return
        period = 1e9 / self.stimuli['hz']
        duty = min(0.99, max(0.01, self.stimuli['duty']))
        self.out ^= 1
        self.changed()
        self.schedule_in(period * (duty if self.out else 1 - duty), lambda: self._toggle(epoch))

    def dynamic(self):
        return (self.out,)

    def elements(self):
        return [('V', '@OUT', '@GND', float(self.props['high']) if self.out else 0.0, 50.0, 'out')]


class HCSR04(Part):
    kind = 'hcsr04'
    prefix = 'sonar'
    pins = ('VCC', 'TRIG', 'ECHO', 'GND')
    inputs = ('TRIG',)
    supply = ('VCC', 'GND', 4.5, 5.5, 6.0)
    stimuli_spec = {'distance_cm': (2.0, 400.0, 50.0, 'cm', 'Distance to object')}
    damaged_behavior = 'No echo pulses.'
    meta = {'name': 'HC-SR04 ultrasonic sensor', 'category': 'Sensors', 'aliases': ['ultrasonic', 'sonar', 'distance', 'range', 'hc-sr04'],
            'interfaces': ['gpio', 'capture'], 'supply': '5 V', 'compat': 'divider', 'shape': 'module-sonar',
            'footprint': [[i, 0] for i in range(4)],
            'description': 'Pulse TRIG HIGH for 10 µs; ECHO then goes HIGH for 58 µs per cm. ECHO is a 5 V signal: '
                           'fine on a 5 V-tolerant GPIO, but use a divider (10 kΩ/18 kΩ) to be safe and for analog pins.'}

    transient = {'echo': 0, 'trigger_start': None, 'busy': False}

    def setup(self):
        self.echo = 0
        self.trigger_start = None
        self.busy = False
        self.pulses = 0

    def sense(self, volts, now):
        high = volts['TRIG'] - self.v('GND') >= 2.0 and self.operational()
        if high and self.trigger_start is None:
            self.trigger_start = now
        elif not high and self.trigger_start is not None:
            width = now - self.trigger_start
            self.trigger_start = None
            if width >= 10_000 and not self.busy:
                self.busy = True
                self.schedule_in(250_000, self._echo_start)
            elif width < 10_000:
                self.circuit.machine.note(f'part:{self.id}:trig', f'{self.label}: TRIG pulse was {width / 1000:.1f} µs; '
                                          'it must be at least 10 µs.')

    def _echo_start(self):
        distance = self.stimuli['distance_cm']
        width = 38_000_000 if distance > 400 else int(distance * 58_300)
        self.echo = 1
        self.pulses += 1
        self.changed()
        self.schedule_in(width, self._echo_end)

    def _echo_end(self):
        self.echo = 0
        self.busy = False
        self.changed()

    def dynamic(self):
        return (self.echo,)

    def elements(self):
        els = [('R', '@VCC', '@GND', 330.0, 'iq'), ('R', '@TRIG', '@GND', 10_000.0, 'trig-pd')]
        if self.powered() and not self.damaged:
            els.append(self.output('ECHO', self.echo, 100.0))
        return els

    def state(self):
        return {'echo': self.echo, 'pulses': self.pulses}


class PIR(Part):
    kind = 'pir'
    prefix = 'pir'
    pins = ('VCC', 'OUT', 'GND')
    supply = ('VCC', 'GND', 4.5, 20.0, 24.0)
    stimuli_spec = {'motion': (0, 1, 0, '', 'Motion detected')}
    meta = {'name': 'PIR motion sensor (HC-SR501)', 'category': 'Sensors', 'aliases': ['motion', 'pir', 'presence', 'occupancy', 'hc-sr501'],
            'interfaces': ['gpio'], 'supply': '4.5–20 V', 'compat': 'direct', 'shape': 'module-pir',
            'footprint': [[0, 0], [1, 0], [2, 0]],
            'description': 'Powered from 5 V, but its OUT is a 3.3 V logic signal: connect directly to a GPIO input.'}

    def elements(self):
        els = [('R', '@VCC', '@GND', 100_000.0, 'iq')]
        if self.powered() and not self.damaged:
            els.append(('V', '@OUT', '@GND', 3.3 if self.stimuli['motion'] else 0.0, 200.0, 'out'))
        return els


class HallSwitch(Part):
    kind = 'hall_switch'
    prefix = 'hall'
    pins = ('VCC', 'GND', 'OUT')
    supply = ('VCC', 'GND', 4.5, 24.0, 28.0)
    stimuli_spec = {'magnet': (0, 1, 0, '', 'Magnet near')}
    meta = {'name': 'Hall switch (A3144)', 'category': 'Sensors', 'aliases': ['hall', 'magnet', 'a3144', 'rpm'],
            'interfaces': ['gpio'], 'supply': '4.5–24 V', 'compat': 'direct', 'shape': 'to92',
            'footprint': [[0, 0], [1, 0], [2, 0]],
            'description': 'Open-collector output pulls LOW near a magnet; needs a pull-up (10 kΩ to 3.3 V).'}

    def elements(self):
        els = [('R', '@VCC', '@GND', 1_000.0, 'iq')]
        if self.powered() and self.stimuli['magnet'] and not self.damaged:
            els.append(('R', '@OUT', '@GND', 20.0, 'out'))
        return els


class DHT(Part):
    kind = 'dht'
    prefix = 'dht'
    pins = ('VCC', 'DATA', 'NC', 'GND')
    inputs = ('DATA',)
    defaults = {'model': 'DHT11', 'pullup': True}
    choices = {'model': ('DHT11', 'DHT22')}
    supply = ('VCC', 'GND', 3.0, 5.5, 6.0)
    stimuli_spec = {'celsius': (-40.0, 80.0, 24.0, '°C', 'Temperature'), 'humidity': (0.0, 100.0, 55.0, '%', 'Humidity')}
    damaged_behavior = 'No response to start signals.'
    meta = {'name': 'DHT11 / DHT22 temperature & humidity', 'category': 'Sensors',
            'aliases': ['humidity', 'temperature', 'dht11', 'dht22', 'am2302', 'weather'],
            'interfaces': ['single-wire'], 'supply': '3.3–5 V', 'compat': 'direct', 'shape': 'module-dht',
            'footprint': [[i, 0] for i in range(4)],
            'description': 'Pull DATA LOW (18 ms DHT11, 1 ms DHT22), release, then time 40 bits: 26–28 µs HIGH = 0, '
                           '70 µs HIGH = 1. Needs a pull-up (built into the module version).'}

    transient = {'low': False, 'sending': False, 'fall': None}

    def setup(self):
        self.low = False
        self.sending = False
        self.fall = None
        self.reads = 0

    def frame(self):
        t, h = self.stimuli['celsius'], self.stimuli['humidity']
        if self.props['model'] == 'DHT11':
            data = [int(round(h)) & 0xFF, 0, int(round(max(0, t))) & 0xFF, 0]
        else:
            hum = int(round(h * 10))
            temp = int(round(abs(t) * 10)) | (0x8000 if t < 0 else 0)
            data = [hum >> 8, hum & 0xFF, temp >> 8, temp & 0xFF]
        return data + [sum(data) & 0xFF]

    def sense(self, volts, now):
        if self.sending or not self.operational():
            return
        level = volts['DATA'] - self.v('GND') >= 0.5 * max(self.supply_voltage(), 1)
        if not level and self.fall is None:
            self.fall = now
        elif level and self.fall is not None:
            held = now - self.fall
            self.fall = None
            if held >= (18_000_000 if self.props['model'] == 'DHT11' else 800_000) * 0.9:
                self.sending = True
                self._respond(now)

    def _respond(self, start):
        t = 30_000
        steps = [(t, True), (t + 80_000, False)]
        t += 160_000
        for byte in self.frame():
            for bit in range(7, -1, -1):
                steps.append((t, True))
                t += 50_000
                steps.append((t, False))
                t += 70_000 if (byte >> bit) & 1 else 27_000
        steps += [(t, True), (t + 50_000, False)]
        for offset, low in steps:
            self.schedule_in(offset, lambda low=low: self._drive(low))
        self.schedule_in(t + 60_000, self._done)

    def _drive(self, low):
        self.low = low
        self.changed()

    def _done(self):
        self.sending = False
        self.reads += 1

    def dynamic(self):
        return (self.low,)

    def elements(self):
        els = [('R', '@VCC', '@GND', 20_000.0, 'iq')]
        if self.props['pullup']:
            els.append(('R', '@DATA', '@VCC', 10_000.0, 'pullup'))
        if self.low:
            els.append(('R', '@DATA', '@GND', 30.0, 'out'))
        return els

    def state(self):
        return {'reads': self.reads}


def crc8(data):
    crc = 0
    for byte in data:
        for _ in range(8):
            mix = (crc ^ byte) & 1
            crc >>= 1
            if mix:
                crc ^= 0x8C
            byte >>= 1
    return crc


class DS18B20(Part):
    """1-Wire temperature sensor: reset/presence, ROM and scratchpad commands."""
    kind = 'ds18b20'
    prefix = 'ds'
    pins = ('GND', 'DQ', 'VDD')
    inputs = ('DQ',)
    supply = ('VDD', 'GND', 3.0, 5.5, 6.0)
    stimuli_spec = {'celsius': (-55.0, 125.0, 22.5, '°C', 'Temperature')}
    damaged_behavior = 'No presence pulse.'
    meta = {'name': 'DS18B20 1-Wire temperature', 'category': 'Sensors', 'aliases': ['temperature', 'one-wire', '1-wire', 'ds18b20', 'waterproof'],
            'interfaces': ['1-wire'], 'supply': '3.0–5.5 V', 'compat': 'direct', 'shape': 'to92',
            'footprint': [[0, 0], [1, 0], [2, 0]],
            'description': 'Needs a 4.7 kΩ pull-up on DQ. Reset (480 µs LOW), SKIP ROM 0xCC, CONVERT 0x44, '
                           'wait 750 ms, READ SCRATCHPAD 0xBE. Before the first conversion it reads 85 °C.'}

    transient = {'driving': False, 'fall': None, 'mode': 'idle', 'bits': [], 'out': [],
                 'converting_until': 0, 'read_slot': False}

    def setup(self):
        serial = [0x28, 0x6F, 0x17, 0x68, 0x04, 0x00, 0x00]
        self.rom = serial + [crc8(serial)]
        self.temperature = 0x0550  # 85 °C power-on value
        self.config = [0x4B, 0x46, 0x7F]
        self.driving = False
        self.fall = None
        self.mode = 'idle'
        self.bits = []
        self.out = []
        self.converting_until = 0
        self._next_after_send = 'idle'
        self.read_slot = False

    def scratchpad(self):
        data = [self.temperature & 0xFF, (self.temperature >> 8) & 0xFF, *self.config, 0xFF, 0x0C, 0x10]
        return data + [crc8(data)]

    def sense(self, volts, now):
        if not self.operational():
            return
        level = volts['DQ'] - self.v('GND') >= 1.5
        if self.driving:
            return
        if not level and self.fall is None:
            self.fall = now
            # Read slots: the device holds the line LOW for ~30 µs to send a 0.
            self.read_slot = self.mode in ('send', 'busy')
            if self.mode == 'send':
                bit = self.out.pop(0) if self.out else 1
                if not self.out:
                    self.mode = self._next_after_send
                if bit == 0:
                    self._hold(30_000)
            elif self.mode == 'busy' and now < self.converting_until:
                self._hold(30_000)
        elif level and self.fall is not None:
            width = now - self.fall
            self.fall = None
            read_slot, self.read_slot = self.read_slot, False
            if width >= 400_000:
                self.mode = 'rom'
                self.bits = []
                self.schedule_in(30_000, lambda: self._hold(120_000))
            elif not read_slot and self.mode in ('rom', 'command', 'match', 'write'):
                self.bits.append(1 if width < 15_000 else 0)
                if len(self.bits) == 8:
                    byte = sum(b << i for i, b in enumerate(self.bits))
                    self.bits = []
                    self._byte(byte, now)

    def _byte(self, byte, now):
        if self.mode == 'rom':
            if byte == 0xCC:
                self.mode = 'command'
            elif byte == 0x33:
                self._send(self.rom, after='command')
            elif byte == 0x55:
                self.mode, self.match = 'match', []
            else:
                self.mode = 'idle'
        elif self.mode == 'match':
            self.match.append(byte)
            if len(self.match) == 8:
                self.mode = 'command' if self.match == self.rom else 'idle'
        elif self.mode == 'command':
            if byte == 0x44:
                self.converting_until = now + 750_000_000
                self.mode = 'busy'
                self.schedule_in(750_000_000, self._converted)
            elif byte == 0xBE:
                self._send(self.scratchpad(), after='idle')
            elif byte == 0x4E:
                self.mode, self.write = 'write', []
            else:
                self.mode = 'idle'
        elif self.mode == 'write':
            self.write.append(byte)
            if len(self.write) == 3:
                self.config = self.write[:2] + [(self.write[2] & 0x60) | 0x1F]
                self.mode = 'idle'

    def _converted(self):
        value = int(round(self.stimuli['celsius'] * 16)) & 0xFFFF
        self.temperature = value
        self.converting_until = 0
        if self.mode == 'busy':
            self.mode = 'idle'

    def _send(self, data, after):
        self.out = [(byte >> i) & 1 for byte in data for i in range(8)]
        self.mode = 'send'
        self._next_after_send = after

    def _hold(self, ns):
        self.driving = True
        self.changed()
        def release():
            self.driving = False
            self.changed()
        self.schedule_in(ns, release)

    def dynamic(self):
        return (self.driving,)

    def elements(self):
        els = [('R', '@VDD', '@GND', 100_000.0, 'iq')]
        if self.driving:
            els.append(('R', '@DQ', '@GND', 30.0, 'out'))
        return els

    def check(self, volts):
        nodes = set(self.circuit.board.net_of(self.node('DQ')).nodes)
        from ..doctor import _pulled_up
        if not _pulled_up(self.circuit, nodes):
            return [finding(f'onewire-pullup:{self.id}', 'warning', 'No pull-up on the 1-Wire bus',
                            f'{self.label} DQ has no resistor to the supply.',
                            '1-Wire is open drain: the line idles HIGH only through a pull-up.',
                            'Reset and presence never work.',
                            [{'label': 'Add a 4.7 kΩ pull-up', 'steps': ['Connect 4.7 kΩ from DQ to VDD.']}],
                            parts=[self.id])]
        return []
