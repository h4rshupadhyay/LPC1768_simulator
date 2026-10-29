"""Assembly passes through LLVM and executes on the real Cortex-M engine."""
import struct
from io import BytesIO

import pytest
from elftools.elf.elffile import ELFFile
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1

from simulator.assembly import AssemblyError, translate
from simulator.compiler import Compiler
from simulator.debugger import Debugger
from simulator.engine import Machine

SOURCE = '''\tAREA RESET, DATA, READONLY
\tEXPORT __Vectors
__Vectors DCD 0x10001000, Reset_Handler
\tAREA code, CODE, READONLY
\tEXPORT Reset_Handler
Reset_Handler
\tMOV R0, #1
\tMOV R1, #5
loop
\tMUL R0, R0, R1
\tSUBS R1, #1
\tBNE loop
\tLDR R2, =array
\tLDR R3, [R2]
\tLDR R4, [R2, #4]
\tSTR R4, [R2]
\tSTR R3, [R2, #4]
stop
\tB stop
\tAREA data, DATA, READWRITE
array DCD 2_1010, 5_34
\tEND
'''


def test_factorial_swap_sram_thumb_vector_and_debug_lines():
    result = Compiler().compile(SOURCE, 'asm')
    machine = Machine(result.hex)
    elf = ELFFile(BytesIO(result.elf))
    symbols = {s.name: s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
    assert machine.entry == symbols['Reset_Handler'] and machine.entry & 1
    assert struct.unpack('<2I', machine.uc.mem_read(symbols['array'], 8)) == (10, 19)
    machine.run(1000)
    assert machine.error is None
    assert machine.uc.reg_read(UC_ARM_REG_R0) == 120
    assert machine.uc.reg_read(UC_ARM_REG_R1) == 0
    assert struct.unpack('<2I', machine.uc.mem_read(symbols['array'], 8)) == (19, 10)
    debugger = Debugger(machine, result.elf)
    assert any(name == 'main.asm' and line == 8 for _, name, line, _ in debugger.lines)


def test_invalid_radix_and_unsupported_directive():
    with pytest.raises(AssemblyError, match='invalid base-2'):
        translate('\tAREA x, DATA, READONLY\nx DCD 2_102')
    with pytest.raises(AssemblyError, match='unsupported directive'):
        translate('\tAREA x, DATA, READONLY\n\tINCBIN x')


def test_armasm_optional_hash_negative_mov():
    source = SOURCE.replace('MOV R0, #1', 'MOV R0, -8').replace('\nloop\n', '\n\tB stop\nloop\n', 1)
    machine = Machine(Compiler().compile(source, 'asm').hex)
    machine.run(20)
    assert machine.uc.reg_read(UC_ARM_REG_R0) == 0xFFFFFFF8


def test_local_thumb_code_pointers_and_embedded_data_addresses():
    source = '''\tAREA RESET, DATA, READONLY
__Vectors DCD 0x10001000, Reset_Handler
\tAREA code, CODE, READONLY
Reset_Handler
\tLDR R0, =subroutine
\tBLX R0
\tLDR R2, =message
\tB stop
subroutine
\tMOV R1, #42
\tBX LR
message DCB "a;b" ; this comment must not truncate the string
\tALIGN
stop B stop
\tEND
'''
    from unicorn.arm_const import UC_ARM_REG_R2
    result = Compiler().compile(source, 'asm')
    machine = Machine(result.hex)
    machine.run(100)
    assert machine.error is None
    assert machine.uc.reg_read(UC_ARM_REG_R1) == 42
    address = machine.uc.reg_read(UC_ARM_REG_R2)
    symbols = {s.name: s['st_value'] for s in ELFFile(BytesIO(result.elf)).get_section_by_name('.symtab').iter_symbols()}
    assert address == symbols['message']  # A data label has no Thumb bit.
    assert bytes(machine.uc.mem_read(address, 3)) == b'a;b'


@pytest.mark.parametrize('standalone', [False, True])
def test_armasm_data_alignment_precedes_the_label(standalone):
    source = '''\tAREA RESET, DATA, READONLY
__Vectors DCD 0x10001000, Reset_Handler
\tAREA code, CODE, READONLY
Reset_Handler
\tLDR R0, =word
\tLDR R1, =half
stop B stop
\tAREA data, DATA, READWRITE
byte DCB 0xAA
word DCD 0x12345678
byte2 DCB 0xBB
half DCW 0x1234
\tEND
'''
    if standalone:
        source = source.replace('word DCD', 'word\n\tDCD').replace('half DCW', 'half\n\tDCW')
    machine = Machine(Compiler().compile(source, 'asm').hex)
    machine.run(20)
    assert machine.error is None
    assert machine.uc.reg_read(UC_ARM_REG_R0) == 0x10000004
    assert machine.uc.reg_read(UC_ARM_REG_R1) == 0x1000000A
    assert bytes(machine.uc.mem_read(0x10000000, 12)) == bytes.fromhex('aa00000078563412bb003412')


def test_conditional_instructions_gcd_and_128_bit_carry():
    source = '''\tAREA RESET, DATA, READONLY
\tEXPORT __Vectors
__Vectors DCD 0x10001000, Reset_Handler
\tAREA code, CODE, READONLY
\tEXPORT Reset_Handler
Reset_Handler
\tMOV R0, #48
\tMOV R1, #18
gcd
\tCMP R0, R1
\tSUBGT R0, R0, R1
\tSUBLT R1, R1, R0
\tBNE gcd
\tLDR R2, =0xffffffff
\tMOV R3, #1
\tADDS R4, R2, R3
\tADCS R5, R2, R4
\tADCS R6, R2, R4
\tADCS R7, R2, R4
\tADC R8, R4, R4
stop
\tB stop
\tEND
'''
    from unicorn.arm_const import UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_R8
    machine = Machine(Compiler().compile(source, 'asm').hex)
    machine.run(1000)
    assert machine.error is None
    assert machine.uc.reg_read(UC_ARM_REG_R0) == 6
    assert [machine.uc.reg_read(r) for r in (UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_R8)] == [0, 0, 0, 0, 1]
