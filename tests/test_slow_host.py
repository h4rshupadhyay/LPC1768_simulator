"""Live execution on a slow or starved host (e.g. a free cloud instance with a fraction of a CPU).

Unicorn's own timeout stops emulation from another thread. When it lands inside a
peripheral callback, the interrupted load or store is executed again on resume:
UART bytes appear twice and I2C transfers are corrupted. The live deadline must
therefore be an instruction budget, never a Unicorn timeout.
"""
import json
import time
from pathlib import Path

from simulator.compiler import Compiler
from simulator.engine import Machine
from simulator.terminal import Terminal

ROOT = Path(__file__).resolve().parents[1]
SPEC = next(e for e in json.loads((ROOT / 'examples/bench/catalog.json').read_text(encoding='utf-8'))
            if e['id'] == 'bmp280')


class Recorder:
    """Wraps Unicorn to record the arguments of every emu_start call."""

    def __init__(self, uc):
        self.uc, self.calls = uc, []

    def emu_start(self, *args, **kwargs):
        self.calls.append(kwargs)
        return self.uc.emu_start(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.uc, name)


def bmp280_machine():
    hexfile = Compiler().compile((ROOT / 'examples/bench' / SPEC['file']).read_text(encoding='utf-8')).hex
    machine = Machine(hexfile, realtime=True, target='als')
    machine.board.circuit.load(SPEC['project'])
    terminal = Terminal('pc', 9600, 0)
    machine.terminals = {0: terminal}
    return machine, terminal


def test_live_deadline_never_uses_the_unicorn_timeout():
    machine, _ = bmp280_machine()
    recorder = Recorder(machine.uc)
    machine.uc = recorder
    machine.resume_clock()
    for timeout in (None, 1000, 100_000):
        machine.run(20000, timeout_us=timeout, fast=True)
        machine.run(20000, timeout_us=timeout)
    assert recorder.calls and all(not call.get('timeout') for call in recorder.calls)


def test_live_deadline_shrinks_the_budget_on_a_slow_host():
    machine, _ = bmp280_machine()
    recorder = Recorder(machine.uc)
    machine.uc = recorder
    machine._ns_per_instruction = 5000.0  # 5 µs per instruction: a heavily starved host
    machine.resume_clock()
    machine.run(20000, timeout_us=1000, fast=True)
    assert recorder.calls[0]['count'] == 200


def test_starved_host_keeps_i2c_and_uart_traffic_intact():
    machine, terminal = bmp280_machine()
    machine.resume_clock()
    for _ in range(40):
        machine.run(20000, timeout_us=1000, fast=True)
        time.sleep(.01)  # the worker thread loses the CPU between slices
    lines = [line for line in ''.join(terminal.text).split('\r\n') if line]
    assert lines and lines[0] == 'chip id 0x58'
    assert len(lines) >= 2
    assert set(lines[1:]) == {'T = 24.50 C   P = 100799 Pa'}
