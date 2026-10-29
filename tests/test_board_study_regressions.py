"""Circuit and reset oracles from the ALS schematic and NXP UM10360."""
from pathlib import Path

import pytest

from simulator.engine import Machine

HEX = Path('examples/idle.hex').read_text()


def keypad():
    m = Machine(HEX)
    m.board.connect('CNC', 'CNB3')
    m.write_word(0x2009C000, 15 << 15)  # Four column outputs, row inputs.
    m.write_word(0x2009C018, 15 << 15)
    return m


@pytest.mark.parametrize('key', range(16))
@pytest.mark.parametrize('column', range(4))
def test_reverse_scan_single_keys_and_release(key, column):
    m = keypad()
    m.write_word(0x2009C01C, 1 << (15 + column))
    assert (m.gpio_value(0) >> 19) & 15 == 15
    m.board.keys.add(key)
    row, key_column = divmod(key, 4)
    expected = 15 ^ (1 << row) if column == key_column else 15
    assert (m.gpio_value(0) >> 19) & 15 == expected
    m.board.keys.clear()
    assert (m.gpio_value(0) >> 19) & 15 == 15


def test_reverse_scan_conflicting_columns_and_ghost_path():
    m = keypad()
    m.write_word(0x2009C01C, 1 << 15)
    m.board.keys = {0, 1, 5}  # Three corners connect both row buses.
    assert (m.gpio_value(0) >> 19) & 15 == 12
    assert any('Conflicting driven levels' in warning for warning in m.board.warnings)
    # Software output latches retain their intended values under contention.
    assert m.read_word(0x2009C018) & (1 << 16)
    assert not m.gpio_value(0) & (1 << 16)


def test_reverse_scan_requires_row_bias_for_unpressed_high():
    m = keypad()
    # PINMODE1: P0.19-22 no pull, rather than the reset pull-up.
    m.write_word(m.PIN + 0x44, sum(2 << (2 * (pin - 16)) for pin in range(19, 23)))
    assert (m.gpio_value(0) >> 19) & 15 == 0  # Floating digital model convention.
    m.board.keys.add(0)
    m.write_word(0x2009C01C, 1 << 15)
    assert not m.gpio_value(0) & (1 << 19)


def test_reset_power_and_default_exception_alignment():
    import struct
    from unicorn.arm_const import UC_ARM_REG_SP
    m = Machine(HEX)
    assert m.read_word(m.SC + 0xC4) & (1 << 6)
    assert m.read_word(0xE000ED14) == 0x200
    m.uc.mem_write(17 * 4, struct.pack('<I', 0x201))
    m.uc.mem_write(0x200, bytes.fromhex('7047'))
    m.uc.reg_write(UC_ARM_REG_SP, 0x10007FFC)
    m.enabled_irq = m.pending_irq = 2
    m._deliver_irq()
    assert m.uc.reg_read(UC_ARM_REG_SP) == 0x10007FD8
    assert int.from_bytes(m.uc.mem_read(0x10007FD8 + 28, 4), 'little') & (1 << 9)
    m.run(1)
    assert m.uc.reg_read(UC_ARM_REG_SP) == 0x10007FFC
