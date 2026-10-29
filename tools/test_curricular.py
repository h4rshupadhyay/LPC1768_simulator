#!/usr/bin/env python3
"""Catalog and compile the unmodified MIT-Curricular ES corpus.

Set CURRICULAR_ES to the ES directory. Output is an evidence ledger, not a
claim that successful compilation or a bounded boot proves behavior.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from simulator.compiler import Compiler, CompileError, elf_to_hex
from simulator.engine import Machine, FirmwareError

DEFAULT = str(Path(__file__).resolve().parents[1] / 'fixtures/curricular')


def catalog(root):
    for path in sorted(root.rglob('*')):
        if path.is_file() and path.suffix.lower() in ('.c', '.asm'):
            yield path


def run(root):
    records = []
    for path in catalog(root):
        raw = path.read_bytes()
        relative = path.relative_to(root).as_posix()
        digest = hashlib.sha256(raw).hexdigest()
        language = 'asm' if path.suffix.lower() == '.asm' else 'c'
        for opt in ([0] if language == 'asm' else range(4)):
            row = dict(source=relative, sha256=digest, compile_flags=f'-O{opt}',
                       language=language, manual_cabling=[], outcome='COMPILE_ERROR')
            try:
                result = Compiler(optimization=opt).compile(raw.decode('utf-8'), language)
                row.update(outcome='COMPILE_PASS', backend=result.backend,
                           diagnostics=result.diagnostics)
                machine = Machine(result.hex)
                try:
                    machine.run(10000, timeout_us=100000)
                except FirmwareError:
                    pass
                if machine.error:
                    row.update(outcome='EXECUTION_ERROR', detail=f'Boot error: {machine.error}')
                else:
                    row.update(outcome='BOOT_PASS', detail='10,000-instruction maximum; behavior not checked')
                row['pc'] = machine.snapshot()['pc']
                if language == 'asm':
                    from unicorn import arm_const
                    row['registers'] = {f'R{i}': machine.uc.reg_read(getattr(arm_const, f'UC_ARM_REG_R{i}')) for i in range(13)}
            except (CompileError, UnicodeError) as exc:
                row.update(detail=str(exc), outcome=('SOURCE_ERROR' if relative in ('Lab/Lab6/JOHNSON_Counter.c', 'Project/code.c') else 'COMPILE_ERROR'))
            records.append(row)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, default=Path(os.environ.get('CURRICULAR_ES', DEFAULT)))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.corpus.is_dir():
        parser.error(f'corpus missing: {args.corpus}')
    records = run(args.corpus)
    args.output.write_text(json.dumps({'corpus': str(args.corpus), 'records': records}, indent=2) + '\n')
    from collections import Counter
    print(Counter(r['outcome'] for r in records))


if __name__ == '__main__':
    main()
