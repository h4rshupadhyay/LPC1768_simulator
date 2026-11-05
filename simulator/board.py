"""Ten-conductor ribbons and single-contact patch wires, derived from the ALS manual.

The board also hosts the external circuit (simulator/circuit.py). Nets that
contain a part pin or a supply rail are solved for voltages; all other nets keep
the ideal digital resolution below, unchanged.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json
import re

MAPPING = json.loads((Path(__file__).resolve().parents[1] / 'board/mapping.json').read_text(encoding='utf-8'))
# One declared FRC header pin, numbered 1-10 as printed beside the header.
# No other board connector is modeled, so no other endpoint exists.
ENDPOINT = re.compile(r'([A-Z][A-Z0-9]*)\.(10|[1-9])')
# One wire per contact already limits the 100 declared contacts to 50 wires;
# the explicit bound keeps a request from growing the graph past that.
MAX_WIRES = 50


@dataclass(slots=True)
class _Net:
    nodes: list[str]
    pins: list[tuple[int, int]]
    ground: bool
    switch: bool
    columns: bool
    digits: bool
    levels: list[tuple[str, bool]]
    ports: list[tuple[int, int]]


TARGETS = ('als', 'mbed', 'bare')
VIH, VIL = 0.7 * 3.3, 0.3 * 3.3


class Board:
    def __init__(self, machine, target='als'):
        if target not in TARGETS:
            raise ValueError(f'Target must be one of {", ".join(TARGETS)}.')
        self.machine = machine
        self.target = target
        self.cables = []
        # Single-conductor patch wires between individual header pins.
        self.wires = []
        self.jumpers = {k: 'open' for k in MAPPING['jumpers']}
        self.sw2 = False
        self.sw2_pin = 7
        self.keys = set()
        self.pots = {4: 1.65, 5: 1.65}
        self._graph_key = None
        self._groups = []
        self._nets = []
        self._diodes = []
        self._connection_warnings = []
        self.warnings = []
        self.conflicts = set()
        self._contacts_key = None
        self._port_masks = [0] * 5
        self._port_values = [0] * 5
        self._floating = set()
        self._floating_masks = [0] * 5
        self._node_net = {}
        self._analog = []
        self._levels = {}
        self._volts = {}
        from .circuit import Circuit
        self.circuit = Circuit(self)

    def connect(self, a, b):
        if not isinstance(a,str) or not isinstance(b,str) or a not in MAPPING['headers'] or b not in MAPPING['headers'] or a == b:
            raise ValueError('Select two different supported FRC headers.')
        if any(a in c or b in c for c in self.cables):
            raise ValueError('Each header can carry only one ribbon cable. Disconnect it first.')
        for header in (a, b):
            if pins := self.wired_pins(header):
                raise ValueError(f'{header} has patch wires on pin{"s" if len(pins) > 1 else ""} '
                                 f'{", ".join(map(str, pins))}. Remove them before attaching a ribbon cable.')
        self.cables.append([a, b])
        self.machine.observe()

    def disconnect(self, header):
        self.cables = [c for c in self.cables if header not in c]
        self.machine.observe()

    @staticmethod
    def endpoint(name):
        """Return (header, zero-based index) for a declared pin such as 'CNA.1'."""
        match = ENDPOINT.fullmatch(name) if isinstance(name, str) else None
        if not match or match[1] not in MAPPING['headers']:
            raise ValueError(f'Unknown patch-wire end {name!r:.32}. Ends must be declared header '
                             'pins written HEADER.PIN, from CNA.1 to CNAD.10.')
        return match[1], int(match[2]) - 1

    def wired_pins(self, header):
        """One-based contacts of `header` that carry a patch wire."""
        return sorted(self.endpoint(end)[1] + 1 for w in self.wires for end in w
                      if self.endpoint(end)[0] == header)

    def connect_wire(self, a, b):
        # Validate everything before mutating, so a rejected wire leaves no trace.
        ha, hb = self.endpoint(a)[0], self.endpoint(b)[0]
        if a == b:
            raise ValueError(f'A patch wire needs two different header pins; both ends are {a}.')
        if any({a, b} == set(w) for w in self.wires):
            raise ValueError(f'{a} and {b} are already patched together.')
        for end in (a, b):
            if used := next((w for w in self.wires if end in w), None):
                raise ValueError(f'{end} already has a patch wire ({used[0]} ↔ {used[1]}). '
                                 'Each pin accepts one wire.')
        for header in (ha, hb):
            # A ribbon socket covers all ten pins of its header.
            if cable := next((c for c in self.cables if header in c), None):
                raise ValueError(f'{header} carries the ribbon cable {cable[0]} ↔ {cable[1]}; '
                                 'its pins cannot take patch wires until it is disconnected.')
        if len(self.wires) >= MAX_WIRES:
            raise ValueError(f'At most {MAX_WIRES} patch wires fit the declared headers.')
        self.wires.append([a, b])
        self.machine.observe()

    def disconnect_wire(self, a, b):
        self.endpoint(a), self.endpoint(b)
        remaining = [w for w in self.wires if set(w) != {a, b}]
        if len(remaining) == len(self.wires):
            raise ValueError(f'No patch wire joins {a} and {b}.')
        self.wires = remaining
        self.machine.observe()

    def disconnect_all(self, kind='all'):
        """Unplug patch wires, ribbon cables or both. Jumpers are settings, not wiring."""
        if kind not in ('all', 'wires', 'cables'):
            raise ValueError("Disconnect-all kind must be 'all', 'wires' or 'cables'.")
        if kind != 'cables':
            self.wires = []
        if kind != 'wires':
            self.cables = []
        self.machine.observe()

    def set_jumper(self, name, value):
        if not isinstance(name,str) or name not in MAPPING['jumpers'] or value not in MAPPING['jumpers'][name]['states']:
            raise ValueError('Unknown jumper or invalid shunt position.')
        self.jumpers[name] = value
        self.machine.observe()

    def _pin(self, header, pin):
        if header == 'CNB1' and pin in (6, 8):
            return 'SW2' if pin == self.sw2_pin - 1 else None
        node = MAPPING['headers'][header]['pins'][pin]
        if node == 'JP4_B':
            return 'P2.13' if self.jumpers['JP4'] == '1-2' else None
        if node == 'JP4_C':
            return 'P2.13' if self.jumpers['JP4'] == '2-3' else None
        if node == 'JP5_DATA':
            return 'P0.26' if self.jumpers['JP5'] == 'closed' else None
        return node

    def groups(self):
        key = (tuple(map(tuple, self.cables)), tuple(map(tuple, self.wires)),
               tuple(self.jumpers.values()), tuple(sorted(self.keys)), self.sw2_pin,
               self.target, self.circuit.version)
        if key == self._graph_key:
            return self._groups
        parents = {}
        def find(n):
            parents.setdefault(n, n)
            if parents[n] != n:
                parents[n] = find(parents[n])
            return parents[n]
        def union(a, b):
            if a is not None and b is not None:
                parents[find(a)] = find(b)
        for a, b in self.cables:
            for i in range(10):
                union(self._pin(a, i), self._pin(b, i))
        for a, b in self.wires:
            # Same pin resolution as ribbons: jumpers, SW2 profile and NC
            # (None) apply. A wire to an NC pin joins nothing.
            union(self._pin(*self.endpoint(a)), self._pin(*self.endpoint(b)))
        if self.target == 'mbed':
            # The module's LED1-LED4 hang off P1.18/P1.20/P1.21/P1.23 permanently.
            from .circuit import MBED_LEDS
            for led, pad in MBED_LEDS.items():
                union(led, pad)
        if self.circuit.active:
            for node in self.circuit.nodes():
                find(node)
            for a, b in self.circuit.connections():
                union(a, b)
        for k in self.keys:
            # ESD schematic PDF p42: D6-D9 isolate the four ROW connector
            # terminals from the switch buses. They are row diodes, not
            # individual key diodes; rectangle ghosting remains possible.
            union(f'MATRIX_ROW{k//4}', f'COL{k%4}')
        groups = {}
        for n in list(parents):
            groups.setdefault(find(n), []).append(n)
        self._groups = list(groups.values())
        # Connectivity changes far less often than GPIO values. Decode the
        # fixed net membership once, without caching dynamic levels, pin mux,
        # direction, pulls, switch state or PWM phase.
        self._nets = []
        self._port_masks = [0] * 5
        node_net = {}
        for index, nodes in enumerate(self._groups):
            pins, level_nodes, port_masks = [], [], {}
            for node in nodes:
                node_net[node] = index
                if node.startswith('P') and '.' in node:
                    port, pin = map(int, node[1:].split('.'))
                    pins.append((port, pin))
                    port_masks[port] = port_masks.get(port, 0) | (1 << pin)
                    self._port_masks[port] |= 1 << pin
                output_load = node.startswith(('LED', 'SEG', 'DIG', 'LCD')) or node == 'PWM_LED'
                level_nodes.append((node, not output_load or node.startswith('DIG')))
            self._nets.append(_Net(nodes, pins, 'GND' in nodes, 'SW2' in nodes,
                                   any(n.startswith('COL') for n in nodes),
                                   any(n.startswith('DIG') for n in nodes), level_nodes, list(port_masks.items())))
        self._node_net = node_net
        part_ids = set(self.circuit.parts)
        self._analog = [index for index, net in enumerate(self._nets)
                        if any(n in ('3V3', '5V') or n.split('.')[0] in part_ids for n in net.nodes)]
        self._diodes = [(node_net[f'ROW{r}'], node_net[f'MATRIX_ROW{r}']) for r in range(4)
                        if f'ROW{r}' in node_net and f'MATRIX_ROW{r}' in node_net]
        self._connection_warnings = [f'{a} ↔ {b}: two {MAPPING["headers"][a]["kind"]} headers; check pin compatibility.'
                                     for a, b in self.cables
                                     if MAPPING['headers'][a]['kind'] == MAPPING['headers'][b]['kind']]
        # A routed contact patched to an NC contact (or an open jumper route) loses
        # its signal. NC-to-NC wires, as in a ribbon-equivalent harness, are harmless.
        for a, b in self.wires:
            ends = [end for end in (a, b) if self._pin(*self.endpoint(end)) is None]
            if len(ends) == 1:
                self._connection_warnings.append(
                    f'{ends[0]}: not connected on the board; the wire {a} ↔ {b} carries nothing.')
        self._graph_key = key
        return self._groups

    def signals(self):
        levels = {}
        self.groups()
        solved = {}
        if self._analog:
            # Parts react to the operating point (clock edges, triggers); re-solve
            # until their outputs settle.
            for _ in range(6):
                before = tuple(part.signature() for part in self.circuit.parts.values())
                solved = self.circuit.solve_nets(self._nets, self._analog)
                if before == tuple(part.signature() for part in self.circuit.parts.values()):
                    break
        warnings = list(self._connection_warnings)
        conflicts = set()
        floating = set()
        self._port_values = [0] * 5
        drives = []
        for net in self._nets:
            strong = [0] if net.ground else []
            if net.switch and self.sw2:
                strong.append(0)
            for port, pin in net.pins:
                out = self.machine.pin_output(port, pin)
                if out is not None:
                    strong.append(out)
            drives.append(strong)
        # A driven HIGH conducts from ROW toward its matrix bus. A LOW on
        # an unselected row cannot sink a different row through this diode.
        # Weak internal MCU pulls do not overcome the external 15k pulldowns.
        # With no pressed keys there are no matrix buses in the graph. Avoid
        # scanning every net for diode paths on each unrelated GPIO access.
        high_buses = {bus for row, bus in self._diodes if drives[row] and min(drives[row]) == 1}
        for bus in high_buses:
            drives[bus].append(1)
        # D6-D9 also conduct current from a weakly pulled-up row input
        # toward a LOW matrix bus. This is the reverse scan used by the
        # course calculator. A driven LOW row still cannot sink the bus.
        # Resolve the ideal digital circuit; diode voltage and pull-current
        # margins require physical measurements rather than this model.
        low_rows = {row for row, bus in self._diodes
                    if (min(drives[bus]) == 0 if drives[bus] else self._nets[bus].columns)}
        for row in low_rows:
            drives[row].append(0)
        floating_masks = [0] * 5
        volts = {}
        for index, (net, strong) in enumerate(zip(self._nets, drives)):
            if index in solved:
                v, driven = solved[index]
                level = int(v >= 1.65) if driven else 0
                if not driven:
                    floating.update(net.nodes)
                    for port, mask in net.ports:
                        floating_masks[port] |= mask
                elif level:
                    for port, mask in net.ports:
                        self._port_values[port] |= mask
                for n in net.nodes:
                    levels[n] = level
                    volts[n] = v
                continue
            if 0 in strong and 1 in strong:
                warnings.append('Conflicting driven levels on ' + ', '.join(net.nodes) + '; resolving LOW.')
                conflicts.update(net.nodes)
            if strong:
                level = min(strong)
            elif net.columns:
                level = 0 # documented external column pulldowns
            elif net.digits or net.switch:
                # R75-R78, 10k to +5V, on U7 A-D (ESD schematic PDF p31).
                # Undriven selector inputs select 1111, disabling all digits.
                level = 1
            else:
                pulls = [self.machine.pin_pull(p, n) for p, n in net.pins]
                level = 0 if 0 in pulls else 1 if 1 in pulls else 0
                if 0 not in pulls and 1 not in pulls:
                    floating.update(net.nodes)
                    for port, mask in net.ports:
                        floating_masks[port] |= mask
            if level:
                for port, mask in net.ports:
                    self._port_values[port] |= mask
            for n, weak_allowed in net.levels:
                # Weak MCU input pulls are observable by firmware, but cannot
                # drive a disconnected/multiplexed output peripheral.
                levels[n] = level if strong or weak_allowed else 0
        self.warnings = warnings
        self.conflicts = conflicts
        self._floating = floating
        self._floating_masks = floating_masks
        self._levels = levels
        self._volts = volts
        return levels

    # -- queries used by peripherals, parts and the Doctor ---------------------------
    def net_of(self, node):
        self.groups()
        index = self._node_net.get(node)
        return self._nets[index] if index is not None else None

    def same_net(self, a, b):
        self.groups()
        index = self._node_net.get(a)
        return index is not None and index == self._node_net.get(b)

    def parts_on(self, node):
        net = self.net_of(node)
        if net is None:
            return []
        found = []
        for member in net.nodes:
            owner, _, pin = member.partition('.')
            part = self.circuit.parts.get(owner)
            if part is not None and pin:
                found.append((part, pin))
        return found

    def node_level(self, node):
        self.signals()
        if node in self._levels:
            return None if node in self._floating else self._levels[node]
        pad = self._pad(node)
        if pad:
            out = self.machine.pin_output(*pad)
            return out if out is not None else self.machine.pin_pull(*pad)
        return None

    def node_voltage(self, node):
        self.signals()
        if node in self._volts:
            return self._volts[node]
        level = self.node_level(node)
        return None if level is None else 3.3 * level

    def released_level(self, node):
        """Does a released open-drain line on `node` rise to a valid HIGH?"""
        self.signals()
        if node in self._volts:
            return node not in self._floating and self._volts[node] >= VIH
        net = self.net_of(node)
        pads = [self._pad(n) for n in (net.nodes if net else [node])]
        pulls = [self.machine.pin_pull(*p) for p in pads if p]
        kit = net is not None and (net.switch or net.digits)
        return kit or (1 in pulls and 0 not in pulls)

    def pad_voltage(self, port, pin):
        return self.node_voltage(f'P{port}.{pin}')

    def floating_mask(self, port):
        return self._floating_masks[port]

    @staticmethod
    def _pad(node):
        if node.startswith('P') and '.' in node and node[1:2].isdigit():
            port, pin = node[1:].split('.')
            return int(port), int(pin)
        return None

    def circuit_snapshot(self):
        return self.circuit.snapshot()

    def sampled_gpio(self, port):
        """Resolved external pads as bit masks, using fresh dynamic signals."""
        self.signals()
        return self._port_masks[port], self._port_values[port]

    def wiring_snapshot(self, levels):
        """Patch wires plus every declared contact's resolved node and level.

        `levels` is this instant's signals(). A level is None for NC contacts,
        open jumper routes, unconnected peripheral terminals and MCU pads that
        neither drive nor pull; the UI must not present those as LOW.
        """
        # Contact resolution changes only with jumpers and the SW2 profile.
        key = (tuple(self.jumpers.values()), self.sw2_pin)
        if self._contacts_key != key:
            self._contacts = [(header, node, tuple(map(int, node[1:].split('.')))
                               if node and node.startswith('P') and '.' in node else None)
                              for header in MAPPING['headers']
                              for node in (self._pin(header, i) for i in range(10))]
            self._contacts_key = key
        pins = {header: [] for header in MAPPING['headers']}
        for header, node, mcu in self._contacts:
            if node is None or node in self._floating:
                level = None
            elif node in levels:
                level = levels[node]
            elif node == 'GND':
                level = 0
            elif node == 'SW2':
                level = int(not self.sw2)
            elif node.startswith('COL'):
                level = 0
            elif node.startswith('DIG'):
                level = 1
            elif mcu:
                out = self.machine.pin_output(*mcu)
                level = out if out is not None else self.machine.pin_pull(*mcu)
            else:
                level = None
            # Every GND contact shares one net; flag only the signal side.
            item = {'node': node, 'level': level,
                    'conflict': node != 'GND' and node in self.conflicts}
            note = MAPPING['headers'][header].get('pinNotes', {}).get(str(len(pins[header]) + 1))
            if note:
                item['note'] = note
            pins[header].append(item)
        return {'wires': [w[:] for w in self.wires], 'headerPins': pins}

    def inputs(self, port):
        levels = self.signals()
        value = 0
        for pin in range(32):
            node = f'P{port}.{pin}'
            default = self.machine.pin_pull(port, pin)
            bit = levels.get(node, default if default is not None else 0)
            value |= int(bool(bit)) << pin
        return value

    def has_signal_connection(self, prefix):
        return any(any(n.startswith(prefix) for n in group) and any(n.startswith('P') and '.' in n for n in group)
                   for group in self.groups())
