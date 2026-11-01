"""Check unchanged course assembly against independent arithmetic/array oracles."""
import argparse
import hashlib
from io import BytesIO
import json
import math
import os
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from elftools.elf.elffile import ELFFile
from unicorn import UC_HOOK_CODE, arm_const
from simulator.compiler import Compiler
from simulator.engine import Machine, FirmwareError


def run(path):
    raw = path.read_bytes()
    result = Compiler().compile(raw.decode(), 'asm')
    symbols = {s.name: s['st_value'] for s in ELFFile(BytesIO(result.elf)).get_section_by_name('.symtab').iter_symbols()}
    machine = Machine(result.hex)
    reads = []

    def address(name):
        return symbols[name] if isinstance(name, str) else name

    def words(name, count=1):
        reads.append({'kind': 'memory', 'address': address(name), 'length': count * 4})
        return list(struct.unpack(f'<{count}I', machine.uc.mem_read(address(name), count * 4)))

    def reg(number):
        reads.append({'kind': 'register', 'name': f'R{number}'})
        return machine.uc.reg_read(getattr(arm_const, f'UC_ARM_REG_R{number}'))

    name = path.stem.upper()
    key = path.as_posix()
    note = ''
    if name == 'DATATRANSFER':
        if 'Init2/' in key:
            expected = [0x12345678, 0xfffffff8]
            observe = lambda: [reg(1), reg(5)]
        else:
            expected = [10, 16, 10, 19, 0xfffffff8]
            observe = lambda: [reg(i) for i in (0, 1, 3, 4, 5)]
            note = '5_34 is 19, despite the original comment saying decimal 34.'
    elif name == 'ARRAY_REVERSAL':
        expected = words('SRC', 10)[::-1]
        observe = lambda: words('SRC', 10)
    elif name in ('LOOP', 'LOOP2', 'SWAP', 'MULTINDEX'):
        source = words('SRC', 10)
        expected = source if name != 'MULTINDEX' else source[:6] + [0] * 4
        observe = lambda: words('DST', 10)
        if name != 'LOOP2':
            note = 'DST declares one word; the code writes beyond that declaration into mapped SRAM.'
        if name == 'MULTINDEX':
            note += ' Mixed indexing intentionally repeats positions; only the first six destination words are filled.'
    elif name == 'ADDER':
        total = sum(words('SRC', 10))
        expected = [total & 0xffffffff, total >> 32]
        observe = lambda: words('Result', 2)
        note = 'Original stores R2 and R5 to the same address, overwriting the sum, and falls into data. R2/R5 are not initialized.'
    elif name == 'ADD128BIT':
        a = sum(v << (32 * i) for i, v in enumerate(words('N1', 4)))
        b = sum(v << (32 * i) for i, v in enumerate(words('N2', 4)))
        expected = [((a + b) >> (32 * i)) & 0xffffffff for i in range(4)]
        observe = lambda: words('Result', 4)
        note = 'Original overwrites R6 for each limb and stores the N2 pointer and last operand instead of four result limbs.'
    elif name == 'ASCIITOHEX':
        expected = [int(bytes(machine.uc.mem_read(symbols['SRC'], 8)), 16)]
        observe = lambda: words('DST')
        note = "Original compares accumulated R1 with '9', rather than the input character R2; it also falls into data."
    elif name == 'HEXTOASCII':
        expected = list(f'{words("SRC")[0]:08X}'.encode())
        observe = lambda: words('DST', 8)
        note = 'Original stores least-significant nibble first, reversing the documented string; digit 9 also takes the letter adjustment. It falls into data.'
    elif name == 'BCDTOHEX':
        packed = words('SRR')[0]
        expected = [sum(((packed >> (4 * i)) & 15) * 10**i for i in range(3))]
        observe = lambda: [reg(4)]
        note = 'R4 is not initialized in the source; this result uses the simulator reset-register convention of zero.'
    elif name in ('HEXTOBCD', 'HEXTOBCD2'):
        expected = [int(str(words('SRR')[0]), 16)]
        observe = lambda: [reg(4)]
    elif name == 'GCD':
        expected = [math.gcd(words('numA')[0], words('numB')[0])]
        observe = lambda: words('result')
    elif name == 'FACTORIAL':
        expected = [math.factorial(5)]
        observe = lambda: words(0x10001000)
    elif name == 'INSERTION':
        expected = sorted(words('ARRAY', 9))
        observe = lambda: words('ARRAY', 9)
        note = 'Original dereferences address 9 as an array length and advances the outer pointer inside the inner loop.'
    elif name == 'SEARCH':
        data, target = words('SRC', 8), words('target')[0]
        index = data.index(target) if target in data else -1
        expected = [int(index >= 0), symbols['SRC'] + index * 4 if index >= 0 else 0]
        observe = lambda: words('result') + words('found_addr')
    elif name in ('PERFECTPERF', 'PERFECTWITHOUTBRANCH'):
        n = 9 if name == 'PERFECTPERF' else 10
        divisors = [d for d in range(1, n) if n % d == 0]
        expected = divisors + [0xff if sum(divisors) == n else 0x11]
        observe = lambda: words(0x10001000, len(expected))
    else:
        raise AssertionError(f'No independent oracle for {path}')

    terminal_name = next((label for label in ('STOP', 'LoopForever', 'DONE') if label in symbols), 'SRC')
    terminal = symbols[terminal_name] & ~1
    reached = False

    def stop(uc, pc, size, data):
        nonlocal reached
        if pc == terminal:
            reached = True
            uc.emu_stop()

    hook = machine.uc.hook_add(UC_HOOK_CODE, stop)
    execution_error = None
    try:
        machine.run(10000, timeout_us=0)
    except FirmwareError as error:
        execution_error = str(error)
    finally:
        machine.uc.hook_del(hook)
    reads.clear()
    actual = observe()
    passed = reached and not execution_error and actual == expected
    return {'source': str(path), 'sha256': hashlib.sha256(raw).hexdigest(),
            'outcome': 'OUTPUT_PASS' if passed else 'ORIGINAL_SOURCE_ISSUE',
            'expected': expected, 'actual': actual, 'reachedBreakpoint': reached,
            'breakpoint': terminal_name, 'breakpointAddress': terminal, 'reads': reads,
            'error': execution_error, 'note': note,
            'hex': result.hex}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path,
                        default=Path(os.environ['CURRICULAR_ES']) if os.environ.get('CURRICULAR_ES') else None,
                        help='complete studied ES tree with its 20 assembly sources')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/assembly-corpus-report.json')
    parser.add_argument('--allow-source-issues', action='store_true')
    args = parser.parse_args()
    if args.corpus is None:
        parser.error('This report requires --corpus PATH or CURRICULAR_ES; '
                     'the full 20-source assembly corpus is not bundled.')
    sources = sorted(args.corpus.rglob('*.asm'))
    if len(sources) != 20:
        parser.error(f'The studied report requires 20 assembly sources; found {len(sources)}. '
                     'Provide the complete original corpus.')
    records = [run(path) for path in sources]
    for record in records:
        record['source'] = str(Path(record['source']).relative_to(args.corpus))
        print(record['outcome'], record['source'], 'expected', record['expected'], 'actual', record['actual'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'records': records, 'scope': 'Unchanged originals, one bounded native run each; breakpoint before terminal/data.'}, indent=2) + '\n')
    issues = sum(record['outcome'] != 'OUTPUT_PASS' for record in records)
    print(f'{len(records) - issues} intended-output passes; {issues} original-source issues.')
    return 0 if not issues or args.allow_source_issues else 2


if __name__ == '__main__':
    raise SystemExit(main())
