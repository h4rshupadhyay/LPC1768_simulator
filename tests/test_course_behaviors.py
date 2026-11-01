"""Behavior of unchanged Unlicense course sources, bounded by CPU instructions."""
import os
from io import BytesIO
from pathlib import Path

import pytest
from elftools.elf.elffile import ELFFile
from simulator.compiler import Compiler
from simulator.engine import Machine

ROOT = Path(os.environ.get('CURRICULAR_ES', Path(__file__).resolve().parents[1] / 'fixtures/curricular'))


def firmware(path):
    compiled = Compiler(optimization=2).compile((ROOT / path).read_text())
    table = ELFFile(BytesIO(compiled.elf)).get_section_by_name('.symtab')
    symbols = {s.name: s['st_value'] for s in table.iter_symbols()}
    m = Machine(compiled.hex)
    for a, b in [('CNC', 'CNB3'), ('CND', 'CNAD'), ('CNB', 'CNB1')]:
        m.board.connect(a, b)
    for name, value in [('JP4', '1-2'), ('JP5', 'closed'), ('JP16', 'closed'), ('JP18', '2-3')]:
        m.board.set_jumper(name, value)
    return m, symbols


def word(m, symbols, name):
    return int.from_bytes(m.uc.mem_read(symbols[name], 4), 'little')


def run_until(m, predicate, slices):
    for _ in range(slices):
        m.run(20000, timeout_us=0)
        assert m.error is None
        if predicate():
            return
    pytest.fail(f'Not reached in at most {slices * 20000} instructions: {m.snapshot()}')


def test_original_pwm_reset_power_irq_ramp_and_pin_waveform():
    m, symbols = firmware('Lab/Lab11/PWM.c')
    assert m.read_word(0x400FC0C4) & (1 << 6)
    run_until(m, lambda: word(m, symbols, 'duty_cycle') >= 250, 40)
    assert word(m, symbols, 'direction') == 1
    assert word(m, symbols, 'duty_cycle') % 50 == 0
    levels = set()
    for _ in range(300):
        m.run(100, timeout_us=0)
        levels.add(m.pin_output(1, 23))
    assert levels == {0, 1}
    run_until(m, lambda: word(m, symbols, 'direction') == 0, 200)
    assert word(m, symbols, 'duty_cycle') == 3000
    run_until(m, lambda: word(m, symbols, 'duty_cycle') < 3000, 30)


@pytest.mark.parametrize(('volts', 'value'), [(0, 0), (1.65, 2048), (3.3, 4095)])
def test_original_adc_interrupt_decimal_lcd(volts, value):
    m, symbols = firmware('Lab/Lab10/ADC_Display.c')
    m.board.pots[4] = volts
    expected = f'ADC Val: {value}'.ljust(16)
    run_until(m, lambda: m.snapshot()['lcd'][0] == expected and word(m, symbols, 'y') == value and m.active_irq is None, 80)
    assert m.irq_count > 0
    assert word(m, symbols, 'result') == value
    assert m.snapshot()['lcd'][1] == ' ' * 16
