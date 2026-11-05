"""I2C, SPI and UART devices modeled at transaction level."""
from __future__ import annotations

import datetime

from .base import Part
from ..doctor import finding
from ..terminal import Terminal


# -- I2C ------------------------------------------------------------------------------
class I2CDevice(Part):
    i2c_pins = ('SDA', 'SCL')
    has_pullups = False
    pullup_rail = 'VCC'
    default_address = 0x50
    defaults = {'address': 0x50}

    def setup(self):
        self.registers = bytearray(256)
        self.pointer = 0
        self.first = True
        self.reset_registers()

    def reset_registers(self):
        pass

    def address(self):
        return int(self.props.get('address', self.default_address))

    def i2c_matches(self, address):
        return address == self.address()

    def i2c_start(self):
        self.first = True

    def i2c_address(self, address, read):
        return self.operational()

    def i2c_write(self, byte):
        if self.first:
            self.pointer = byte
            self.first = False
        else:
            self.write_register(self.pointer, byte)
            self.pointer = (self.pointer + 1) & 0xFF
        return True

    def i2c_read(self, ack):
        value = self.read_register(self.pointer)
        self.pointer = (self.pointer + 1) & 0xFF
        return value

    def i2c_stop(self):
        pass

    def write_register(self, register, value):
        self.registers[register] = value

    def read_register(self, register):
        return self.registers[register]

    def elements(self):
        els = [('R', f'@{self.supply[0]}', f'@{self.supply[1]}', 5_000.0, 'iq')] if self.supply else []
        if self.has_pullups:
            els += [('R', '@SDA', f'@{self.pullup_rail}', 4_700.0, 'sda-pull'),
                    ('R', '@SCL', f'@{self.pullup_rail}', 4_700.0, 'scl-pull')]
        return els


def s16(value):
    return value & 0xFFFF


class BMP280(I2CDevice):
    kind = 'bmp280'
    prefix = 'bmp'
    pins = ('VCC', 'GND', 'SCL', 'SDA', 'CSB', 'SDO')
    supply = ('VCC', 'GND', 1.71, 3.6, 4.25)
    pin_limits = {'SDA': 4.25, 'SCL': 4.25}
    defaults = {'address': 0x76}
    choices = {'address': (0x76, 0x77)}
    stimuli_spec = {'celsius': (-40.0, 85.0, 23.5, '°C', 'Temperature'),
                    'hpa': (300.0, 1100.0, 1013.25, 'hPa', 'Pressure')}
    damaged_behavior = 'It no longer acknowledges its I2C address.'
    meta = {'name': 'BMP280 pressure & temperature', 'category': 'Sensors',
            'aliases': ['barometer', 'pressure', 'altitude', 'temperature', 'bmp280', 'bme280', 'weather'],
            'interfaces': ['i2c'], 'supply': '3.3 V only (1.71–3.6 V)', 'compat': 'direct-3v3', 'shape': 'module',
            'footprint': [[i, 0] for i in range(6)],
            'description': 'Bosch BMP280 on a bare breakout: 3.3 V ONLY (absolute maximum 4.25 V). '
                           'Address 0x76 (SDO to GND) or 0x77. Chip ID 0x58 at register 0xD0.'}
    CAL = {'T1': 27504, 'T2': 26435, 'T3': -1000, 'P1': 36477, 'P2': -10685, 'P3': 3024, 'P4': 2855,
           'P5': 140, 'P6': -7, 'P7': 15500, 'P8': -14600, 'P9': 6000}

    def reset_registers(self):
        r = self.registers
        r[0xD0] = 0x58
        for i, name in enumerate(['T1', 'T2', 'T3', 'P1', 'P2', 'P3', 'P4', 'P5', 'P6', 'P7', 'P8', 'P9']):
            value = s16(self.CAL[name])
            r[0x88 + 2 * i] = value & 0xFF
            r[0x89 + 2 * i] = value >> 8
        r[0xF7:0xFD] = bytes([0x80, 0, 0, 0x80, 0, 0])

    def compensate_t(self, adc_t):
        c = self.CAL
        var1 = (((adc_t >> 3) - (c['T1'] << 1)) * c['T2']) >> 11
        var2 = (((((adc_t >> 4) - c['T1']) * ((adc_t >> 4) - c['T1'])) >> 12) * c['T3']) >> 14
        t_fine = var1 + var2
        return t_fine, (t_fine * 5 + 128) >> 8

    def compensate_p(self, adc_p, t_fine):
        c = self.CAL
        var1 = t_fine - 128000
        var2 = var1 * var1 * c['P6']
        var2 += (var1 * c['P5']) << 17
        var2 += c['P4'] << 35
        var1 = ((var1 * var1 * c['P3']) >> 8) + ((var1 * c['P2']) << 12)
        var1 = (((1 << 47) + var1) * c['P1']) >> 33
        if var1 == 0:
            return 0
        p = 1048576 - adc_p
        p = int((((p << 31) - var2) * 3125) / var1)
        var1 = (c['P9'] * (p >> 13) * (p >> 13)) >> 25
        var2 = (c['P8'] * p) >> 19
        return ((p + var1 + var2) >> 8) + (c['P7'] << 4)

    def measure(self):
        target = int(round(self.stimuli['celsius'] * 100))
        low, high = 0, (1 << 20) - 1
        while low < high:
            mid = (low + high) // 2
            if self.compensate_t(mid)[1] < target:
                low = mid + 1
            else:
                high = mid
        adc_t = low
        t_fine = self.compensate_t(adc_t)[0]
        target_p = self.stimuli['hpa'] * 100 * 256
        low, high = 0, (1 << 20) - 1
        while low < high:  # pressure falls as adc_P rises
            mid = (low + high) // 2
            if self.compensate_p(mid, t_fine) > target_p:
                low = mid + 1
            else:
                high = mid
        adc_p = low
        r = self.registers
        r[0xF7], r[0xF8], r[0xF9] = adc_p >> 12, (adc_p >> 4) & 0xFF, (adc_p & 15) << 4
        r[0xFA], r[0xFB], r[0xFC] = adc_t >> 12, (adc_t >> 4) & 0xFF, (adc_t & 15) << 4

    def write_register(self, register, value):
        if register == 0xE0 and value == 0xB6:
            self.registers = bytearray(256)
            self.reset_registers()
            return
        if register in (0xF4, 0xF5):
            self.registers[register] = value
            if register == 0xF4 and value & 3:
                self.measure()
                if value & 3 in (1, 2):
                    self.registers[0xF4] = value & ~3  # forced mode returns to sleep

    def read_register(self, register):
        if register == 0xF3:
            return 0
        if 0xF7 <= register <= 0xFC and self.registers[0xF4] & 3 == 3:
            self.measure()
        return self.registers[register]


class MPU6050(I2CDevice):
    kind = 'mpu6050'
    prefix = 'imu'
    pins = ('VCC', 'GND', 'SCL', 'SDA', 'XDA', 'XCL', 'AD0', 'INT')
    supply = ('VCC', 'GND', 3.0, 5.5, 6.0)
    has_pullups = True
    defaults = {'address': 0x68}
    choices = {'address': (0x68, 0x69)}
    stimuli_spec = {'ax': (-4.0, 4.0, 0.0, 'g', 'Accel X'), 'ay': (-4.0, 4.0, 0.0, 'g', 'Accel Y'),
                    'az': (-4.0, 4.0, 1.0, 'g', 'Accel Z'), 'gx': (-500.0, 500.0, 0.0, '°/s', 'Gyro X'),
                    'gy': (-500.0, 500.0, 0.0, '°/s', 'Gyro Y'), 'gz': (-500.0, 500.0, 0.0, '°/s', 'Gyro Z'),
                    'celsius': (-40.0, 85.0, 25.0, '°C', 'Die temperature')}
    damaged_behavior = 'It no longer acknowledges its I2C address.'
    meta = {'name': 'MPU-6050 accelerometer + gyro (GY-521)', 'category': 'Sensors',
            'aliases': ['imu', 'gyroscope', 'accelerometer', 'tilt', 'mpu6050', 'gy-521', 'motion'],
            'interfaces': ['i2c'], 'supply': '3.3–5 V module (on-board LDO)', 'compat': 'direct', 'shape': 'module',
            'footprint': [[i, 0] for i in range(8)],
            'description': 'Wake it by writing 0 to PWR_MGMT_1 (0x6B): it powers up asleep and returns zeros. '
                           'WHO_AM_I (0x75) = 0x68. Module has 4.7 kΩ pull-ups to 3.3 V.'}
    pullup_rail = '_3v3'
    hidden = ('_3v3',)

    def elements(self):
        els = super().elements()
        if self.supply_voltage() > 3.4:
            els.append(('V', '@_3v3', '@GND', 3.3, 1.0, 'ldo'))
        else:
            els.append(('R', '@_3v3', '@VCC', 0.5, 'ldo'))
        return els

    def reset_registers(self):
        self.registers[0x75] = 0x68
        self.registers[0x6B] = 0x40

    def write_register(self, register, value):
        if register == 0x6B and value & 0x80:
            self.registers = bytearray(256)
            self.reset_registers()
            return
        self.registers[register] = value

    def read_register(self, register):
        if 0x3B <= register <= 0x48:
            if self.registers[0x6B] & 0x40:
                return 0
            accel_scale = 16384 >> ((self.registers[0x1C] >> 3) & 3)
            gyro_scale = (131.0, 65.5, 32.8, 16.4)[(self.registers[0x1B] >> 3) & 3]
            s = self.stimuli
            words = [s['ax'] * accel_scale, s['ay'] * accel_scale, s['az'] * accel_scale,
                     (s['celsius'] - 36.53) * 340, s['gx'] * gyro_scale, s['gy'] * gyro_scale, s['gz'] * gyro_scale]
            word = max(-32768, min(32767, int(round(words[(register - 0x3B) // 2])))) & 0xFFFF
            return word >> 8 if (register - 0x3B) % 2 == 0 else word & 0xFF
        return self.registers[register]


class SSD1306(I2CDevice):
    kind = 'ssd1306'
    prefix = 'oled'
    pins = ('GND', 'VCC', 'SCL', 'SDA')
    supply = ('VCC', 'GND', 3.0, 5.5, 6.0)
    has_pullups = True
    defaults = {'address': 0x3C}
    choices = {'address': (0x3C, 0x3D)}
    damaged_behavior = 'The panel stays dark.'
    meta = {'name': 'SSD1306 OLED 128×64 (I2C)', 'category': 'Displays',
            'aliases': ['oled', 'display', 'screen', 'ssd1306', 'graphics', '0.96'],
            'interfaces': ['i2c'], 'supply': '3.3–5 V module', 'compat': 'direct', 'shape': 'oled',
            'footprint': [[i, 0] for i in range(4)],
            'description': 'Send 0x00 + commands or 0x40 + pixel data. The panel stays dark until you enable the '
                           'charge pump (0x8D, 0x14) and send display ON (0xAF).'}
    ARGS = {0x20: 1, 0x21: 2, 0x22: 2, 0x81: 1, 0x8D: 1, 0xA8: 1, 0xD3: 1, 0xD5: 1, 0xD9: 1, 0xDA: 1,
            0xDB: 1, 0x26: 6, 0x27: 6, 0x29: 5, 0x2A: 5, 0xA3: 2}

    def reset_registers(self):
        self.fb = bytearray(1024)
        self.on = False
        self.pump = False
        self.invert = False
        self.mode = 2
        self.page, self.column = 0, 0
        self.col_range, self.page_range = (0, 127), (0, 7)
        self.pending = None
        self.args = []
        self.control = None
        self.flip_x = self.flip_y = False
        self.contrast = 0x7F
        self.writes = 0

    def i2c_start(self):
        self.control = None

    def i2c_write(self, byte):
        if self.control is None:
            self.control = byte
            return True
        if self.control & 0x40:
            self._data(byte)
        else:
            self._command(byte)
            if self.control & 0x80:
                self.control = None
        return True

    def _command(self, byte):
        if self.pending is not None:
            self.args.append(byte)
            if len(self.args) < self.ARGS[self.pending]:
                return
            cmd, args = self.pending, self.args
            self.pending, self.args = None, []
            if cmd == 0x20:
                self.mode = args[0] & 3
            elif cmd == 0x21:
                self.col_range = (args[0] & 127, args[1] & 127)
                self.column = self.col_range[0]
            elif cmd == 0x22:
                self.page_range = (args[0] & 7, args[1] & 7)
                self.page = self.page_range[0]
            elif cmd == 0x81:
                self.contrast = args[0]
            elif cmd == 0x8D:
                self.pump = bool(args[0] & 4)
            return
        if byte in self.ARGS:
            self.pending = byte
        elif byte in (0xAE, 0xAF):
            self.on = byte == 0xAF
        elif byte in (0xA6, 0xA7):
            self.invert = byte == 0xA7
        elif byte in (0xA0, 0xA1):
            self.flip_x = byte == 0xA1
        elif byte in (0xC0, 0xC8):
            self.flip_y = byte == 0xC8
        elif 0xB0 <= byte <= 0xB7:
            self.page = byte & 7
        elif byte <= 0x0F:
            self.column = (self.column & 0xF0) | byte
        elif byte <= 0x1F:
            self.column = (self.column & 0x0F) | ((byte & 7) << 4)

    def _data(self, byte):
        self.fb[self.page * 128 + (self.column & 127)] = byte
        self.writes += 1
        if self.mode == 0:
            if self.column >= self.col_range[1]:
                self.column = self.col_range[0]
                self.page = self.page_range[0] if self.page >= self.page_range[1] else self.page + 1
            else:
                self.column += 1
        elif self.mode == 1:
            if self.page >= self.page_range[1]:
                self.page = self.page_range[0]
                self.column = self.col_range[0] if self.column >= self.col_range[1] else self.column + 1
            else:
                self.page += 1
        else:
            self.column = (self.column + 1) & 127

    def i2c_read(self, ack):
        return 0x43 if self.on else 0x03  # status byte

    def state(self):
        visible = self.on and self.pump and not self.damaged and self.powered()
        return {'on': visible, 'invert': self.invert, 'flipX': self.flip_x, 'flipY': self.flip_y,
                'fb': self.fb.hex() if visible else '', 'contrast': self.contrast,
                'hint': '' if visible or not self.on else 'Display ON was sent but the charge pump (0x8D 0x14) is off.'}


class LCDBackpack(I2CDevice):
    """16x2 HD44780 with a PCF8574 I2C backpack: P0=RS P1=RW P2=E P3=backlight P4-P7=D4-D7."""
    kind = 'lcd_i2c'
    prefix = 'lcd'
    pins = ('GND', 'VCC', 'SDA', 'SCL')
    supply = ('VCC', 'GND', 4.5, 5.5, 7.0)
    has_pullups = True
    defaults = {'address': 0x27}
    choices = {'address': (0x27, 0x3F)}
    meta = {'name': 'LCD 16×2 with I2C backpack (PCF8574)', 'category': 'Displays',
            'aliases': ['lcd', '1602', 'i2c lcd', 'pcf8574', 'character display', 'text'],
            'interfaces': ['i2c'], 'supply': '5 V', 'compat': 'direct', 'shape': 'lcd1602',
            'footprint': [[i, 0] for i in range(4)],
            'description': 'Character LCD over I2C. Bits: P0 RS, P1 RW, P2 E, P3 backlight, P4–P7 D4–D7. '
                           'Its on-board pull-ups go to 5 V, which the LPC1768 I2C pins tolerate.'}

    def reset_registers(self):
        from ..displays import LCD
        self.lcd = LCD()
        self.port = 0xFF

    def i2c_write(self, byte):
        self.port = byte
        if self.operational():
            self.lcd.observe(True, (byte >> 2) & 1, byte & 1, byte >> 4)
        return True

    def i2c_read(self, ack):
        return self.port

    def state(self):
        return {'lines': self.lcd.lines(self.operational()), 'backlight': bool(self.port & 8) and self.operational()}


class EEPROM24C(I2CDevice):
    kind = 'eeprom24c02'
    prefix = 'eep'
    pins = ('A0', 'A1', 'A2', 'GND', 'SDA', 'SCL', 'WP', 'VCC')
    supply = ('VCC', 'GND', 1.8, 5.5, 6.5)
    meta = {'name': 'AT24C02 EEPROM (256 B)', 'category': 'Memory', 'aliases': ['eeprom', 'memory', 'storage', '24c02', 'nonvolatile'],
            'interfaces': ['i2c'], 'supply': '1.8–5.5 V', 'compat': 'direct', 'shape': 'dip8',
            'footprint': [[i, 0] for i in range(4)] + [[3 - i, -3] for i in range(4)],
            'description': 'Address 0x50 + A2..A0. 8-byte pages; after a write it ignores its address for ~5 ms '
                           '(poll for ACK). Tie WP to GND to allow writes.'}

    def setup(self):
        super().setup()
        self.memory = bytearray([0xFF]) * 256
        self.busy_until = 0
        self.page = []

    def address(self):
        bits = sum(self.logic(pin) << i for i, pin in enumerate(('A0', 'A1', 'A2')))
        return 0x50 | bits

    def i2c_address(self, address, read):
        return self.operational() and self.now() >= self.busy_until

    def i2c_start(self):
        super().i2c_start()
        self.page = []

    def write_register(self, register, value):
        self.page.append((self.pointer, value))

    def i2c_write(self, byte):
        if self.first:
            self.pointer = byte
            self.first = False
        else:
            if len(self.page) < 8:
                self.page.append(byte)
        return True

    def i2c_stop(self):
        if self.page and not self.logic('WP'):
            base = self.pointer & ~7
            for offset, value in enumerate(self.page):
                self.memory[base | ((self.pointer + offset) & 7)] = value
            self.busy_until = self.now() + 5_000_000
        self.pointer = (self.pointer + len(self.page)) & 0xFF
        self.page = []

    def i2c_read(self, ack):
        value = self.memory[self.pointer]
        self.pointer = (self.pointer + 1) & 0xFF
        return value

    def state(self):
        return {'memory': self.memory[:32].hex()}


class RTCModule(I2CDevice):
    kind = 'rtc'
    prefix = 'rtc'
    pins = ('GND', 'VCC', 'SDA', 'SCL', 'SQW')
    defaults = {'model': 'DS3231', 'address': 0x68}
    choices = {'model': ('DS3231', 'DS1307'), 'address': (0x68,)}
    has_pullups = True
    meta = {'name': 'RTC module (DS3231 / DS1307)', 'category': 'Timekeeping',
            'aliases': ['clock', 'rtc', 'time', 'date', 'ds3231', 'ds1307', 'calendar'],
            'interfaces': ['i2c'], 'supply': 'DS3231 2.3–5.5 V, DS1307 4.5–5.5 V', 'compat': 'direct', 'shape': 'module',
            'footprint': [[i, 0] for i in range(5)],
            'description': 'BCD time at registers 0x00–0x06. The DS1307 needs 5 V and starts halted '
                           '(CH, bit 7 of register 0) until firmware clears it.'}

    @property
    def supply(self):
        return ('VCC', 'GND', 4.5, 5.5, 7.0) if self.props['model'] == 'DS1307' else ('VCC', 'GND', 2.3, 5.5, 6.0)

    def reset_registers(self):
        now = datetime.datetime.now()
        self.base_time = now
        self.base_ns = None
        self.halted = self.props['model'] == 'DS1307'

    def current(self):
        if self.base_ns is None:
            self.base_ns = self.now()
        if self.halted:
            return self.base_time
        return self.base_time + datetime.timedelta(microseconds=(self.now() - self.base_ns) / 1000)

    def read_register(self, register):
        t = self.current()
        bcd = lambda v: ((v // 10) << 4) | (v % 10)
        values = [bcd(t.second) | (0x80 if self.halted else 0), bcd(t.minute), bcd(t.hour),
                  t.isoweekday() % 7 + 1, bcd(t.day), bcd(t.month), bcd(t.year % 100)]
        if register < 7:
            return values[register]
        return self.registers[register]

    def write_register(self, register, value):
        unbcd = lambda v: ((v >> 4) & 7) * 10 + (v & 15)
        if register < 7:
            t = self.current()
            fields = {'second': t.second, 'minute': t.minute, 'hour': t.hour, 'day': t.day,
                      'month': t.month, 'year': t.year}
            if register == 0:
                fields['second'] = unbcd(value & 0x7F)
                if self.props['model'] == 'DS1307':
                    self.halted = bool(value & 0x80)
            elif register == 1:
                fields['minute'] = unbcd(value)
            elif register == 2:
                fields['hour'] = unbcd(value & 0x3F)
            elif register == 4:
                fields['day'] = max(1, unbcd(value))
            elif register == 5:
                fields['month'] = max(1, min(12, unbcd(value & 0x1F)))
            elif register == 6:
                fields['year'] = 2000 + unbcd(value)
            try:
                self.base_time = datetime.datetime(**fields)
            except ValueError:
                pass
            self.base_ns = self.now()
        else:
            self.registers[register] = value

    def state(self):
        return {'time': self.current().strftime('%Y-%m-%d %H:%M:%S'), 'halted': self.halted}


class LM75(I2CDevice):
    kind = 'lm75'
    prefix = 'lm'
    pins = ('SDA', 'SCL', 'OS', 'GND', 'A2', 'A1', 'A0', 'VCC')
    supply = ('VCC', 'GND', 2.8, 5.5, 6.5)
    stimuli_spec = {'celsius': (-55.0, 125.0, 25.0, '°C', 'Temperature')}
    meta = {'name': 'LM75 I2C temperature sensor', 'category': 'Sensors', 'aliases': ['temperature', 'lm75', 'tmp102', 'thermometer'],
            'interfaces': ['i2c'], 'supply': '2.8–5.5 V', 'compat': 'direct', 'shape': 'module',
            'footprint': [[i, 0] for i in range(8)],
            'description': 'Address 0x48 + A2..A0. Read two bytes from register 0: temperature × 256, 0.5 °C steps.'}

    def address(self):
        return 0x48 | sum(self.logic(pin) << i for i, pin in enumerate(('A0', 'A1', 'A2')))

    def i2c_start(self):
        self.first = True
        self.byte_index = 0

    def i2c_write(self, byte):
        if self.first:
            self.pointer = byte & 3
            self.first = False
        return True

    def i2c_read(self, ack):
        if self.pointer == 0:
            raw = (int(round(self.stimuli['celsius'] * 2)) << 7) & 0xFFFF
        else:
            raw = {1: 0, 2: 75 << 8, 3: 80 << 8}[self.pointer]
        index = getattr(self, 'byte_index', 0)
        self.byte_index = index + 1
        return (raw >> 8) & 0xFF if index % 2 == 0 else raw & 0xFF


class BH1750(I2CDevice):
    kind = 'bh1750'
    prefix = 'lux'
    pins = ('VCC', 'GND', 'SCL', 'SDA', 'ADDR')
    supply = ('VCC', 'GND', 2.4, 5.5, 6.0)
    has_pullups = True
    stimuli_spec = {'lux': (0.0, 65000.0, 250.0, 'lx', 'Light')}
    meta = {'name': 'BH1750 light sensor', 'category': 'Sensors', 'aliases': ['light', 'lux', 'ambient', 'bh1750', 'gy-30'],
            'interfaces': ['i2c'], 'supply': '3.3–5 V module', 'compat': 'direct', 'shape': 'module',
            'footprint': [[i, 0] for i in range(5)],
            'description': 'Send 0x01 (power on) then 0x10 (continuous high resolution); read two bytes = lux × 1.2.'}

    def address(self):
        return 0x5C if self.logic('ADDR') else 0x23

    def i2c_start(self):
        self.byte_index = 0

    def i2c_write(self, byte):
        if byte == 0x01:
            self.powered_on = True
        elif byte == 0x00:
            self.powered_on = False
        elif byte in (0x10, 0x11, 0x13, 0x20, 0x21, 0x23):
            self.measuring = True
        return True

    def i2c_read(self, ack):
        raw = int(min(65535, self.stimuli['lux'] * 1.2)) if getattr(self, 'measuring', False) else 0
        index = self.byte_index
        self.byte_index += 1
        return (raw >> 8) & 0xFF if index % 2 == 0 else raw & 0xFF


class GenericI2C(I2CDevice):
    kind = 'generic_i2c'
    prefix = 'dev'
    pins = ('VCC', 'GND', 'SDA', 'SCL')
    supply = ('VCC', 'GND', 1.8, 5.5, 6.0)
    defaults = {'address': 0x40, 'registers': '0x00:0x00'}
    meta = {'name': 'Generic I2C register device', 'category': 'Generic',
            'aliases': ['i2c', 'generic', 'register map', 'custom device'],
            'interfaces': ['i2c'], 'supply': '1.8–5.5 V', 'compat': 'direct', 'shape': 'module',
            'footprint': [[i, 0] for i in range(4)],
            'description': 'Stands in for any register-based I2C chip: set its address and initial registers '
                           '(e.g. "0x0F:0x33, 0x20:0x07"). Writes after the register pointer are stored.'}

    def configured(self):
        if not 0x08 <= int(self.props['address']) <= 0x77:
            raise ValueError('I2C addresses run from 0x08 to 0x77.')

    def reset_registers(self):
        for item in str(self.props['registers']).split(','):
            if ':' in item:
                register, value = item.split(':', 1)
                try:
                    self.registers[int(register.strip(), 0) & 0xFF] = int(value.strip(), 0) & 0xFF
                except ValueError:
                    pass

    def state(self):
        return {'registers': self.registers[:64].hex()}


# -- SPI ------------------------------------------------------------------------------
class SPIDevice(Part):
    spi_pins = {'SCK': 'CLK', 'MOSI': 'DIN', 'MISO': 'DOUT', 'CS': 'CS'}

    def spi_selected(self, ssel_pad):
        cs = self.spi_pins.get('CS')
        if cs is None:
            return self.operational()
        node = self.node(cs)
        if ssel_pad and self.circuit.board.same_net(node, f'P{ssel_pad[0]}.{ssel_pad[1]}'):
            return self.operational()
        return self.operational() and self.circuit.board.node_level(node) == 0


class MCP3008(SPIDevice):
    kind = 'mcp3008'
    prefix = 'adc'
    pins = ('CH0', 'CH1', 'CH2', 'CH3', 'CH4', 'CH5', 'CH6', 'CH7',
            'DGND', 'CS', 'DIN', 'DOUT', 'CLK', 'AGND', 'VREF', 'VDD')
    supply = ('VDD', 'DGND', 2.7, 5.5, 7.0)
    meta = {'name': 'MCP3008 8-channel 10-bit ADC (SPI)', 'category': 'Converters',
            'aliases': ['adc', 'analog', 'mcp3008', 'converter', 'spi adc'],
            'interfaces': ['spi'], 'supply': '2.7–5.5 V', 'compat': 'direct', 'shape': 'dip16',
            'footprint': [[i, 0] for i in range(8)] + [[7 - i, -3] for i in range(8)],
            'description': 'Send 0x01, 0x80|(ch<<4), 0x00; the result is ((b1&3)<<8)|b2. '
                           'Power from 3.3 V with VREF = 3.3 V.'}

    def setup(self):
        self.bits = []
        self.outbits = []

    def spi_transfer(self, value, bits, mode, hz):
        reply = 0
        for i in range(bits - 1, -1, -1):
            bit_in = (value >> i) & 1
            bit_out = self.outbits.pop(0) if self.outbits else 0
            reply = (reply << 1) | bit_out
            if self.outbits or bit_out:
                continue
            if not self.bits and not bit_in:
                continue
            self.bits.append(bit_in)
            if len(self.bits) == 5:
                single, channel = self.bits[1], self.bits[2] << 2 | self.bits[3] << 1 | self.bits[4]
                self.bits = []
                ref = max(0.01, self.v('VREF') - self.v('AGND'))
                vin = self.v(f'CH{channel}') - (self.v('AGND') if single else self.v(f'CH{channel ^ 1}'))
                code = max(0, min(1023, int(vin / ref * 1024)))
                # One sample clock, then the null bit, then B9..B0 (MCP3008 Figure 5-1).
                self.outbits = [0, 0] + [(code >> k) & 1 for k in range(9, -1, -1)]
        return reply

    def elements(self):
        return [('R', '@VDD', '@DGND', 10_000.0, 'iq')] + [
            ('R', f'@CH{n}', '@AGND', 1e7, f'ch{n}') for n in range(8)]


class MAX7219(SPIDevice):
    kind = 'max7219'
    prefix = 'mx'
    pins = ('VCC', 'GND', 'DIN', 'CS', 'CLK')
    inputs = ('CS',)
    supply = ('VCC', 'GND', 4.0, 5.5, 6.0)
    meta = {'name': 'MAX7219 8×8 LED matrix', 'category': 'Displays',
            'aliases': ['matrix', 'led matrix', 'max7219', 'dot matrix', '8x8'],
            'interfaces': ['spi'], 'supply': '5 V', 'compat': 'level-shift', 'shape': 'matrix',
            'footprint': [[i, 0] for i in range(5)],
            'description': 'Write 16-bit frames (register, data) while CS is LOW; CS rising latches. It powers up in '
                           'shutdown (write 0x0C=1). Its inputs need 3.5 V for HIGH at 5 V: 3.3 V logic is marginal.'}
    spi_pins = {'SCK': 'CLK', 'MOSI': 'DIN', 'CS': 'CS'}

    def setup(self):
        self.rows = [0] * 8
        self.shift = 0
        self.count = 0
        self.shutdown = True
        self.test = False
        self.intensity = 0
        self.last_cs = 1

    def spi_transfer(self, value, bits, mode, hz):
        self.shift = ((self.shift << bits) | value) & 0xFFFF
        self.count += bits
        return None

    def sense(self, volts, now):
        cs = int(volts['CS'] - self.v('GND') >= 0.5 * max(self.supply_voltage(), 1))
        if cs and not self.last_cs and self.count >= 16:
            register, data = (self.shift >> 8) & 15, self.shift & 0xFF
            if 1 <= register <= 8:
                self.rows[register - 1] = data
            elif register == 0x0A:
                self.intensity = data & 15
            elif register == 0x0C:
                self.shutdown = not data & 1
            elif register == 0x0F:
                self.test = bool(data & 1)
            self.count = 0
        if not cs and self.last_cs:
            self.count = 0
        self.last_cs = cs

    def check(self, volts):
        vcc = self.supply_voltage()
        din = volts.get(self.node('DIN'), 0.0)
        if vcc > 4.5 and 2.0 < din < 0.7 * vcc:
            return [finding(f'vih:{self.id}', 'warning', f'{self.label}: 3.3 V logic into a 5 V chip',
                            f'DIN reaches {din:.1f} V; at {vcc:.1f} V supply the MAX7219 needs {0.7 * vcc:.1f} V for HIGH.',
                            'CMOS inputs switch at a fraction of their own supply.',
                            'Some bits are misread: random pixels flicker.',
                            [{'label': 'Add a 74HCT125 or BSS138 level shifter', 'steps': ['Shift DIN, CLK and CS to 5 V.']}],
                            parts=[self.id])]
        return []

    def elements(self):
        return [('R', '@VCC', '@GND', 500.0, 'iq')]

    def state(self):
        rows = [0xFF] * 8 if self.test else ([0] * 8 if self.shutdown else self.rows)
        return {'rows': rows, 'intensity': self.intensity}


# -- UART -------------------------------------------------------------------------------
class UARTDevice(Part):
    defaults = {'baud': 9600}
    choices = {'baud': (1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200)}
    tx_pin = 'TXD'

    def uart_send(self, data):
        baud = int(self.props['baud'])
        frame = int(10 * 1e9 / baud)
        node = self.node(self.tx_pin)
        for index, byte in enumerate(data):
            self.schedule_in(frame * (index + 1),
                             lambda b=byte: self.machine.send_serial_from_node(node, b, baud, sender=self.label))


class SerialBridge(UARTDevice):
    kind = 'usb_serial'
    prefix = 'usb'
    pins = ('GND', 'TXD', 'RXD', '3V3', '5V')
    source_pins = ('3V3', '5V')
    meta = {'name': 'USB–serial adapter (CP2102)', 'category': 'Communication',
            'aliases': ['usb', 'serial', 'uart', 'ftdi', 'cp2102', 'terminal', 'pc', 'console'],
            'interfaces': ['uart'], 'supply': 'USB powered', 'compat': 'direct', 'shape': 'module-usb',
            'footprint': [[i, 0] for i in range(5)],
            'description': 'Connect its RXD to the MCU TXD and its TXD to the MCU RXD (crossed) and GND to GND. '
                           'Open its terminal in the Serial monitor. Also supplies 3.3 V and 5 V from USB.'}

    def setup(self):
        self.terminal = Terminal(f'{self.id} (USB serial)', int(self.props['baud']))

    def configured(self):
        if hasattr(self, 'terminal'):
            self.terminal.baud = int(self.props['baud'])

    def uart_rx(self, pin, byte, baud, bits, parity, stops):
        if pin == 'RXD':
            self.terminal.receive(byte, baud, bits, parity, stops)

    def elements(self):
        return [('V', '@3V3', '@GND', 3.3, 0.5, '3v3'), ('V', '@5V', '@GND', 5.0, 0.3, '5v'),
                ('V', '@TXD', '@GND', 3.3, 1_000.0, 'idle')]

    def state(self):
        return self.terminal.snapshot()


class Bluetooth(UARTDevice):
    kind = 'hc05'
    prefix = 'bt'
    pins = ('EN', 'VCC', 'GND', 'TXD', 'RXD', 'STATE')
    supply = ('VCC', 'GND', 3.6, 6.0, 7.0)
    pin_limits = {'RXD': 3.6}
    meta = {'name': 'HC-05 Bluetooth serial module', 'category': 'Communication',
            'aliases': ['bluetooth', 'wireless', 'hc-05', 'hc-06', 'serial', 'phone'],
            'interfaces': ['uart'], 'supply': '3.6–6 V (3.3 V logic)', 'compat': 'direct', 'shape': 'module-bt',
            'footprint': [[i, 0] for i in range(6)],
            'description': '9600 baud default. Bytes sent by the MCU appear on the "phone" terminal; typed text is '
                           'sent back. RXD is a 3.3 V input: from 5 V logic use a divider.'}

    def setup(self):
        self.terminal = Terminal(f'{self.id} (phone)', int(self.props['baud']))
        self.line = b''

    def uart_rx(self, pin, byte, baud, bits, parity, stops):
        if pin != 'RXD' or not self.operational():
            return
        self.terminal.receive(byte, baud, bits, parity, stops)
        self.line = (self.line + bytes([byte]))[-32:]
        if self.line.endswith(b'AT\r\n'):
            self.uart_send(b'OK\r\n')

    def elements(self):
        els = [('R', '@VCC', '@GND', 200.0, 'iq')]
        if self.powered():
            els.append(('V', '@TXD', '@GND', 3.3, 200.0, 'tx-idle'))
        return els

    def state(self):
        return self.terminal.snapshot()


class GPS(UARTDevice):
    kind = 'gps'
    prefix = 'gps'
    pins = ('VCC', 'RX', 'TX', 'GND')
    supply = ('VCC', 'GND', 2.7, 5.5, 6.0)
    tx_pin = 'TX'
    stimuli_spec = {'lat': (-90.0, 90.0, 12.9716, '°', 'Latitude'), 'lon': (-180.0, 180.0, 77.5946, '°', 'Longitude'),
                    'fix': (0, 1, 1, '', 'Satellite fix')}
    meta = {'name': 'GPS receiver (NEO-6M)', 'category': 'Communication', 'aliases': ['gps', 'location', 'nmea', 'neo-6m', 'navigation'],
            'interfaces': ['uart'], 'supply': '3.3–5 V module', 'compat': 'direct', 'shape': 'module-gps',
            'footprint': [[i, 0] for i in range(4)],
            'description': 'Streams NMEA sentences ($GPRMC, $GPGGA) once a second at 9600 baud on TX.'}

    transient = {'started': False}

    def setup(self):
        self.started = False
        self.sentences = 0

    def sense(self, volts, now):
        if not self.started and self.operational():
            self.started = True
            self.schedule_in(1_000_000_000, self._emit)

    inputs = ('RX',)

    def _emit(self):
        if not self.operational():
            self.started = False
            return
        lat, lon = self.stimuli['lat'], self.stimuli['lon']
        def coord(value, width):
            degrees = int(abs(value))
            return f'{degrees:0{width}d}{(abs(value) - degrees) * 60:07.4f}'
        t = datetime.datetime.now(datetime.timezone.utc)
        fix = 'A' if self.stimuli['fix'] else 'V'
        body = (f'GPRMC,{t:%H%M%S}.00,{fix},{coord(lat, 2)},{"N" if lat >= 0 else "S"},'
                f'{coord(lon, 3)},{"E" if lon >= 0 else "W"},0.0,0.0,{t:%d%m%y},,,A')
        checksum = 0
        for c in body.encode():
            checksum ^= c
        self.uart_send(f'${body}*{checksum:02X}\r\n'.encode())
        self.sentences += 1
        self.schedule_in(1_000_000_000, self._emit)

    def elements(self):
        els = [('R', '@VCC', '@GND', 100.0, 'iq')]
        if self.powered():
            els.append(('V', '@TX', '@GND', 3.3, 200.0, 'tx-idle'))
        return els

    def state(self):
        return {'sentences': self.sentences}
