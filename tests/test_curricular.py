"""Original course sources; opt in with CURRICULAR_ES, no source rewriting."""
import os
from pathlib import Path

import pytest
from simulator.compiler import Compiler
from simulator.engine import Machine

ROOT = Path(os.environ.get('CURRICULAR_ES', Path(__file__).resolve().parents[1] / 'fixtures/curricular'))


def board(source):
    raw = (ROOT / source).read_bytes()
    m = Machine(Compiler(optimization=2).compile(raw.decode('utf-8')).hex)
    m.board.connect('CND', 'CNAD')
    m.board.connect('CNC', 'CNB3')
    for name, value in [('JP4', '1-2'), ('JP5', 'closed'), ('JP16', 'closed')]:
        m.board.set_jumper(name, value)
    return m


def until(m, predicate, slices=200):
    for _ in range(slices):
        m.run(20000)
        assert m.error is None
        if predicate(m.snapshot()):
            return
    pytest.fail(f'Firmware did not reach expected state within instruction budget: {m.snapshot()}')


def test_original_lcd_upper_line():
    m = board('Lab/Lab9/LCD_UPPERLINE.c')
    until(m, lambda s: s['lcd'][0].startswith('We have fun.'))
    assert m.snapshot()['lcd'][1] == ' ' * 16


def test_original_keypad_reverse_scan_and_transposed_key_identity():
    m = board('Lab/Lab9/keyp.c')
    until(m, lambda s: s['lcd'][0].startswith('Key: '))
    # Board key 6 is row 1, column 2. The unchanged source returns
    # col*4+row, so it displays 9. A symmetric key would hide this distinction.
    m.board.keys.add(6)
    until(m, lambda s: s['lcd'][0].startswith('Key: 9'))
    m.board.keys.discard(6)


def test_original_dice_newlib_memset_links_at_every_optimization():
    path = ROOT / 'Lab/Lab9/dice.c'
    if not path.is_file():
        pytest.skip('Additional original corpus source not installed')
    for optimization in range(4):
        result = Compiler(optimization=optimization).compile(path.read_text())
        m = Machine(result.hex)
        m.run(10000)
        assert m.error is None


def test_prebuilt_keil_datatransfer_registers():
    from simulator.compiler import elf_to_hex
    from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5
    path = ROOT / 'Lab/Lab1/Init/init.axf'
    if not path.is_file():
        pytest.skip('Prebuilt Keil image is not bundled; set CURRICULAR_ES')
    image = path.read_bytes()
    m = Machine(elf_to_hex(image))
    m.run(1000)
    assert [m.uc.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5)] == [10, 16, 10, 19, 0xfffffff8]


def test_original_adc_interrupt_source_expression():
    from io import BytesIO
    from elftools.elf.elffile import ELFFile
    raw = (ROOT / 'Lab/Lab10/ADC.c').read_bytes()
    compiled = Compiler(optimization=2).compile(raw.decode('utf-8'))
    symbols = {s.name: s['st_value'] for s in ELFFile(BytesIO(compiled.elf)).get_section_by_name('.symtab').iter_symbols()}
    m = Machine(compiled.hex)
    m.board.set_jumper('JP18', '2-3')
    m.board.pots[4] = 1234 * 3.3 / 4095
    for _ in range(100):
        m.run(10000)
    assert m.snapshot()['interrupts'] > 0
    # Source parses as raw & ((0xfff << 4) >> 4), not (raw >> 4) & 0xfff.
    assert [int.from_bytes(m.uc.mem_read(symbols[name], 4), 'little') for name in ('result', 'y')] == [3360, 3360]
