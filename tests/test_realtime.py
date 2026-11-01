"""Elapsed-time peripheral behavior, independent of UI polling or CPU throughput."""
import struct
import time
from pathlib import Path

import pytest

from simulator.compiler import Compiler
from simulator.engine import Machine
from simulator.displays import SevenSegment
from simulator.runtime import Runtime


TIMER0 = 0x40004000
MAILBOX = 0x10007000


class Clock:
    def __init__(self):
        self.ns = 0

    def __call__(self):
        return self.ns

    def advance(self, ns):
        self.ns += ns


@pytest.fixture(scope='module')
def firmware():
    cache = {}

    def compile_source(body):
        if body not in cache:
            cache[body] = Compiler().compile('#include <LPC17xx.h>\n' + body).hex
        return cache[body]

    return compile_source


def start(firmware, body):
    clock = Clock()
    machine = Machine(firmware(body), realtime=True, clock_ns=clock)
    machine.resume_clock()
    machine.run(10000)
    return machine, clock


@pytest.mark.parametrize('selection,expected', [(0, 2), (1, 8), (2, 4), (3, 1)])
def test_configured_pclk_and_prescaler_follow_elapsed_time(firmware, selection, expected):
    m, clock = start(firmware, f'''int main(void) {{
      LPC_SC->PCLKSEL0={selection}u<<2;LPC_TIM0->TCR=2;
      LPC_TIM0->PR=24999;LPC_TIM0->TCR=1;while(1) {{}}}}''')
    assert m.core_clock_hz() == 100_000_000
    clock.advance(2_000_000)
    assert m.read_word(TIMER0 + 8) == expected
    # Executing more instructions at the same timestamp must not move the timer.
    m.run(30000)
    assert m.read_word(TIMER0 + 8) == expected


@pytest.mark.parametrize('timer,base,power,pclksel,shift', [
    (0, 0x40004000, 1, 0, 2), (1, 0x40008000, 2, 0, 4),
    (2, 0x40090000, 22, 1, 12), (3, 0x40094000, 23, 1, 14),
])
def test_each_timer_uses_its_own_clock_selector(firmware, timer, base, power, pclksel, shift):
    m, clock = start(firmware, f'''int main(void) {{LPC_SC->PCONP|=1u<<{power};
      LPC_SC->PCLKSEL{pclksel}=1u<<{shift};LPC_TIM{timer}->PR=99999;
      LPC_TIM{timer}->TCR=1;while(1) {{}}}}''')
    clock.advance(5_000_000)
    assert m.read_word(base + 8) == 5


def test_fractional_clock_prescaler_pause_and_resume(firmware):
    m, clock = start(firmware, '''int main(void) {
      LPC_TIM0->PR=24999;LPC_TIM0->TCR=1;while(1) {}}''')
    for _ in range(10):
        clock.advance(100_000)
        m.read_word(TIMER0 + 8)
    assert m.read_word(TIMER0 + 8) == 1
    clock.advance(500_000)
    assert m.read_word(TIMER0 + 0x10) == 12500
    m.pause_clock()
    clock.advance(20_000_000_000)
    assert m.read_word(TIMER0 + 8) == 1
    m.resume_clock()
    clock.advance(500_000)
    assert m.read_word(TIMER0 + 8) == 2


def test_frequency_and_power_changes_account_time_at_old_rate(firmware):
    m, clock = start(firmware, '''int main(void) {
      LPC_TIM0->PR=24999;LPC_TIM0->TCR=1;while(1) {}}''')
    clock.advance(1_000_000)
    m.write_word(Machine.SC + 0x1A8, 1 << 2)  # CCLK/4 -> CCLK
    clock.advance(1_000_000)
    assert m.read_word(TIMER0 + 8) == 5
    m.write_word(Machine.SC + 0xC4, m.regs[Machine.SC + 0xC4] & ~2)
    clock.advance(1_000_000_000)
    assert m.read_word(TIMER0 + 8) == 5
    m.write_word(Machine.SC + 0xC4, m.regs[Machine.SC + 0xC4] | 2)
    clock.advance(1_000_000)
    assert m.read_word(TIMER0 + 8) == 9


def test_match_flag_requires_mr0i_and_is_cleared_by_writing_one(firmware):
    for mcr in [2, 3]:
        m, clock = start(firmware, f'''int main(void) {{LPC_TIM0->PR=24999;
          LPC_TIM0->MR0=1;LPC_TIM0->MCR={mcr};LPC_TIM0->TCR=1;while(1) {{}}}}''')
        clock.advance(1_000_000)
        assert m.read_word(TIMER0) == (mcr & 1)
        assert m.read_word(TIMER0 + 8) == 0
        m.write_word(TIMER0, 1)
        assert m.read_word(TIMER0) == 0


def test_large_host_gap_batches_matches_without_losing_reset_or_other_flags(firmware):
    m, clock = start(firmware, '''int main(void) {
      LPC_TIM0->MR0=10;LPC_TIM0->MR1=8;LPC_TIM0->MCR=3|(1u<<3);
      LPC_TIM0->TCR=1;while(1) {}}''')
    clock.advance(3_600_000_000_000)
    assert m.read_word(TIMER0 + 8) == 0
    assert m.read_word(TIMER0) == 3


def test_unreachable_stop_match_does_not_disable_reset_period_batching(firmware):
    m, clock = start(firmware, '''int main(void) {
      LPC_TIM0->MR0=1;LPC_TIM0->MR1=2;
      LPC_TIM0->MCR=2|(4u<<3);LPC_TIM0->TCR=1;while(1) {}}''')
    clock.advance(3_600_000_000_000)
    assert m.read_word(TIMER0 + 8) == 0
    assert m.read_word(TIMER0 + 4) & 1


def test_realtime_match_interrupt_executes_actual_handler(firmware):
    m, clock = start(firmware, '''void TIMER0_IRQHandler(void) {
      LPC_TIM0->IR=1;(*(volatile unsigned*)0x10007000)++;}
      int main(void) {LPC_TIM0->PR=24999;LPC_TIM0->MR0=10;
      LPC_TIM0->MCR=3;LPC_TIM0->TCR=1;NVIC_EnableIRQ(TIMER0_IRQn);while(1) {}}''')
    for expected in range(1, 4):
        clock.advance(10_000_000)
        for _ in range(4):
            m.run(1000)
        assert struct.unpack('<I', bytes(m.uc.mem_read(MAILBOX, 4)))[0] == expected
    assert m.active_irq is None


def test_pwm_counter_uses_elapsed_time_and_its_pclk_divider(firmware):
    m, clock = start(firmware, '''int main(void) {LPC_SC->PCONP|=1u<<6;
      LPC_SC->PCLKSEL0=2u<<12;LPC_PINCON->PINSEL3=2u<<14;
      LPC_PWM1->PR=49999;LPC_PWM1->MR0=1000;LPC_PWM1->MR4=250;
      LPC_PWM1->LER=0x11;LPC_PWM1->MCR=2;LPC_PWM1->PCR=1u<<12;
      LPC_PWM1->TCR=9;while(1) {}}''')
    clock.advance(250_000_000)
    assert m.read_word(Machine.PWM + 8) == 251  # PWM cycle starts at1 (UM10360 Table447)
    assert m.pwm_duty() == pytest.approx(0.25)


def test_stop_on_match_freezes_prescaler_at_match_not_end_of_host_interval(firmware):
    m, clock = start(firmware, '''int main(void) {LPC_TIM0->PR=24999;
      LPC_TIM0->MR0=2;LPC_TIM0->MCR=5;LPC_TIM0->TCR=1;while(1) {}}''')
    clock.advance(2_500_000)
    assert m.read_word(TIMER0 + 8) == 2
    assert m.read_word(TIMER0 + 0x10) == 0
    clock.advance(1_000_000_000)
    assert m.read_word(TIMER0 + 8) == 2
    assert not m.read_word(TIMER0 + 4) & 1


def test_sub_clock_intervals_accumulate_without_rounding_drift(firmware):
    m, clock = start(firmware, '''int main(void) {
      LPC_TIM0->PR=999;LPC_TIM0->TCR=1;while(1) {}}''')
    for _ in range(100):
        clock.advance(10)
        m.read_word(TIMER0 + 8)
    assert m.read_word(TIMER0 + 0x10) == 25


def test_lowering_prescaler_below_current_pc_waits_for_equality_after_wrap(firmware):
    m, clock = start(firmware, '''int main(void) {
      LPC_TIM0->PR=24999;LPC_TIM0->TCR=1;while(1) {}}''')
    clock.advance(500_000)
    assert m.read_word(TIMER0 + 0x10) == 12500
    m.write_word(TIMER0 + 0xC, 2499)
    clock.advance(1_000)
    assert m.read_word(TIMER0 + 8) == 0
    assert m.read_word(TIMER0 + 0x10) == 12525


def test_multiplex_blanking_uses_firmware_dwell_and_expires_by_active_time():
    display = SevenSegment(window=50_000_000)
    now, ticks = 0, 0
    patterns = [6, 91, 79, 102]
    for _ in range(10):
        for digit, pattern in enumerate(patterns):
            display.observe(now, digit, pattern, dwell_tick=ticks)
            now += 100_000
            ticks += 300
            display.observe(now, digit, 0, dwell_tick=ticks)
            # Host overhead may make a few blanking instructions take longer
            # than a software delay; it must not dominate the decoded pattern.
            now += 600_000
            ticks += 5
            display.observe(now, -1, 0, dwell_tick=ticks)
    assert display.patterns(now, dwell_tick=ticks) == patterns
    assert display.patterns(now + 60_000_000, dwell_tick=ticks) == [0] * 4


@pytest.mark.parametrize('source,frequency', [(0, 4_000_000), (1, 12_000_000), (2, 32_768)])
def test_bypassed_pll_uses_selected_oscillator_and_cpu_divider(firmware, source, frequency):
    m, clock = start(firmware, f'''int main(void) {{LPC_SC->PLL0CON=0;
      LPC_SC->CLKSRCSEL={source};LPC_SC->CCLKCFG=1;while(1) {{}}}}''')
    assert m.core_clock_hz() == frequency // 2


def test_live_runtime_freezes_and_reanchors_its_machine_clock(firmware):
    rt = Runtime(start_worker=False, realtime=True)
    try:
        rt.load(firmware('int main(void) {while(1) {}}'))
        rt.control('run')
        assert rt.machine.realtime
        rt.control('pause')
        before = rt.snapshot()['elapsedSeconds']
        rt.control('resume')
        rt.control('pause')
        assert rt.snapshot()['elapsedSeconds'] >= before
        rt.control('reset')
        assert rt.snapshot()['elapsedSeconds'] == 0
    finally:
        rt.close()


@pytest.mark.parametrize('retained_hook', [False, True])
def test_frequent_live_systick_does_not_starve_foreground_loop(retained_hook):
    import io
    from intelhex import IntelHex
    from unicorn.arm_const import UC_ARM_REG_R0
    image = bytearray(0x130)
    struct.pack_into('<II', image, 0, 0x10008000, 0x101)
    struct.pack_into('<I', image, 15 * 4, 0x121)
    image[0x100:0x106] = bytes.fromhex('00200130fde7')  # R0++ loop
    image[0x120:0x130] = bytes.fromhex('02490a6801320a607047000000700010')
    ih = IntelHex()
    ih.frombytes(image)
    stream = io.StringIO()
    ih.write_hex_file(stream)
    clock = Clock()
    machine = Machine(stream.getvalue(), realtime=True, clock_ns=clock)
    machine.resume_clock()
    machine.run(100, fast=True, timeout_us=0)
    if retained_hook:
        machine.run(1, timeout_us=0)
    emu_start = machine.uc.emu_start
    def host_gap_after_return(*args, **kwargs):
        was_in_handler = machine.active_irq is not None
        emu_start(*args, **kwargs)
        if was_in_handler and machine.active_irq is None:
            clock.advance(2_000_000)
    machine.uc.emu_start = host_gap_after_return
    machine.write_word(0xe000e014, 3999)  # 1 ms at reset 4 MHz
    machine.write_word(0xe000e010, 7)
    for expected in range(1, 5):
        before = machine.uc.reg_read(UC_ARM_REG_R0)
        clock.advance(2_000_000)  # another IRQ is pending on every host slice
        machine.run(20000, fast=True, timeout_us=0)
        assert machine.uc.reg_read(UC_ARM_REG_R0) > before
        assert int.from_bytes(machine.uc.mem_read(MAILBOX, 4), 'little') == expected
        assert machine.active_irq is None
        assert (machine._block_hook is not None) == retained_hook


@pytest.fixture(scope='module')
def counter_hex():
    return Compiler().compile((Path(__file__).parent / 'fixtures/realtime_counter.c').read_text()).hex


def counter_machine(image):
    clock = Clock()
    machine = Machine(image, realtime=True, clock_ns=clock)
    for a, b in [('CNA', 'CNA2'), ('CNB', 'CNB2'), ('CND', 'CNB1')]:
        machine.board.connect(a, b)
    machine.resume_clock()
    machine.run(5000, timeout_us=0)
    return machine, clock


def test_compiled_millisecond_counter_rate_with_controlled_service_clock(counter_hex):
    machine, clock = counter_machine(counter_hex)
    transitions = {}
    expected = [(63, 63, 63, pattern) for pattern in (6, 91, 79)]
    for step in range(12400):
        clock.advance(250_000)
        machine.run(200, timeout_us=0)
        if step % 16 == 15:
            pattern = tuple(machine.snapshot()['segments'])
            if pattern in expected and pattern not in transitions:
                transitions[pattern] = clock.ns / 1_000_000_000
    assert machine.error is None
    for second, pattern in enumerate(expected, 1):
        # Includes the display's persistence window and four-ms observation cadence.
        assert second <= transitions.get(pattern, float('inf')) <= second + .15


def test_compiled_polled_match_flag_coalesces_when_service_is_late(counter_hex):
    machine, clock = counter_machine(counter_hex)
    for _ in range(550):
        clock.advance(2_000_000)
        machine.run(400, timeout_us=0)
    # 1,100 matches have elapsed but a single pending bit cannot queue two
    # wait1ms returns per service slice. Firmware has not counted to 1,000.
    assert machine.snapshot()['segments'] == [63, 63, 63, 63]
    assert machine.error is None


@pytest.mark.performance
def test_millisecond_multiplexed_counter_advances_near_wall_clock_seconds():
    source = (Path(__file__).parent / 'fixtures/realtime_counter.c').read_text()
    rt = Runtime()
    try:
        rt.compile(source)
        for a, b in [('CNA', 'CNA2'), ('CNB', 'CNB2'), ('CND', 'CNB1')]:
            rt.physical(dict(action='connect', a=a, b=b))
        started = time.perf_counter()
        rt.control('run')
        transitions = []
        for expected in [[63, 63, 63, 6], [63, 63, 63, 91], [63, 63, 63, 79]]:
            deadline = started + len(transitions) + 1.8
            while time.perf_counter() < deadline:
                state = rt.snapshot()
                observed_at = time.perf_counter()
                assert state['error'] is None
                if state['segments'] == expected and observed_at <= deadline:
                    transitions.append(observed_at - started)
                    break
                time.sleep(.01)
            else:
                raise AssertionError(f'Counter missed its wall-clock deadline: {rt.snapshot()}')
        assert .8 < transitions[0] < 1.8
        assert all(.8 < b-a < 1.4 for a, b in zip(transitions, transitions[1:]))
        rt.control('pause')
        frozen = rt.snapshot()
        time.sleep(.1)
        assert rt.snapshot()['elapsedSeconds'] == frozen['elapsedSeconds']
        assert rt.snapshot()['segments'] == frozen['segments']
    finally:
        rt.close()
