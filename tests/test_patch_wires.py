"""Single-conductor patch wires between declared FRC header pins.

Header pin orders come from board/mapping.json (ALS board pp24-26,31-37;
ESD Appendix C). Expected values below are derived from those pin tables and
from the firmware's own register writes, not from simulator snapshots.
"""
from pathlib import Path
import os
import random

import pytest

from simulator.board import Board
from simulator.compiler import Compiler
from simulator.engine import Machine
from simulator.runtime import Runtime
from tools.test_electrical_sweep import Pins, ReversePins, oracle, reverse_oracle

IDLE = (Path(__file__).resolve().parents[1] / 'examples/idle.hex').read_text()
GPIO0, GPIO1, GPIO2 = 0x2009C000, 0x2009C020, 0x2009C040
FIODIR, FIOMASK, FIOPIN, FIOSET = 0x00, 0x10, 0x14, 0x18

# P0.4-P0.11 drive the low byte of `v`; P0.15 (CNC.1) and P2.12 (CNB.7) are
# active-LOW inputs that add bits 6 and 7 respectively.
MIRROR = r'''#include <LPC17xx.h>
int main(void) {
  LPC_PINCON->PINSEL0 &= ~0x00FFFF00u;
  LPC_PINCON->PINSEL4 &= ~(3u << 24);
  LPC_GPIO0->FIODIR = 0xFF0u;
  LPC_GPIO2->FIODIR &= ~(1u << 12);
  while (1) {
    unsigned v = 0x03u;
    if (!(LPC_GPIO0->FIOPIN & (1u << 15))) v |= 0x40u;
    if (!(LPC_GPIO2->FIOPIN & (1u << 12))) v |= 0x80u;
    LPC_GPIO0->FIOPIN = v << 4;
  }
}
'''

# Forward scan: P2.10-P2.13 drive one row HIGH; P1.23-P1.26 read columns.
FORWARD = r'''#include <LPC17xx.h>
int main(void) {
  LPC_PINCON->PINSEL0 &= ~0x00FFFF00u;
  LPC_PINCON->PINSEL3 &= ~0x003FC000u;
  LPC_PINCON->PINSEL4 &= ~0x0FF00000u;
  LPC_GPIO0->FIODIR = 0xFF0u;
  LPC_GPIO2->FIODIR |= 0x3C00u;
  LPC_GPIO1->FIODIR &= ~0x07800000u;
  while (1) {
    unsigned shown = 0, row, col, bits;
    for (row = 0; row < 4 && !shown; row++) {
      LPC_GPIO2->FIOCLR = 0x3C00u;
      LPC_GPIO2->FIOSET = 1u << (10 + row);
      bits = (LPC_GPIO1->FIOPIN >> 23) & 15u;
      for (col = 0; col < 4; col++)
        if (bits & (1u << col)) { shown = 0x10u | (row * 4 + col); break; }
    }
    LPC_GPIO0->FIOPIN = shown << 4;
  }
}
'''

# Reverse scan used by the course calculator: P0.15-P0.18 column outputs,
# one LOW at a time; P0.19-P0.22 row inputs with reset pull-ups.
REVERSE = r'''#include <LPC17xx.h>
int main(void) {
  LPC_PINCON->PINSEL0 &= ~0xC0FFFF00u;
  LPC_PINCON->PINSEL1 &= ~0x00003FFFu;
  LPC_GPIO0->FIODIR = 0xFF0u | (15u << 15);
  while (1) {
    unsigned shown = 0, row, col, rows;
    for (col = 0; col < 4 && !shown; col++) {
      LPC_GPIO0->FIOSET = 15u << 15;
      LPC_GPIO0->FIOCLR = 1u << (15 + col);
      rows = (~LPC_GPIO0->FIOPIN >> 19) & 15u;
      for (row = 0; row < 4; row++)
        if (rows & (1u << row)) { shown = 0x10u | (row * 4 + col); break; }
    }
    LPC_GPIO0->FIOCLR = 0xFF0u;
    LPC_GPIO0->FIOSET = shown << 4;
  }
}
'''


@pytest.fixture(scope='module')
def hexes():
    compiler = Compiler()
    return {name: compiler.compile(source).hex
            for name, source in [('mirror', MIRROR), ('forward', FORWARD), ('reverse', REVERSE)]}


def leds(m, instructions=20000):
    m.run(instructions)
    return m.snapshot()['leds']


def shown_key(m):
    # LD6 (bit 4) is the firmware's "key valid" flag; LD2-LD5 carry the index.
    # The reverse scan briefly clears its LEDs, so take the settled value.
    for _ in range(4):
        bits = sum(on << i for i, on in enumerate(leds(m, 4000)))
        if bits:
            break
    return bits & 15 if bits & 0x10 else None


def wire_all(board, a, b, pins=range(1, 9)):
    for pin in pins:
        board.connect_wire(f'{a}.{pin}', f'{b}.{pin}')


# Actual firmware routes -----------------------------------------------------

def test_led_wires_follow_individual_pins_not_ribbon_order(hexes):
    m = Machine(hexes['mirror'])
    # v=0x03: P0.4 and P0.5 HIGH, P0.6 LOW.
    m.board.connect_wire('CNA.1', 'CNA1.8')
    m.board.connect_wire('CNA1.2', 'CNA.2')
    m.board.connect_wire('CNA.3', 'CNA1.1')
    assert leds(m) == [False, True, False, False, False, False, False, True]
    assert m.snapshot()['wires'] == [['CNA.1', 'CNA1.8'], ['CNA1.2', 'CNA.2'], ['CNA.3', 'CNA1.1']]
    assert m.snapshot()['cables'] == []


def test_sw2_patch_to_alternate_gpio_and_detach(hexes):
    m = Machine(hexes['mirror'])
    m.board.connect_wire('CNC.1', 'CNB1.7')  # SW2 -> P0.15 (bit 6)
    m.board.connect_wire('CNA.7', 'CNA1.1')  # P0.10 shows bit 6 on LD2
    assert leds(m)[0] is False
    m.board.sw2 = True
    m.observe()
    assert leds(m)[0] is True
    m.board.disconnect_wire('CNB1.7', 'CNC.1')  # either order
    # Detached P0.15 returns to its reset pull-up while SW2 is still held.
    assert leds(m)[0] is False
    m.board.sw2 = False


def test_sw2_default_lab_route_by_patch(hexes):
    m = Machine(hexes['mirror'])
    m.board.connect_wire('CNB.7', 'CNB1.7')  # P2.12 <- SW2, bit 7
    m.board.connect_wire('CNA.8', 'CNA1.1')  # P0.11 -> LD2
    assert leds(m)[0] is False
    m.board.sw2 = True
    assert leds(m)[0] is True


@pytest.mark.parametrize('firmware,header,jp4', [('forward', 'CNB', '1-2'), ('reverse', 'CNC', 'open')])
def test_patched_keypad_matches_every_key(hexes, firmware, header, jp4):
    m = Machine(hexes[firmware])
    m.board.set_jumper('JP4', jp4)
    m.board.connect('CNA', 'CNA1')  # ribbons and patch wires on different headers mix
    wire_all(m.board, header, 'CNB3')
    assert shown_key(m) is None
    for key in range(16):
        m.board.keys = {key}
        assert shown_key(m) == key, (firmware, key)
        m.board.keys = set()
        assert shown_key(m) is None


def test_keypad_miswire_reports_the_physically_connected_column(hexes):
    m = Machine(hexes['forward'])
    m.board.set_jumper('JP4', '1-2')
    m.board.connect('CNA', 'CNA1')
    m.board.connect_wire('CNB.1', 'CNB3.2')
    m.board.connect_wire('CNB.2', 'CNB3.1')
    wire_all(m.board, 'CNB', 'CNB3', range(3, 9))
    m.board.keys = {0}  # row 1, column 1 reaches P1.24
    assert shown_key(m) == 1
    m.board.keys = {5}
    assert shown_key(m) == 4


def test_forward_keypad_needs_jp4_for_cnb8_row(hexes):
    m = Machine(hexes['forward'])
    m.board.connect('CNA', 'CNA1')
    wire_all(m.board, 'CNB', 'CNB3')
    m.board.keys = {12}  # row 4 is driven by P2.13 only through JP4 1-2
    assert shown_key(m) is None
    m.board.set_jumper('JP4', '1-2')
    assert shown_key(m) == 12


def test_patched_pwm_route_and_wrong_pin():
    m = Machine(IDLE)
    m.write_word(m.SC + 0xC4, m.regs[m.SC + 0xC4] | 64)
    m.write_word(m.PIN + 12, 2 << 14)  # P1.23 = PWM1.4
    for off, value in [(4, 2), (12, 0), (24, 1000), (64, 250), (20, 2), (76, 1 << 12), (80, 17), (4, 9)]:
        m.write_word(m.PWM + off, value)
    m.board.connect_wire('CNB.1', 'CNB1.1')
    assert m.snapshot()['pwm'] == pytest.approx(.25)
    m.board.disconnect_wire('CNB.1', 'CNB1.1')
    m.board.connect_wire('CNB.2', 'CNB1.1')  # P1.24 carries no PWM1.4 output
    assert m.snapshot()['pwm'] == 0


# Electrical rules -----------------------------------------------------------

def output_high(m, port_base, bit):
    m.write_word(port_base + FIODIR, m.read_word(port_base + FIODIR) | bit)
    m.write_word(port_base + FIOSET, bit)


def test_ground_short_resolves_low_with_visible_contention():
    m = Machine(IDLE)
    bit = 1 << 4
    output_high(m, GPIO0, bit)
    m.board.connect_wire('CNA.1', 'CNB.10')
    assert not m.read_word(GPIO0 + FIOPIN) & bit
    assert m.read_word(GPIO0 + FIOSET) & bit  # latch retained
    warnings = m.snapshot()['warnings']
    assert any('Conflicting driven levels' in w and 'P0.4' in w and 'GND' in w and 'resolving LOW' in w
               for w in warnings), warnings
    m.board.disconnect_wire('CNA.1', 'CNB.10')
    assert m.read_word(GPIO0 + FIOPIN) & bit
    assert m.snapshot()['warnings'] == []


def test_grounded_input_reads_low_without_contention():
    m = Machine(IDLE)
    m.board.connect_wire('CNC.10', 'CNC.1')
    assert not m.read_word(GPIO0 + FIOPIN) & (1 << 15)
    assert m.snapshot()['warnings'] == []


def test_two_driven_mcu_pins_contend_low():
    m = Machine(IDLE)
    output_high(m, GPIO0, 1 << 4)
    m.write_word(GPIO0 + FIODIR, m.read_word(GPIO0 + FIODIR) | 1 << 15)  # P0.15 driven LOW
    m.board.connect_wire('CNA.1', 'CNC.1')
    assert not m.read_word(GPIO0 + FIOPIN) & (1 << 4)
    assert any('Conflicting' in w for w in m.snapshot()['warnings'])


def test_nc_endpoints_have_no_electrical_effect():
    m = Machine(IDLE)
    before = sorted(map(sorted, m.board.groups()))
    m.board.connect_wire('CNA.9', 'CNA1.1')    # NC to LED0
    m.board.connect_wire('CNA1.9', 'CNA.1')    # NC to P0.4
    m.board.connect_wire('CNB2.5', 'CNAD.7')   # NC to NC
    assert sorted(map(sorted, m.board.groups())) == before
    output_high(m, GPIO0, 1 << 4)
    assert m.snapshot()['leds'] == [False] * 8
    assert len(m.snapshot()['wires']) == 3


def test_pull_modes_mask_and_mux_through_patch():
    m = Machine(IDLE)
    bit = 1 << 15
    m.board.connect_wire('CNC.1', 'CNA.9')  # P0.15 to NC: pad keeps its own pull
    assert m.read_word(GPIO0 + FIOPIN) & bit
    m.write_word(m.PIN + 0x40, 3 << 30)  # PINMODE0 P0.15 pull-down
    assert not m.read_word(GPIO0 + FIOPIN) & bit
    m.write_word(m.PIN + 0x40, 0)
    m.board.disconnect_wire('CNA.9', 'CNC.1')
    # Weak pull-up cannot overcome the documented 15k column pulldown.
    m.board.connect_wire('CNC.1', 'CNB3.1')
    assert not m.read_word(GPIO0 + FIOPIN) & bit
    m.board.disconnect_wire('CNC.1', 'CNB3.1')
    m.board.connect_wire('CNC.1', 'CNB1.7')  # released SW2 drives HIGH
    m.write_word(m.PIN + 0x40, 3 << 30)
    assert m.read_word(GPIO0 + FIOPIN) & bit
    m.write_word(GPIO0 + FIOMASK, bit)
    assert not m.read_word(GPIO0 + FIOPIN) & bit
    m.write_word(GPIO0 + FIOMASK, 0)
    m.board.sw2 = True
    assert not m.read_word(GPIO0 + FIOPIN) & bit
    m.board.sw2 = False
    # A weak pull on an input never lights an output load.
    m.write_word(m.PIN + 0x40, 0)
    m.board.connect_wire('CNC.2', 'CNA1.1')
    assert m.snapshot()['leds'][0] is False
    # Driven GPIO lights it; selecting a different pin function releases it.
    output_high(m, GPIO0, 1 << 16)
    assert m.snapshot()['leds'][0] is True
    m.write_word(m.PIN + 4, 1)  # PINSEL1 P0.16 function 01
    assert m.snapshot()['leds'][0] is False
    m.write_word(m.PIN + 4, 0)
    m.write_word(m.PIN + 0x68, 1 << 16)  # open-drain HIGH releases the pad
    assert m.snapshot()['leds'][0] is False


@pytest.mark.parametrize('endpoint,jumper,closed,other', [
    ('CNB.8', 'JP4', '1-2', '2-3'),
    ('CNC.9', 'JP4', '2-3', '1-2'),
    ('CND.4', 'JP5', 'closed', 'open'),
])
def test_jumper_mediated_endpoints(endpoint, jumper, closed, other):
    m = Machine(IDLE)
    port_base, bit = (GPIO2, 1 << 13) if jumper == 'JP4' else (GPIO0, 1 << 26)
    output_high(m, port_base, bit)
    m.board.connect_wire(endpoint, 'CNA1.1')
    for position in ('open', other, closed):
        m.board.set_jumper(jumper, position)
        assert m.snapshot()['leds'][0] is (position == closed), (endpoint, position)


def test_sw2_profile_applies_to_patch_endpoint():
    m = Machine(IDLE)
    m.board.connect_wire('CNB.7', 'CNB1.9')
    m.board.sw2 = True
    assert m.read_word(GPIO2 + FIOPIN) & (1 << 12)  # profile pin 7: CNB1.9 is NC
    m.board.sw2_pin = 9
    assert not m.read_word(GPIO2 + FIOPIN) & (1 << 12)


def test_graph_cache_keys_on_wires():
    board = Board(Pins())
    assert not any('LED0' in g for g in board.groups())
    board.wires.append(['CNA.1', 'CNA1.1'])  # even a direct mutation invalidates
    assert any({'P0.4', 'LED0'} <= set(g) for g in board.groups())
    board.wires.clear()
    assert not any('LED0' in g for g in board.groups())


# Keypad diode campaigns with patch wires instead of the CNB ribbon ----------

def keypad_cases():
    if os.environ.get('LPC_WIRING_COMPLETE') == '1':
        return range(65536)
    return sorted(random.Random(1768).sample(range(65536), 512))


def patched(pins, jp4='1-2'):
    # All ten conductors, including NC pin 9 and GND pin 10, like the ribbon.
    board = Board(pins)
    wire_all(board, 'CNB', 'CNB3', range(1, 11))
    board.set_jumper('JP4', jp4)
    return board


def test_forward_diode_campaign_through_patch_wires():
    pins = Pins()
    board = patched(pins)
    failures = []
    for keys in keypad_cases():
        board.keys = {i for i in range(16) if keys & (1 << i)}
        for rows in (1, 2, 4, 8):
            pins.rows = rows
            levels = board.signals()
            actual = sum(levels.get(f'COL{i}', 0) << i for i in range(4))
            if actual != oracle(keys, rows):
                failures.append((keys, rows, actual))
    assert not failures[:10]


def test_reverse_diode_campaign_through_patch_wires():
    pins = ReversePins()
    board = patched(pins)
    failures = []
    for keys in keypad_cases():
        board.keys = {i for i in range(16) if keys & (1 << i)}
        for col in range(4):
            pins.selected = col
            levels = board.signals()
            actual = sum(levels.get(f'ROW{i}', 0) << i for i in range(4))
            if actual != reverse_oracle(keys, col):
                failures.append((keys, col, actual))
    assert not failures[:10]


def test_patch_harness_resolves_like_the_ribbon():
    ribbon_pins, patch_pins = Pins(), Pins()
    ribbon = Board(ribbon_pins)
    ribbon.connect('CNB', 'CNB3')
    ribbon.set_jumper('JP4', '1-2')
    patch = patched(patch_pins)
    for keys in keypad_cases():
        ribbon.keys = patch.keys = {i for i in range(16) if keys & (1 << i)}
        for rows in range(16):
            ribbon_pins.rows = patch_pins.rows = rows
            assert ribbon.signals() == patch.signals(), (keys, rows)
            assert ribbon.warnings == patch.warnings


# Validation and atomic state ------------------------------------------------

@pytest.mark.parametrize('a,b', [
    ('CNA.1', 'CNA.1'),             # self
    ('CNA1.1', 'CNA.1'),            # reverse duplicate
    ('CNA.1', 'CNA1.2'),            # pin already patched
    ('CNA2.1', 'CNA1.1'),           # other end already patched
    ('CNA.0', 'CNA1.3'), ('CNA.11', 'CNA1.3'), ('CNA.01', 'CNA1.3'),
    ('cna.2', 'CNA1.3'), (' CNA.2', 'CNA1.3'), ('CNA.2 ', 'CNA1.3'), ('CNA.2.1', 'CNA1.3'),
    ('CNA', 'CNA1.3'), ('CN16.1', 'CNB1.1'), ('P1.20', 'CNB1.1'), ('CNA.2', None), (2, 'CNA1.3'),
    ('CNC.1', 'CNA1.3'),            # CNC carries a ribbon
    ('CNA.2', 'CNB3.8'),            # CNB3 carries a ribbon
])
def test_invalid_wire_leaves_state_untouched(a, b):
    rt = Runtime(start_worker=False)
    rt.physical({'action': 'connect-wire', 'a': 'CNA.1', 'b': 'CNA1.1'})
    rt.physical({'action': 'connect', 'a': 'CNC', 'b': 'CNB3'})
    before = rt.snapshot()
    with pytest.raises(ValueError):
        rt.physical({'action': 'connect-wire', 'a': a, 'b': b})
    after = rt.snapshot()
    for field in ('wires', 'cables', 'jumpers', 'leds', 'warnings', 'keys', 'sw2'):
        assert after[field] == before[field], field
    rt.close()


def test_ribbon_rejected_on_patched_header_and_disconnect_errors():
    rt = Runtime(start_worker=False)
    rt.physical({'action': 'connect-wire', 'a': 'CNA.3', 'b': 'CNA1.1'})
    for a, b in [('CNA', 'CNA2'), ('CNB', 'CNA1')]:
        with pytest.raises(ValueError, match='patch wires'):
            rt.physical({'action': 'connect', 'a': a, 'b': b})
    for a, b in [('CNA.3', 'CNA1.2'), ('CNA.3', 'CNX.1'), ('CNA.3', 'CNA.3')]:
        with pytest.raises(ValueError):
            rt.physical({'action': 'disconnect-wire', 'a': a, 'b': b})
    state = rt.snapshot()
    assert state['wires'] == [['CNA.3', 'CNA1.1']] and state['cables'] == []
    # Removing the last wire frees the header for a ribbon again.
    rt.physical({'action': 'disconnect-wire', 'a': 'CNA1.1', 'b': 'CNA.3'})
    assert rt.physical({'action': 'connect', 'a': 'CNA', 'b': 'CNA1'})['cables'] == [['CNA', 'CNA1']]
    rt.close()


def test_every_declared_endpoint_is_accepted():
    board = Board(Pins())
    names = [f'{h}.{p}' for h in Board.__init__.__globals__['MAPPING']['headers'] for p in range(1, 11)]
    assert len(names) == 100
    for a, b in zip(names[0::2], names[1::2]):
        board.connect_wire(a, b)
    assert len(board.wires) == 50
    board.disconnect_all()
    assert board.wires == [] and board.cables == []


# Runtime persistence ---------------------------------------------------------

def test_load_reset_and_stop_preserve_wires_and_disconnect_all(hexes):
    rt = Runtime(start_worker=False)
    rt.physical({'action': 'jumper', 'name': 'JP4', 'value': '1-2'})
    rt.physical({'action': 'connect-wire', 'a': 'CNA.1', 'b': 'CNA1.1'})
    rt.physical({'action': 'connect', 'a': 'CNC', 'b': 'CNB3'})
    rt.load(hexes['mirror'], 'mirror.hex')
    wires = [['CNA.1', 'CNA1.1']]
    for action in ('reset', 'stop'):
        state = rt.control(action)
        assert state['wires'] == wires and state['cables'] == [['CNC', 'CNB3']], action
    # A fixed instruction budget; worker slices are capped by host time.
    rt.machine.run(20000)
    assert rt.snapshot()['leds'][0] is True  # P0.4 HIGH routed after reset
    rt.control('reset')
    assert rt.snapshot()['leds'][0] is False  # reset releases P0.4
    rt.machine.run(20000)
    assert rt.snapshot()['leds'][0] is True and rt.snapshot()['wires'] == wires
    rt.load(IDLE, 'idle.hex')
    assert rt.snapshot()['wires'] == wires
    state = rt.physical({'action': 'disconnect-all'})
    assert state['wires'] == [] and state['cables'] == []
    assert state['jumpers']['JP4'] == '1-2'  # jumpers are settings, not connections
    assert state['leds'] == [False] * 8
    rt.close()


# Snapshot contract shared by Flask and the Pyodide worker ---------------------

def pin(state, end):
    header, number = end.split('.')
    return state['headerPins'][header][int(number) - 1]


def test_header_pins_report_resolved_nodes_levels_and_conflicts():
    rt = Runtime(start_worker=False)
    m = rt.machine
    state = rt.snapshot()
    assert set(state['headerPins']) == {'CNA', 'CNB', 'CNC', 'CND', 'CNA1', 'CNA2',
                                        'CNB2', 'CNB3', 'CNB1', 'CNAD'}
    assert all(len(contacts) == 10 for contacts in state['headerPins'].values())
    assert pin(state, 'CNA.1') == {'node': 'P0.4', 'level': 1, 'conflict': False}  # reset pull-up
    assert pin(state, 'CNA.9') == {'node': None, 'level': None, 'conflict': False}
    assert pin(state, 'CNA.10') == {'node': 'GND', 'level': 0, 'conflict': False}
    assert pin(state, 'CNB.8')['node'] is None  # JP4 open: no P2.13 route
    assert pin(state, 'CNA1.1') == {'node': 'LED0', 'level': None, 'conflict': False}
    m.write_word(m.PIN + 0x40, 2 << 8)  # PINMODE0 P0.4: neither pull
    assert pin(rt.snapshot(), 'CNA.1')['level'] is None
    state = rt.physical({'action': 'jumper', 'name': 'JP4', 'value': '2-3'})
    assert pin(state, 'CNC.9')['node'] == 'P2.13' and pin(state, 'CNB.8')['node'] is None
    state = rt.physical({'action': 'sw2-profile', 'pin': 9})
    assert pin(state, 'CNB1.9')['node'] == 'SW2' and pin(state, 'CNB1.7')['node'] is None
    # P0.6 driven HIGH and grounded by a wire: the signal side is flagged, and
    # the shared GND net is not marked on every header.
    m.write_word(GPIO0 + FIODIR, 1 << 6)
    m.write_word(GPIO0 + FIOSET, 1 << 6)
    state = rt.physical({'action': 'connect-wire', 'a': 'CNA.3', 'b': 'CNB2.10'})
    assert pin(state, 'CNA.3') == {'node': 'P0.6', 'level': 0, 'conflict': True}
    assert pin(state, 'CNB2.10')['conflict'] is False and pin(state, 'CNA1.10')['conflict'] is False
    state = rt.physical({'action': 'disconnect-wire', 'a': 'CNB2.10', 'b': 'CNA.3'})
    assert pin(state, 'CNA.3') == {'node': 'P0.6', 'level': 1, 'conflict': False}
    rt.close()


def test_rejections_name_the_blocking_hardware():
    rt = Runtime(start_worker=False)
    rt.physical({'action': 'connect', 'a': 'CNC', 'b': 'CNB3'})
    rt.physical({'action': 'connect-wire', 'a': 'CNA.1', 'b': 'CNA1.1'})
    rt.physical({'action': 'connect-wire', 'a': 'CNA.4', 'b': 'CNA2.3'})
    cases = [
        ({'action': 'connect', 'a': 'CNA', 'b': 'CNB2'}, 'CNA has patch wires on pins 1, 4. Remove them'),
        ({'action': 'connect-wire', 'a': 'CNB3.2', 'b': 'CNA.2'}, 'CNB3 carries the ribbon cable CNC ↔ CNB3'),
        ({'action': 'connect-wire', 'a': 'CNA2.4', 'b': 'CNA1.1'}, 'CNA1.1 already has a patch wire (CNA.1 ↔ CNA1.1)'),
        ({'action': 'connect-wire', 'a': 'CNA1.1', 'b': 'CNA.1'}, 'CNA1.1 and CNA.1 are already patched together'),
        ({'action': 'connect-wire', 'a': 'CNA.2', 'b': 'CNA.2'}, 'both ends are CNA.2'),
        ({'action': 'connect-wire', 'a': 'CN16.1', 'b': 'CNA.2'}, "Unknown patch-wire end 'CN16.1'"),
        ({'action': 'disconnect-wire', 'a': 'CNA.2', 'b': 'CNA1.2'}, 'No patch wire joins CNA.2 and CNA1.2'),
        ({'action': 'disconnect-all', 'kind': 'jumpers'}, "kind must be 'all', 'wires' or 'cables'"),
    ]
    before = rt.snapshot()
    for request, message in cases:
        with pytest.raises(ValueError) as error:
            rt.physical(request)
        assert message in str(error.value), (request, str(error.value))
        assert rt.snapshot()['wires'] == before['wires'] and rt.snapshot()['cables'] == before['cables']
    # A huge bogus endpoint is not echoed back in full.
    with pytest.raises(ValueError) as error:
        rt.physical({'action': 'connect-wire', 'a': 'X' * 100_000, 'b': 'CNA.2'})
    assert len(str(error.value)) < 200
    rt.close()


def test_disconnect_all_kinds_remove_only_what_they_name():
    rt = Runtime(start_worker=False)
    def setup():
        rt.physical({'action': 'connect', 'a': 'CNC', 'b': 'CNB3'})
        rt.physical({'action': 'connect-wire', 'a': 'CNA.1', 'b': 'CNA1.1'})
    setup()
    state = rt.physical({'action': 'disconnect-all', 'kind': 'wires'})
    assert state['wires'] == [] and state['cables'] == [['CNC', 'CNB3']]
    rt.physical({'action': 'connect-wire', 'a': 'CNA.1', 'b': 'CNA1.1'})
    state = rt.physical({'action': 'disconnect-all', 'kind': 'cables'})
    assert state['wires'] == [['CNA.1', 'CNA1.1']] and state['cables'] == []
    rt.physical({'action': 'connect', 'a': 'CNC', 'b': 'CNB3'})
    state = rt.physical({'action': 'disconnect-all'})
    assert state['wires'] == [] and state['cables'] == []
    # Clearing an empty board is a harmless no-op.
    assert rt.physical({'action': 'disconnect-all'})['wires'] == []
    rt.close()


def test_wire_count_is_bounded_without_partial_mutation(monkeypatch):
    import simulator.board as board_module
    monkeypatch.setattr(board_module, 'MAX_WIRES', 2)
    board = Board(Pins())
    board.connect_wire('CNA.1', 'CNA1.1')
    board.connect_wire('CNA.2', 'CNA1.2')
    with pytest.raises(ValueError, match='At most 2 patch wires'):
        board.connect_wire('CNA.3', 'CNA1.3')
    assert board.wires == [['CNA.1', 'CNA1.1'], ['CNA.2', 'CNA1.2']]
    assert board_module.MAX_WIRES == 2 and Board.__init__.__globals__['MAX_WIRES'] == 2


def test_http_contract_matches_runtime_and_rejects_without_mutation():
    from simulator.server import create_app
    rt = Runtime(start_worker=False)
    client = create_app(rt).test_client()
    ok = client.post('/api/physical', json={'action': 'connect-wire', 'a': 'CNB.7', 'b': 'CNB1.7'})
    assert ok.status_code == 200
    body = ok.get_json()
    assert body['wires'] == [['CNB.7', 'CNB1.7']] and pin(body, 'CNB1.7')['node'] == 'SW2'
    for payload in ({'action': 'connect-wire', 'a': 'CNB.7', 'b': 'CNA1.1'},
                    {'action': 'connect-wire', 'a': 'CNB.70', 'b': 'CNA1.1'},
                    {'action': 'connect-wire'},
                    {'action': 'connect', 'a': 'CNB', 'b': 'CNB1'},
                    {'action': 'disconnect-wire', 'a': 'CNB.7', 'b': 'CNB1.9'}):
        response = client.post('/api/physical', json=payload)
        assert response.status_code == 400 and response.get_json()['error'], payload
    assert client.post('/api/physical', json=['connect-wire']).status_code == 400
    state = client.get('/api/state').get_json()
    assert state['wires'] == [['CNB.7', 'CNB1.7']] and state['cables'] == []
    gone = client.post('/api/physical', json={'action': 'disconnect-wire', 'a': 'CNB1.7', 'b': 'CNB.7'})
    assert gone.status_code == 200 and gone.get_json()['wires'] == []
    rt.close()


HEADER_NAMES = list(Board.__init__.__globals__['MAPPING']['headers'])


@pytest.mark.parametrize('jp4,jp5,sw2', [(j4, j5, s) for j4 in ('open', '1-2', '2-3')
                                         for j5 in ('open', 'closed') for s in (7, 9)])
def test_ten_wires_equal_one_ribbon_for_every_header_pair(jp4, jp5, sw2):
    # Every unordered header pair, MCU-peripheral and same-kind alike, with
    # wires written in both directions: the electrical graph must be identical.
    for i, a in enumerate(HEADER_NAMES):
        for b in HEADER_NAMES[i + 1:]:
            boards = []
            for kind in ('ribbon', 'forward', 'reverse'):
                board = Board(Pins())
                board.set_jumper('JP4', jp4)
                board.set_jumper('JP5', jp5)
                board.sw2_pin = sw2
                if kind == 'ribbon':
                    board.connect(a, b)
                else:
                    for n in range(1, 11):
                        ends = (f'{a}.{n}', f'{b}.{n}')
                        board.connect_wire(*(ends if kind == 'forward' else ends[::-1]))
                boards.append(sorted(sorted(g) for g in board.groups()))
            assert boards[0] == boards[1] == boards[2], (a, b, jp4, jp5, sw2)
