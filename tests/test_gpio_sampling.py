"""Port-word sampling compared with the independent, scalar pad definition."""
from pathlib import Path
import random

from simulator.engine import Machine


def test_all_ports_random_mux_direction_pull_od_and_external_nets():
    m = Machine(Path('examples/idle.hex').read_text())
    m.board.connect('CNA', 'CNC')
    m.board.connect('CND', 'CNB3')
    m.board.set_jumper('JP5', 'closed')
    rng = random.Random(1768)
    for _ in range(500):
        m.board.keys = {key for key in range(16) if rng.randrange(8) == 0}
        for port in range(5):
            gpio = m.gpio[port]
            gpio.direction, gpio.latch, gpio.mask = (rng.getrandbits(32) for _ in range(3))
            for offset in (0, 4, 0x40, 0x44):
                m.regs[m.PIN + port * 8 + offset] = rng.getrandbits(32)
            m.regs[m.PIN + 0x68 + port * 4] = rng.getrandbits(32)
        levels = m.board.signals()
        for port in range(5):
            expected = 0
            for pin in range(32):
                node = f'P{port}.{pin}'
                level = levels.get(node)
                if node not in levels:
                    level = m.pin_output(port, pin)
                    if level is None:
                        level = m.pin_pull(port, pin)
                expected |= int(bool(level)) << pin
            expected &= ~m.gpio[port].mask & 0xffffffff
            assert m.gpio_value(port) == expected


def test_switch_pullup_cannot_power_an_led_or_fight_ground():
    m = Machine(Path('examples/idle.hex').read_text())
    m.board.connect_wire('CNB1.7', 'CNA1.1')
    assert not m.snapshot()['leds'][0]
    m.board.disconnect_all()
    m.board.connect_wire('CNB1.7', 'CNB1.10')
    assert not m.snapshot()['warnings']
    assert not m.snapshot()['headerPins']['CNB1'][6]['conflict']


def test_inspector_distinguishes_floating_and_external_biases():
    m = Machine(Path('examples/idle.hex').read_text())
    m.regs[m.PIN + 0x40] = (2 << 8) | (2 << 10)  # P0.4/5 no pulls.
    m.board.connect_wire('CNA.1', 'CNA.2')
    pins = m.snapshot()['headerPins']
    assert pins['CNA'][0]['level'] is None and pins['CNA'][1]['level'] is None
    assert pins['CNB3'][0]['level'] == 0
    assert pins['CNB2'][0]['level'] == 1
    assert pins['CNB1'][6]['level'] == 1
    m.board.sw2 = True
    assert m.snapshot()['headerPins']['CNB1'][6]['level'] == 0
