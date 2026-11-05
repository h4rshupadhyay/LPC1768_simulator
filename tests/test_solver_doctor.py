"""Circuit solver and Circuit Doctor behavior, without firmware."""
from pathlib import Path

import pytest

from simulator.engine import Machine
from simulator.solver import solve
from simulator import doctor

IDLE = Path('examples/idle.hex').read_text()


def bare():
    return Machine(IDLE, target='bare')


def kinds(findings):
    return {f['key'].split(':')[0] for f in findings}


def test_divider_and_led_operating_points():
    # 5 V -> 10k -> node -> 20k -> ground
    s = solve(1, [('V', 0, -1, 5.0, 0.0001, 'src'), ])
    assert s.v(0) == pytest.approx(5.0, abs=1e-3)
    s = solve(2, [('V', 0, -1, 5.0, 0.01, 'src'), ('R', 0, 1, 10_000, 'top'), ('R', 1, -1, 20_000, 'bottom')])
    assert s.v(1) == pytest.approx(3.333, abs=2e-3)
    # 3.3 V through 330 ohm into a red LED: (3.3 - 1.9) / (330 + 12)
    s = solve(2, [('V', 0, -1, 3.3, 0.01, 'src'), ('R', 0, 1, 330, 'r'), ('D', 1, -1, 1.9, 12, 'led')])
    assert s.results['led']['i'] == pytest.approx(1.4 / 342, rel=1e-3)
    assert s.results['led']['state'] == 'on'
    # Reverse-biased LED carries nothing.
    s = solve(2, [('V', 0, -1, 3.3, 0.01, 'src'), ('R', 0, 1, 330, 'r'), ('D', -1, 1, 1.9, 12, 'led')])
    assert s.results['led']['i'] == 0


def test_npn_low_side_switch_saturates():
    elements = [('V', 0, -1, 5.0, 0.01, 'vcc'), ('R', 0, 1, 100, 'load'),
                ('V', 2, -1, 3.3, 70, 'pin'), ('R', 2, 3, 1_000, 'rb'), ('NPN', 3, 1, -1, 150.0, 'q')]
    s = solve(4, elements)
    assert s.results['q']['state'] == 'sat'
    assert s.v(1) < 0.3
    elements[2] = ('V', 2, -1, 0.0, 70, 'pin')
    s = solve(4, elements)
    assert s.results['q']['state'] == 'off'
    assert s.v(1) == pytest.approx(5.0, abs=0.01)


def test_divider_fix_values_stay_below_3v3():
    top, bottom, out = doctor.divider(5.0)
    assert out <= 3.3 and out >= 2.6
    assert out == pytest.approx(5.0 * bottom / (top + bottom))
    value, current = doctor.series_resistor(3.3, 1.9, 0.0035)
    assert value >= 400 and current <= 0.0035


def test_external_led_lights_from_gpio_and_reports_overcurrent_without_resistor():
    m = bare()
    c = m.board.circuit
    led = c.add_part('led', 'led1')
    c.connect('mcu.P0.4', 'led1.A')
    c.connect('led1.K', 'mcu.GND')
    m.write_word(0x2009C000, 1 << 4)
    m.write_word(0x2009C018, 1 << 4)
    m.observe()
    assert led.current() > 0.01  # ~ (3.3-1.9)/(70+12)
    findings = c.evaluate()
    assert 'led-resistor' in kinds(findings)
    assert any(f['key'] == 'pad-current:P0.4' for f in findings)
    c.add_part('resistor', 'r1', {'ohms': 470})
    c.disconnect('mcu.P0.4', 'led1.A')
    c.connect('mcu.P0.4', 'r1.1')
    c.connect('r1.2', 'led1.A')
    m.observe()
    assert 0.002 < led.current() < 0.004
    findings = c.evaluate()
    assert not any(f['key'].startswith(('pad-current', 'led-resistor')) for f in findings)


def test_bmp280_on_5v_is_damaged_after_hold_off_and_fix_moves_supply():
    m = Machine(IDLE, target='bare')
    c = m.board.circuit
    c.add_part('bench_supply', 'psu')
    bmp = c.add_part('bmp280', 'bmp')
    c.connect('psu.+', 'bmp.VCC')
    c.connect('psu.-', 'mcu.GND')
    c.connect('bmp.GND', 'mcu.GND')
    m.observe()
    findings = c.evaluate()
    over = next(f for f in findings if f['key'] == 'overvolt:bmp')
    assert over['severity'] == 'damage-risk'
    assert 'absolute maximum 4.25' in over['what']
    m.virtual_ns += 60_000_000  # sustained overstress
    findings = c.evaluate()
    assert bmp.damaged and any(f['key'] == 'damaged:bmp' for f in findings)
    assert not bmp.operational()
    replace = next(f for f in findings if f['key'] == 'damaged:bmp')['fixes'][0]['apply']
    c.disconnect('psu.+', 'bmp.VCC')
    c.connect('mcu.3V3', 'bmp.VCC')
    c.apply(replace)
    m.observe()
    assert bmp.damaged is None and bmp.operational()
    assert not any(f['key'].startswith('overvolt') for f in c.evaluate())


def test_5v_echo_into_analog_pin_explains_and_divider_fix_applies():
    m = bare()
    c = m.board.circuit
    c.add_part('analog_source', 'echo')
    c.set_stimulus('echo', 'volts', 5.0)
    c.connect('echo.OUT', 'mcu.P0.23')
    c.connect('echo.GND', 'mcu.GND')
    m.write_word(m.PIN + 4, 1 << 14)  # PINSEL1: P0.23 = AD0.0
    m.observe()
    findings = c.evaluate()
    finding = next(f for f in findings if f['key'] == 'pad-over:P0.23')
    assert 'not 5 V tolerant' in finding['what']
    fix = finding['fixes'][0]
    assert 'divider' in fix['label'].lower() and fix['apply']
    c.apply(fix['apply'])
    m.observe()
    v = m.board.pad_voltage(0, 23)
    assert 2.5 < v <= 3.3
    assert not any(f['key'].startswith('pad-over') for f in c.evaluate())


def test_digital_5v_signal_is_information_only():
    m = bare()
    c = m.board.circuit
    c.add_part('analog_source', 'sig')
    c.set_stimulus('sig', 'volts', 5.0)
    c.connect('sig.OUT', 'mcu.P0.4')
    c.connect('sig.GND', 'mcu.GND')
    m.observe()
    finding = next(f for f in c.evaluate() if f['key'] == 'pad-5v:P0.4')
    assert finding['severity'] == 'info'
    assert m.gpio_value(0) & (1 << 4)


def test_short_from_output_to_ground_damages_pad_in_realistic_mode():
    m = bare()
    c = m.board.circuit
    c.add_part('resistor', 'r0', {'ohms': 0.1})
    c.connect('mcu.P0.4', 'r0.1')
    c.connect('r0.2', 'mcu.GND')
    m.write_word(0x2009C000, 1 << 4)
    m.write_word(0x2009C018, 1 << 4)
    m.observe()
    c.evaluate()
    m.virtual_ns += 60_000_000
    findings = c.evaluate()
    assert (0, 4) in m.damaged_pads
    assert m.pin_output(0, 4) is None
    assert any(f['key'] == 'damaged-pad:P0.4' for f in findings)


def test_i2c_device_without_pullups_is_flagged_statically():
    m = bare()
    c = m.board.circuit
    c.add_part('bmp280', 'bmp')
    c.connect('bmp.SDA', 'mcu.P0.27')
    c.connect('bmp.SCL', 'mcu.P0.28')
    c.connect('bmp.VCC', 'mcu.3V3')
    c.connect('bmp.GND', 'mcu.GND')
    m.observe()
    keys = {f['key'] for f in c.evaluate()}
    assert 'pullup:bmp:SDA' in keys and 'pullup:bmp:SCL' in keys
    fix = next(f for f in c.evaluate() if f['key'] == 'pullup:bmp:SDA')['fixes'][0]['apply']
    c.apply(fix)
    keys = {f['key'] for f in c.evaluate()}
    assert 'pullup:bmp:SDA' not in keys


def test_breadboard_strips_join_holes_and_reject_double_occupancy():
    m = bare()
    c = m.board.circuit
    c.add_part('breadboard', 'bb1')
    c.add_part('resistor', 'r1', {'ohms': 1000}, mount={'1': 'bb1.a10', '2': 'bb1.a14'})
    with pytest.raises(ValueError, match='occupied'):
        c.add_part('resistor', 'r2', mount={'1': 'bb1.a10', '2': 'bb1.a20'})
    c.connect('mcu.P0.4', 'bb1.e10')
    c.connect('bb1.c14', 'bb1.tn1')
    c.connect('bb1.tn50', 'mcu.GND')
    m.write_word(0x2009C000, 1 << 4)
    m.write_word(0x2009C018, 1 << 4)
    m.observe()
    current = c.element_result('r1:r')['i']
    assert current == pytest.approx(3.3 / 1070, rel=1e-2)
    assert m.board.same_net('r1.2', 'GND')


def test_unpowered_part_and_project_round_trip():
    m = Machine(IDLE, target='als')
    c = m.board.circuit
    c.add_part('breadboard', 'bb1', {'size': 'half'})
    c.add_part('hcsr04', 'sonar1', mount={'VCC': 'bb1.a1', 'TRIG': 'bb1.a2', 'ECHO': 'bb1.a3', 'GND': 'bb1.a4'})
    c.connect('kit.CNA.1', 'bb1.b2')
    keys = {f['key'] for f in c.evaluate()}
    assert 'unpowered:sonar1' in keys
    exported = c.export()
    c.clear()
    c.load(exported)
    assert set(c.parts) == {'bb1', 'sonar1'}
    assert c.wires == exported['wires']
    assert m.board.same_net('sonar1.TRIG', 'P0.4')


def test_floating_input_is_noted_and_can_be_randomized():
    m = bare()
    m.write_word(m.PIN + 0x40, 2 << 8)  # P0.4 no pull
    m.read_word(0x2009C014)
    assert 'floating-read' in m.notes
    m.floating_mode = 'random'
    values = {(m.read_word(0x2009C014) >> 4) & 1 for _ in range(64)}
    assert values == {0, 1}
