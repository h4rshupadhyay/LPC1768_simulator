"""Every Workbench example: wired project + firmware behave as described."""
import functools
import json
from pathlib import Path

import pytest

from simulator.compiler import Compiler
from simulator.engine import Machine
from simulator.terminal import Terminal

ROOT = Path(__file__).resolve().parents[1]
CATALOG = {e['id']: e for e in json.loads((ROOT / 'examples/bench/catalog.json').read_text(encoding='utf-8'))}


@functools.lru_cache(maxsize=None)
def firmware(name):
    return Compiler().compile((ROOT / 'examples/bench' / name).read_text(encoding='utf-8')).hex


def bench(example_id):
    spec = CATALOG[example_id]
    m = Machine(firmware(spec['file']), target=spec['project']['target'])
    m.board.circuit.load(spec['project'])
    terminal = Terminal('pc', 9600, 0)
    m.terminals = {0: terminal}
    return m, terminal


def run_until(m, condition, slices):
    for _ in range(slices):
        m.run(20000)
        if condition():
            return True
    return False


def text(terminal):
    return ''.join(terminal.text)


def test_catalog_entries_reference_existing_files_and_parts():
    from simulator.parts import REGISTRY
    for spec in CATALOG.values():
        assert (ROOT / 'examples/bench' / spec['file']).is_file()
        for part in spec['project']['parts']:
            assert part['type'] in REGISTRY


def test_uart_hello_prints_and_echoes():
    m, t = bench('uart_hello')
    assert run_until(m, lambda: 'Type something' in text(t), 600)
    uart = m.uarts[0]
    t.send(m, b'ok', lambda b: uart.receive(b, t.baud))
    assert run_until(m, lambda: text(t).endswith('ok'), 300)


@pytest.mark.parametrize('distance', [42, 120])
def test_ultrasonic_reports_the_slider_distance(distance):
    m, t = bench('ultrasonic')
    m.board.circuit.set_stimulus('sonar', 'distance_cm', distance)
    assert run_until(m, lambda: 'cm' in text(t), 1500)
    line = text(t).split('distance: ')[1]
    assert abs(int(line.split()[0]) - distance) <= 1
    keys = {f['key'] for f in m.board.circuit.evaluate()}
    assert not any(k.startswith(('pad-over', 'pad-5v')) for k in keys)


def test_unsafe_ultrasonic_is_explained_with_a_divider_fix():
    m, t = bench('ultrasonic_unsafe')
    assert run_until(m, lambda: 'cm' in text(t), 1500)

    def echo_finding():  # the 5 V level exists only while an echo pulse is HIGH
        return next((f for f in m.board.circuit.evaluate() if f['key'] == 'pad-5v:P0.6'), None)
    assert run_until(m, echo_finding, 2000)
    finding = echo_finding() or next(f for f in m.board.circuit.findings if f['key'] == 'pad-5v:P0.6')
    assert finding['severity'] == 'info'
    assert 'ADC' in finding['why'] or 'analog' in finding['consequence']


def test_bmp280_example_reads_id_and_temperature():
    m, t = bench('bmp280')
    assert run_until(m, lambda: ' Pa' in text(t), 1500)
    assert 'chip id 0x58' in text(t)
    temperature = float(text(t).split('T = ')[1].split()[0])
    assert temperature == pytest.approx(24.5, abs=0.02)
    pressure = int(text(t).split('P = ')[1].split()[0])
    assert pressure == pytest.approx(100800, abs=3)


def test_bmp280_on_5v_is_damaged_and_fix_restores_it():
    m, t = bench('bmp280_5v')
    c = m.board.circuit
    run_until(m, lambda: 'T = ' in text(t), 200)
    findings = c.evaluate()
    finding = next(f for f in findings if f['key'] == 'overvolt:bmp')
    assert finding['severity'] == 'damage-risk'
    patch = finding['fixes'][0]['apply']
    assert patch, 'the Doctor offers a one-click supply move'

    def damaged():
        c.evaluate()  # damage escalates when overstress outlasts the hold-off
        return c.parts['bmp'].damaged is not None
    assert run_until(m, damaged, 600)
    # A damaged chip no longer acknowledges: the I2C2 controller finds no device.
    assert m.i2c_devices(m.i2cs[2], 0x76) == []
    c.apply(patch)
    c.apply([{'op': 'replace', 'id': 'bmp'}])
    m.observe()
    assert c.parts['bmp'].operational()
    assert not any(f['key'].startswith(('overvolt', 'damaged')) for f in c.evaluate())


def test_servo_example_sweeps_the_horn():
    m, t = bench('servo')
    servo = m.board.circuit.parts['servo1']
    angles = set()
    for _ in range(1200):
        m.run(20000)
        angles.add(round(servo.angle))
        if len(angles) > 3:
            break
    assert len(angles) > 3
    assert servo.state()['period_ms'] == pytest.approx(20.0, abs=0.2)


def test_pot_dimmer_reads_the_wiper_and_dims_the_led():
    m, t = bench('pot_dimmer')
    assert run_until(m, lambda: '\n' in text(t), 400)
    value = int(text(t).split()[0])
    assert value == pytest.approx(0.3 * 4095, abs=40)  # wiper 30% up from GND
    assert m.pwm_duty(1, (2, 0)) == pytest.approx(value / 4096, abs=0.02)


def test_oled_example_draws_on_the_panel():
    m, t = bench('oled')
    oled = m.board.circuit.parts['oled1']
    assert run_until(m, lambda: oled.writes >= 1024, 1500)
    state = oled.state()
    assert state['on'] and state['fb']
    assert bytes.fromhex(state['fb'])[0] & 1  # top-left corner of the frame


def test_dht11_example_decodes_in_precise_timing():
    m, t = bench('dht11')
    assert run_until(m, lambda: text(t).endswith('\n') and len(text(t)) > 5, 2500)
    assert 'humidity 61 %  temperature 27 C' in text(t)
