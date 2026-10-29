"""Bounded real-firmware portability checks; no simulator implementation oracle.

ARM C integer division truncates toward zero (C11 6.5.5); GPIO addresses and
SET/CLR semantics are from NXP UM10360 sections 9.5 and 9.6.
"""
import struct
from pathlib import Path

import pytest

from simulator.compiler import CompileError, Compiler
from simulator.engine import Machine
from simulator.runtime import Runtime


ROOT = Path(__file__).resolve().parents[1]

SOURCE = r'''
#include <LPC17xx.h>
volatile unsigned initialized = 0x12345678;
volatile unsigned zeroed;
volatile unsigned numerator = 1000000007u, denominator = 97u;
__attribute__((noinline)) unsigned compute(unsigned n, unsigned d) {
    volatile unsigned stack[4] = {n, d, n / d, n % d};
    return stack[2] + stack[3];
}
int main(void) {
    volatile unsigned *out = (void *)0x10007000;
    LPC_GPIO0->FIODIR = 0xFF0;
    LPC_GPIO0->FIOSET = 0xA50;
    LPC_GPIO0->FIOCLR = 0x050;
    out[0] = initialized;
    out[1] = zeroed;
    out[2] = compute(numerator, denominator);
    out[3] = LPC_GPIO0->FIOPIN & 0xFF0;
    out[4] = 0xB16B00B5;
    while (1) {}
}
'''


def execute(compiler):
    result = compiler.compile(SOURCE)
    machine = Machine(result.hex)
    for _ in range(20):
        machine.run(5000)
        values = struct.unpack('<5I', bytes(machine.uc.mem_read(0x10007000, 20)))
        if values[4] == 0xB16B00B5:
            break
    assert values[4] == 0xB16B00B5, f'firmware did not finish: {machine.snapshot()}'
    assert machine.error is None
    return values


@pytest.mark.parametrize('optimization', range(4))
def test_portable_firmware_semantics(optimization):
    compiler = Compiler(optimization=optimization)
    assert compiler.info()['available'], 'A portable ARM compiler is required for the matrix'
    assert compiler.info()['backend'] != 'keil'
    expected = (0x12345678, 0, 1000000007 // 97 + 1000000007 % 97, 0xA00, 0xB16B00B5)
    assert execute(compiler) == expected


def test_available_compilers_produce_same_observable_state():
    compilers = [Compiler(backend=name) for name in ('zig', 'clang', 'gcc')]
    compilers = [compiler for compiler in compilers if compiler.info()['available']]
    if len(compilers) < 2:
        pytest.skip('Cross-compiler comparison requires two installed portable backends')
    expected = (0x12345678, 0, 1000000007 // 97 + 1000000007 % 97, 0xA00, 0xB16B00B5)
    for compiler in compilers:
        assert execute(compiler) == expected, compiler.info()['backend']


@pytest.mark.parametrize('bad_hex', [
    '', 'bad', ':00000001FE\n', ':0100000000FE\n:00000001FF\n',
    ':0400000000100010DC\n:00000001FF\n',
])
def test_bad_firmware_is_rejected_atomically(bad_hex):
    runtime = Runtime(start_worker=False)
    try:
        runtime.load((ROOT / 'examples/idle.hex').read_text())
        old = runtime.machine
        before = runtime.snapshot()
        with pytest.raises(ValueError):
            runtime.load(bad_hex)
        assert runtime.machine is old
        assert runtime.snapshot() == before
    finally:
        runtime.close()


def test_failed_compilation_preserves_running_firmware():
    runtime = Runtime(start_worker=False)
    try:
        runtime.load((ROOT / 'examples/idle.hex').read_text())
        old = runtime.machine
        before = runtime.snapshot()
        assert runtime.compiler.info()['available'], 'Compiler required to exercise invalid C'
        with pytest.raises(CompileError):
            runtime.compile('int main( {')
        assert runtime.machine is old
        assert runtime.snapshot() == before
    finally:
        runtime.close()
