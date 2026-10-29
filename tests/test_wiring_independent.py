"""Independent ribbon and per-pin patch-wire oracle for the ALS LPC1768 board.

Pins are transcribed from ALS-SDA-ARMCTXM3-01-UM1 printed pp.23-24 (CNA-CND),
p.30 (CNAD), pp.33-35 (CNA1, CNB1, CNB2) and ESD Appendix C with PDF p.42
(CNB3 columns on pins 1-4, rows on 5-8). This module imports neither
board/mapping.json, simulator.board.MAPPING nor Board._pin. It drives the model
through Runtime.physical, the API shared by Flask and the Pyodide worker, and
LPC1768 GPIO/PINCON registers; it observes FIOPIN, the public snapshot and
display output only.

The oracle is ideal digital connectivity: one conductor joins two nets, LOW wins
a strong-driver conflict, keypad columns have 15k pulldowns, U7 address inputs
have 10k pullups and released SW2 holds its net HIGH. It does not measure a
physical board, voltage margins or current.
"""
import hashlib
import itertools
import json
import os
from pathlib import Path

import pytest

from simulator.runtime import Runtime

GPIO_HEADERS = {
    'CNA': ['P0.4', 'P0.5', 'P0.6', 'P0.7', 'P0.8', 'P0.9', 'P0.10', 'P0.11', 'NC', 'GND'],
    'CNB': ['P1.23', 'P1.24', 'P1.25', 'P1.26', 'P2.10', 'P2.11', 'P2.12', 'JP4=1-2:P2.13', 'NC', 'GND'],
    'CNC': ['P0.15', 'P0.16', 'P0.17', 'P0.18', 'P0.19', 'P0.20', 'P0.21', 'P0.22', 'JP4=2-3:P2.13', 'GND'],
    'CND': ['P0.23', 'P0.24', 'P0.25', 'JP5=closed:P0.26', 'P0.27', 'P0.28', 'P2.0', 'P2.1', 'NC', 'GND'],
}
PERIPHERAL_HEADERS = {
    'CNA1': [f'LED{i}' for i in range(8)] + ['NC', 'GND'],              # LD2-LD9 anodes
    'CNA2': [f'SEG{i}' for i in range(8)] + ['NC', 'GND'],              # a-g, dp via U12
    'CNB2': ['ADDR0', 'ADDR1', 'ADDR2', 'ADDR3'] + ['NC'] * 5 + ['GND'],  # U7 inputs A-D
    'CNB3': ['COL0', 'COL1', 'COL2', 'COL3', 'ROW0', 'ROW1', 'ROW2', 'ROW3', 'NC', 'GND'],
    'CNB1': ['PWM', 'NC', 'MAT1.1', 'CAP0.0', 'NC', 'NC', 'SW2@7', 'NC', 'SW2@9', 'GND'],
    'CNAD': ['D4', 'D5', 'D6', 'D7', 'RS', 'E', 'NC', 'NC', 'NC', 'GND'],
}
HEADERS = {**GPIO_HEADERS, **PERIPHERAL_HEADERS}
PINS = [f'{h}.{n}' for h in HEADERS for n in range(1, 11)]
GPIO_PINS = [p for p in PINS if p.split('.')[0] in GPIO_HEADERS]
# The manual documents CNB1 match/capture lines, but the model has no
# MAT1.1/CAP0.0 pad function; the oracle treats them as electrically absent.
UNMODELED = {'MAT1.1', 'CAP0.0'}
OUTPUT_LOADS = {f'SEG{i}' for i in range(8)} | {'D4', 'D5', 'D6', 'D7', 'RS', 'E'}
BASE_JUMPERS = {'JP4': '1-2', 'JP5': 'closed', 'JP16': 'closed', 'JP18': 'open'}

GPIO_BASE = 0x2009C000
PINMODE_BASE = 0x4002C040
PINSEL_BASE = 0x4002C000
EXTINT = 0x400FC140


def resolve(endpoint, jumpers, sw2_pin=7):
    """Net reached by one header pin, or None when nothing is connected."""
    header, number = endpoint.split('.')
    token = HEADERS[header][int(number) - 1]
    if '=' in token:
        condition, net = token.split(':')
        jumper, position = condition.split('=')
        return net if jumpers[jumper] == position else None
    if token.startswith('SW2@'):
        return 'SW2' if int(token[4:]) == sw2_pin else None
    return None if token == 'NC' or token in UNMODELED else token


def is_mcu(net):
    return net is not None and net[0] == 'P' and '.' in net


def port_pin(net):
    port, pin = net[1:].split('.')
    return int(port), int(pin)


class Bench:
    def __init__(self, jumpers=BASE_JUMPERS, sw2_pin=7):
        self.rt = Runtime(start_worker=False, realtime=False)
        self.jumpers = dict(jumpers)
        self.sw2_pin = sw2_pin
        for name, value in self.jumpers.items():
            self.act(action='jumper', name=name, value=value)
        self.act(action='sw2-profile', pin=sw2_pin)

    @property
    def m(self):
        return self.rt.machine

    def act(self, **data):
        return self.rt.physical(data)

    def state(self):
        return self.rt.snapshot()

    def close(self):
        self.rt.close()

    def set_jumper(self, name, value):
        self.jumpers[name] = value
        return self.act(action='jumper', name=name, value=value)

    def output(self, net, level):
        port, pin = port_pin(net)
        base = GPIO_BASE + port * 0x20
        self.m.write_word(base, self.m.read_word(base) | 1 << pin)
        self.m.write_word(base + (0x18 if level else 0x1C), 1 << pin)

    def input(self, net, pull):
        port, pin = port_pin(net)
        address = PINMODE_BASE + (port * 2 + pin // 16) * 4
        shift = 2 * (pin % 16)
        mode = {'up': 0, 'down': 3}[pull]
        self.m.write_word(address, (self.m.read_word(address) & ~(3 << shift)) | mode << shift)
        base = GPIO_BASE + port * 0x20
        self.m.write_word(base, self.m.read_word(base) & ~(1 << pin))

    def idle(self, net):
        port, pin = port_pin(net)
        self.input(net, 'up')
        self.m.write_word(GPIO_BASE + port * 0x20 + 0x1C, 1 << pin)

    def sense(self, net):
        port, pin = port_pin(net)
        return (self.m.read_word(GPIO_BASE + port * 0x20 + 0x14) >> pin) & 1

    def leds(self):
        return self.state()['leds']

    def warnings(self):
        return self.state()['warnings']


def conflicts(bench):
    # Same-kind ribbons add a separate advisory warning; only drive conflicts matter here.
    return [w for w in bench.warnings() if 'Conflicting' in w]


def expect_isolated(bench, net, why):
    bench.input(net, 'up')
    assert bench.sense(net) == 1, why
    bench.input(net, 'down')
    assert bench.sense(net) == 0, why
    bench.output(net, 1)
    state = bench.state()
    assert not any(state['leds']) and state['pwm'] == 0.0, why
    bench.idle(net)


def expect_link(bench, x, y, why):
    """Assert the observable effect of one conductor joining resolved nets x and y."""
    if not is_mcu(x):
        x, y = y, x
    if not is_mcu(x):
        return  # no MCU pad on this conductor; nothing firmware-observable
    if y is None:
        expect_isolated(bench, x, why)
        return
    if is_mcu(y):
        for a, b in ((x, y), (y, x)):
            bench.output(a, 1)
            bench.input(b, 'down')
            assert bench.sense(b) == 1, why
            bench.output(a, 0)
            bench.input(b, 'up')
            assert bench.sense(b) == 0, why
        bench.output(x, 1)
        bench.output(y, 0)
        assert (bench.sense(x), bench.sense(y)) == (0, 0), why
        assert any('Conflicting' in w for w in bench.warnings()), why
        bench.idle(x)
        bench.idle(y)
        assert not conflicts(bench), why
        return
    if y.startswith('LED'):
        bench.output(x, 1)
        assert bench.leds() == [i == int(y[3:]) for i in range(8)], why
        assert not conflicts(bench), why
        bench.output(x, 0)
        assert not any(bench.leds()), why
    elif y == 'PWM':
        bench.output(x, 1)
        assert bench.state()['pwm'] == 1.0, why
        bench.output(x, 0)
        assert bench.state()['pwm'] == 0.0, why
    elif y == 'SW2':
        bench.input(x, 'down')
        assert bench.sense(x) == 1, why
        bench.act(action='switch', pressed=True)
        assert bench.sense(x) == 0, why
        bench.input(x, 'up')
        assert bench.sense(x) == 0, why
        bench.act(action='switch', pressed=False)
        assert bench.sense(x) == 1, why
    elif y.startswith('COL'):
        for pull in ('up', 'down'):
            bench.input(x, pull)
            assert bench.sense(x) == 0, why
    elif y.startswith('ROW'):
        bench.input(x, 'up')
        assert bench.sense(x) == 1, why
        key = int(y[3:]) * 4
        bench.act(action='key', key=key, pressed=True)
        assert bench.sense(x) == 0, why  # weak pull-up sinks through D6-D9 and 15k
        bench.act(action='key', key=key, pressed=False)
        assert bench.sense(x) == 1, why
    elif y.startswith('ADDR'):
        for pull in ('up', 'down'):
            bench.input(x, pull)
            assert bench.sense(x) == 1, why
    elif y == 'GND':
        bench.input(x, 'up')
        assert bench.sense(x) == 0, why
        bench.output(x, 1)
        assert bench.sense(x) == 0, why
        assert any('Conflicting' in w for w in bench.warnings()), why
    elif y in OUTPUT_LOADS:
        bench.input(x, 'up')
        assert bench.sense(x) == 1, why
        bench.input(x, 'down')
        assert bench.sense(x) == 0, why
    else:
        raise AssertionError(f'oracle has no rule for {y}')
    bench.idle(x)


def relevant_configs(headers):
    """Jumper and SW2-profile combinations that can change these headers."""
    jp4 = ['open', '1-2', '2-3'] if {'CNB', 'CNC'} & set(headers) else ['1-2']
    jp5 = ['open', 'closed'] if 'CND' in headers else ['closed']
    sw2 = [7, 9] if 'CNB1' in headers else [7]
    for a, b, c in itertools.product(jp4, jp5, sw2):
        yield {**BASE_JUMPERS, 'JP4': a, 'JP5': b}, c


# --- Ribbon baseline: every declared header pair, every conductor -------------

@pytest.mark.parametrize('pair', list(itertools.combinations(HEADERS, 2)), ids='-'.join)
def test_straight_ribbon_every_conductor(pair):
    a, b = pair
    for jumpers, sw2 in relevant_configs(pair):
        bench = Bench(jumpers, sw2)
        try:
            bench.act(action='connect', a=a, b=b)
            assert bench.state()['cables'] == [[a, b]]
            for n in range(1, 11):
                ea, eb = f'{a}.{n}', f'{b}.{n}'
                expect_link(bench, resolve(ea, jumpers, sw2), resolve(eb, jumpers, sw2),
                            f'{ea}<->{eb} {jumpers} SW2@{sw2}')
        finally:
            bench.close()


def test_ribbon_occupancy_and_invalid_headers_are_atomic():
    bench = Bench()
    try:
        bench.act(action='connect', a='CNA', b='CNA1')
        before = bench.state()
        for a, b in [('CNA', 'CNA2'), ('CNC', 'CNA1'), ('CNA1', 'CNA'), ('CNC', 'CNC'),
                     ('CN16', 'CNB1'), ('cnc', 'CNA2'), (None, 'CNA2'), ('CNC', 1)]:
            with pytest.raises(ValueError):
                bench.act(action='connect', a=a, b=b)
            assert bench.state() == before, (a, b)
    finally:
        bench.close()


# --- Patch wires --------------------------------------------------------------

def wire_bench(jumpers=BASE_JUMPERS, sw2=7):
    bench = Bench(jumpers, sw2)
    try:
        bench.act(action='disconnect-wire', a='CNA.1', b='CNA1.1')
    except ValueError as error:
        if 'Unknown physical input action' in str(error):
            bench.close()
            pytest.skip('Runtime.physical has no connect-wire/disconnect-wire action yet')
    return bench


def wires(state):
    return sorted(sorted(w) for w in state['wires'])


def sweep(bench, pairs, sw2=7):
    for i, (a, b) in enumerate(pairs):
        if i % 2:
            a, b = b, a
        state = bench.act(action='connect-wire', a=a, b=b)
        assert wires(state) == [sorted([a, b])]
        expect_link(bench, resolve(a, bench.jumpers, sw2), resolve(b, bench.jumpers, sw2),
                    f'wire {a}<->{b} {bench.jumpers} SW2@{sw2}')
        state = bench.act(action='disconnect-wire', a=b, b=a)
        assert state['wires'] == [] and not any(state['leds']) and not state['warnings']


def test_single_wire_every_gpio_pin_to_every_header_pin():
    bench = wire_bench()
    try:
        pairs = [(a, b) for a, b in itertools.combinations(PINS, 2) if a in GPIO_PINS or b in GPIO_PINS]
        assert len(pairs) == 780 + 40 * 60
        sweep(bench, pairs)
    finally:
        bench.close()


def test_peripheral_to_peripheral_wires_are_accepted_and_removed():
    bench = wire_bench()
    try:
        peripheral = [p for p in PINS if p not in GPIO_PINS]
        for a, b in itertools.combinations(peripheral, 2):
            assert wires(bench.act(action='connect-wire', a=a, b=b)) == [sorted([a, b])]
            assert bench.act(action='disconnect-wire', a=a, b=b)['wires'] == []
    finally:
        bench.close()


@pytest.mark.parametrize('jp4,jp5', itertools.product(['open', '1-2', '2-3'], ['open', 'closed']))
def test_jumper_gated_pins_follow_every_jumper_position(jp4, jp5):
    bench = wire_bench({**BASE_JUMPERS, 'JP4': jp4, 'JP5': jp5})
    try:
        gated = ['CNB.8', 'CNC.9', 'CND.4']
        sweep(bench, [(g, p) for g in gated for p in PINS if p not in gated])
    finally:
        bench.close()


@pytest.mark.parametrize('sw2', [7, 9])
def test_sw2_profile_pins_from_every_gpio_pin(sw2):
    bench = wire_bench(sw2=sw2)
    try:
        sweep(bench, [(g, s) for g in GPIO_PINS for s in ('CNB1.7', 'CNB1.9')], sw2)
    finally:
        bench.close()


BAD_ENDPOINTS = [None, 1, 1.0, True, ['CNA', 1], {'h': 'CNA'}, '', 'CNA', 'CNA.', 'CNA.0', 'CNA.11',
                 'CNA.01', 'CNA.1.0', 'cna.1', ' CNA.1', 'CNA.1 ', 'CNA.1\n', 'CNA.+1', 'CNA.1_0',
                 'CNA.١', 'CNA.１', 'CN16.1', 'CNX.1', 'CNA:1', 'CNA-1', 'P0.4', 'JP4.1']


def test_rejected_wire_requests_leave_no_trace():
    bench = wire_bench()
    try:
        bench.act(action='connect', a='CNB', b='CNB3')
        bench.act(action='connect-wire', a='CNA.1', b='CNA1.1')
        bench.output('P0.4', 1)
        before = bench.state()
        assert before['leds'][0] and wires(before) == [['CNA.1', 'CNA1.1']]
        attempts = [(bad, 'CNA1.2') for bad in BAD_ENDPOINTS] + [('CNA1.2', bad) for bad in BAD_ENDPOINTS]
        attempts += [
            ('CNA.2', 'CNA.2'),        # one pin to itself
            ('CNA.1', 'CNA1.1'),       # duplicate
            ('CNA1.1', 'CNA.1'),       # duplicate, reversed
            ('CNA.1', 'CNA1.2'),       # first pin already patched
            ('CNA1.1', 'CNC.1'),       # second pin already patched
            ('CNB.1', 'CNA1.3'),       # header carries a ribbon
            ('CNA1.3', 'CNB3.10'),     # header carries a ribbon
        ]
        for a, b in attempts:
            with pytest.raises(ValueError):
                bench.act(action='connect-wire', a=a, b=b)
            assert bench.state() == before, (a, b)
        for a, b in [('CNA.1', 'CNA1.2'), ('CNA.2', 'CNA1.2'), ('CNA.1', 'CNA.1'), ('CNA.01', 'CNA1.1'),
                     (None, 'CNA1.1'), ('CNA.1', None)]:
            with pytest.raises(ValueError):
                bench.act(action='disconnect-wire', a=a, b=b)
            assert bench.state() == before, ('disconnect', a, b)
        for a, b in [('CNA', 'CNA2'), ('CNA1', 'CNC'), ('CNA2', 'CNA')]:
            with pytest.raises(ValueError):
                bench.act(action='connect', a=a, b=b)
            assert bench.state() == before, ('ribbon', a, b)
        # A wire on a no-connection pin still occupies that FRC socket.
        bench.act(action='connect-wire', a='CNC.9', b='CND.9')
        with pytest.raises(ValueError):
            bench.act(action='connect', a='CND', b='CNAD')
        # Removing the ribbon from a header leaves unrelated patch wires in place.
        bench.act(action='disconnect', header='CNA')
        assert wires(bench.state()) == [['CNA.1', 'CNA1.1'], ['CNC.9', 'CND.9']]
        cleared = bench.act(action='disconnect-all')
        assert cleared['cables'] == [] and cleared['wires'] == [] and not any(cleared['leds'])
    finally:
        bench.close()


def test_same_header_loopback_and_one_wire_per_pin():
    bench = wire_bench()
    try:
        bench.act(action='connect-wire', a='CNA.1', b='CNA.2')
        expect_link(bench, 'P0.4', 'P0.5', 'same-header loopback')
        bench.act(action='connect-wire', a='CNA.3', b='CNA1.1')
        bench.act(action='connect-wire', a='CNA.4', b='CNA1.2')
        with pytest.raises(ValueError):
            bench.act(action='connect-wire', a='CNA.2', b='CNA1.3')
        state = bench.state()
        assert json.loads(json.dumps(state))['wires'] == state['wires']
        assert all(isinstance(w, list) and len(w) == 2 and all(isinstance(e, str) for e in w) for w in state['wires'])
        assert wires(state) == [['CNA.1', 'CNA.2'], ['CNA.3', 'CNA1.1'], ['CNA.4', 'CNA1.2']]
    finally:
        bench.close()


def test_graph_cache_follows_wire_jumper_and_profile_changes():
    bench = wire_bench({**BASE_JUMPERS, 'JP5': 'open'})
    try:
        bench.output('P0.4', 1)
        assert bench.act(action='connect-wire', a='CNA.1', b='CNA1.1')['leds'][0]
        assert not bench.act(action='disconnect-wire', a='CNA.1', b='CNA1.1')['leds'][0]
        assert bench.act(action='connect-wire', a='CNA1.2', b='CNA.1')['leds'] == [False, True] + [False] * 6
        bench.act(action='disconnect-wire', a='CNA.1', b='CNA1.2')
        bench.output('P0.26', 1)
        bench.act(action='connect-wire', a='CND.4', b='CNA1.8')
        for position, lit in [('open', False), ('closed', True), ('open', False)]:
            assert bench.set_jumper('JP5', position)['leds'][7] is lit
        bench.act(action='connect-wire', a='CNB.7', b='CNB1.9')
        bench.act(action='switch', pressed=True)
        bench.input('P2.12', 'up')
        for profile, level in [(7, 1), (9, 0), (7, 1)]:
            bench.act(action='sw2-profile', pin=profile)
            assert bench.sense('P2.12') == level
    finally:
        bench.close()


def test_reset_stop_and_reload_preserve_wires_on_the_new_machine():
    bench = wire_bench()
    try:
        bench.act(action='connect', a='CND', b='CNAD')
        bench.act(action='connect-wire', a='CNA.1', b='CNA1.1')
        bench.act(action='connect-wire', a='CNB.7', b='CNB1.7')
        hex_text = (Path(__file__).resolve().parents[1] / 'examples/idle.hex').read_text()
        for step in ('reset', 'stop', 'load'):
            previous = bench.m
            if step == 'load':
                bench.rt.load(hex_text, 'idle')
            else:
                bench.rt.control(step)
            assert bench.m is not previous
            state = bench.state()
            assert wires(state) == [['CNA.1', 'CNA1.1'], ['CNB.7', 'CNB1.7']], step
            assert state['cables'] == [['CND', 'CNAD']], step
            bench.output('P0.4', 1)
            assert bench.leds()[0], step
            bench.input('P2.12', 'down')
            bench.act(action='switch', pressed=True)
            assert bench.sense('P2.12') == 0, step
            bench.act(action='switch', pressed=False)
        bench.act(action='connect-wire', a='CNC.1', b='CNA1.2')
        assert len(previous.board.wires) == 2 and len(bench.m.board.wires) == 3  # copied, not aliased
    finally:
        bench.close()


# --- Display, keypad, PWM and interrupt routes through patch wires -----------

def lcd_send(bench, pins, value, rs):
    for nibble in (value >> 4, value & 15):
        for bit, line in enumerate(('D4', 'D5', 'D6', 'D7')):
            bench.output(pins[line], nibble >> bit & 1)
        bench.output(pins['RS'], rs)
        bench.output(pins['E'], 1)
        bench.output(pins['E'], 0)


def lcd_text(bench, pins, text):
    for nibble in (3, 3, 3, 2):
        for bit, line in enumerate(('D4', 'D5', 'D6', 'D7')):
            bench.output(pins[line], nibble >> bit & 1)
        bench.output(pins['RS'], 0)
        bench.output(pins['E'], 1)
        bench.output(pins['E'], 0)
    for command in (0x28, 0x0C, 0x06, 0x01, 0x80):
        lcd_send(bench, pins, command, 0)
    for character in text:
        lcd_send(bench, pins, ord(character), 1)
    return bench.state()['lcd']


TEXT = 'Wire~0x5A?z'  # every data bit toggles across these characters


@pytest.mark.parametrize('route', ['straight-CND', 'crossed-CNC'])
def test_lcd_over_individual_patch_wires(route):
    bench = wire_bench()
    try:
        if route == 'straight-CND':
            lines = dict(zip(('D4', 'D5', 'D6', 'D7', 'RS', 'E'), [f'CND.{n}' for n in range(1, 7)]))
        else:
            lines = dict(zip(('D4', 'D5', 'D6', 'D7', 'RS', 'E'), ['CNC.8', 'CNC.7', 'CNC.6', 'CNC.5', 'CNC.1', 'CNC.2']))
        for n, line in enumerate(('D4', 'D5', 'D6', 'D7', 'RS', 'E'), 1):
            bench.act(action='connect-wire', a=lines[line], b=f'CNAD.{n}')
        pins = {line: resolve(end, bench.jumpers) for line, end in lines.items()}
        assert lcd_text(bench, pins, TEXT)[0] == TEXT.ljust(16)
        if route == 'straight-CND':
            bench.set_jumper('JP16', 'open')
            assert bench.state()['lcd'] == [' ' * 16] * 2
            bench.set_jumper('JP16', 'closed')
            bench.set_jumper('JP5', 'open')  # D7 now floats at the LCD
            lcd_send(bench, pins, 0x01, 0)
            lcd_send(bench, pins, ord('Q'), 1)
            assert bench.state()['lcd'][0] == TEXT.ljust(16)  # writes without D7 are dropped
    finally:
        bench.close()


def test_keypad_rows_and_columns_through_swapped_patch_wires():
    bench = wire_bench()
    try:
        rows = ['P0.15', 'P0.16', 'P0.17', 'P0.18']
        cols = ['P0.19', 'P0.20', 'P0.21', 'P0.22']
        for n in range(1, 5):
            bench.act(action='connect-wire', a=f'CNC.{n}', b=f'CNB3.{n + 4}')  # P0.15-18 -> rows
            bench.act(action='connect-wire', a=f'CNC.{n + 4}', b=f'CNB3.{n}')  # P0.19-22 -> columns
        for key in range(16):
            bench.act(action='key', key=key, pressed=True)
            for row in range(4):  # documented forward scan: one row HIGH
                for r, net in enumerate(rows):
                    bench.output(net, r == row)
                for net in cols:
                    bench.input(net, 'down')
                seen = [bench.sense(net) for net in cols]
                assert seen == [int(row == key // 4 and c == key % 4) for c in range(4)], (key, row)
            for column in range(4):  # course calculator reverse scan: one column LOW
                for net in rows:
                    bench.input(net, 'up')
                for c, net in enumerate(cols):
                    bench.output(net, c != column)
                seen = [bench.sense(net) for net in rows]
                assert seen == [int(not (column == key % 4 and r == key // 4)) for r in range(4)], (key, column)
            for net in rows + cols:
                bench.idle(net)
            bench.act(action='key', key=key, pressed=False)
    finally:
        bench.close()


def seven_segment(bench, address_nets, segment_nets, digit, pattern):
    for bit, net in enumerate(address_nets):
        bench.output(net, digit >> bit & 1)
    for bit, net in enumerate(segment_nets):
        bench.output(net, pattern >> bit & 1)
    bench.m.ticks += 1000
    return bench.state()['segments']


@pytest.mark.parametrize('digit', range(4))
def test_calculator_seven_segment_variant_uses_wires_to_share_cnb(digit):
    """Project/code.c needs CNB on CNB2 and CNB1 at once; one ribbon cannot."""
    bench = wire_bench()
    try:
        bench.act(action='connect', a='CNA', b='CNA2')
        bench.act(action='connect', a='CNC', b='CNB3')
        bench.act(action='connect', a='CND', b='CNAD')
        for n in range(1, 5):
            bench.act(action='connect-wire', a=f'CNB.{n}', b=f'CNB2.{n}')
        bench.act(action='connect-wire', a='CNB.7', b='CNB1.7')
        addresses = ['P1.23', 'P1.24', 'P1.25', 'P1.26']
        segments = [f'P0.{n}' for n in range(4, 12)]
        for bit in range(8):
            shown = seven_segment(bench, addresses, segments, digit, 1 << bit)
            assert shown == [1 << bit if d == digit else 0 for d in range(4)], (digit, bit, shown)
            for net in addresses:
                bench.output(net, 1)
            bench.m.ticks += 400_000  # address 15 selects no fitted digit; age out history
            bench.state()
        bench.input('P2.12', 'up')
        bench.act(action='switch', pressed=True)
        assert bench.sense('P2.12') == 0
        bench.act(action='switch', pressed=False)
        assert bench.sense('P2.12') == 1
        pins = dict(zip(('D4', 'D5', 'D6', 'D7', 'RS', 'E'), ['P0.23', 'P0.24', 'P0.25', 'P0.26', 'P0.27', 'P0.28']))
        assert lcd_text(bench, pins, 'MODE')[0] == 'MODE'.ljust(16)
    finally:
        bench.close()


def configure_pwm1_4(m, mr0=100, mr4=25):
    m.write_word(PINSEL_BASE + 0x0C, (m.read_word(PINSEL_BASE + 0x0C) & ~(3 << 14)) | 2 << 14)
    pwm = 0x40018000
    for offset, value in [(0x0C, 0), (0x18, mr0), (0x40, mr4), (0x14, 2), (0x4C, 1 << 12),
                          (0x50, 1 | 1 << 4), (0x04, 2), (0x04, 9)]:
        m.write_word(pwm + offset, value)
    for _ in range(4):
        m.ticks += 10 * mr0
        m.read_word(pwm + 0x08)


@pytest.mark.parametrize('link', ['ribbon', 'wire'])
def test_ld10_pwm_through_ribbon_and_single_wire(link):
    bench = wire_bench()
    try:
        if link == 'ribbon':
            bench.act(action='connect', a='CNB', b='CNB1')
        else:
            bench.act(action='connect-wire', a='CNB.1', b='CNB1.1')
        configure_pwm1_4(bench.m)
        assert bench.state()['pwm'] == pytest.approx(0.25)
    finally:
        bench.close()


def test_ld10_from_another_gpio_pin_and_absent_cn16():
    bench = wire_bench()
    try:
        bench.act(action='connect-wire', a='CNA.1', b='CNB1.1')
        configure_pwm1_4(bench.m)  # PWM1.4 runs on unconnected P1.23
        bench.output('P0.4', 1)
        assert bench.state()['pwm'] == 1.0
        bench.output('P0.4', 0)
        assert bench.state()['pwm'] == 0.0
        with pytest.raises(ValueError):  # P1.20/PWM1.2 is CN16 pin 1, not a declared FRC header
            bench.act(action='connect-wire', a='CN16.1', b='CNB1.2')
    finally:
        bench.close()


@pytest.mark.parametrize('wire,jp4,channel', [('CNB.7', '1-2', 2), ('CNC.9', '2-3', 3)])
def test_sw2_external_interrupt_through_patch_wire(wire, jp4, channel):
    bench = wire_bench({**BASE_JUMPERS, 'JP4': jp4})
    try:
        m = bench.m
        pin = 10 + channel
        m.write_word(PINSEL_BASE + 0x10, 1 << (2 * pin))  # PINSEL4: P2.pin as EINTn
        m.write_word(EXTINT, 15)
        bench.act(action='switch', pressed=True)
        assert not m.read_word(EXTINT) & (1 << channel)
        bench.act(action='switch', pressed=False)
        bench.act(action='connect-wire', a=wire, b='CNB1.7')
        bench.act(action='switch', pressed=True)
        assert m.read_word(EXTINT) & (1 << channel)
    finally:
        bench.act(action='release-inputs')
        bench.close()


def test_exercise_check_reports_patch_wires():
    bench = wire_bench()
    try:
        bench.act(action='connect', a='CNA', b='CNA1')
        assert bench.rt.check('lab6_blink')['ok']
        bench.act(action='connect-wire', a='CNC.10', b='CNB.1')  # grounds P1.23
        result = bench.rt.check('lab6_blink')
        assert not result['ok'] and any('CNC.10' in issue for issue in result['issues']), result
    finally:
        bench.close()


# --- Unchanged original course sources ------------------------------------------

CURRICULAR_ES = Path(os.environ.get('CURRICULAR_ES', str(Path(__file__).resolve().parents[1] / 'fixtures/curricular')))
SWITCH_COUNTER = ('Lab/Lab7/SwitchCounter.c', '042470570dc546f709e2e516de1eb5968c4a91b1c2cf936d902a20e332200247')


def original(relative, digest):
    path = CURRICULAR_ES / relative
    if not path.is_file():
        pytest.fail(f'{path} is unavailable; set CURRICULAR_ES to the Unlicense corpus')
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        pytest.fail(f'{relative} differs from the reviewed SHA-256 {digest}')
    return data.decode()


@pytest.fixture(scope='module')
def switch_counter_hex():
    from simulator.compiler import Compiler
    return Compiler().compile(original(*SWITCH_COUNTER)).hex


@pytest.mark.parametrize('route', ['manual-ribbon', 'patch-wire'])
def test_original_switch_counter_needs_p1_23_patched_to_sw2(route, switch_counter_hex):
    """SwitchCounter.c reads its key on P1.23 (CNB.1); straight CNB->CNB1 puts LD10 there."""
    bench = wire_bench()
    try:
        bench.rt.load(switch_counter_hex, 'SwitchCounter.c')
        bench.act(action='connect', a='CNA', b='CNA1')
        if route == 'manual-ribbon':
            bench.act(action='connect', a='CNB', b='CNB1')
        else:
            bench.act(action='connect-wire', a='CNB.1', b='CNB1.7')
        for _ in range(20):
            bench.m.run(5000)
        assert not any(bench.leds())
        bench.act(action='switch', pressed=True)
        for _ in range(3):
            bench.m.run(5000)
        bench.act(action='switch', pressed=False)
        for _ in range(3):
            bench.m.run(5000)
        assert bench.m.error is None
        assert any(bench.leds()) is (route == 'patch-wire')
    finally:
        bench.close()
