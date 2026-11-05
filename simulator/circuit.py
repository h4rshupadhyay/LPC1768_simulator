"""External circuit: parts, breadboards and wires attached to a target board.

Endpoints name every connectable point:
  kit.CNA.1, kit.3V3, kit.5V, kit.GND           ALS kit header pins and power taps
  mbed.p5 ... mbed.p30, mbed.VOUT/VU/GND        mbed LPC1768 module pins
  mcu.P0.4, mcu.3V3, mcu.GND                    bare LPC1768 breakout pads
  bb1.a12, bb1.tp3                              breadboard holes and rails
  r1.1, hcsr04.ECHO                             part pins
Every net that contains a part pin or a supply rail is solved for voltages and
currents; the remaining nets keep the established digital model.
"""
from __future__ import annotations

import re

from . import pins
from .errors import FirmwareError
from .solver import solve
from . import doctor

PART_ID = re.compile(r'[a-z][a-z0-9_]{0,23}')
RESERVED = {'kit', 'mcu', 'mbed'}
MAX_PARTS = 120
MAX_WIRES = 400

# mbed LPC1768 DIP-40 module, from the mbed handbook pinout.
MBED_PINS = {
    'p5': 'P0.9', 'p6': 'P0.8', 'p7': 'P0.7', 'p8': 'P0.6', 'p9': 'P0.0', 'p10': 'P0.1',
    'p11': 'P0.18', 'p12': 'P0.17', 'p13': 'P0.15', 'p14': 'P0.16', 'p15': 'P0.23',
    'p16': 'P0.24', 'p17': 'P0.25', 'p18': 'P0.26', 'p19': 'P1.30', 'p20': 'P1.31',
    'p21': 'P2.5', 'p22': 'P2.4', 'p23': 'P2.3', 'p24': 'P2.2', 'p25': 'P2.1', 'p26': 'P2.0',
    'p27': 'P0.11', 'p28': 'P0.10', 'p29': 'P0.5', 'p30': 'P0.4',
    'VOUT': '3V3', 'VU': '5V', 'GND': 'GND',
}
MBED_LEDS = {'LED_M1': 'P1.18', 'LED_M2': 'P1.20', 'LED_M3': 'P1.21', 'LED_M4': 'P1.23'}
# Approximate supply limits used by the Doctor (A). ALS: on-board regulator; mbed: handbook.
RAIL_LIMITS = {'als': {'3V3': 0.8, '5V': 1.0}, 'mbed': {'3V3': 0.04, '5V': 0.5},
               'bare': {'3V3': 0.3, '5V': 0.5}}

PAD_OHMS = 70.0          # VOH >= VDD-0.4 V at 4 mA; ~45-50 mA short circuit
PULLUP = (3.3, 66_000.0)  # ~50 uA into a grounded pin
PULLDOWN = 100_000.0
VIH, VIL = 0.7 * 3.3, 0.3 * 3.3


def pad_node(node):
    if node.startswith('P') and '.' in node and node[1:2].isdigit():
        port, pin = node[1:].split('.')
        return int(port), int(pin)
    return None


class Circuit:
    def __init__(self, board):
        self.board = board
        self.parts = {}
        self.wires = []          # [a, b, color]
        self.mounts = {}         # part id -> {pin: hole endpoint}
        self.placement = {}      # part id -> opaque frontend geometry
        self.version = 0
        self.damage_mode = 'realistic'
        self.solution = None
        self.net_voltage = {}
        self.findings = []
        self._static = []
        self._static_version = -1
        self._cache = {}
        self._watch = {}         # finding key -> first time seen (ns)
        self.counter = 0
        self.probes = {}         # logic analyzer: endpoint -> deque[(t_ns, level)]

    # -- logic analyzer ------------------------------------------------------------------
    def set_probes(self, endpoints):
        if not isinstance(endpoints, list) or len(endpoints) > 8:
            raise ValueError('Probe at most 8 endpoints.')
        for endpoint in endpoints:
            self.resolve(endpoint)
        from collections import deque
        self.probes = {e: self.probes.get(e, deque(maxlen=2000)) for e in endpoints}

    def record(self, now):
        """Called on every board observation: append level changes of probed nodes."""
        for endpoint, trace in self.probes.items():
            node = self.try_resolve(endpoint)
            level = self.board._levels.get(node) if node else None
            if node in self.board._floating:
                level = None
            if not trace or trace[-1][1] != level:
                trace.append((now, level))

    @property
    def machine(self):
        return self.board.machine

    @property
    def active(self):
        return bool(self.parts) or bool(self.wires)

    def touch(self):
        self.version += 1
        self._cache.clear()
        self.board._graph_key = None

    # -- parts ----------------------------------------------------------------------
    def new_id(self, kind):
        from .parts import REGISTRY
        prefix = REGISTRY[kind].prefix
        while True:
            self.counter += 1
            pid = f'{prefix}{self.counter}'
            if pid not in self.parts:
                return pid

    def add_part(self, kind, pid=None, props=None, placement=None, mount=None):
        from .parts import REGISTRY
        if kind not in REGISTRY:
            raise ValueError(f'Unknown part type {kind!r:.40}.')
        if len(self.parts) >= MAX_PARTS:
            raise ValueError(f'At most {MAX_PARTS} parts fit on the bench.')
        pid = pid or self.new_id(kind)
        if not isinstance(pid, str) or not PART_ID.fullmatch(pid) or pid in RESERVED:
            raise ValueError('Part ids are 1-24 lowercase letters, digits or _, starting with a letter.')
        if pid in self.parts:
            raise ValueError(f'A part named {pid} already exists.')
        part = REGISTRY[kind](self, pid, props or {})
        self.parts[pid] = part
        self.placement[pid] = placement or {}
        if mount:
            try:
                self.set_mount(pid, mount)
            except ValueError:
                del self.parts[pid]
                del self.placement[pid]
                raise
        self.touch()
        return part

    def remove_part(self, pid):
        part = self._part(pid)
        if part.kind == 'breadboard':
            prefix = pid + '.'
            self.mounts = {k: {p: h for p, h in m.items() if not h.startswith(prefix)}
                           for k, m in self.mounts.items()}
        self.wires = [w for w in self.wires if not any(e.split('.')[0] == pid for e in w[:2])]
        self.mounts.pop(pid, None)
        self.placement.pop(pid, None)
        del self.parts[pid]
        self.touch()

    def _part(self, pid):
        if pid not in self.parts:
            raise ValueError(f'No part named {pid!r:.30}.')
        return self.parts[pid]

    def set_props(self, pid, props):
        part = self._part(pid)
        part.configure(props)
        self.touch()

    def set_stimulus(self, pid, name, value):
        part = self._part(pid)
        part.set_stimulus(name, value)
        self.machine.observe()

    def move(self, pid, placement, mount=None):
        self._part(pid)
        self.placement[pid] = placement or {}
        if mount is not None:
            self.set_mount(pid, mount)
        self.touch()

    def set_mount(self, pid, mount):
        part = self._part(pid)
        if not isinstance(mount, dict):
            raise ValueError('mount must map part pins to breadboard holes.')
        taken = self._occupied(exclude=pid)
        clean = {}
        for pin, hole in mount.items():
            if pin not in part.pins:
                raise ValueError(f'{part.label} has no pin {pin!r:.20}.')
            board_id = hole.split('.')[0] if isinstance(hole, str) else ''
            if board_id not in self.parts or self.parts[board_id].kind != 'breadboard':
                raise ValueError(f'{hole!r:.30} is not a breadboard hole.')
            self.parts[board_id].hole_node(hole.split('.', 1)[1])
            if hole in taken:
                raise ValueError(f'Hole {hole} is already occupied by {taken[hole]}.')
            taken[hole] = f'{pid}.{pin}'
            clean[pin] = hole
        if clean:
            self.mounts[pid] = clean
        else:
            self.mounts.pop(pid, None)
        self.touch()

    def _occupied(self, exclude=None):
        taken = {}
        for pid, mount in self.mounts.items():
            if pid != exclude:
                for pin, hole in mount.items():
                    taken[hole] = f'{pid}.{pin}'
        for a, b, _ in self.wires:
            for end in (a, b):
                if self._is_hole(end):
                    taken[end] = 'a wire'
        return taken

    def _is_hole(self, endpoint):
        pid = endpoint.split('.')[0]
        return pid in self.parts and self.parts[pid].kind == 'breadboard'

    # -- wires ------------------------------------------------------------------------
    def connect(self, a, b, color='#d33'):
        if not isinstance(color, str) or len(color) > 20:
            color = '#d33'
        self.resolve(a), self.resolve(b)
        if a == b:
            raise ValueError('A wire needs two different endpoints.')
        if any({a, b} == {w[0], w[1]} for w in self.wires):
            raise ValueError(f'{a} and {b} are already wired together.')
        if len(self.wires) >= MAX_WIRES:
            raise ValueError(f'At most {MAX_WIRES} wires fit the bench.')
        taken = self._occupied()
        for end in (a, b):
            if self._is_hole(end) and end in taken:
                raise ValueError(f'Hole {end} is already occupied by {taken[end]}.')
            if end.startswith('kit.CN'):
                header = end.split('.')[1]
                if cable := next((c for c in self.board.cables if header in c), None):
                    raise ValueError(f'{header} carries the ribbon cable {cable[0]} ↔ {cable[1]}; '
                                     'unplug it before attaching jumper wires.')
                if any(end in w[:2] for w in self.wires):
                    raise ValueError(f'{end} already has a jumper wire.')
        self.wires.append([a, b, color])
        self.touch()

    def disconnect(self, a, b):
        remaining = [w for w in self.wires if {w[0], w[1]} != {a, b}]
        if len(remaining) == len(self.wires):
            raise ValueError(f'No wire joins {a} and {b}.')
        self.wires = remaining
        self.touch()

    def clear(self):
        self.parts.clear()
        self.wires.clear()
        self.mounts.clear()
        self.placement.clear()
        self.findings = []
        self._watch.clear()
        self.machine.damaged_pads.clear()
        self.touch()

    # -- endpoint resolution -------------------------------------------------------------
    def resolve(self, endpoint):
        """Electrical node of an endpoint, or a private node for an unconnected contact."""
        if not isinstance(endpoint, str) or len(endpoint) > 40 or '.' not in endpoint:
            raise ValueError(f'Unknown endpoint {endpoint!r:.40}.')
        owner, rest = endpoint.split('.', 1)
        target = self.board.target
        if owner == 'kit':
            if target != 'als':
                raise ValueError('kit.* endpoints exist only on the ALS kit target.')
            if rest in ('3V3', '5V', 'GND'):
                return rest
            header, _, number = rest.rpartition('.')
            from .board import MAPPING
            if header not in MAPPING['headers'] or not number.isdigit() or not 1 <= int(number) <= 10:
                raise ValueError(f'Unknown kit endpoint {endpoint!r:.40}; use kit.HEADER.PIN or kit.3V3/5V/GND.')
            return self.board._pin(header, int(number) - 1) or f'NC:{endpoint}'
        if owner == 'mbed':
            if target != 'mbed':
                raise ValueError('mbed.* endpoints exist only on the mbed LPC1768 target.')
            if rest not in MBED_PINS:
                raise ValueError(f'The mbed module has no pin {rest!r:.20}.')
            return MBED_PINS[rest]
        if owner == 'mcu':
            if target != 'bare':
                raise ValueError('mcu.* endpoints exist only on the bare LPC1768 target.')
            if rest in ('3V3', 'GND'):
                return rest
            pad = pad_node(rest)
            if pad is None or not pins.exists(*pad):
                raise ValueError(f'The LPC1768 LQFP100 has no pad {rest!r:.20}.')
            return rest
        part = self.parts.get(owner)
        if part is None:
            raise ValueError(f'Unknown endpoint {endpoint!r:.40}.')
        if part.kind == 'breadboard':
            return part.hole_node(rest)
        if rest not in part.pins:
            raise ValueError(f'{part.label} has no pin {rest!r:.20}.')
        return f'{owner}.{rest}'

    def try_resolve(self, endpoint):
        try:
            return self.resolve(endpoint)
        except ValueError:
            return None

    def connections(self):
        """(node, node) pairs joined by wires, mounts, internal part links and the target."""
        pairs = []
        for a, b, _ in self.wires:
            na, nb = self.try_resolve(a), self.try_resolve(b)
            if na and nb:
                pairs.append((na, nb))
        for pid, mount in self.mounts.items():
            for pin, hole in mount.items():
                node = self.try_resolve(hole)
                if node and pid in self.parts:
                    pairs.append((f'{pid}.{pin}', node))
        for part in self.parts.values():
            for a, b in part.internal:
                pairs.append((f'{part.id}.{a}', f'{part.id}.{b}'))
        return pairs

    def nodes(self):
        for part in self.parts.values():
            for pin in (*part.pins, *part.hidden):
                yield f'{part.id}.{pin}'

    # -- electrical solution ---------------------------------------------------------------
    def solve_nets(self, nets, analog):
        """Voltages for `analog` net indices. Returns {net index: (volts, driven)}."""
        board, machine = self.board, self.machine
        index_of = {}
        ground = set()
        for k in analog:
            if 'GND' in nets[k].nodes:
                ground.add(k)
            else:
                index_of[k] = len(index_of)
        node_index = {}
        for k in analog:
            for node in nets[k].nodes:
                node_index[node] = -1 if k in ground else index_of[k]
        key = self._key(nets, analog)
        cached = self._cache.get(key)
        if cached is None:
            elements = self._elements(nets, analog, node_index)
            solution = solve(len(index_of), elements)
            result = {}
            for k in analog:
                if k in ground:
                    result[k] = (0.0, True)
                else:
                    i = index_of[k]
                    result[k] = (solution.v(i), i in solution.driven)
            cached = (result, solution, node_index, elements)
            if len(self._cache) > 512:
                self._cache.clear()
            self._cache[key] = cached
        if cached is not self.solution:
            # Parts sense every change of operating point, including a return
            # to a previously cached one (each PWM or clock edge).
            self.solution = cached
            self._after_solve(nets, analog)
        return cached[0]

    def _key(self, nets, analog):
        machine = self.machine
        pads = []
        for k in analog:
            for node in nets[k].nodes:
                pad = pad_node(node)
                if pad:
                    function = machine.function(*pad)
                    analog_out = machine.dac.voltage() if pins.name(*pad, function) == 'AOUT' else None
                    pads.append((node, machine.pin_output(*pad), machine.pin_pull(*pad), analog_out))
        kit = (self.board.sw2, tuple(sorted(self.board.keys)))
        return (self.board._graph_key, tuple(pads), kit,
                tuple(part.signature() for part in self.parts.values()))

    def _elements(self, nets, analog, node_index):
        machine = self.machine
        elements = []
        for k in analog:
            for node in nets[k].nodes:
                i = node_index[node]
                pad = pad_node(node)
                if pad:
                    function = machine.function(*pad)
                    out = machine.pin_output(*pad)
                    if pins.name(*pad, function) == 'AOUT':
                        elements.append(('V', i, -1, machine.dac.voltage(), 100.0, f'pad:{node}'))
                    elif out is not None:
                        elements.append(('V', i, -1, 3.3 * out, PAD_OHMS, f'pad:{node}'))
                    pull = machine.pin_pull(*pad)
                    if pull == 1:
                        elements.append(('V', i, -1, PULLUP[0], PULLUP[1], f'pull:{node}'))
                    elif pull == 0:
                        elements.append(('R', i, -1, PULLDOWN, f'pull:{node}'))
                elif node == '3V3':
                    elements.append(('V', i, -1, 3.3, 0.05, 'rail:3V3'))
                elif node == '5V':
                    elements.append(('V', i, -1, 5.0, 0.05, 'rail:5V'))
                else:
                    elements.extend(self._kit_load(node, i))
        for part in self.parts.values():
            def idx(pin, part=part):
                return node_index.get(f'{part.id}.{pin}')
            if any(idx(pin) is None for pin in part.pins):
                continue
            for element in part.elements():
                kind, *rest = element
                converted = [kind]
                for value in rest:
                    if isinstance(value, str) and value.startswith('@'):
                        converted.append(idx(value[1:]))
                    else:
                        converted.append(value)
                converted[-1] = f'{part.id}:{converted[-1]}'
                elements.append(tuple(converted))
        return elements

    def _kit_load(self, node, i):
        """Kit-side terminals that a jumper wire can reach (ESD/ALS manual values)."""
        if node.startswith('LED') or node.startswith(('SEG', 'LCD')):
            return [('R', i, -1, 100_000.0, f'kit:{node}')]  # buffered/high-impedance inputs
        if node == 'PWM_LED':
            return [('R', i, -1, 1_000.0, 'kit:PWM_LED-r')]
        if node.startswith('DIG'):
            return [('V', i, -1, 5.0, 10_000.0, f'kit:{node}')]  # R75-R78 to +5 V
        if node.startswith('COL'):
            return [('R', i, -1, 15_000.0, f'kit:{node}')]
        if node == 'SW2':
            elements = [('V', i, -1, 3.3, 10_000.0, 'kit:SW2-pullup')]
            if self.board.sw2:
                elements.append(('R', i, -1, 1.0, 'kit:SW2'))
            return elements
        return []

    def _after_solve(self, nets, analog):
        result, solution, node_index, elements = self.solution
        volts = {}
        for k in analog:
            v = result[k][0]
            for node in nets[k].nodes:
                volts[node] = v
        self.net_voltage = volts
        now = self.machine.time_ns()
        for part in list(self.parts.values()):
            if part.inputs:
                part.sense({pin: volts.get(f'{part.id}.{pin}', 0.0) for pin in part.inputs}, now)

    def voltage(self, node):
        return self.net_voltage.get(node)

    def element_result(self, tag):
        if not self.solution:
            return None
        return self.solution[1].results.get(tag)

    # -- doctor -----------------------------------------------------------------------------
    def evaluate(self):
        """Refresh findings and apply sustained-overstress damage."""
        if self._static_version != self.version:
            self._static = doctor.static_findings(self)
            self._static_version = self.version
        live = doctor.live_findings(self) if self.solution else []
        now = self.machine.time_ns()
        damage = []
        for finding in live:
            if finding.get('severity') != 'damage-risk':
                continue
            first = self._watch.setdefault(finding['key'], now)
            if self.damage_mode == 'realistic' and now - first >= doctor.HOLD_OFF_NS:
                damage.append(finding)
        for key in list(self._watch):
            if not any(f['key'] == key for f in live):
                del self._watch[key]
        for finding in damage:
            doctor.apply_damage(self, finding)
        self.findings = self._static + live + doctor.note_findings(self.machine) + doctor.damage_findings(self)
        return self.findings

    # -- snapshot ------------------------------------------------------------------------------
    def snapshot(self):
        findings = self.evaluate() if self.active or self.machine.notes else \
            doctor.note_findings(self.machine)
        parts = []
        for pid, part in self.parts.items():
            pin_volts = {pin: self._round(self.net_voltage.get(f'{pid}.{pin}')) for pin in part.pins}
            parts.append({'id': pid, 'type': part.kind, 'props': part.props, 'stimuli': part.stimuli,
                          'placement': self.placement.get(pid, {}), 'mount': self.mounts.get(pid, {}),
                          'damaged': part.damaged, 'state': part.state(), 'pins': pin_volts})
        now = self.machine.time_ns()
        traces = {e: [[t, level] for t, level in trace if now - t < 2_000_000_000][-400:]
                  for e, trace in self.probes.items()}
        return {'parts': parts, 'wires': [w[:] for w in self.wires], 'findings': findings,
                'damageMode': self.damage_mode, 'version': self.version,
                'probes': traces, 'now': now}

    @staticmethod
    def _round(value):
        return None if value is None else round(value, 3)

    def endpoint_info(self, endpoint):
        node = self.try_resolve(endpoint)
        if node is None:
            return None
        volts = self.net_voltage.get(node)
        level = self.board.node_level(node)
        pad = pad_node(node)
        info = {'endpoint': endpoint, 'node': node, 'volts': self._round(volts), 'level': level}
        if pad:
            function = self.machine.function(*pad)
            info['function'] = pins.name(*pad, function)
            info['functions'] = [f for f in pins.FUNCTIONS.get(pad, ()) if f]
        return info

    # -- doctor fixes ------------------------------------------------------------------------------
    def apply(self, patch):
        """Apply a Doctor fix: a list of ops. Atomic: a failing op restores the circuit."""
        if not isinstance(patch, list) or not patch or len(patch) > 20:
            raise ValueError('A fix is a non-empty list of operations.')
        saved = self.export()
        damaged = {pid: p.damaged for pid, p in self.parts.items()}
        pads = set(self.machine.damaged_pads)
        names = {}

        def name(endpoint):
            if isinstance(endpoint, str) and endpoint.startswith('$'):
                alias, _, pin = endpoint[1:].partition('.')
                if alias not in names:
                    raise ValueError(f'Unknown part alias {alias!r:.20} in fix.')
                return f'{names[alias]}.{pin}'
            return endpoint
        try:
            for op in patch:
                kind = op.get('op') if isinstance(op, dict) else None
                if kind == 'add-part':
                    anchor = next(iter(self.placement.values()), {}) if self.placement else {}
                    placement = {'x': anchor.get('x', 0) + 20 + 12 * len(names), 'y': anchor.get('y', 0),
                                 'z': anchor.get('z', 0) - 40, 'rot': 0, 'free': True}
                    part = self.add_part(op.get('type'), props=op.get('props'), placement=placement)
                    names[op.get('as', part.id)] = part.id
                elif kind == 'connect':
                    self.connect(name(op.get('a')), name(op.get('b')), op.get('color', '#e8a33a'))
                elif kind == 'disconnect':
                    self.disconnect(name(op.get('a')), name(op.get('b')))
                elif kind == 'replace':
                    self._part(op.get('id')).repair()
                    for key in [k for k in self._watch if op.get('id') in k]:
                        del self._watch[key]
                elif kind == 'repair-pads':
                    self.machine.damaged_pads.clear()
                else:
                    raise ValueError(f'Unknown fix operation {kind!r:.20}.')
        except (ValueError, FirmwareError):
            self.load(saved)
            for pid, reason in damaged.items():
                if pid in self.parts:
                    self.parts[pid].damaged = reason
            self.machine.damaged_pads.update(pads)
            raise
        self.touch()
        self.machine.observe()

    # -- persistence ------------------------------------------------------------------------------
    def export(self):
        return {'target': self.board.target,
                'parts': [{'id': pid, 'type': p.kind, 'props': p.props, 'stimuli': p.stimuli,
                           'placement': self.placement.get(pid, {}), 'mount': self.mounts.get(pid, {})}
                          for pid, p in self.parts.items()],
                'wires': [w[:] for w in self.wires]}

    def load(self, data):
        if not isinstance(data, dict):
            raise ValueError('A circuit project must be a JSON object.')
        parts = data.get('parts', [])
        wires = data.get('wires', [])
        if not isinstance(parts, list) or not isinstance(wires, list):
            raise ValueError('Circuit parts and wires must be lists.')
        self.clear()
        try:
            # Breadboards first so that other parts can mount on them.
            for item in sorted(parts, key=lambda p: p.get('type') != 'breadboard'):
                part = self.add_part(item.get('type'), item.get('id'), item.get('props'),
                                     item.get('placement'))
                for name, value in (item.get('stimuli') or {}).items():
                    part.set_stimulus(name, value)
            for item in parts:
                if item.get('mount'):
                    self.set_mount(item['id'], item['mount'])
            for wire in wires:
                if not isinstance(wire, list) or len(wire) < 2:
                    raise ValueError('Each wire is [endpoint, endpoint, color].')
                self.connect(wire[0], wire[1], wire[2] if len(wire) > 2 else '#d33')
        except (ValueError, FirmwareError):
            self.clear()
            raise
        self.counter = max([self.counter] + [int(m[0]) for p in self.parts
                                              if (m := re.findall(r'\d+$', p))])
