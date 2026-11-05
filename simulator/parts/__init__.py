"""Component catalogue: every part type the bench can hold.

The catalogue is generated from the part classes so that metadata, pins,
ratings and behavior cannot drift apart.
"""
from __future__ import annotations

from .passive import Breadboard, Resistor, Capacitor, Potentiometer, PushButton, Switch, Keypad, Joystick, RotaryEncoder
from .semis import LED, RGBLed, Diode, Zener, NPN, PNP, MOSFET, LevelShifter, Regulator, SevenSegment, ShiftRegister, ULN2003
from .sensors import (LDR, Thermistor, LM35, TMP36, GasSensor, SoilMoisture, SoundSensor, FlameSensor, SharpIR,
                      CurrentSensor, Accelerometer, AnalogSource, SignalGenerator, HCSR04, PIR, HallSwitch, DHT, DS18B20)
from .bus_devices import (BMP280, MPU6050, SSD1306, LCDBackpack, EEPROM24C, RTCModule, LM75, BH1750, GenericI2C,
                          MCP3008, MAX7219, SerialBridge, Bluetooth, GPS)
from .outputs import Buzzer, Servo, DCMotor, RelayModule, StepperBoard, LCD1602, NeoPixel, PowerModule, Battery, BenchSupply

CLASSES = [
    Breadboard, Resistor, Capacitor, Potentiometer, PushButton, Switch, Keypad, Joystick, RotaryEncoder,
    LED, RGBLed, Diode, Zener, NPN, PNP, MOSFET, LevelShifter, Regulator, SevenSegment, ShiftRegister, ULN2003,
    LDR, Thermistor, LM35, TMP36, GasSensor, SoilMoisture, SoundSensor, FlameSensor, SharpIR, CurrentSensor,
    Accelerometer, AnalogSource, SignalGenerator, HCSR04, PIR, HallSwitch, DHT, DS18B20,
    BMP280, MPU6050, SSD1306, LCDBackpack, EEPROM24C, RTCModule, LM75, BH1750, GenericI2C, MCP3008, MAX7219,
    SerialBridge, Bluetooth, GPS,
    Buzzer, Servo, DCMotor, RelayModule, StepperBoard, LCD1602, NeoPixel, PowerModule, Battery, BenchSupply,
]
REGISTRY = {cls.kind: cls for cls in CLASSES}
assert len(REGISTRY) == len(CLASSES), 'duplicate part kinds'

COMPAT_TEXT = {
    'direct': 'Works directly with the LPC1768',
    'direct-3v3': 'Direct, but 3.3 V supply only',
    'divider': 'Needs a divider or level shifter on its output',
    'divider-if-5v': 'Direct from 3.3 V; needs a divider when powered from 5 V',
    'level-shift': 'Needs a level shifter (5 V logic input)',
    'driver': 'Needs a transistor driver',
    'supply': 'Needs its own supply (more current than a pin or the 3.3 V rail)',
}


def catalog():
    items = []
    for cls in CLASSES:
        meta = dict(cls.meta)
        supply = cls.supply if not isinstance(cls.__dict__.get('supply'), property) else None
        items.append({
            'kind': cls.kind, 'name': meta.get('name', cls.kind), 'category': meta.get('category', 'Other'),
            'aliases': meta.get('aliases', []), 'interfaces': meta.get('interfaces', []),
            'supply': meta.get('supply', '-'), 'compat': meta.get('compat', 'direct'),
            'compatText': COMPAT_TEXT.get(meta.get('compat', 'direct'), ''),
            'description': meta.get('description', ''), 'shape': meta.get('shape', 'module'),
            'footprint': meta.get('footprint', [[i, 0] for i in range(len(cls.pins))]),
            'pins': list(cls.pins), 'defaults': cls.defaults, 'choices': {k: list(v) for k, v in cls.choices.items()},
            'stimuli': {name: {'min': spec[0], 'max': spec[1], 'default': spec[2], 'unit': spec[3], 'label': spec[4]}
                        for name, spec in cls.stimuli_spec.items()},
            'ratings': {'supply': list(supply) if supply else None, 'pins': cls.pin_limits},
        })
    return items
