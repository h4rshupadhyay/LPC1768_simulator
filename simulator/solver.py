"""DC operating point of a small circuit by nodal analysis.

Sources are Thevenin equivalents (stamped as Norton conductances and currents),
so the system is a plain conductance matrix. Diodes, LEDs, transistors and
switches are piecewise-linear; their conduction states are iterated until they
are self-consistent. Node -1 is ground. All quantities are SI units.

The model is deliberately simple: no capacitance, no temperature, no reverse
breakdown except explicit Zener elements. It answers the questions the Circuit
Doctor asks: which nodes sit at which voltage, and which currents flow.
"""
from __future__ import annotations

from dataclasses import dataclass, field

GMIN = 1e-9
MAX_ITERATIONS = 40


@dataclass
class Solution:
    voltages: list[float]
    results: dict = field(default_factory=dict)  # element tag -> {'i': A, 'p': W, 'state': str}
    driven: set = field(default_factory=set)      # nodes with a conductive path to a source or ground
    converged: bool = True

    def v(self, node):
        return 0.0 if node < 0 else self.voltages[node]


def _solve_linear(g, i):
    n = len(i)
    a = [row[:] + [i[k]] for k, row in enumerate(g)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-18:
            continue
        a[col], a[pivot] = a[pivot], a[col]
        p = a[col][col]
        row = a[col]
        for r in range(col + 1, n):
            factor = a[r][col] / p
            if factor:
                target = a[r]
                for c in range(col, n + 1):
                    target[c] -= factor * row[c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        p = a[r][r]
        if abs(p) < 1e-18:
            x[r] = 0.0
            continue
        x[r] = (a[r][n] - sum(a[r][c] * x[c] for c in range(r + 1, n))) / p
    return x


def solve(n, elements):
    """`elements` are tuples whose first item is the element kind; see module docs."""
    states = {}
    for index, e in enumerate(elements):
        kind = e[0]
        if kind in ('D', 'Z'):
            states[index] = 'off'
        elif kind in ('NPN', 'PNP', 'NMOS', 'PMOS'):
            states[index] = 'off'
    voltages = [0.0] * n
    converged = False
    for _ in range(MAX_ITERATIONS):
        g = [[0.0] * n for _ in range(n)]
        i = [0.0] * n
        for k in range(n):
            g[k][k] += GMIN

        def conductance(a, b, value):
            if a >= 0:
                g[a][a] += value
            if b >= 0:
                g[b][b] += value
            if a >= 0 and b >= 0:
                g[a][b] -= value
                g[b][a] -= value

        def inject(node, amps):
            if node >= 0:
                i[node] += amps

        def thevenin(a, ref, volts, ohms):
            value = 1 / max(ohms, 1e-6)
            conductance(a, ref, value)
            inject(a, volts * value)
            inject(ref, -volts * value)

        for index, e in enumerate(elements):
            kind = e[0]
            if kind == 'R':
                conductance(e[1], e[2], 1 / max(e[3], 1e-6))
            elif kind == 'V':
                thevenin(e[1], e[2], e[3], e[4])
            elif kind == 'I':
                inject(e[1], -e[3])
                inject(e[2], e[3])
            elif kind == 'SW':
                if e[3]:
                    conductance(e[1], e[2], 1 / max(e[4], 1e-6))
            elif kind in ('D', 'Z'):
                state = states[index]
                if state == 'on':
                    thevenin(e[1], e[2], e[3], e[4])
                elif state == 'zener':
                    thevenin(e[2], e[1], e[5], e[4])
            elif kind in ('NPN', 'PNP'):
                _, b, c, emitter, beta = e[:5]
                state = states[index]
                sign = 1 if kind == 'NPN' else -1
                if state != 'off':
                    # Base-emitter junction: 0.7 V behind 100 ohms.
                    if sign > 0:
                        thevenin(b, emitter, 0.7, 100)
                    else:
                        thevenin(emitter, b, 0.7, 100)
                if state == 'sat':
                    if sign > 0:
                        thevenin(c, emitter, 0.2, 2)
                    else:
                        thevenin(emitter, c, 0.2, 2)
                elif state == 'active':
                    ib = states.get(('ib', index), 0.0)
                    if sign > 0:
                        inject(c, -beta * ib)
                        inject(emitter, beta * ib)
                    else:
                        inject(emitter, -beta * ib)
                        inject(c, beta * ib)
            elif kind in ('NMOS', 'PMOS'):
                if states[index] == 'on':
                    conductance(e[2], e[3], 1 / max(e[5], 1e-6))
        new = _solve_linear(g, i)
        voltages = new
        changed = False

        def v(node):
            return 0.0 if node < 0 else voltages[node]

        for index, e in enumerate(elements):
            kind = e[0]
            state = states.get(index)
            if kind in ('D', 'Z'):
                vd = v(e[1]) - v(e[2])
                if state == 'on':
                    current = (vd - e[3]) / e[4]
                    nxt = 'on' if current > -1e-12 else 'off'
                elif state == 'zener':
                    current = (-vd - e[5]) / e[4]
                    nxt = 'zener' if current > -1e-12 else 'off'
                else:
                    nxt = 'on' if vd > e[3] + 1e-9 else 'zener' if kind == 'Z' and -vd > e[5] + 1e-9 else 'off'
                if nxt != state:
                    states[index] = nxt
                    changed = True
            elif kind in ('NPN', 'PNP'):
                _, b, c, emitter, beta = e[:5]
                sign = 1 if kind == 'NPN' else -1
                vbe = sign * (v(b) - v(emitter))
                ib = max(0.0, (vbe - 0.7) / 100) if state != 'off' else 0.0
                if state == 'off':
                    nxt = 'sat' if vbe > 0.7 + 1e-9 else 'off'
                elif ib <= 1e-12:
                    nxt = 'off'
                else:
                    vce = sign * (v(c) - v(emitter))
                    if state == 'sat':
                        ic = (vce - 0.2) / 2
                        nxt = 'active' if ic > beta * ib * 1.0001 else 'sat'
                    else:
                        nxt = 'sat' if vce < 0.2 else 'active'
                    old_ib = states.get(('ib', index), 0.0)
                    if abs(old_ib - ib) > max(1e-9, ib * 1e-4):
                        changed = True
                    states[('ib', index)] = ib
                if nxt != state:
                    states[index] = nxt
                    changed = True
            elif kind in ('NMOS', 'PMOS'):
                _, gate, drain, source, vth = e[:5]
                if kind == 'NMOS':
                    vgs = v(gate) - min(v(drain), v(source))
                else:
                    vgs = max(v(drain), v(source)) - v(gate)
                nxt = 'on' if vgs > vth else 'off'
                if nxt != state:
                    states[index] = nxt
                    changed = True
        if not changed:
            converged = True
            break

    def v(node):
        return 0.0 if node < 0 else voltages[node]

    solution = Solution(voltages, converged=converged)
    # Element currents and the set of nodes conductively tied to a source.
    parent = list(range(n + 1))  # index n stands for ground / any source

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def tie(a, b):
        ra, rb = find(n if a < 0 else a), find(n if b < 0 else b)
        if ra != rb:
            parent[ra] = rb

    for index, e in enumerate(elements):
        kind, tag = e[0], e[-1]
        state = states.get(index)
        current = 0.0
        if kind == 'R':
            current = (v(e[1]) - v(e[2])) / max(e[3], 1e-6)
            tie(e[1], e[2])
        elif kind == 'V':
            current = (e[3] - (v(e[1]) - v(e[2]))) / max(e[4], 1e-6)  # out of node a
            tie(e[1], n)
            tie(e[2], n)
        elif kind == 'I':
            current = e[3]
        elif kind == 'SW':
            if e[3]:
                current = (v(e[1]) - v(e[2])) / max(e[4], 1e-6)
                tie(e[1], e[2])
        elif kind in ('D', 'Z'):
            if state == 'on':
                current = max(0.0, (v(e[1]) - v(e[2]) - e[3]) / e[4])
                tie(e[1], e[2])
            elif state == 'zener':
                current = -max(0.0, (v(e[2]) - v(e[1]) - e[5]) / e[4])
                tie(e[1], e[2])
        elif kind in ('NPN', 'PNP'):
            _, b, c, emitter, beta = e[:5]
            sign = 1 if kind == 'NPN' else -1
            ib = states.get(('ib', index), 0.0) if state != 'off' else 0.0
            if state == 'sat':
                current = max(0.0, (sign * (v(c) - v(emitter)) - 0.2) / 2)
                tie(c, emitter)
            elif state == 'active':
                current = beta * ib
            if state != 'off':
                tie(b, emitter)
            solution.results[tag] = {'i': current, 'ib': ib, 'state': state,
                                     'p': abs(current * (v(c) - v(emitter)))}
            continue
        elif kind in ('NMOS', 'PMOS'):
            if state == 'on':
                current = (v(e[2]) - v(e[3])) / max(e[5], 1e-6)
                tie(e[2], e[3])
            solution.results[tag] = {'i': current, 'state': state,
                                     'p': abs(current * (v(e[2]) - v(e[3])))}
            continue
        drop = v(e[1]) - v(e[2]) if kind != 'V' else e[3] - current * e[4]
        solution.results[tag] = {'i': current, 'state': state, 'p': abs(current * drop)}
    root = find(n)
    solution.driven = {k for k in range(n) if find(k) == root}
    return solution
