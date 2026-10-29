"""Debugger metadata and bounded, side-effect-free CPU inspection."""
from bisect import bisect_right
from io import BytesIO

from unicorn import UC_HOOK_CODE
from unicorn import arm_const

REGISTERS = {name: getattr(arm_const, 'UC_ARM_REG_' + name) for name in
             [*(f'R{i}' for i in range(13)), 'SP', 'LR', 'PC', 'XPSR', 'PRIMASK']}
RANGES = ((0, 0x80000), (0x10000000, 0x10008000), (0x2007c000, 0x20084000))


def number(value, name):
    try:
        if type(value) is int:
            return value
        if isinstance(value, str):
            return int(value, 0)
    except ValueError:
        pass
    raise ValueError(f'{name} must be an integer or 0x-prefixed address.')


def valid_range(address, length):
    return any(start <= address and address + length <= end for start, end in RANGES)


class Debugger:
    def __init__(self, machine, elf=b''):
        if not isinstance(elf, bytes) or len(elf) > 10_000_000:
            raise ValueError('ELF must be bytes, at most 10 MB.')
        self.machine = machine
        self.elf = elf
        self.breakpoints = set()
        self.hook = None
        self.skip = None
        self.stepping = False
        self.hit = False
        self.stop_reason = 'ready'
        self.lines = []
        self.symbols = []
        if elf:
            self._parse(elf)
        self.line_addresses = [line[0] for line in self.lines]

    def _parse(self, data):
        if not isinstance(data, bytes) or len(data) > 10_000_000:
            raise ValueError('ELF must be bytes, at most 10 MB.')
        try:
            from elftools.elf.elffile import ELFFile
            elf = ELFFile(BytesIO(data))
            if elf['e_machine'] != 'EM_ARM' or elf.elfclass != 32 or not elf.little_endian:
                raise ValueError('Expected a little-endian 32-bit ARM ELF.')
            for section in elf.iter_sections():
                if section['sh_type'] not in ('SHT_SYMTAB', 'SHT_DYNSYM'):
                    continue
                for symbol in section.iter_symbols():
                    typ = symbol['st_info']['type']
                    if symbol.name and typ in ('STT_OBJECT', 'STT_FUNC') and symbol['st_shndx'] != 'SHN_UNDEF':
                        address = symbol['st_value'] & (~1 if typ == 'STT_FUNC' else -1)
                        self.symbols.append({'name': symbol.name, 'address': address,
                                             'size': symbol['st_size'], 'type': 'function' if typ == 'STT_FUNC' else 'object'})
            self.symbols.sort(key=lambda s: (s['address'], s['name']))
            if elf.has_dwarf_info():
                dwarf = elf.get_dwarf_info()
                for cu in dwarf.iter_CUs():
                    program = dwarf.line_program_for_CU(cu)
                    if not program:
                        continue
                    files = program['file_entry']
                    previous = None
                    for entry in program.get_entries():
                        state = entry.state
                        if state is None:
                            continue
                        if previous and state.address > previous[0]:
                            self.lines.append((*previous, state.address))
                        if state.end_sequence:
                            previous = None
                        elif 1 <= state.file <= len(files) and state.line:
                            filename = files[state.file - 1].name.decode('utf-8', 'replace')
                            previous = (state.address, filename, state.line)
                self.lines.sort()
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f'Invalid ELF debug data: {e}') from e

    def attach(self, machine):
        self.machine = machine
        self.hook = None
        self.skip = None
        self.hit = False
        self.stop_reason = 'ready'
        self._sync_hook()

    def _sync_hook(self):
        if self.breakpoints and self.hook is None:
            self.hook = self.machine.uc.hook_add(UC_HOOK_CODE, self._on_code)
            self.machine.invalidate_translations()
        elif not self.breakpoints and self.hook is not None:
            self.machine.uc.hook_del(self.hook)
            self.hook = None
            self.machine.invalidate_translations()

    def _on_code(self, uc, address, size, user_data):
        if self.stepping:
            return
        if self.skip is not None:
            skip, self.skip = self.skip, None
            if address == skip:
                return
        if address in self.breakpoints:
            self.hit = True
            self.stop_reason = 'breakpoint'
            uc.emu_stop()

    def resume(self):
        if self.hit:
            self.skip = self.machine.uc.reg_read(REGISTERS['PC']) & ~1
        self.hit = False
        self.stop_reason = 'ready'

    def execution_limit(self):
        # Unicorn's exit address also bounds translation at a breakpoint.
        # This matters at instruction/data boundaries: a backend must not
        # translate embedded data before the execution hook can stop there.
        if not self.breakpoints:
            return None
        pc = self.machine.uc.reg_read(REGISTERS['PC']) & ~1
        return min((address for address in self.breakpoints if address > pc), default=None)

    def complete_slice(self, limit):
        if limit is not None and self.machine.uc.reg_read(REGISTERS['PC']) & ~1 == limit:
            self.hit = True
            self.stop_reason = 'breakpoint'

    def breakpoint(self, data):
        enabled = data.get('enabled', True)
        if type(enabled) is not bool:
            raise ValueError('enabled must be a boolean.')
        if 'address' in data:
            address = number(data['address'], 'address') & ~1
            if not valid_range(address, 2):
                raise ValueError('Breakpoint must be in flash or SRAM.')
            addresses = {address}
        else:
            line = number(data.get('line'), 'line')
            filename = data.get('file')
            if filename is not None and not isinstance(filename, str):
                raise ValueError('file must be a string.')
            addresses = {a for a, f, n, _ in self.lines if n == line and (filename is None or f == filename)}
            if not addresses:
                raise ValueError('No executable address for that source line.')
        if enabled:
            self.breakpoints.update(addresses)
        else:
            self.breakpoints.difference_update(addresses)
        self._sync_hook()

    def source(self, pc):
        i = bisect_right(self.line_addresses, pc) - 1
        if i >= 0:
            start, file, line, end = self.lines[i]
            if start <= pc < end:
                return {'file': file, 'line': line, 'address': start}
        return None

    def memory(self, address, length):
        address, length = number(address, 'address'), number(length, 'length')
        if not 1 <= length <= 256 or not valid_range(address, length):
            raise ValueError('Memory reads require 1–256 bytes entirely within flash or SRAM.')
        return {'address': address, 'bytes': list(self.machine.uc.mem_read(address, length))}

    def snapshot(self):
        uc = self.machine.uc
        registers = {name: uc.reg_read(reg) for name, reg in REGISTERS.items()}
        pc = registers['PC'] & ~1
        size = min(4, next((end - pc for start, end in RANGES if start <= pc < end), 0))
        symbols = []
        console_length = 0
        length_symbol = next((s for s in self.symbols if s['name'] == 'lpc_console_length'
                              and s['type'] == 'object' and s['size'] == 4
                              and valid_range(s['address'], 4)), None)
        if length_symbol:
            console_length = min(4096, int.from_bytes(uc.mem_read(length_symbol['address'], 4), 'little'))
        for sym in self.symbols:
            item = dict(sym)
            if sym['type'] == 'object' and 0 < sym['size'] <= 256 and valid_range(sym['address'], sym['size']):
                item['bytes'] = list(uc.mem_read(sym['address'], sym['size']))
            elif sym['name'] == 'lpc_console_buffer' and sym['type'] == 'object' and valid_range(sym['address'], sym['size']):
                count = min(console_length, sym['size'], 4096)
                item['bytes'] = list(uc.mem_read(sym['address'], count)) if count else []
            symbols.append(item)
        return {'registers': registers, 'pc': pc, 'source': self.source(pc),
                'hasElf': bool(self.elf), 'hasSource': bool(self.lines), 'symbols': symbols,
                'breakpoints': sorted(self.breakpoints), 'instructionBytes': list(uc.mem_read(pc, size)) if size else [],
                'stopReason': self.stop_reason}
