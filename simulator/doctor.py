"""Circuit Doctor: explain what is wrong with a setup, why, and how to fix it.

Findings come from three places:
  * static rules on the wiring (unpowered parts, missing pull-ups, LEDs without
    resistors, inductive loads without flyback diodes),
  * live checks of the solved operating point against data-sheet ratings
    (LPC1768 pad current and voltage, part supply ranges, LED current, resistor power),
  * firmware observations recorded by the peripherals (wrong PINSEL, baud mismatch,
    unpowered peripheral, floating inputs, illegal clock settings).

A rating exceeded beyond its absolute maximum for longer than HOLD_OFF_NS marks the
part as damaged; its model then misbehaves the way a damaged part would.
"""
from __future__ import annotations

from . import pins

HOLD_OFF_NS = 50_000_000
VIH, VIL = 0.7 * 3.3, 0.3 * 3.3  # LPC1768 input thresholds at VDD = 3.3 V (data sheet Table 8)
E12 = (1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2)
PAD_RATED = 0.004
PAD_DAMAGE = 0.025


def e12_values(low=100, high=1_000_000):
    decade = 1
    while decade <= high:
        for m in E12:
            value = round(m * decade)
            if low <= value <= high:
                yield value
        decade *= 10


def ohms(value):
    if value >= 1_000_000:
        return f'{value / 1_000_000:g} MΩ'
    if value >= 1000:
        return f'{value / 1000:g} kΩ'
    return f'{value:g} Ω'


def divider(v_in, v_max=3.3, v_min=None):
    """Best E12 pair (top, bottom, v_out) keeping v_out at or below v_max."""
    v_min = v_max * 0.8 if v_min is None else v_min
    best = None
    for top in e12_values(1_000, 47_000):
        for bottom in e12_values(1_000, 100_000):
            total = top + bottom
            if not 3_000 <= total <= 120_000:
                continue
            v_out = v_in * bottom / total
            if v_out > v_max or v_out < v_min:
                continue
            score = (v_max - v_out) + (0 if top == 10_000 else 0.05) + total / 1e7
            if best is None or score < best[0]:
                best = (score, top, bottom, v_out)
    return best[1:] if best else (10_000, 20_000, v_in * 2 / 3)


def series_resistor(v_source, v_forward, current):
    needed = max(1.0, (v_source - v_forward) / current)
    value = next((v for v in e12_values(10, 1_000_000) if v >= needed), 1_000_000)
    return value, (v_source - v_forward) / value


def finding(key, severity, title, what, why='', consequence='', fixes=(), parts=(), nodes=()):
    return {'key': key, 'severity': severity, 'title': title, 'what': what, 'why': why,
            'consequence': consequence, 'fixes': list(fixes), 'parts': list(parts), 'nodes': list(nodes)}


def rail_endpoint(circuit, rail):
    target = circuit.board.target
    if target == 'als':
        return f'kit.{rail}'
    if target == 'mbed':
        return {'3V3': 'mbed.VOUT', '5V': 'mbed.VU', 'GND': 'mbed.GND'}[rail]
    return f'mcu.{rail}'


# -- static rules --------------------------------------------------------------------
def _net_nodes(circuit, node):
    net = circuit.board.net_of(node)
    return set(net.nodes) if net else {node}


def _supplied(circuit, nodes):
    """True when a net carries a rail or a powered supply output."""
    if nodes & {'3V3', '5V'}:
        return True
    for part in circuit.parts.values():
        for pin in getattr(part, 'source_pins', ()):
            if f'{part.id}.{pin}' in nodes:
                return True
    return False


def static_findings(circuit):
    results = []
    board = circuit.board
    board.groups()
    for a, b, _ in circuit.wires:
        for end in (a, b):
            if (circuit.try_resolve(end) or '').startswith('NC:'):
                results.append(finding(
                    f'nc:{end}', 'info', f'{end} is not connected on the board',
                    f'{end} is an NC contact (or an open jumper route), so this wire joins nothing.',
                    'Only contacts that the board routes to a pin carry a signal.',
                    'Whatever is wired here is effectively unconnected.',
                    [{'label': 'Use a routed contact', 'steps': ['Check the header table for the pin you meant.']}]))
    for part in circuit.parts.values():
        supply = getattr(part, 'supply', None)
        if supply:
            vcc, gnd = supply[0], supply[1]
            vcc_nodes = _net_nodes(circuit, f'{part.id}.{vcc}')
            gnd_nodes = _net_nodes(circuit, f'{part.id}.{gnd}')
            if not _supplied(circuit, vcc_nodes):
                results.append(finding(
                    f'unpowered:{part.id}', 'warning', f'{part.label} has no power',
                    f'Its {vcc} pin is not connected to a supply rail.',
                    'Every active part needs its supply pin on a rail and its ground on GND.',
                    'The part does nothing: it cannot answer the MCU or drive its outputs.',
                    [{'label': f'Connect {vcc} to {"3.3 V" if supply[3] <= 3.6 else "5 V"}',
                      'steps': [f'Wire {part.id}.{vcc} to the {"3V3" if supply[3] <= 3.6 else "5V"} rail.']}],
                    parts=[part.id]))
            if 'GND' not in gnd_nodes:
                results.append(finding(
                    f'ungrounded:{part.id}', 'warning', f'{part.label} ground is not connected',
                    f'Its {gnd} pin is not on the GND net.',
                    'Signals are measured against ground; without a common ground nothing is defined.',
                    'The part is unpowered or its signals float.',
                    [{'label': 'Connect GND', 'steps': [f'Wire {part.id}.{gnd} to GND.']}], parts=[part.id]))
        i2c = getattr(part, 'i2c_pins', None)
        if i2c and not getattr(part, 'has_pullups', False):
            for line in i2c:
                nodes = _net_nodes(circuit, f'{part.id}.{line}')
                if not _pulled_up(circuit, nodes):
                    results.append(finding(
                        f'pullup:{part.id}:{line}', 'warning', f'No pull-up on {line}',
                        f'{part.label} {line} has no resistor to 3.3 V.',
                        'I2C devices and the LPC1768 only pull lines LOW (open drain). '
                        'A resistor must return each line HIGH.',
                        'START never completes, or the bus reads garbage.',
                        [{'label': 'Add 4.7 kΩ pull-up resistors', 'steps': [
                            f'Connect a 4.7 kΩ resistor from {line} to 3.3 V (one per line).'],
                          'apply': [{'op': 'add-part', 'type': 'resistor', 'props': {'ohms': 4700},
                                     'as': 'pull'},
                                    {'op': 'connect', 'a': '$pull.1', 'b': f'{part.id}.{line}'},
                                    {'op': 'connect', 'a': '$pull.2', 'b': rail_endpoint(circuit, '3V3')}]}],
                        parts=[part.id], nodes=[f'{part.id}.{line}']))
        if part.kind in ('led', 'rgb_led'):
            for anode, cathode in part.diodes():
                a_nodes = _net_nodes(circuit, f'{part.id}.{anode}')
                c_nodes = _net_nodes(circuit, f'{part.id}.{cathode}')
                direct = any(n in ('3V3', '5V') or n.startswith('P') and '.' in n for n in a_nodes)
                if direct and 'GND' in c_nodes:
                    vf = part.vf(anode)
                    source = 5.0 if '5V' in a_nodes else 3.3
                    target_i = 0.0035 if source == 3.3 and '3V3' not in a_nodes else 0.01
                    value, current = series_resistor(source, vf, target_i)
                    results.append(finding(
                        f'led-resistor:{part.id}:{anode}', 'warning', f'{part.label} has no series resistor',
                        f'The LED sits directly between {"a GPIO pin" if source == 3.3 and "3V3" not in a_nodes else "the supply"} and GND.',
                        'An LED is a diode: above its forward voltage the current is limited only by '
                        'whatever drives it, so it must have a resistor in series.',
                        'Excess current overheats the LED and the driving pin.',
                        [{'label': f'Add a {ohms(value)} resistor in series',
                          'steps': [f'Put {ohms(value)} between the source and the LED anode '
                                    f'(≈{current * 1000:.1f} mA at Vf {vf:.1f} V).']}],
                        parts=[part.id]))
        inductive = getattr(part, 'inductive', None)
        if inductive and not getattr(part, 'has_flyback', False):
            a_nodes = _net_nodes(circuit, f'{part.id}.{inductive[0]}')
            b_nodes = _net_nodes(circuit, f'{part.id}.{inductive[1]}')
            if not _has_diode_across(circuit, a_nodes, b_nodes):
                results.append(finding(
                    f'flyback:{part.id}', 'warning', f'{part.label} needs a flyback diode',
                    'No diode is connected across the coil.',
                    'When the driver switches off, the coil current must go somewhere: the voltage '
                    'spikes far above the supply until something breaks down.',
                    'The spike can destroy the driving transistor or MCU pin.',
                    [{'label': 'Add a 1N4007 across the coil',
                      'steps': ['Cathode (band) to the positive supply side, anode to the driver side.']}],
                    parts=[part.id]))
    return results


def _pulled_up(circuit, nodes):
    for part in circuit.parts.values():
        if part.kind == 'resistor':
            a, b = _net_nodes(circuit, f'{part.id}.1'), _net_nodes(circuit, f'{part.id}.2')
            if (a == nodes and _supplied(circuit, b)) or (b == nodes and _supplied(circuit, a)):
                return True
        if getattr(part, 'has_pullups', False) and any(f'{part.id}.{p}' in nodes for p in part.pins):
            return True
    target = circuit.board.target
    # ALS kit: on-board pull-ups assumed on the I2C0 pads (see engine._true_open_drain).
    return target == 'als' and bool(nodes & {'P0.27', 'P0.28'})


def _has_diode_across(circuit, a_nodes, b_nodes):
    for part in circuit.parts.values():
        if part.kind == 'diode':
            n1, n2 = _net_nodes(circuit, f'{part.id}.A'), _net_nodes(circuit, f'{part.id}.K')
            if {frozenset(n1), frozenset(n2)} == {frozenset(a_nodes), frozenset(b_nodes)}:
                return True
    return False


# -- live checks -------------------------------------------------------------------------
def live_findings(circuit):
    results = []
    board, machine = circuit.board, circuit.machine
    _, solution, node_index, elements = circuit.solution
    volts = circuit.net_voltage
    for tag, result in solution.results.items():
        if tag.startswith('pad:'):
            node = tag[4:]
            current = result['i']
            if abs(current) <= PAD_RATED * 1.02:
                continue
            severity = 'damage-risk' if abs(current) >= PAD_DAMAGE else 'stress'
            direction = 'sources' if current > 0 else 'sinks'
            led = _led_on_net(circuit, node)
            fixes = []
            if led:
                value, i = series_resistor(3.3, led.vf(), 0.0035)
                fixes.append({'label': f'Add a {ohms(value)} series resistor',
                              'steps': [f'Insert {ohms(value)} between {node} and {led.label} '
                                        f'(≈{i * 1000:.1f} mA, inside the 4 mA rating).']})
            fixes.append({'label': 'Drive the load through a transistor',
                          'steps': ['Use an NPN (2N2222) or logic-level MOSFET (IRLZ44N) as a low-side switch;',
                                    'the pin then supplies only a few mA of base/gate current.']})
            if severity == 'damage-risk':
                fixes.insert(0, {'label': 'Remove the short circuit',
                                 'steps': [f'{node} is driven straight into a supply or another output.']})
            results.append(finding(
                f'pad-current:{node}', severity, f'{node} {direction} {abs(current) * 1000:.1f} mA',
                f'The pin {direction} {abs(current) * 1000:.1f} mA; LPC1768 pins are rated for 4 mA '
                '(the output drops 0.4 V at 4 mA).',
                'Output current is set by the load. Above the rating the pin voltage sags; near the '
                '45–50 mA short-circuit limit the output transistor overheats.',
                'Sustained short-circuit current destroys the pin driver.' if severity == 'damage-risk'
                else 'Logic levels degrade and the chip heats; the pin may fail over time.',
                fixes, nodes=[node]))
    for node, v in volts.items():
        pad = _pad(node)
        if not pad:
            continue
        function = machine.function(*pad)
        limits = pins.pad_class(*pad, function)
        source = _highest_source(circuit, node)
        if v > limits['vabs'] + 0.05:
            results.append(_overvoltage(circuit, node, v, limits, 'damage-risk', source))
        elif v > limits['vmax'] + 0.05:
            results.append(_overvoltage(circuit, node, v, limits, 'stress', source))
        elif v > 3.6 and limits['tolerant5v']:
            results.append(finding(
                f'pad-5v:{node}', 'info', f'{v:.1f} V signal on {node}',
                f'{node} sees {v:.2f} V. This pad is 5 V tolerant while it is a digital input.',
                'LPC1768 digital pads accept up to 5.5 V when the chip is powered, '
                'but not in ADC mode and not while the board is off.',
                'Fine as a digital input. Do not switch this pin to an analog function.',
                [{'label': 'Optional: add a divider', 'steps': ['A divider keeps the signal within 3.3 V '
                                                                'regardless of pin mode.']}], nodes=[node]))
        if v < -0.5:
            results.append(finding(f'pad-negative:{node}', 'damage-risk', f'{node} is driven below ground',
                                   f'{node} sits at {v:.2f} V.', 'The pad clamp diodes conduct below −0.5 V.',
                                   'Injected current can latch up or destroy the pin.',
                                   [{'label': 'Check polarity', 'steps': ['A supply or sensor is reversed.']}],
                                   nodes=[node]))
        direction = machine.gpio[pad[0]].direction & (1 << pad[1])
        if function == 0 and not direction and pad[0] in machine.ports_read and VIL < v < VIH:
            results.append(finding(
                f'indeterminate:{node}', 'warning', f'{node} reads an undefined level',
                f'The input sits at {v:.2f} V, between V_IL {VIL:.2f} V and V_IH {VIH:.2f} V.',
                'Inside that band the input buffer may read either value and draws extra current.',
                'Firmware sees random 0/1 readings.',
                [{'label': 'Fix the logic level', 'steps': ['Use a stronger pull resistor, or check that a divider '
                                                            'produces at least 2.4 V for HIGH.']}],
                nodes=[node]))
    for part in circuit.parts.values():
        if part.damaged:
            continue
        results.extend(part.check(volts))
        supply = getattr(part, 'supply', None)
        if supply:
            vcc, gnd, v_min, v_max, v_abs = supply
            vs = volts.get(f'{part.id}.{vcc}', 0.0) - volts.get(f'{part.id}.{gnd}', 0.0)
            if vs > v_abs + 0.05:
                results.append(_overvolted_part(circuit, part, vs, supply, 'damage-risk'))
            elif vs > v_max + 0.05:
                results.append(_overvolted_part(circuit, part, vs, supply, 'stress'))
            elif 0.3 < vs < v_min - 0.05:
                results.append(finding(
                    f'undervolt:{part.id}', 'warning', f'{part.label} is under-powered',
                    f'Its supply is {vs:.2f} V; it needs {v_min:g}–{v_max:g} V.',
                    'Below the minimum supply the internal circuits do not start reliably.',
                    'The part may not respond, or its readings are wrong.',
                    [{'label': f'Power it from {"5 V" if v_min > 3.6 else "3.3 V"}',
                      'steps': ['Move its supply wire to the correct rail.']}], parts=[part.id]))
        for pin, limit in getattr(part, 'pin_limits', {}).items():
            gnd = supply[1] if supply else None
            v = volts.get(f'{part.id}.{pin}', 0.0) - (volts.get(f'{part.id}.{gnd}', 0.0) if gnd else 0)
            if v > limit + 0.05:
                top, bottom, v_out = divider(v, min(limit, 3.3))
                results.append(finding(
                    f'pin-over:{part.id}:{pin}', 'damage-risk', f'{part.label} {pin} sees {v:.1f} V',
                    f'{pin} is at {v:.2f} V; its absolute maximum is {limit:.1f} V.',
                    'Input protection diodes conduct above the supply; the injected current heats the chip.',
                    'The part is damaged if this continues.',
                    [{'label': 'Use a level shifter or divider',
                      'steps': [f'Divider: {ohms(top)} on top, {ohms(bottom)} to GND gives {v_out:.2f} V; '
                                'for bidirectional lines use a BSS138 level shifter.']}],
                    parts=[part.id]))
    for tag, result in solution.results.items():
        if tag.startswith('rail:'):
            rail = tag[5:]
            limit = circuit_rail_limit(circuit, rail)
            if result['i'] > max(limit, 2.0):
                results.append(finding(
                    f'rail-short:{rail}', 'damage-risk', f'{rail} rail is short-circuited',
                    f'About {result["i"]:.1f} A would flow from the {rail} rail.',
                    'A supply wired straight to GND (or to another rail) has nothing to limit the current.',
                    'The regulator shuts down or overheats; wires and tracks can burn.',
                    [{'label': 'Find the short', 'steps': [f'Look for a wire joining {rail} to GND or to the other rail.']}],
                    nodes=[rail]))
            elif result['i'] > limit:
                results.append(finding(
                    f'rail-load:{rail}', 'warning', f'{rail} rail overloaded',
                    f'Parts draw {result["i"] * 1000:.0f} mA from {rail}; about {limit * 1000:.0f} mA is available.',
                    'The board regulator or USB supply has a limited current.',
                    'The rail sags and the MCU may brown out.',
                    [{'label': 'Use an external supply', 'steps': ['Power motors and servos from a separate supply '
                                                                   'sharing GND with the board.']}], nodes=[rail]))
    return results


def circuit_rail_limit(circuit, rail):
    from .circuit import RAIL_LIMITS
    return RAIL_LIMITS.get(circuit.board.target, {}).get(rail, 0.5)


def _pad(node):
    if node.startswith('P') and '.' in node and node[1:2].isdigit():
        port, pin = node[1:].split('.')
        return int(port), int(pin)
    return None


def _led_on_net(circuit, node):
    nodes = _net_nodes(circuit, node)
    for part in circuit.parts.values():
        if part.kind in ('led', 'rgb_led') and any(f'{part.id}.{p}' in nodes for p in part.pins):
            return part
    return None


def _highest_source(circuit, node):
    nodes = _net_nodes(circuit, node)
    for part in circuit.parts.values():
        if any(f'{part.id}.{p}' in nodes for p in part.pins):
            return part
    return None


def _overvoltage(circuit, node, v, limits, severity, source):
    analog = limits['kind'] == 'analog'
    top, bottom, v_out = divider(v, 3.3 if analog else 3.3, 2.5 if not analog else None)
    who = source.label if source else 'The source'
    fixes = [{'label': f'Add a voltage divider ({ohms(top)} / {ohms(bottom)})',
              'steps': [f'{who} output → {ohms(top)} → {node}; {node} → {ohms(bottom)} → GND.',
                        f'{v:.2f} V × {bottom}/({top}+{bottom}) = {v * bottom / (top + bottom):.2f} V.'],
              'apply': _divider_patch(circuit, node, source, top, bottom)}]
    if not analog:
        fixes.append({'label': 'Use a level shifter', 'steps': ['A BSS138 or 74LVC245 translates 5 V logic to 3.3 V.']})
    if analog:
        what = (f'{node} is in ADC mode and sees {v:.2f} V. Analog-mode pads are not 5 V tolerant: '
                f'the input range is 0–3.3 V (absolute maximum {limits["vabs"]} V).')
        consequence = ('The ADC channel is destroyed and nearby channels read wrong values.'
                       if severity == 'damage-risk' else 'Readings clip at 4095 above 3.3 V.')
    else:
        what = f'{node} sees {v:.2f} V; the absolute maximum for this pad is {limits["vabs"]} V.'
        consequence = 'The pad input protection fails and the pin stops working.'
    return finding(f'pad-over:{node}', severity, f'{v:.1f} V on {node} ({"analog" if analog else limits["kind"]})',
                   what, 'Voltages above a pin\'s rating forward-bias its protection diodes and '
                   'push current into the chip.', consequence, fixes,
                   parts=[source.id] if source else [], nodes=[node])


def _divider_patch(circuit, node, source, top, bottom):
    """Rewire a direct source→pin wire through a divider, when such a wire exists."""
    if source is None:
        return None
    for a, b, _ in circuit.wires:
        for src, dst in ((a, b), (b, a)):
            owner = src.split('.')[0]
            if owner == source.id and circuit.try_resolve(dst) == node:
                return [{'op': 'disconnect', 'a': a, 'b': b},
                        {'op': 'add-part', 'type': 'resistor', 'props': {'ohms': top}, 'as': 'top'},
                        {'op': 'add-part', 'type': 'resistor', 'props': {'ohms': bottom}, 'as': 'bottom'},
                        {'op': 'connect', 'a': src, 'b': '$top.1'},
                        {'op': 'connect', 'a': '$top.2', 'b': dst},
                        {'op': 'connect', 'a': '$top.2', 'b': '$bottom.1'},
                        {'op': 'connect', 'a': '$bottom.2', 'b': rail_endpoint(circuit, 'GND')}]
    return None


def _overvolted_part(circuit, part, vs, supply, severity):
    vcc, _, v_min, v_max, v_abs = supply
    rail = '3V3' if v_max <= 3.6 else '5V'
    fix = {'label': f'Power it from {"3.3 V" if rail == "3V3" else "5 V"}',
           'steps': [f'Move {part.id}.{vcc} to the {rail} rail.']}
    patch = _move_supply_patch(circuit, part, vcc, rail)
    if patch:
        fix['apply'] = patch
    return finding(
        f'overvolt:{part.id}', severity, f'{part.label} supply is {vs:.1f} V',
        f'{part.label} runs from {v_min:g}–{v_max:g} V (absolute maximum {v_abs:g} V); it is getting {vs:.2f} V.',
        'Supply voltage above the absolute maximum breaks down the chip\'s internal transistors.',
        'The part is permanently damaged and stops responding.' if severity == 'damage-risk'
        else 'Outside its recommended range the part is unreliable and runs hot.',
        [fix], parts=[part.id])


def _move_supply_patch(circuit, part, vcc, rail):
    vcc_nodes = _net_nodes(circuit, f'{part.id}.{vcc}')
    for a, b, _ in circuit.wires:
        for keep, move in ((a, b), (b, a)):
            if circuit.try_resolve(move) in ('5V', '3V3') and circuit.try_resolve(move) != rail \
                    and circuit.try_resolve(keep) in vcc_nodes:
                return [{'op': 'disconnect', 'a': a, 'b': b},
                        {'op': 'connect', 'a': keep, 'b': rail_endpoint(circuit, rail)}]
    return None


# -- notes and damage ------------------------------------------------------------------------
def note_findings(machine):
    results = []
    for key, message in sorted(machine.notes.items()):
        source = key.split(':')[0]
        results.append(finding(f'note:{key}', 'info' if source == 'floating-read' else 'warning',
                               _note_title(key), message,
                               fixes=[{'label': 'Fix the firmware', 'steps': [message]}]))
    return results


def _note_title(key):
    source, _, kind = key.partition(':')
    titles = {'pin': 'pin not configured', 'baud': 'baud rate mismatch', 'power': 'peripheral not powered',
              'pullups': 'I2C bus has no pull-ups', 'pins': 'pins not configured', 'conflict': 'I2C address conflict',
              'contention': 'SPI MISO contention', 'cpsr': 'invalid SSP clock prescaler', 'clock': 'no bit clock',
              'feed': 'PLL feed sequence missing', 'fcco': 'PLL out of range', 'cclk': 'CPU clock too high',
              'outputs': 'outputs not modeled', 'slave': 'slave mode not modeled'}
    if source == 'floating-read':
        return 'Floating input read'
    return f'{source}: {titles.get(kind, kind)}'


def apply_damage(circuit, item):
    reason = item['title']
    for pid in item['parts']:
        part = circuit.parts.get(pid)
        if part and not part.damaged and (item['key'].startswith(('overvolt:', 'pin-over:'))
                                           or part.kind in ('led', 'rgb_led', 'resistor')):
            part.damage(f'{reason}: {item["what"]}')
    for node in item['nodes']:
        pad = _pad(node)
        if pad and item['key'].startswith(('pad-current:', 'pad-over:', 'pad-negative:')):
            circuit.machine.damaged_pads.add(pad)
    circuit.touch()
    circuit.machine.observe()


def damage_findings(circuit):
    results = []
    for part in circuit.parts.values():
        if part.damaged:
            results.append(finding(
                f'damaged:{part.id}', 'damaged', f'{part.label} is damaged', part.damaged,
                'The overstress lasted long enough to destroy it, as it would on a real bench.',
                part.damaged_behavior, [{'label': 'Replace the part', 'steps': ['Fix the cause first, then replace it.'],
                                         'apply': [{'op': 'replace', 'id': part.id}]}], parts=[part.id]))
    for pad in sorted(circuit.machine.damaged_pads):
        node = f'P{pad[0]}.{pad[1]}'
        results.append(finding(
            f'damaged-pad:{node}', 'damaged', f'MCU pin {node} is damaged',
            f'{node} was overstressed; it no longer drives or reads reliably.',
            'Exceeding a pin\'s current or voltage rating destroys its driver or input buffer.',
            'The pin is dead: outputs float and inputs read LOW.',
            [{'label': 'Replace the LPC1768', 'steps': ['Fix the wiring first.'],
              'apply': [{'op': 'repair-pads'}]}], nodes=[node]))
    return results
