import io
import struct

import pytest
from intelhex import IntelHex

from simulator.runtime import Runtime
from simulator.server import create_app


def firmware():
    # movs r0,#1; adds r0,#1; b back to adds
    ih = IntelHex()
    ih.frombytes(struct.pack('<II', 0x10008000, 9) + bytes.fromhex('01200130fde7'), offset=0)
    out = io.StringIO()
    ih.write_hex_file(out)
    return out.getvalue()


@pytest.fixture
def runtime():
    rt = Runtime(start_worker=False, realtime=False)
    rt.load(firmware())
    yield rt
    rt.close()


def test_step_registers_memory_and_validation(runtime):
    state = runtime.debug({'action': 'step', 'count': 2})
    assert state['state']['status'] == 'paused'
    assert state['debug']['registers']['R0'] == 2
    assert state['debug']['pc'] == 12
    assert len(state['debug']['registers']) == 18
    assert runtime.debug({'action': 'memory', 'address': '0x8', 'length': 4})['debug']['memory']['bytes'] == [1, 32, 1, 48]
    for address, length in [(0x40000000, 4), (0x7ffff, 2), (0, 257), (0, 0)]:
        with pytest.raises(ValueError):
            runtime.debug({'action': 'memory', 'address': address, 'length': length})
    for count in (0, 1001, True, '1'):
        with pytest.raises(ValueError):
            runtime.debug({'action': 'step', 'count': count})


def test_breakpoint_resume_reset_and_clear(runtime):
    runtime.debug({'action': 'breakpoint', 'address': 10, 'enabled': True})
    runtime.control('run')
    runtime._run_slice()
    assert runtime.status == 'paused'
    assert runtime.debug({'action': 'state'})['debug']['pc'] == 10
    assert runtime.debugger.stop_reason == 'breakpoint'
    runtime.control('resume')
    runtime._run_slice()
    assert runtime.status == 'paused'
    assert runtime.debug({'action': 'state'})['debug']['registers']['R0'] == 2
    runtime.control('reset')
    assert runtime.debug({'action': 'state'})['debug']['breakpoints'] == [10]
    runtime.debug({'action': 'clear-breakpoints'})
    assert runtime.debugger.hook is None


def test_atomic_load_and_api(runtime):
    client = create_app(runtime).test_client()
    assert client.post('/api/debug', json={'action': 'state'}).status_code == 200
    assert client.post('/api/debug', json={'action': 'memory', 'address': 0, 'length': 257}).status_code == 400
    old = runtime.machine
    with pytest.raises(ValueError):
        runtime.load(firmware(), elf=b'bad elf')
    assert runtime.machine is old
    assert client.post('/api/firmware', json={'hex': firmware(), 'elfBase64': '!'}).status_code == 400


def test_real_compiler_source_symbols(runtime):
    source = 'volatile unsigned int counter;\nint main(void) {\n counter = 7;\n while (1) counter++;\n}\n'
    result = runtime.compiler.compile(source)
    assert result.elf
    runtime.load(result.hex, elf=result.elf)
    debug = runtime.debug({'action': 'state'})['debug']
    assert debug['hasElf'] and debug['hasSource']
    assert any(s['name'] == 'counter' for s in debug['symbols'])
    response = runtime.debug({'action': 'breakpoint', 'line': 3})
    assert response['debug']['breakpoints']


def test_pause_clock_and_wiring_on_step_and_reset():
    rt = Runtime(start_worker=False, realtime=True)
    try:
        rt.load(firmware())
        rt.physical({'action': 'connect', 'a': 'CNC', 'b': 'CNA1'})
        rt.control('run')
        assert rt.machine._clock_anchor is not None
        result = rt.debug({'action': 'step'})
        assert rt.machine._clock_anchor is None
        assert result['state']['cables'] == [['CNC', 'CNA1']]
        rt.control('reset')
        assert rt.snapshot()['cables'] == [['CNC', 'CNA1']]
    finally:
        rt.close()


def test_step_error_is_preserved(runtime):
    # UDF triggers an unsupported CPU exception.
    runtime.machine.uc.mem_write(8, bytes.fromhex('00de'))
    with pytest.raises(ValueError):
        runtime.debug({'action': 'step'})
    assert runtime.status == 'error'
    assert runtime.machine.error
    assert runtime.debug({'action': 'state'})['debug']['stopReason'] == 'error'
    runtime.control('reset')
    assert runtime.machine.error is None


@pytest.mark.parametrize('fast', [False, True])
@pytest.mark.parametrize('base', [8, 0x10000000, 0x2007c000])
def test_breakpoint_added_after_loop_warmup(fast, base):
    from unicorn.arm_const import UC_ARM_REG_PC
    rt = Runtime(start_worker=False, realtime=True)
    try:
        rt.load(firmware())
        rt.machine._clock_ns = lambda: 0
        if base != 8:
            rt.machine.uc.mem_write(base, bytes.fromhex('01200130fde7'))
            rt.machine.uc.reg_write(UC_ARM_REG_PC, base | 1)
        rt.machine.run(20000, timeout_us=0, fast=fast)
        # The breakpoint is behind the current PC, so an exit-address limit
        # cannot hide a missing callback in the already translated loop.
        for _ in range(3):
            rt.debug({'action': 'breakpoint', 'address': base + 2})
            rt.control('run')
            rt._run_slice()
            assert rt.status == 'paused'
            assert rt.debugger.stop_reason == 'breakpoint'
            assert rt.machine.uc.reg_read(UC_ARM_REG_PC) == base + 2
            rt.debug({'action': 'clear-breakpoints'})
            rt.control('run')
            rt._run_slice()
    finally:
        rt.close()


def test_precise_accounting_after_fast_loop_warmup():
    from simulator.engine import Machine
    from unicorn.arm_const import UC_ARM_REG_R0
    machine = Machine(firmware(), realtime=True, clock_ns=lambda: 0)
    machine.run(20000, timeout_us=0, fast=True)
    previous_ticks = machine.ticks
    previous_value = machine.uc.reg_read(UC_ARM_REG_R0)
    machine.run(100, timeout_us=0)
    assert machine.uc.reg_read(UC_ARM_REG_R0) - previous_value == 50
    # Existing block accounting rounds a partial final block; it must still
    # count the loop, rather than only its first cached block.
    assert 99 <= machine.ticks - previous_ticks <= 102


def test_offline_instruction_budget_survives_slow_host_callbacks():
    import time
    from simulator.engine import Machine
    from unicorn import UC_HOOK_CODE
    from unicorn.arm_const import UC_ARM_REG_R0
    machine = Machine(firmware())
    # Twenty instructions deliberately exceed the old 100 ms wall timeout.
    # Deterministic execution still owes the caller all twenty instructions.
    machine.uc.hook_add(UC_HOOK_CODE, lambda *args: time.sleep(.01))
    machine.run(20)
    assert machine.uc.reg_read(UC_ARM_REG_R0) == 11

def test_breakpoint_at_code_data_boundary_stops_before_data_translation():
    from io import BytesIO
    from elftools.elf.elffile import ELFFile
    from simulator.compiler import Compiler
    from simulator.runtime import Runtime
    source = '''\tAREA RESET, DATA, READONLY
__Vectors DCD 0x10001000, Reset_Handler
\tAREA code, CODE, READONLY
Reset_Handler
\tLDR R0, =values
\tLDR R1, [R0]
values DCD 0x12345678
\tEND
'''
    compiled = Compiler().compile(source, 'asm')
    symbols = {s.name: s['st_value'] for s in ELFFile(BytesIO(compiled.elf)).get_section_by_name('.symtab').iter_symbols()}
    runtime = Runtime(start_worker=False)
    try:
        runtime.load(compiled.hex, elf=compiled.elf)
        runtime.debug({'action': 'breakpoint', 'address': symbols['values']})
        runtime.control('run')
        runtime._run_slice()
        result = runtime.debug({'action': 'state'})
        assert result['state']['status'] == 'paused'
        assert result['debug']['stopReason'] == 'breakpoint'
        assert result['debug']['pc'] == symbols['values']
        assert result['debug']['registers']['R1'] == 0x12345678
    finally:
        runtime.close()
