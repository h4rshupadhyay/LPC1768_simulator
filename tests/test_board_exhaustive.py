"""Independent board connectivity checks and bounded keypad graph campaign."""
from itertools import product

import pytest

from simulator.board import Board
from tools.test_electrical_sweep import Pins, campaign, oracle


# Connector pin order from ALS board pp24-26 and ESD schematic pp31,42.
HEADERS = {
    'CNA': [f'P0.{n}' for n in range(4, 12)],
    'CNB': [f'P1.{n}' for n in range(23, 27)] + [f'P2.{n}' for n in range(10, 14)],
    'CNC': [f'P0.{n}' for n in range(15, 23)],
    'CND': [f'P0.{n}' for n in range(23, 29)] + ['P2.0', 'P2.1'],
}


def test_matrix_graph_controls():
    assert oracle(0, 15) == 0
    assert oracle((1 << 0) | (1 << 4) | (1 << 5), 1) == 3
    assert oracle((1 << 0) | (1 << 4), 1) == 1
    assert oracle(0xffff, 0) == 0


def test_fast_keypad_campaign():
    result = campaign()
    assert result['vectors'] == 4096
    assert not result['failures'], result


@pytest.mark.parametrize('header', HEADERS)
@pytest.mark.parametrize('jp4,jp5,jp16,jp18', product(
    ('open', '1-2', '2-3'), ('open', 'closed'), ('open', 'closed'), ('open', '1-2', '2-3')))
def test_declared_ribbon_routes(header, jp4, jp5, jp16, jp18):
    board = Board(Pins())
    for jumper, value in zip(('JP4', 'JP5', 'JP16', 'JP18'), (jp4, jp5, jp16, jp18)):
        board.set_jumper(jumper, value)
    board.connect(header, 'CNA1')
    groups = board.groups()
    for i, pin in enumerate(HEADERS[header]):
        connected = any(pin in group and f'LED{i}' in group for group in groups)
        expected = not (header == 'CNB' and i == 7 and jp4 != '1-2')
        expected &= not (header == 'CND' and i == 3 and jp5 != 'closed')
        assert connected == expected, (header, i, jp4, jp5, jp16, jp18)


def test_wrong_cable_and_decoder_pulls():
    board = Board(Pins())
    board.connect('CNA1', 'CNB2')
    levels = board.signals()
    assert all(levels[f'DIG{i}'] == 1 for i in range(4))
    assert any('two peripheral' in warning for warning in board.warnings)


@pytest.mark.parametrize('header', HEADERS)
@pytest.mark.parametrize('peripheral,nodes', [
    ('CNA1', [f'LED{i}' for i in range(8)]),
    ('CNA2', [f'SEG{i}' for i in range(8)]),
    ('CNB2', [f'DIG{i}' for i in range(4)] + [None] * 4),
    ('CNB3', [f'COL{i}' for i in range(4)] + [f'ROW{i}' for i in range(4)]),
    ('CNB1', ['PWM_LED', None, None, None, None, None, 'SW2', None]),
    ('CNAD', [f'LCD{i}' for i in range(4)] + ['LCD_RS', 'LCD_EN', None, None]),
])
@pytest.mark.parametrize('jp4,jp5', product(('open', '1-2', '2-3'), ('open', 'closed')))
def test_all_header_peripheral_routes(header, peripheral, nodes, jp4, jp5):
    board = Board(Pins())
    board.set_jumper('JP4', jp4)
    board.set_jumper('JP5', jp5)
    board.connect(header, peripheral)
    for i, (pin, node) in enumerate(zip(HEADERS[header], nodes)):
        connected = node is not None and any(pin in group and node in group for group in board.groups())
        expected = node is not None
        expected &= not (header == 'CNB' and i == 7 and jp4 != '1-2')
        expected &= not (header == 'CND' and i == 3 and jp5 != 'closed')
        assert connected == expected, (header, peripheral, i, jp4, jp5)


@pytest.mark.parametrize('position,expected', [('open', False), ('1-2', False), ('2-3', True)])
def test_cnc_ninth_pin_route(position, expected):
    board = Board(Pins())
    board.set_jumper('JP4', position)
    assert (board._pin('CNC', 8) == 'P2.13') is expected


def test_open_drain_and_mux_release_pad():
    from pathlib import Path
    from simulator.engine import Machine
    m = Machine((Path(__file__).resolve().parents[1] / 'examples/idle.hex').read_text())
    m.board.connect('CNA', 'CNB3')
    bit = 1 << 4
    m.write_word(0x2009C000, bit)
    m.write_word(0x2009C018, bit)
    assert m.board.signals()['COL0'] == 1
    m.write_word(m.PIN + 0x68, bit)
    assert m.board.signals()['COL0'] == 0
    assert m.read_word(0x2009C018) & bit
    assert not m.read_word(0x2009C014) & bit
    m.write_word(m.PIN + 0x68, 0)
    m.write_word(m.PIN, 1 << 8)
    assert m.board.signals()['COL0'] == 0
