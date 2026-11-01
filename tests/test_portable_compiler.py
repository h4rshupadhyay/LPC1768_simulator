"""Real portable toolchain and reset/ISR integration, without installed Keil."""

import math
import struct
from io import BytesIO
from pathlib import Path

import pytest
from elftools.elf.elffile import ELFFile

from simulator.compiler import CompileError, Compiler, elf_to_hex
from simulator.engine import Machine


@pytest.mark.parametrize("optimization", range(4))
def test_portable_startup_initializers_clock_and_weak_vector_override(optimization):
    compiler = Compiler(optimization=optimization)
    assert compiler.info()["available"]
    assert compiler.info()["backend"] != "keil"
    result = compiler.compile("""#include <LPC17xx.h>
      volatile unsigned initialized = 0x12345678;
      volatile unsigned cleared;
      void TIMER0_IRQHandler(void) {
        LPC_TIM0->IR=1; *(volatile unsigned*)0x1000700C=0xBEEF;
        LPC_TIM0->TCR=0;
      }
      int main(void) {
        volatile unsigned *box=(void*)0x10007000;
        box[0]=initialized; box[1]=cleared; box[2]=SystemCoreClock;
        LPC_TIM0->MR0=100; LPC_TIM0->MCR=1;
        NVIC_EnableIRQ(TIMER0_IRQn); LPC_TIM0->TCR=1;
        while(1) {}
      }""")
    assert result.elf[:4] == b"\x7fELF"
    assert b".debug_line" in result.elf
    assert b"main.c" in result.elf
    machine = Machine(result.hex)
    for _ in range(20):
        machine.run(5000)
        values = struct.unpack("<4I", machine.uc.mem_read(0x10007000, 16))
        if values[-1] == 0xBEEF:
            break
    assert values == (0x12345678, 0, 100000000, 0xBEEF)
    assert machine.irq_count == 1


@pytest.mark.parametrize("filename", ["calculator_timer.c", "pwm_keypad_timer.c"])
def test_extra_timer_based_examples_compile_and_boot(filename):
    source = (Path(__file__).resolve().parents[1] / "examples" / filename).read_text()
    machine = Machine(Compiler().compile(source).hex)
    machine.run(30000)
    assert machine.ticks > 0
    assert machine.error is None


@pytest.mark.parametrize("elf", [b"", b"not ELF", b"\x7fELF" + bytes(100)])
def test_invalid_compiler_artifact_cannot_be_uploaded_as_firmware(elf):
    with pytest.raises(CompileError):
        elf_to_hex(elf)


@pytest.mark.parametrize("optimization", range(4))
def test_m3_libraries_execute_float_64bit_math_allocation_and_formatted_output(
    optimization,
):
    source = r"""#include <LPC17xx.h>
      #include <stdio.h>
      #include <stdlib.h>
      #include <string.h>
      #include <math.h>
      volatile unsigned long long a=0xFEDCBA9876543210ULL, b=1234567ULL;
      volatile double x=1.25,y=2.5;
      int main(void) {
        volatile unsigned long long *wide=(void*)0x10007000;
        wide[0]=a/b;wide[1]=a%b;
        snprintf((char*)0x10007040,128,"%llu:%u:%.2f",a/b,42u,(x+y)*2);
        volatile double *values=(void*)0x10007020;
        values[0]=sin(x);values[1]=sqrt(y*y);
        char *p=malloc(64);
        if (!p) { *(volatile unsigned*)0x10007034=0xBAD; while(1) {} }
        strcpy(p,"portable libc");
        *(volatile unsigned*)0x10007030=strcmp(p,"portable libc")==0;
        free(p);printf("hello %u\n",42u);fflush(stdout);
        *(volatile unsigned*)0x10007034=0xC0DE;
        while(1) {}
      }"""
    result = Compiler(optimization=optimization).compile(source)
    machine = Machine(result.hex)
    for _ in range(200):
        machine.run(10000)
        if struct.unpack("<I", machine.uc.mem_read(0x10007034, 4))[0] == 0xC0DE:
            break
    assert struct.unpack("<2Q", machine.uc.mem_read(0x10007000, 16)) == (
        14875465280129,
        45577,
    )
    values = struct.unpack("<2d", machine.uc.mem_read(0x10007020, 16))
    assert values == pytest.approx((math.sin(1.25), 2.5), rel=1e-12)
    assert struct.unpack("<2I", machine.uc.mem_read(0x10007030, 8)) == (1, 0xC0DE)
    assert (
        bytes(machine.uc.mem_read(0x10007040, 128)).split(b"\0")[0]
        == b"14875465280129:42:7.50"
    )
    elf = ELFFile(BytesIO(result.elf))
    symbols = {
        s.name: s["st_value"] for s in elf.get_section_by_name(".symtab").iter_symbols()
    }
    size = struct.unpack("<I", machine.uc.mem_read(symbols["lpc_console_length"], 4))[0]
    assert (
        bytes(machine.uc.mem_read(symbols["lpc_console_buffer"], size)) == b"hello 42\n"
    )
