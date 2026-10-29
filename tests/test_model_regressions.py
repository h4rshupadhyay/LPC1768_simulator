"""Independent register-level regressions found during the portability audit."""
from pathlib import Path

import pytest

from simulator.engine import Machine

HEX = (Path(__file__).resolve().parents[1] / 'examples/idle.hex').read_text()


@pytest.mark.parametrize('base,register,shift,power', [
    (0x40004000, 0x1A8, 2, 1), (0x40008000, 0x1A8, 4, 2),
    (0x40090000, 0x1AC, 12, 22), (0x40094000, 0x1AC, 14, 23),
    (0x40018000, 0x1A8, 12, 6),
])
@pytest.mark.parametrize('selector,divider', [(0, 4), (1, 1), (2, 2), (3, 8)])
def test_offline_timer_pclk_and_prescale_counter(base, register, shift, power, selector, divider):
    m = Machine(HEX)
    m.write_word(m.SC + 0xC4, m.read_word(m.SC + 0xC4) | (1 << power))
    m.write_word(m.SC + register, selector << shift)
    m.write_word(base + 0xC, 2)
    m.write_word(base + 4, 1)
    m.ticks += 11 * divider
    assert m.read_word(base + 8) == 3
    assert m.read_word(base + 0x10) == 2
    m.ticks += divider
    assert m.read_word(base + 8) == 4
    assert m.read_word(base + 0x10) == 0


def test_offline_clock_change_accounts_progress_at_old_divider():
    m = Machine(HEX)
    base = 0x40004000
    m.write_word(base + 4, 1)
    m.ticks += 40
    m.write_word(m.SC + 0x1A8, 1 << 2)
    m.ticks += 10
    assert m.read_word(base + 8) == 20


@pytest.mark.parametrize('channel', [4, 5])
def test_adc_pclk_change_preserves_half_completed_conversion(channel):
    m = Machine(HEX)
    m.write_word(m.SC + 0xC4, m.read_word(m.SC + 0xC4) | (1 << 12))
    m.write_word(m.PIN + 0xC, 0xF0000000)
    m.board.set_jumper('JP18', '2-3')
    m.write_word(m.ADC, (1 << channel) | (1 << 21) | (1 << 24))
    m.ticks += 128  # 32 of the required 65 ADC clocks at core/4.
    m.write_word(m.SC + 0x1A8, 1 << 24)  # PCLK becomes core/1.
    m.ticks += 32
    assert not m.read_word(m.ADC + 4) & (1 << 31)
    m.ticks += 1
    assert m.read_word(m.ADC + 4) & (1 << 31)


def test_pwm_gpio_read_advances_to_current_electrical_phase():
    now = [0]
    m = Machine(HEX, realtime=True, clock_ns=lambda: now[0])
    m.write_word(m.SC + 0xC4, m.read_word(m.SC + 0xC4) | (1 << 6))
    m.write_word(m.PIN + 0xC, 2 << 14)
    for offset, value in [(4, 2), (0x18, 1000), (0x40, 250),
                          (0x14, 2), (0x4C, 1 << 12), (0x50, 17), (4, 9)]:
        m.write_word(m.PWM + offset, value)
    m.resume_clock()
    assert m.read_word(0x2009C034) & (1 << 23)
    now[0] = 400_000  # 400 PWM clocks at the reset PCLK of 1 MHz.
    assert not m.read_word(0x2009C034) & (1 << 23)
    now[0] = 1_100_000
    assert m.read_word(0x2009C034) & (1 << 23)


def test_contended_gpio_read_matches_resolved_pad_and_retains_latch():
    m = Machine(HEX)
    m.board.connect('CNA', 'CNC')
    m.write_word(0x2009C000, (1 << 4) | (1 << 15))
    m.write_word(0x2009C018, 1 << 4)
    assert m.board.signals()['P0.4'] == 0
    assert not m.read_word(0x2009C014) & (1 << 4)
    assert m.read_word(0x2009C018) & (1 << 4)
    assert any('Conflicting driven levels' in warning for warning in m.board.warnings)


def test_offline_stop_match_freezes_prescaler_at_match_then_resumes():
    m = Machine(HEX)
    timer = 0x40004000
    for offset, value in [(0xC, 9), (0x18, 2), (0x14, 5), (4, 1)]:
        m.write_word(timer + offset, value)
    m.ticks += 100  # 25 PCLKs, with stop occurring at PCLK 20.
    assert m.read_word(timer + 8) == 2
    assert m.read_word(timer + 0x10) == 0
    assert m.read_word(timer + 4) == 0
    m.write_word(timer + 4, 1)
    m.ticks += 36
    assert m.read_word(timer + 8) == 2
    assert m.read_word(timer + 0x10) == 9
    m.ticks += 4
    assert m.read_word(timer + 8) == 3


@pytest.mark.parametrize('align,padding', [(False, 0), (True, 4)])
def test_exception_stack_alignment_and_return(align, padding):
    import struct
    from unicorn.arm_const import UC_ARM_REG_SP, UC_ARM_REG_XPSR
    m = Machine(HEX)
    m.uc.mem_write(17 * 4, struct.pack('<I', 0x201))
    m.uc.mem_write(0x200, bytes.fromhex('7047'))  # BX LR / exception return.
    m.uc.reg_write(UC_ARM_REG_SP, 0x10007FFC)
    m.write_word(0xE000ED14, (1 << 9) if align else 0)
    m.enabled_irq = m.pending_irq = 2
    m._deliver_irq()
    sp = m.uc.reg_read(UC_ARM_REG_SP)
    assert sp == 0x10007FFC - 32 - padding
    stacked_xpsr = struct.unpack('<I', m.uc.mem_read(sp + 28, 4))[0]
    assert bool(stacked_xpsr & (1 << 9)) == align
    m.run(1)
    assert m.uc.reg_read(UC_ARM_REG_SP) == 0x10007FFC
    assert not m.uc.reg_read(UC_ARM_REG_XPSR) & (1 << 9)
