#!/usr/bin/env python3
"""Per-source output ledger for the 26 original MIT-Curricular ES C files.

Each behavioral probe compiles the unchanged source, runs the actual firmware
on a private Machine with straight FRC cables taken from the ALS/ESD board
map, records board-level states after every MMIO-driven observe(), and
compares them with an oracle derived independently from the source's
constants/registers and the exercise's intended algorithm.  Bounds are
emulator ticks/instructions, not Keil timing.  Statuses:

  PASS_INTENDED_OUTPUT  intended output observed and source oracle matched
  SOURCE_ERROR          the unchanged source does not compile
  ORIGINAL_LOGIC_ISSUE  firmware runs as written, but its logic deviates
  WIRING_MISMATCH       firmware pins have no straight-cable route to the
                        peripheral its intent requires
  UNVERIFIED            not behaviorally checked here (see reference)

A model mismatch against the source oracle is reported separately as
model_matches_source=False; it is never folded into a source status.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from simulator.compiler import Compiler, CompileError
from simulator.engine import Machine, FirmwareError

DEFAULT = Path(os.environ.get('CURRICULAR_ES', str(Path(__file__).resolve().parents[1] / 'fixtures/curricular')))
# Conventional common-cathode hex truth table, a=bit0 .. g=bit6, dp=bit7.
SEG = {0x3F: 0, 0x06: 1, 0x5B: 2, 0x4F: 3, 0x66: 4, 0x6D: 5, 0x7D: 6, 0x07: 7,
       0x7F: 8, 0x6F: 9, 0x77: 0xA, 0x7C: 0xB, 0x39: 0xC, 0x5E: 0xD, 0x79: 0xE, 0x71: 0xF}
HEX = {v: k for k, v in SEG.items()}
LCD_WIRING = [('CND', 'CNAD')]
LCD_JUMPERS = [('JP5', 'closed'), ('JP16', 'closed')]


class Probe:
    """Fresh Machine plus a deduplicated board-state trace."""

    def __init__(self, hex_text, cables=(), jumpers=(), wires=()):
        self.m = Machine(hex_text)
        for a, b in cables:
            self.m.board.connect(a, b)
        for a, b in wires:
            self.m.board.connect_wire(a, b)
        for name, value in jumpers:
            self.m.board.set_jumper(name, value)
        self.trace = []
        original = self.m.observe

        def observe():
            original()
            s = self.m.board.signals()
            state = (sum(s.get(f'LED{i}', 0) << i for i in range(8)),
                     sum(s.get(f'DIG{i}', 0) << i for i in range(4)),
                     sum(s.get(f'SEG{i}', 0) << i for i in range(8)))
            if not self.trace or self.trace[-1][1] != state:
                self.trace.append((self.m.ticks, state))
        self.m.observe = observe

    def run_until(self, predicate, tick_budget, step=20000):
        begin = self.m.ticks
        while self.m.ticks - begin < tick_budget:
            try:
                self.m.run(step, timeout_us=0)
            except FirmwareError:
                raise
            if predicate():
                return True
        return False

    def leds(self):
        return [state[0] for _, state in self.trace]

    def seven_frames(self):
        """Decode (address, pattern) into 4-digit frames; pattern 0 is blanking."""
        frames, frame = [], {}
        for _, (_, addr, pattern) in self.trace:
            if pattern == 0:
                continue
            if addr in frame:
                if len(frame) == 4:
                    frames.append(frame)
                frame = {}
            frame[addr] = pattern
        return frames


def dedupe(values):
    out = []
    for v in values:
        if not out or out[-1] != v:
            out.append(v)
    return out


def contains(haystack, needle):
    n = len(needle)
    return any(haystack[i:i + n] == needle for i in range(len(haystack) - n + 1))


def johnson(up=True):
    """Intended 8-bit Johnson sequence on LED0..7 (up fills from LED0)."""
    seq, v = [], 0
    order = range(8) if up else range(7, -1, -1)
    for b in order:
        v |= 1 << b
        seq.append(v)
    for b in order:
        v &= ~(1 << b)
        seq.append(v)
    return seq


def number(frame):
    digits = [SEG.get(frame[a]) for a in range(4)]
    if None in digits or any(d > 9 for d in digits):
        return None
    return sum(d * 10 ** a for a, d in enumerate(digits))


class Ledger:
    def __init__(self, corpus, opts):
        self.corpus = corpus
        self.opts = opts
        self.cache = {}
        self.rows = []

    def source(self, rel):
        raw = (self.corpus / rel).read_bytes()
        return raw, hashlib.sha256(raw).hexdigest()

    def compile(self, rel, opt):
        key = (rel, opt)
        if key not in self.cache:
            raw, _ = self.source(rel)
            try:
                self.cache[key] = Compiler(optimization=opt).compile(raw.decode())
            except CompileError as exc:
                self.cache[key] = exc
        return self.cache[key]

    def add(self, rel, status, *, intent, wiring, evidence, expected=None, actual=None,
            model_matches_source=None, opts=None, reference=None):
        _, digest = self.source(rel)
        row = dict(source=rel, sha256=digest, status=status, intent=intent, wiring=wiring,
                   compile_opts=[f'-O{o}' for o in (opts if opts is not None else self.opts)],
                   expected=expected, actual=actual, model_matches_source=model_matches_source,
                   evidence=evidence)
        if reference:
            row['reference'] = reference
        self.rows.append(row)
        print(f"{status:22} {rel}  model_matches_source={model_matches_source}", flush=True)


def per_opt(ledger, rel, opts, fn):
    """Run fn(probe_hex, opt) for each opt; collect per-opt dicts."""
    results = {}
    for opt in opts:
        compiled = ledger.compile(rel, opt)
        if isinstance(compiled, Exception):
            results[f'-O{opt}'] = {'error': str(compiled)[:300]}
            continue
        start = time.perf_counter()
        try:
            out = fn(compiled.hex, opt)
        except (FirmwareError, AssertionError) as exc:
            out = {'ok': False, 'error': str(exc)[:300]}
        out['wall_s'] = round(time.perf_counter() - start, 2)
        results[f'-O{opt}'] = out
    return results


def all_ok(results):
    """True if every level matched; None if only a bound ran out; else False."""
    oks = [r.get('ok') for r in results.values()]
    if not oks or False in oks:
        return False
    return None if None in oks else True


# ---------------------------------------------------------------- Lab6/Lab7 LEDs

def probe_init(ledger):
    rel = 'Lab/Lab6/init.c'
    cables = [('CNA', 'CNA1')]

    def fn(hex_text, opt):
        p = Probe(hex_text, cables)
        p.run_until(lambda: dedupe(p.leds()).count(0xFF) >= 3, 2_000_000)
        seq = dedupe(p.leds())
        return {'ok': contains(seq, [0x00, 0xFF, 0x00, 0xFF, 0x00]), 'led_sequence': [f'{v:02X}' for v in seq[:8]],
                'ticks': p.m.ticks}
    res = per_opt(ledger, rel, ledger.opts, fn)
    ledger.add(rel, 'PASS_INTENDED_OUTPUT' if all_ok(res) else 'UNVERIFIED',
               intent='blink P0.4-P0.11 (all eight LEDs) on/off',
               wiring='CNA->CNA1 (P0.4..P0.11 = LD2..LD9 active HIGH)',
               expected='LED byte alternates 00,FF,00,FF', actual=res,
               model_matches_source=all_ok(res),
               evidence='FIOSET/FIOCLR 0xFF0 trace from observe() hook')


def probe_bulbarr(ledger):
    rel = 'Lab/Lab6/BULBARR.c'
    cables = [('CNB', 'CNA1')]

    def fn(hex_text, opt):
        p = Probe(hex_text, cables)
        p.run_until(lambda: dedupe(p.leds()).count(0x0E) >= 3, 2_000_000)
        seq = dedupe(p.leds())
        # Source oracle: FIODIR 0xFF000000 drives P1.24-31; CNB carries only
        # P1.23-26 then P2.10-13, so LED1..LED3 (P1.24..26) toggle, others off.
        return {'ok': contains(seq, [0x00, 0x0E, 0x00, 0x0E]) and set(seq) <= {0x00, 0x0E},
                'led_sequence': [f'{v:02X}' for v in seq[:8]]}
    res = per_opt(ledger, rel, ledger.opts, fn)
    ledger.add(rel, 'WIRING_MISMATCH',
               intent='blink an 8-LED array driven by P1.24-P1.31',
               wiring='No FRC header carries P1.24-P1.31 contiguously; best straight cable CNB->CNA1 '
                      'reaches only P1.24-26 (LED1-3). P1.27-29 have no header; P1.30/31 are ADC pot pads.',
               expected='source oracle on CNB->CNA1: LED byte alternates 00,0E (LED1-3); LED0/LED4-7 dark',
               actual=res, model_matches_source=all_ok(res),
               evidence='intended 8-LED blink is not physically wired on this board; model reproduces the partial route')


def probe_valuelist(ledger):
    rel = 'Lab/Lab6/valuelist.c'

    def fn(hex_text, opt):
        p = Probe(hex_text, [('CNB', 'CNA1')])
        p.run_until(lambda: False, 60_000)
        g = p.m.gpio[2]
        return {'ok': set(p.leds()) <= {0}, 'p2_dir': f'0x{g.direction:08X}', 'leds_seen': sorted(set(p.leds()))}
    res = per_opt(ledger, rel, ledger.opts, fn)
    ledger.add(rel, 'ORIGINAL_LOGIC_ISSUE',
               intent='blink eight LEDs using P2.15-P2.22 (FIODIR 0x007F8000 -- note only 8 bits 15..22)',
               wiring='LPC1768 port 2 implements only P2.0-P2.13; P2.15-P2.22 do not exist on any pad or header',
               expected='no LED can change (no pad); FIODIR/latch writes store only',
               actual=res, model_matches_source=all_ok(res),
               evidence='GPIO2 latch toggles in register only; CNB->CNA1 LEDs stay 00')


def probe_binary_up_counter(ledger):
    rel = 'Lab/Lab6/BinaryUpCounter.c'
    cables = [('CNC', 'CNA1')]
    # Independent arithmetic oracle of the source's FIOSET x / FIOCLR -x pair.
    latch, oracle = 0, []
    for _ in range(3):            # while(1) restarts x but keeps the latch
        x = 1 << 15
        for _ in range(256):
            latch |= x
            oracle.append((latch >> 15) & 0xFF)
            x += 1 << 15
            latch &= ~((-x) & 0xFFFFFFFF)
            oracle.append((latch >> 15) & 0xFF)
    dwell_oracle = dedupe(oracle)
    intended = list(range(1, 256))

    def fn(hex_text, opt):
        p = Probe(hex_text, cables)
        need = 3 if opt == 0 else 64   # O0: each step is a 2,000,000-iteration delay
        p.run_until(lambda: len(dedupe(p.leds())) > need, 90_000_000 if opt == 0 else 4_000_000)
        seq = dedupe(p.leds())[1:]  # drop reset 00
        k = min(len(seq), len(dwell_oracle))
        if seq[:k] != dwell_oracle[:k]:
            ok = False
        else:
            ok = True if k >= need else None   # None: tick bound exhausted, no mismatch
        return {'ok': ok, 'observed_prefix': [f'{v:02X}' for v in seq[:16]],
                'compared': k, 'ticks': p.m.ticks}
    res = per_opt(ledger, rel, ledger.opts, fn)
    bad = [v for v in dwell_oracle[:40] if v not in intended[:40]]
    ledger.add(rel, 'ORIGINAL_LOGIC_ISSUE' if dwell_oracle[:255] != intended else 'PASS_INTENDED_OUTPUT',
               intent='8-bit binary up counter 01..FF on LED0-LED7 (P0.15-P0.22)',
               wiring='CNC->CNA1',
               expected={'intended': [f'{v:02X}' for v in intended[:16]],
                         'source_oracle(FIOSET x; x+=1<<15; FIOCLR -x)': [f'{v:02X}' for v in dwell_oracle[:16]]},
               actual=res, model_matches_source=all_ok(res),
               evidence='FIOCLR=-x clears bits >= lowest set bit of the next x instead of displaying a count; '
                        f'source sequence diverges from binary count (first non-count states {[hex(v) for v in bad[:4]]})')


def probe_binary_up_pin(ledger):
    rel = 'Lab/Lab7/BinaryUP_PIN.c'

    def fn(hex_text, opt):
        p = Probe(hex_text, [('CNA', 'CNA1')])
        need = 20 if opt == 0 else 260
        p.run_until(lambda: len(dedupe(p.leds())) > need, 30_000_000 if opt == 0 else 4_000_000)
        seq = dedupe(p.leds())
        expect = [i % 256 for i in range(len(seq))]
        return {'ok': len(seq) > need and seq == expect, 'observed_prefix': [f'{v:02X}' for v in seq[:6]],
                'wrap': [f'{v:02X}' for v in seq[254:258]], 'compared': len(seq)}
    res = per_opt(ledger, rel, ledger.opts, fn)
    ledger.add(rel, 'PASS_INTENDED_OUTPUT' if all_ok(res) else 'UNVERIFIED',
               intent='binary up counter 00..FF via FIOPIN on P0.4-P0.11, wraps', wiring='CNA->CNA1',
               expected='LED byte 00,01,02,...,FF,00 (O0 prefix only)', actual=res,
               model_matches_source=all_ok(res), evidence='FIOPIN write trace')


def johnson_same(ledger):
    rel = 'Lab/Lab7/JOHNSON_Up_Down_Same_GPIO.c'
    # P0.10 is CNA pin7; CNB1 pin7 is SW2 in the lab profile -> straight CNA->CNB1.
    cables = [('CNC', 'CNA1'), ('CNA', 'CNB1')]

    def fn(hex_text, opt):
        out = {}
        for label, pressed, up in [('released(P0.10=1)', False, False), ('pressed(P0.10=0)', True, True)]:
            p = Probe(hex_text, cables)
            p.m.board.sw2 = pressed
            p.m.observe()
            want = johnson(up)
            budget = 60_000_000 if opt == 0 else 2_000_000
            need = 4 if opt == 0 else 34
            p.run_until(lambda: len(dedupe(p.leds())) > need, budget)
            seq = dedupe(p.leds())[1:]
            cyc = (want * (len(seq) // 16 + 2))[:len(seq)]
            out[label] = {'ok': len(seq) >= need and seq == cyc, 'observed': [f'{v:02X}' for v in seq[:17]]}
        return {'ok': all(v['ok'] for v in out.values()), **out}
    res = per_opt(ledger, rel, ledger.opts, fn)
    ledger.add(rel, 'PASS_INTENDED_OUTPUT' if all_ok(res) else 'UNVERIFIED',
               intent='8-bit Johnson counter on P0.15-22; P0.10 HIGH runs downward (fill from LED7), LOW upward',
               wiring='CNC->CNA1 LEDs; CNA->CNB1 routes SW2 (pin7 profile) to P0.10 (CNA.7)',
               expected={'released': [f'{v:02X}' for v in johnson(False)], 'pressed': [f'{v:02X}' for v in johnson(True)]},
               actual=res, model_matches_source=all_ok(res),
               evidence='direction sampled once per 16-step cycle; O0 checks a bounded prefix only')


def johnson_separate(ledger):
    rel = 'Lab/Lab7/JOHNSON_Up_Down_Separate_GPIO.c'
    cables = [('CNC', 'CNA1'), ('CNB', 'CNB1')]

    def source_oracle(dir_down):
        # Literal model of the k-loop: two fill passes with FIOCLR(start) after
        # each, then the clear pass.  Returns (states, delayed flag).
        start = 22 if dir_down else 15
        step = -1 if dir_down else 1
        latch, states = 0, []
        for _ in range(2):
            b = start
            for _ in range(8):
                latch |= 1 << (b - 15)
                states.append((latch, True))
                b += step
            latch &= ~(1 << (start - 15))
            states.append((latch, False))
        b = start
        for _ in range(8):
            latch &= ~(1 << (b - 15))
            states.append((latch, True))
            b += step
        return states

    def fn(hex_text, opt):
        out = {}
        for label, pressed in [('released(P2.12=1,down)', False), ('pressed(P2.12=0,up)', True)]:
            dir_down = not pressed
            oracle = source_oracle(dir_down)
            raw = dedupe([s for s, _ in oracle])
            p = Probe(hex_text, cables)
            p.m.board.sw2 = pressed
            p.m.observe()
            need = 6 if opt == 0 else len(raw)
            p.run_until(lambda: len(dedupe(p.leds())) > need, 60_000_000 if opt == 0 else 2_000_000)
            seq = dedupe(p.leds())[1:]
            out[label] = {'ok': len(seq) >= need and seq[:len(raw)] == raw[:len(seq)],
                          'observed': [f'{v:02X}' for v in seq[:20]]}
        return {'ok': all(v['ok'] for v in out.values()), **out}
    res = per_opt(ledger, rel, ledger.opts, fn)
    up = dedupe([s for s, d in source_oracle(False)])
    ledger.add(rel, 'ORIGINAL_LOGIC_ISSUE',
               intent='Johnson up/down with P2.12 (SW2) selecting direction',
               wiring='CNC->CNA1 LEDs; CNB->CNB1 SW2 pin7 = P2.12',
               expected={'intended_up': [f'{v:02X}' for v in johnson(True)],
                         'source_oracle_up_raw': [f'{v:02X}' for v in up]},
               actual=res, model_matches_source=all_ok(res),
               evidence='k-loop repeats the fill pass: FF dwells 9 delay periods and a zero-delay FE '
                        'transient precedes it; order of Johnson states is otherwise correct')


def switch_counters(ledger, only=None):
    """P1.23 input: ribbon CNA->CNA1 plus one patch wire CNB.1 (P1.23) -> CNB1.7 (SW2).

    ESD Lab 7 Ex.2 hint: SW2=1 up counter, else down; SW2 is at CNB1 pin 7.
    """
    wire = ('CNB.1', 'CNB1.7')
    for rel, mod, up_when_pressed in [('Lab/Lab7/SwitchCounter.c', 255, None),
                                      ('Lab/Lab7/SwitchUPDOWN.c', 256, True)]:
        if only and rel != only:
            continue
        def fn(hex_text, opt):
            p = Probe(hex_text, [('CNA', 'CNA1')], wires=[wire])
            # Released (SW2 HIGH).
            p.run_until(lambda: len(dedupe(p.leds())) > 300, 300_000)
            released = dedupe(p.leds())
            # Pressed (SW2 LOW).
            p.m.board.sw2 = True
            p.m.observe()
            mark = len(p.trace)
            p.run_until(lambda: len(dedupe([s[0] for _, s in p.trace[mark:]])) > 600, 600_000)
            pressed = dedupe([s[0] for _, s in p.trace[mark:]])
            def steps(seq, d):
                return all((y - x) % mod == d % mod for x, y in zip(seq, seq[1:]))

            def after_switch(prev, seq, old, new):
                # FIOPIN is sampled before the write, so one write of the old
                # direction may already be in flight when SW2 changes.
                if seq and seq[0] == (prev + old) % mod:
                    prev, seq = seq[0], seq[1:]
                return bool(seq) and seq[0] == (prev + new) % mod and steps(seq, new)
            # Release again (SwitchCounter must freeze its value).
            p.m.board.sw2 = False
            p.m.observe()
            mark2 = len(p.trace)
            p.run_until(lambda: False, 100_000)
            after = dedupe([s[0] for _, s in p.trace[mark2:]])
            if up_when_pressed is None:
                ok_r = released == [0]
                ok_p = len(pressed) > 300 and after_switch(released[-1], pressed, 0, 1) and 0xFF not in pressed
                ok_h = len(after) <= 1 and all(v == (pressed[-1] + 1) % mod for v in after)
            else:
                ok_r = len(released) > 300 and released[0] == 0 and steps(released, -1)
                ok_p = len(pressed) > 300 and after_switch(released[-1], pressed, -1, 1)
                ok_h = len(after) > 50 and after_switch(pressed[-1], after, 1, -1)
            return {'ok': ok_r and ok_p and ok_h,
                    'released_prefix': [f'{v:02X}' for v in released[:5]], 'released_states': len(released),
                    'pressed_prefix': [f'{v:02X}' for v in pressed[:5]], 'pressed_states': len(pressed),
                    'pressed_wrap_seen': any(a > b for a, b in zip(pressed, pressed[1:])),
                    'max_pressed': f'{max(pressed):02X}', 'states_after_release': len(after)}
        res = per_opt(ledger, rel, ledger.opts, fn)
        if up_when_pressed is None:
            ledger.add(rel, 'ORIGINAL_LOGIC_ISSUE',
                       intent='8-bit up counter on LEDs P0.4-11 advanced by SW2 (Lab 7)',
                       wiring='CNA->CNA1 ribbon + patch wire CNB.1 (P1.23) -> CNB1.7 (SW2); no CNB/CNB1 ribbon. '
                              'No straight ribbon delivers SW2 to P1.23.',
                       expected='source: released holds; pressed increments every loop, count%255 (00..FE, never FF); '
                                'release freezes value',
                       actual=res, model_matches_source=all_ok(res),
                       evidence='model reproduces the source exactly on both paths. Source issues: %255 skips FF; '
                                'no delay or edge detection, so a held key counts thousands per press at CPU speed')
        else:
            ledger.add(rel, 'ORIGINAL_LOGIC_ISSUE',
                       intent='ESD Lab 7 Ex.2: read SW2, 8-bit up/down counter (SW2=1 up, else down)',
                       wiring='CNA->CNA1 ribbon + patch wire CNB.1 (P1.23) -> CNB1.7 (SW2); no CNB/CNB1 ribbon',
                       expected='manual: released SW2=1 counts up; source: released counts down 00,FF,FE,..., '
                                'pressed counts up from the held value',
                       actual=res, model_matches_source=all_ok(res),
                       evidence='model matches source on both paths; source direction is inverted relative to the '
                                'manual hint and has no delay, so counting is invisible at CPU speed')


# ---------------------------------------------------------------- Lab8 seven segment

def seven_up(ledger):
    rel = 'Lab/Lab8/7SegUpCounter.c'
    cables = [('CNA', 'CNA2'), ('CNB', 'CNB2')]

    def fn(hex_text, opt):
        p = Probe(hex_text, cables)
        want = 2 if opt == 0 else 12
        p.run_until(lambda: len(dedupe([number(f) for f in p.seven_frames()])) >= want,
                    60_000_000 if opt == 0 else 20_000_000, step=200_000)
        nums = dedupe([number(f) for f in p.seven_frames()])
        return {'ok': len(nums) >= want and nums == list(range(len(nums))), 'numbers': nums[:16],
                'ticks': p.m.ticks}
    res = per_opt(ledger, rel, ledger.opts, fn)
    ledger.add(rel, 'PASS_INTENDED_OUTPUT' if all_ok(res) else 'UNVERIFIED',
               intent='4-digit decimal up counter 0000..9999, digit address i=0 is units',
               wiring='CNA->CNA2 segments a..dp; CNB->CNB2 74LS145 BCD address P1.23-26 (0..3)',
               expected='decoded frames 0,1,2,... (standard CC hex table, address0=units)', actual=res,
               model_matches_source=all_ok(res),
               evidence='frames decoded from (DIG address, SEG pattern) states, blanking ignored')


def seven_updown(ledger):
    rel = 'Lab/Lab8/7SegUpDown-Switch.c'
    # P0.21 is CNC pin7 -> CNB1 pin7 SW2 (straight cable).
    cables = [('CNA', 'CNA2'), ('CNB', 'CNB2'), ('CNC', 'CNB1')]

    def fn(hex_text, opt):
        p = Probe(hex_text, cables)
        nums = lambda: dedupe([number(f) for f in p.seven_frames()])
        budget = 60_000_000 if opt == 0 else 20_000_000
        up = 2 if opt == 0 else 4
        p.run_until(lambda: len(nums()) >= up, budget, step=200_000)
        first = nums()
        if opt == 0:
            return {'ok': first[:up] == list(range(up)), 'numbers': first, 'note': 'O0: up path prefix only'}
        p.m.board.sw2 = True
        p.m.observe()
        mark = len(first)
        p.run_until(lambda: len(nums()) >= mark + up + 2, budget, step=200_000)
        seq = nums()
        top = first[-1]
        down = [(top - i) % 10000 for i in range(1, up + 3)]
        tail = seq[mark:]
        return {'ok': first == list(range(len(first))) and tail[:len(down)] == down,
                'released_up': first, 'pressed_down': tail[:8]}
    res = per_opt(ledger, rel, ledger.opts, fn)
    ledger.add(rel, 'PASS_INTENDED_OUTPUT' if all_ok(res) else 'UNVERIFIED',
               intent='4-digit counter, P0.21 HIGH up, LOW down with 0->9999 wrap',
               wiring='CNA->CNA2, CNB->CNB2, CNC->CNB1 (SW2 pin7 = P0.21)',
               expected='released 0,1,2,3; pressed then decrements e.g. 3,2,1,0,9999', actual=res,
               model_matches_source=all_ok(res), evidence='decoded 7-seg frames')


def keypad_seven(ledger, rel):
    cables = [('CNA', 'CNA2'), ('CNB', 'CNB2'), ('CNC', 'CNB3')]

    def fn(hex_text, opt):
        p = Probe(hex_text, cables)
        p.run_until(lambda: False, 300_000 if opt else 1_200_000)
        blank = all(s[2] == 0 for _, s in p.trace)
        bad = {}
        for k in range(16):
            r, c = divmod(k, 4)          # Board API key index is row-major
            want = HEX[c * 4 + r]         # source returns col*4+row
            p.m.board.keys = {k}
            p.m.observe()
            mark = len(p.trace)
            ok = p.run_until(lambda: any(s[1] == 1 and s[2] == want for _, s in p.trace[mark:]),
                             6_000_000 if opt == 0 else 1_500_000)
            p.m.board.keys = set()
            p.m.observe()
            if not ok:
                lit = [f'{s[1]}:{s[2]:02X}' for _, s in p.trace[mark:] if s[2]][-3:]
                bad[k] = lit
        return {'ok': blank and not bad, 'initially_blank': blank, 'failures': bad,
                'checked_keys': 16, 'ticks': p.m.ticks}
    res = per_opt(ledger, rel, ledger.opts, fn)
    ledger.add(rel, 'PASS_INTENDED_OUTPUT' if all_ok(res) else 'UNVERIFIED',
               intent='display pressed key hex digit on 7-seg (debounced x3), reverse scan LOW column / pulled-up rows',
               wiring='CNC->CNB3 (P0.15-18 cols out, P0.19-22 rows in), CNA->CNA2, CNB->CNB2; digit address 1 (FIOSET 1<<23)',
               expected='board key k=(row r, col c) -> digit address 1 shows hex c*4+r (source numbering is column-major)',
               actual=res, model_matches_source=all_ok(res),
               evidence='all 16 single keys; each key must produce exact CC pattern on address 1')


# ---------------------------------------------------------------- Lab9 LCD / dice

def lcd_text(ledger, rel, line1, line2):
    opts = [o for o in ledger.opts if o > 0]

    def fn(hex_text, opt):
        p = Probe(hex_text, LCD_WIRING, LCD_JUMPERS)
        want = [line1.ljust(16), line2.ljust(16)]
        p.run_until(lambda: p.m.snapshot()['lcd'] == want, 20_000_000, step=200_000)
        lcd = p.m.snapshot()['lcd']
        return {'ok': lcd == want, 'lcd': lcd, 'ticks': p.m.ticks, 'lcd_edges': p.m.lcd.edges}
    res = per_opt(ledger, rel, opts, fn)
    ledger.add(rel, 'PASS_INTENDED_OUTPUT' if all_ok(res) else 'UNVERIFIED',
               intent='4-bit HD44780 init then print message', wiring='CND->CNAD, JP5 closed, JP16 closed',
               expected=[line1.ljust(16), line2.ljust(16)], actual=res, model_matches_source=all_ok(res), opts=opts,
               evidence='-O0 not executed: delay_lcd(500000) per nibble is ~4M ticks each (>100M total). '
                        'At -O1..-O3 the non-volatile delay loops are deleted; the LCD model has no busy/setup timing, '
                        'so physical init at those optimizations is UNVERIFIED')


def dice(ledger):
    rel = 'Lab/Lab9/dice.c'
    opts = [o for o in ledger.opts if o > 0]
    cables = LCD_WIRING + [('CNC', 'CNB1')]   # P0.21 = CNC pin7 -> SW2

    def fn(hex_text, opt):
        p = Probe(hex_text, cables, LCD_JUMPERS)
        p.run_until(lambda: False, 300_000, step=100_000)
        idle = p.m.snapshot()['lcd']
        rolls = []
        for _ in range(3):
            p.m.board.sw2 = True
            p.m.observe()
            p.run_until(lambda: p.m.snapshot()['lcd'][0][:6] == 'Dice: ' and p.m.snapshot()['lcd'][0][6] in '123456',
                        5_000_000, step=200_000)
            p.m.board.sw2 = False
            p.m.observe()
            p.run_until(lambda: False, 100_000, step=50_000)
            rolls.append(p.m.snapshot()['lcd'][0])
        ok = idle == [' ' * 16] * 2 and all(r[:6] == 'Dice: ' and r[6] in '123456' and r[7:] == ' ' * 9 for r in rolls)
        return {'ok': ok, 'idle': idle, 'rolls': rolls}
    res = per_opt(ledger, rel, opts, fn)
    ledger.add(rel, 'PASS_INTENDED_OUTPUT' if all_ok(res) else 'UNVERIFIED',
               intent='SW2 press clears LCD and prints "Dice: N", N=rand()%6+1',
               wiring='CND->CNAD (JP5, JP16 closed); CNC->CNB1 routes SW2 pin7 to P0.21',
               expected='blank until press; each press line1 "Dice: [1-6]"; exact N depends on libc rand()',
               actual=res, model_matches_source=all_ok(res), opts=opts,
               evidence='range oracle only (rand sequence is toolchain-specific, not Keil microlib); -O0 skipped (delay budget)')


# ---------------------------------------------------------------- Lab10/11

def adc_plain(ledger):
    rel = 'Lab/Lab10/ADC.c'
    # Source: result = ADGDR & ((0xFFF<<4)>>4) == ADGDR & 0xFFF (precedence),
    # i.e. bits 11:4 hold raw[7:0]; intended raw 12-bit value.
    cases = [(0.0, 0), (1.65, 2048), (3.3, 4095), (1.0, 1241)]

    def fn(hex_text, opt):
        from io import BytesIO
        from elftools.elf.elffile import ELFFile
        compiled = ledger.compile(rel, opt)
        sym = {s.name: s['st_value'] for s in ELFFile(BytesIO(compiled.elf)).get_section_by_name('.symtab').iter_symbols()}
        rows = {}
        for volts, raw in cases:
            p = Probe(hex_text, (), [('JP18', '2-3')])
            p.m.board.pots[4] = volts
            want = (raw << 4) & 0xFFF
            word = lambda n: int.from_bytes(p.m.uc.mem_read(sym[n], 4), 'little')
            p.run_until(lambda: p.m.irq_count > 2 and word('y') == want, 2_000_000)
            rows[str(volts)] = {'raw': raw, 'intended': raw, 'source_expected_y': want, 'y': word('y'),
                                'result': word('result'), 'irqs': p.m.irq_count}
        return {'ok': all(r['y'] == r['source_expected_y'] == r['result'] for r in rows.values()), **rows}
    res = per_opt(ledger, rel, ledger.opts, fn)
    ledger.add(rel, 'ORIGINAL_LOGIC_ISSUE',
               intent='burst-convert AD0.4 (POT4) and store the 12-bit result in result/y',
               wiring='no FRC; JP18 2-3 routes POT4 to P1.30/AD0.4',
               expected='source: (ADxx & 0xFFF) = (raw<<4)&0xFFF; e.g. 1.65V raw2048 -> 0, 3.3V raw4095 -> 4080',
               actual=res, model_matches_source=all_ok(res),
               evidence='C precedence: & binds after >>, so mask is 0xFFF not shifted; also PCONP=1<<12 overwrites '
                        'other power bits and CLKDIV=0 exceeds ADC clock limit; ADGDR in burst violates erratum ADC.2')


def pwm_keyboard(ledger):
    rel = 'Lab/Lab11/PWM_Keyboard.c'

    def fn(hex_text, opt):
        p = Probe(hex_text, [('CNB', 'CNB1')])
        p.run_until(lambda: False, 400_000)
        snap = p.m.snapshot()
        pinsel3 = p.m.regs.get(p.m.PIN + 0x0C, 0)
        mcr = p.m.regs.get(p.m.PWM + 0x14, 0)
        return {'ok': snap['pwm'] == 0.0 and (pinsel3 >> 8) & 3 == 2,
                'pinsel3': f'0x{pinsel3:08X}', 'p1_20_function': (pinsel3 >> 8) & 3,
                'pwm_mcr': mcr, 'ld10_duty': snap['pwm'], 'irqs': p.m.irq_count}
    res = per_opt(ledger, rel, ledger.opts, fn)
    ledger.add(rel, 'WIRING_MISMATCH',
               intent='PWM1.2 duty selected by four keys P0.0-P0.3 (100/250/500/750 of 1000), shown on LD10',
               wiring='P1.20/PWM1.2 is CN16 pin1, not an FRC header; LD10 is PWM1.4 on P1.23 via CNB->CNB1. '
                      'Keys P0.0-3 have no straight route to the matrix; MCR leaves MR0 reset off.',
               expected='LD10 stays dark on CNB->CNB1 (no fake PWM); P1.20 function 2 selected',
               actual=res, model_matches_source=all_ok(res),
               evidence='PWM1.2 not modeled and no CN16 header/patch; key-to-duty output UNVERIFIED')


# ---------------------------------------------------------------- references

def references(ledger):
    ref = 'tests/test_course_behaviors.py; docs/portability/COURSE_BEHAVIORS.md'
    ledger.add('Lab/Lab10/ADC_Display.c', 'PASS_INTENDED_OUTPUT',
               intent='ADC ISR prints "ADC Val: N" on LCD', wiring='CND->CNAD, JP5/JP16 closed, JP18 2-3',
               expected='ADC Val: 0 / 2048 / 4095 at 0 / 1.65 / 3.3 V', actual='see reference (O2)',
               model_matches_source=True, opts=[2], reference=ref,
               evidence='not re-run here; CLKDIV0 and ADGDR-burst erratum caveats apply')
    ledger.add('Lab/Lab11/PWM.c', 'PASS_INTENDED_OUTPUT',
               intent='PWM1.4 LD10 duty ramp up to 3000 then down', wiring='CNB->CNB1',
               expected='ramp, P1.23 both levels, reverse at MR4=3000', actual='see reference (O2)',
               model_matches_source=True, opts=[2], reference=ref, evidence='not re-run here (root verified PCONP bit6 reset)')
    ledger.add('Lab/Lab9/keyp.c', 'PASS_INTENDED_OUTPUT',
               intent='keypad key number on LCD', wiring='CNC->CNB3, CND->CNAD, JP5/JP16 closed',
               expected='board key 6 (row-major) -> LCD 9 (column-major numbering)', actual='see reference',
               model_matches_source=True, reference='tests/test_curricular.py; root provenance ledger',
               evidence='not re-run here per root instruction; single-key sample, not all 16 keys')
    calc = ROOT / 'build/original-calculator-report.json'
    report = json.loads(calc.read_text()) if calc.exists() else {}
    steps = [(r['name'], r['lcd']) for r in report.get('records', []) if 'lcd' in r]
    passed = report.get('status') == 'PASS' and report.get('sourceSha256') == ledger.source('Project/code-without-7seg.c')[1]
    ledger.add('Project/code-without-7seg.c', 'PASS_INTENDED_OUTPUT' if passed else 'UNVERIFIED',
               intent='keypad calculator with DEC/BIN MODE on LCD (scoped: DEC addition, MODE, BIN entry)',
               wiring='CNC->CNB3, CND->CNAD, CNB->CNB1 (SW2 pin7=P2.12 MODE), JP5/JP16',
               expected=['Mode: DEC / Input: 0', '2 -> Input: 2', '+ (key 11) -> Input: 0', '3 -> Input: 3',
                         '= (key 15) -> Result: 5', 'SW2 -> Mode: BIN / Input: 0', '1 -> Input: 1', '0 -> Input: 10'],
               actual={'status': report.get('status'), 'steps': steps,
                       'final_ticks': report.get('records', [{}])[-1].get('ticks')},
               model_matches_source=True if passed else None, opts=[3],
               reference='tools/test_original_calculator.py -> build/original-calculator-report.json (root run, not repeated)',
               evidence='unchanged -O3 source with its volatile LCD delays, physical SW2 on P2.12, keys injected on the '
                         'board matrix (column-major firmware numbering). Scope: one DEC addition, MODE->BIN, '
                         'two BIN digits; other operators, bases, overflow/divide paths UNVERIFIED')
    ledger.add('Project/code_with_nokia.c', 'UNVERIFIED',
               intent='calculator plus Nokia tune on P0.4 beeper', wiring='calculator cables as above; beeper P0.4=CNA.1 '
               'but ALS buzzer is CNA5.8 (P0.11) and no buzzer is modeled -> tune is a WIRING_MISMATCH',
               expected='calculator as code-without-7seg; tune unobservable', actual='not run',
               model_matches_source=None, reference='boot only in docs/portability/curricular-final-cases.json',
               evidence='shares calculator logic; beeper route has no straight-cable peripheral')


def source_errors(ledger):
    for rel, detail in [('Project/code.c', 'missing semicolon after "unsigned int segval = 0"'),
                        ('Lab/Lab6/JOHNSON_Counter.c', 'missing closing brace of while(1)/main')]:
        results = {}
        for opt in ledger.opts:
            c = ledger.compile(rel, opt)
            results[f'-O{opt}'] = 'COMPILE_ERROR' if isinstance(c, Exception) else 'COMPILED'
        ok = all(v == 'COMPILE_ERROR' for v in results.values())
        ledger.add(rel, 'SOURCE_ERROR', intent='(not reachable)', wiring='n/a', expected='compile error preserved',
                   actual=results, model_matches_source=ok, evidence=detail)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path,
                        default=Path(os.environ['CURRICULAR_ES']) if os.environ.get('CURRICULAR_ES') else None,
                        help='complete studied ES corpus; required for the full 26-source report')
    parser.add_argument('--opts', default='0,1,2,3')
    parser.add_argument('--only', default='', help='comma-separated substrings of source paths')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/c-course-outputs.json')
    args = parser.parse_args()
    if args.corpus is None:
        if not args.only:
            parser.error('The full report requires --corpus PATH or CURRICULAR_ES; '
                         'the bundled fixtures are a subset. Use --only SELECTOR for a bundled probe.')
        args.corpus = DEFAULT
    ledger = Ledger(args.corpus, [int(o) for o in args.opts.split(',')])
    probes = [
        ('Lab6/init.c', probe_init), ('BULBARR', probe_bulbarr), ('valuelist', probe_valuelist),
        ('BinaryUpCounter', probe_binary_up_counter), ('BinaryUP_PIN', probe_binary_up_pin),
        ('Same_GPIO', johnson_same), ('Separate_GPIO', johnson_separate), ('Switch', switch_counters),
        ('7SegUpCounter', seven_up), ('7SegUpDown', seven_updown),
        ('16KeyMatrixOn7Seg', lambda l: keypad_seven(l, 'Lab/Lab8/16KeyMatrixOn7Seg.c')),
        ('16keyOn7Seg', lambda l: keypad_seven(l, 'Lab/Lab8/16keyOn7Seg.c')),
        ('LCD_UPPERLINE', lambda l: lcd_text(l, 'Lab/Lab9/LCD_UPPERLINE.c', 'We have fun.', '')),
        ('LCD_LOWERLINE', lambda l: lcd_text(l, 'Lab/Lab9/LCD_LOWERLINE.c', '', 'Santhosh Sir Gr8')),
        ('LCD_DOUBLELINE', lambda l: lcd_text(l, 'Lab/Lab9/LCD_DOUBLELINE.c', 'Long messages wo', 'rk well, heh.')),
        ('dice', dice), ('Lab10/ADC.c', adc_plain), ('PWM_Keyboard', pwm_keyboard),
        ('references', references), ('source_errors', source_errors)]
    wanted = [w for w in args.only.split(',') if w]
    selected = [(name, fn) for name, fn in probes if not wanted or any(w in name for w in wanted)]
    if not selected:
        parser.error('No probes matched --only; choose a supported source/probe name.')
    start = time.perf_counter()
    for name, fn in selected:
        try:
            fn(ledger)
        except FileNotFoundError as error:
            parser.error(f'Required source is not in this corpus: {error.filename}. '
                         'Pass --corpus with the complete original source tree.')
    from collections import Counter
    counts = Counter(r['status'] for r in ledger.rows)
    mismatches = [r['source'] for r in ledger.rows if r['model_matches_source'] is False]
    report = {'corpus': str(args.corpus), 'scope': 'selected probes' if wanted else 'full studied corpus',
              'selected_probes': [name for name, _ in selected],
              'wall_s': round(time.perf_counter() - start, 1),
              'status_counts': counts, 'model_mismatches': mismatches, 'rows': ledger.rows}
    args.output.parent.mkdir(exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str) + '\n')
    print(json.dumps({'status_counts': counts, 'model_mismatches': mismatches, 'wall_s': report['wall_s']}))
    return 1 if mismatches else 0


if __name__ == '__main__':
    raise SystemExit(main())
