"""Translate a conservative Keil ARMASM subset to GNU unified Thumb syntax."""
import re


class AssemblyError(ValueError):
    pass


def strip_comment(line: str) -> str:
    quote = None
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
        elif quote and char == '\\':
            escaped = True
        elif quote and char == quote:
            quote = None
        elif not quote and char in ('"', "'"):
            quote = char
        elif not quote and char == ';':
            return line[:index].rstrip()
    return line.rstrip()


def translate(source: str) -> str:
    lines = ['.syntax unified', '.cpu cortex-m3', '.thumb', '.file 1 "main.asm"']
    code = False
    pending_labels = []
    directives = {'AREA', 'EXPORT', 'IMPORT', 'ENTRY', 'PRESERVE8', 'THUMB',
                  'END', 'DCD', 'DCW', 'DCB', 'SPACE', 'ALIGN', 'EQU', 'ARM', 'CODE32', '.ARM'}
    ended = False
    radix = re.compile(r'\b(\d+)_([0-9A-Za-z]+)\b')
    for number, original in enumerate(source.splitlines(), 1):
        text = strip_comment(original)
        if not text.strip():
            continue
        if ended:
            raise AssemblyError(f'main.asm:{number}: content after END')
        def convert(m):
            base = int(m.group(1))
            try:
                if not 2 <= base <= 36:
                    raise ValueError()
                return str(int(m.group(2), base))
            except ValueError:
                raise AssemblyError(f'main.asm:{number}: invalid base-{base} literal {m.group(0)}') from None
        pieces = re.split(r'''("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')''', text)
        for index in range(0, len(pieces), 2):
            pieces[index] = radix.sub(convert, pieces[index])
            pieces[index] = re.sub(r"(?<![\w.])0+(\d+)(?![\w.])", lambda m: str(int(m.group(1))), pieces[index])
        text = "".join(pieces)
        label = None
        if not text[0].isspace():
            match = re.match(r'^([A-Za-z_.$][\w.$]*):?(?:\s+|$)(.*)$', text)
            if not match:
                raise AssemblyError(f'main.asm:{number}: invalid label')
            label, text = match.group(1), match.group(2)
        text = text.strip()
        parts = text.split(None, 1)
        op = parts[0].upper() if parts else ''
        arg = parts[1].strip() if len(parts) > 1 else ''
        lines.append(f'.loc 1 {number} 0')
        if label and op == 'EQU':
            lines.append(f'.equ {label}, {arg}')
            continue
        if label:
            pending_labels.append(label)
        if not op:
            continue
        if op not in ('EXPORT', 'IMPORT', 'ENTRY', 'PRESERVE8', 'THUMB'):
            if op in ('DCD', 'DCW'):
                lines.append(f'.balign {4 if op == "DCD" else 2}')
            for pending in pending_labels:
                if code and op not in directives:
                    lines.append('.thumb_func')
                lines.append(f'{pending}:')
            pending_labels.clear()
        if op == 'AREA':
            fields = [x.strip() for x in arg.split(',')]
            if len(fields) < 3 or not re.fullmatch(r'[\w.$]+', fields[0]):
                raise AssemblyError(f'main.asm:{number}: malformed AREA')
            attrs = {x.upper() for x in fields[1:]}
            if attrs not in ({'CODE', 'READONLY'}, {'DATA', 'READONLY'}, {'DATA', 'READWRITE'}):
                raise AssemblyError(f'main.asm:{number}: unsupported AREA attributes')
            code = 'CODE' in attrs
            section = '.vectors' if fields[0].upper() == 'RESET' else ('.text.' if code else '.data.' if 'READWRITE' in attrs else '.rodata.') + fields[0]
            flags = 'ax' if code else 'aw' if 'READWRITE' in attrs else 'a'
            lines.append(f'.section {section},"{flags}",%progbits')
        elif op in ('EXPORT', 'IMPORT'):
            if not re.fullmatch(r'[A-Za-z_.$][\w.$]*', arg):
                raise AssemblyError(f'main.asm:{number}: malformed {op}')
            lines.append(f'.global {arg}')
        elif op in ('ENTRY', 'PRESERVE8', 'THUMB', 'END'):
            if arg:
                raise AssemblyError(f'main.asm:{number}: unexpected operand for {op}')
            ended = op == 'END'
        elif op == 'DCB' and re.fullmatch(r'"(?:\\.|[^"\\])*"', arg):
            lines.append(f'.ascii {arg}')
        elif op in ('DCD', 'DCW', 'DCB', 'SPACE'):
            lines.append(f"{ {'DCD':'.word', 'DCW':'.hword', 'DCB':'.byte', 'SPACE':'.space'}[op]} {arg}")
        elif op == 'ALIGN':
            lines.append(f'.balign {arg or "4"}')
        elif op == 'EQU':
            raise AssemblyError(f'main.asm:{number}: EQU requires a label')
        elif op in ('ARM', 'CODE32', '.ARM'):
            raise AssemblyError(f'main.asm:{number}: ARM state is unsupported on Cortex-M3')
        elif not code:
            raise AssemblyError(f'main.asm:{number}: unsupported directive {op}')
        else:
            # ARMASM permits an omitted immediate marker. Clang needs it to
            # recognize a negative MOV constant and choose the MVN encoding.
            if op.startswith('MOV'):
                arg = re.sub(r'^((?:R(?:1[0-5]|[0-9])|SP|LR|PC)\s*,\s*)(-(?:0[xX][0-9A-Fa-f]+|\d+))$',
                             r'\1#\2', arg, flags=re.IGNORECASE)
            lines.append(f'{op} {arg}')
    lines.extend(f'{label}:' for label in pending_labels)
    lines.extend([
        '.section .debug_abbrev,"",%progbits', '.byte 1, 0x11, 0',
        '.byte 0x10, 0x17, 0x03, 0x08, 0x13, 0x05, 0, 0, 0',
        '.section .debug_info,"",%progbits', '.long 2f-1f', '1:',
        '.hword 4', '.long 0', '.byte 4', '.byte 1', '.long 0',
        '.asciz "main.asm"', '.hword 0x8001', '2:',
    ])
    return '\n'.join(lines) + '\n'
