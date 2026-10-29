"""Compile the shipped C and observe the wired display, not program variables."""
from pathlib import Path

from simulator.compiler import Compiler
from simulator.engine import Machine

ROOT = Path(__file__).resolve().parents[1]


class Clock:
    ns = 0

    def __call__(self):
        return self.ns


def start(name):
    clock = Clock()
    source = (ROOT / 'templates' / name).read_text()
    machine = Machine(Compiler().compile(source).hex, realtime=True, clock_ns=clock)
    machine.board.connect('CNA', 'CNA2')
    machine.board.connect('CNB', 'CNB2')
    machine.resume_clock()
    return machine, clock


def advance(machine, clock, milliseconds):
    clock.ns += milliseconds * 1_000_000
    machine.run(3000)


def test_walking_segment_sequence():
    machine, clock = start('segment_walk.c')
    machine.run(3000)
    advance(machine, clock, 1)
    assert machine.snapshot()['segments'] == [0, 0, 0, 1]
    for bit in range(1, 8):
        advance(machine, clock, 250)
        advance(machine, clock, 1)
        assert machine.snapshot()['segments'] == [0, 0, 0, 1 << bit]
    advance(machine, clock, 250)
    advance(machine, clock, 1)
    assert machine.snapshot()['segments'] == [0, 0, 0, 1]


def test_multiplex_displays_all_digits_repeatedly():
    machine, clock = start('segment_1234.c')
    counts = [0] * 4
    unexpected = []
    original = machine.seven.observe

    def observe(tick, digit, pattern, **kwargs):
        if 0 <= digit < 4 and pattern and pattern != [102, 79, 91, 6][digit]:
            unexpected.append((digit, pattern))
        if 0 <= digit < 4 and pattern == [102, 79, 91, 6][digit]:
            counts[digit] += 1
        original(tick, digit, pattern, **kwargs)

    machine.seven.observe = observe
    machine.run(3000)
    observed = set()
    for _ in range(24):
        advance(machine, clock, 2)
        observed.add(tuple(machine.snapshot()['segments']))
    assert (102, 79, 91, 6) in observed
    # Every digit must be driven repeatedly, not merely written once.
    assert all(count > 1 for count in counts), counts
    assert unexpected == [], unexpected


def test_walking_segment_uses_wall_clock():
    import time

    source = (ROOT / 'templates' / 'segment_walk.c').read_text()
    machine = Machine(Compiler().compile(source).hex, realtime=True)
    machine.board.connect('CNA', 'CNA2')
    machine.board.connect('CNB', 'CNB2')
    machine.resume_clock()
    deadline = time.monotonic() + 1.2
    seen = set()
    while time.monotonic() < deadline and not {1, 2, 4}.issubset(seen):
        machine.run(3000)
        seen.add(machine.snapshot()['segments'][3])
    assert {1, 2, 4}.issubset(seen), seen
