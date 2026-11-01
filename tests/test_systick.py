from pathlib import Path

from unicorn.arm_const import UC_ARM_REG_PRIMASK

from simulator.compiler import Compiler
from simulator.engine import Machine

BASE = 0xE000E010


def machine(**kwargs):
    return Machine(Path('examples/idle.hex').read_text(), **kwargs)


def test_counter_boundaries_and_registers():
    m = machine()
    assert m.read_word(BASE) == 4
    assert m.read_word(BASE + 12) == 0xF423F
    m.write_word(BASE + 4, 0xFF000003)
    assert m.read_word(BASE + 4) == 3
    m.write_word(BASE, 7)
    m.ticks += 1
    assert m.read_word(BASE + 8) == 3
    m.ticks += 2
    assert m.read_word(BASE + 8) == 1
    m.ticks += 1
    assert m.read_word(BASE + 8) == 0
    assert m.pending_system == 1 << 15
    assert m.read_word(BASE) & (1 << 16)
    assert not m.read_word(BASE) & (1 << 16)
    m.ticks += 4
    m.write_word(BASE + 8, 99)
    assert m.read_word(BASE + 8) == 0
    assert not m.read_word(BASE) & (1 << 16)
    assert m.pending_system == 1 << 15
    m.write_word(0xE000ED04, 1 << 25)
    assert not m.pending_system
    m.write_word(0xE000ED04, 1 << 26)
    assert m.read_word(0xE000ED04) & 1 << 26


def test_external_stclk_is_independent_of_core_clock_and_zero_reload():
    m = machine()
    m.write_word(BASE + 4, 1)
    m.write_word(BASE, 1)
    m.ticks += 1000
    assert m.read_word(BASE + 8) == 0
    assert not m.read_word(BASE) & (1 << 16)
    m.systick.external_edges(1)
    assert m.read_word(BASE + 8) == 1
    m.systick.external_edges(1)
    assert m.read_word(BASE) & (1 << 16)
    m.write_word(BASE + 4, 0)
    m.write_word(BASE + 8, 0)
    m.systick.external_edges(100)
    assert not m.read_word(BASE) & (1 << 16)
    m.write_word(BASE + 4, 2)
    m.write_word(BASE, 5)
    m.systick.external_edges(100)
    assert m.read_word(BASE + 8) == 0
    m.ticks += 1
    assert m.read_word(BASE + 8) == 2


def test_realtime_pause_and_clock_change():
    now = [0]
    m = machine(realtime=True, clock_ns=lambda: now[0])
    m.write_word(BASE + 4, 99)
    m.write_word(BASE, 5)
    m.resume_clock()
    now[0] += 10_000
    assert m.read_word(BASE + 8) == 60  # 40 clocks at 4 MHz
    m.write_word(m.SC + 0x10C, 1)  # 12 MHz
    now[0] += 5_000
    assert m.read_word(BASE + 8) == 0
    assert m.read_word(BASE) & (1 << 16)
    m.pause_clock()
    now[0] += 100_000
    assert m.read_word(BASE + 8) == 0
    m.resume_clock()
    now[0] += 1_000
    assert m.read_word(BASE + 8) == 88


def test_compiled_handler_and_primask():
    source = '''#include <LPC17xx.h>
volatile unsigned count;
void SysTick_Handler(void) { count++; LPC_GPIO0->FIOSET = 1 << 22; }
int main(void) { LPC_GPIO0->FIODIR = 1 << 22; SysTick_Config(40); while (1) {} }
'''
    m = Machine(Compiler().compile(source).hex)
    m.uc.reg_write(UC_ARM_REG_PRIMASK, 1)
    for _ in range(20):
        m.run(1000)
    assert m.pending_system & (1 << 15)
    assert m.irq_count == 0
    m.uc.reg_write(UC_ARM_REG_PRIMASK, 0)
    for _ in range(100):
        m.run(1000)
        if m.gpio[0].latch & (1 << 22):
            break
    assert m.irq_count > 0
    assert m.gpio[0].latch & (1 << 22)


def test_pending_arbitration_and_exception_return():
    m = Machine(Compiler().compile('''#include <LPC17xx.h>
void SysTick_Handler(void) { }
void TIMER0_IRQHandler(void) { }
int main(void) { while (1) {} }
''').hex)
    m.enabled_irq = 1 << 1
    m.pending_irq = 1 << 1
    m.pending_system = 1 << 15
    m.uc.reg_write(UC_ARM_REG_PRIMASK, 1)
    m._deliver_irq()
    assert m.active_irq is None
    m.uc.reg_write(UC_ARM_REG_PRIMASK, 0)
    m._deliver_irq()
    assert m.active_irq == -1
    assert m.pending_irq == 1 << 1
    assert m.read_word(0xE000E300) == 0
    m.run(100)
    assert m.active_irq is None
    m._deliver_irq()
    assert m.active_irq == 1
