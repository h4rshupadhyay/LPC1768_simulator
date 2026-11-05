"""One bounded firmware worker; all mutations serialize with CPU execution."""
from __future__ import annotations
from pathlib import Path
import json
import threading
import time

from .engine import Machine, FirmwareError
from .compiler import Compiler
from .board import MAPPING, TARGETS
from .debugger import Debugger
from .terminal import Terminal

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / 'examples/catalog.json').read_text(encoding='utf-8'))
TIMING_MODES = ('realtime', 'precise')


class Runtime:
    def __init__(self, start_worker=True, *, realtime=None, target='als'):
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.closed = threading.Event()
        # `live` paces execution against the wall clock; `realtime` additionally
        # derives peripheral time from it. Precise mode keeps live pacing but
        # runs every peripheral on deterministic instruction-derived time.
        self.live = start_worker if realtime is None else realtime
        self.timing = 'realtime'
        self.realtime = self.live
        self.target = target
        self.terminals = {0: Terminal('UART0 (PC serial port)', 9600, 0)}
        self._pace = None
        self.speed = 1.0
        self.machine = self._new_machine((ROOT / 'examples/idle.hex').read_text())
        self.debugger = Debugger(self.machine)
        self.loaded = False
        self.status = 'empty'
        self.name = 'No firmware loaded'
        self.diagnostics = 'Compile Embedded C or upload an Intel HEX file.'
        self.compiler = Compiler()
        self.thread = None
        if start_worker:
            self.thread = threading.Thread(target=self._worker, name='lpc1768-cpu', daemon=True)
            self.thread.start()

    def _new_machine(self, hex_text):
        machine = Machine(hex_text, realtime=self.realtime, target=self.target)
        machine.terminals = self.terminals
        return machine

    def _worker(self):
        while not self.closed.is_set():
            self.wake.wait(.1)
            if not self.wake.is_set():
                continue
            delay = self._run_slice()
            # Yield to API/input threads without adding a 2 ms floor to each
            # firmware slice (the user's timer polling interval can be 1 ms).
            time.sleep(delay or 0)

    def _run_slice(self):
        with self.lock:
            if self.status != 'running':
                self.wake.clear()
                return 0
            try:
                limit = self.debugger.execution_limit()
                # Keep instruction dwell for multiplexed displays and precise
                # hooks for debugging. Other live workloads can execute pure
                # C delay loops without calling Python for every block.
                fast = (self.realtime and not self.debugger.breakpoints
                        and not (self.machine.board.has_signal_connection('SEG')
                                 and self.machine.board.has_signal_connection('DIG')))
                self.machine.run(20000, timeout_us=1000, until=limit, fast=fast)
                self.debugger.complete_slice(limit)
                if self.machine.reset_requested:
                    reason = self.machine.reset_requested
                    self._reset(running=True)
                    self.diagnostics = reason
                    return 0
                if self.debugger.hit:
                    self.machine.pause_clock()
                    self.status = 'paused'
                    self.wake.clear()
                return self._pace_delay()
            except FirmwareError as e:
                self.status = 'error'
                self.diagnostics = self._explain(str(e))
                self.wake.clear()
                self.machine.pause_clock()
                return 0

    def _pace_delay(self):
        """Precise mode: keep simulated time from running ahead of the wall clock."""
        if self.realtime or not self.live:
            return 0
        now = time.perf_counter_ns()
        simulated = self.machine.time_ns()
        if self._pace is None:
            self._pace = (now, simulated)
            return 0
        wall0, sim0 = self._pace
        wall, sim = now - wall0, simulated - sim0
        if wall > 1_000_000_000:
            self.speed = min(1.0, sim / wall) if wall else 1.0
            self._pace = (now - min(wall, 50_000_000), simulated - min(sim, int(50_000_000 * self.speed)))
        ahead = sim - wall
        return min(0.02, ahead / 1e9) if ahead > 0 else 0

    def _explain(self, message):
        """Attach the C source line of the faulting instruction when debug data exists."""
        try:
            pc = self.machine.uc.reg_read(__import__('unicorn').arm_const.UC_ARM_REG_PC) & ~1
            source = self.debugger.source(pc)
        except Exception:
            source = None
        if source:
            return f'{message} ({source["file"].split("/")[-1]}:{source["line"]})'
        return message

    def close(self):
        self.closed.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=2)
        if not self.thread or not self.thread.is_alive():
            with self.lock:
                self.machine.pause_clock()
                self._dispose(self.machine)

    @staticmethod
    def _dispose(machine):
        # Native Unicorn owns its weakref finalizer. The WASM binding needs
        # explicit disposal to release its engine and Python callback proxies.
        close = getattr(machine.uc, 'close', None)
        if close is not None:
            close()

    def _replace(self, candidate):
        previous = self.machine
        old = self.machine.board
        # Programming/reset restarts the MCU, not the separately powered LCD.
        # Retain DDRAM and 4-bit transaction phase until firmware reinitializes
        # the controller; observe below applies the reset GPIO signal levels.
        candidate.lcd = self.machine.lcd
        b = candidate.board
        b.cables = [c[:] for c in old.cables]
        b.wires = [w[:] for w in old.wires]
        b.jumpers = dict(old.jumpers)
        b.pots = dict(old.pots)
        b.sw2, b.sw2_pin = old.sw2, old.sw2_pin
        b.keys = set(old.keys)
        # The external circuit and any physical damage outlive an MCU reset.
        if old.target == b.target:
            circuit = old.circuit
            circuit.board = b
            b.circuit = circuit
            for part in circuit.parts.values():
                part.reset_transient()
            circuit.touch()
            candidate.damaged_pads = set(previous.damaged_pads)
        candidate.floating_mode = previous.floating_mode
        candidate.observe()
        self.machine = candidate
        self._pace = None
        self._dispose(previous)

    def _reset(self, running):
        self.machine.pause_clock()
        self._replace(self._new_machine(self.machine.hex_text))
        self.debugger.attach(self.machine)
        self.status = 'running' if running else ('ready' if self.loaded else 'empty')
        if running:
            self.machine.resume_clock()
            self.wake.set()
        else:
            self.wake.clear()

    def load(self, text, name='Uploaded HEX', diagnostics='HEX loaded and validated.', *, elf: bytes = b''):
        candidate = self._new_machine(text) # validation is atomic
        try:
            debugger = Debugger(candidate, elf)
        except Exception:
            self._dispose(candidate)
            raise
        with self.lock:
            self.machine.pause_clock()
            self._replace(candidate)
            self.debugger = debugger
            self.loaded = True
            self.name, self.status = name, 'ready'
            self.diagnostics = diagnostics
            self.wake.clear()
            return self.snapshot()

    def compile(self, source, language="c"):
        result = self.compiler.compile(source) if language == "c" else self.compiler.compile(source, language=language)
        state = self.load(result.hex, 'Compiled assembly program' if language == 'asm' else 'Compiled C program', result.diagnostics, elf=getattr(result, 'elf', b''))
        return {'state':state,'hex':result.hex,'diagnostics':result.diagnostics}

    def control(self, action):
        with self.lock:
            if action in ('run','resume'):
                if not self.loaded:
                    raise ValueError('Compile or upload firmware before running.')
                if self.machine.error:
                    raise ValueError('Reset the firmware after a runtime error.')
                self.debugger.resume()
                self.status = 'running'
                self._pace = None
                self.machine.resume_clock()
                self.wake.set()
            elif action == 'pause':
                self.machine.pause_clock()
                if self.status == 'running':
                    self.status = 'paused'
                self.wake.clear()
            elif action in ('stop','reset'):
                running = self.status == 'running' and action == 'reset'
                self._reset(running)
                self.diagnostics = 'MCU reset. Ribbon cables, patch wires and jumper settings retained.'
            else:
                raise ValueError('Unknown runtime control.')
            return self.snapshot()

    def debug(self, data):
        if not isinstance(data, dict):
            raise ValueError('Expected a JSON object.')
        with self.lock:
            action = data.get('action')
            memory = None
            if action == 'state':
                pass
            elif action == 'memory':
                memory = self.debugger.memory(data.get('address'), data.get('length'))
            elif action == 'breakpoint':
                self.debugger.breakpoint(data)
            elif action == 'clear-breakpoints':
                self.debugger.breakpoints.clear()
                self.debugger._sync_hook()
            elif action == 'step':
                count = data.get('count', 1)
                if type(count) is not int or not 1 <= count <= 1000:
                    raise ValueError('Step count must be an integer from 1 to 1000.')
                if not self.loaded:
                    raise ValueError('Compile or upload firmware before stepping.')
                if self.machine.error:
                    raise ValueError('Reset the firmware after a runtime error.')
                self.machine.pause_clock()
                self.wake.clear()
                self.status = 'paused'
                self.debugger.hit = False
                self.debugger.skip = None
                self.debugger.stepping = True
                try:
                    self.machine.run(count, timeout_us=100000)
                    self.debugger.stop_reason = 'step'
                except FirmwareError as e:
                    self.status = 'error'
                    self.diagnostics = self._explain(str(e))
                    self.debugger.stop_reason = 'error'
                    raise
                finally:
                    self.debugger.stepping = False
            else:
                raise ValueError('Unknown debugger action.')
            debug = self.debugger.snapshot()
            if memory is not None:
                debug['memory'] = memory
            return {'state': self.snapshot(), 'debug': debug}

    def physical(self, data):
        with self.lock:
            b = self.machine.board
            action = data.get('action')
            if action == 'connect':
                b.connect(data.get('a'),data.get('b'))
            elif action == 'disconnect':
                if not isinstance(data.get('header'),str) or data.get('header') not in MAPPING['headers']:
                    raise ValueError('Unknown header.')
                b.disconnect(data['header'])
            elif action == 'connect-wire':
                b.connect_wire(data.get('a'), data.get('b'))
            elif action == 'disconnect-wire':
                b.disconnect_wire(data.get('a'), data.get('b'))
            elif action == 'disconnect-all':
                b.disconnect_all(data.get('kind', 'all'))
            elif action == 'jumper':
                b.set_jumper(data.get('name'),data.get('value'))
            elif action == 'switch':
                if not isinstance(data.get('pressed'),bool):
                    raise ValueError('Switch pressed must be true or false.')
                b.sw2 = data['pressed']
            elif action == 'key':
                key = data.get('key')
                if type(key) is not int or not 0 <= key < 16 or not isinstance(data.get('pressed'),bool):
                    raise ValueError('Key must be 0–15, with a boolean pressed state.')
                if data['pressed']:
                    b.keys.add(key)
                else:
                    b.keys.discard(key)
            elif action == 'pot':
                channel, voltage = data.get('channel'),data.get('voltage')
                if type(channel) is not int or channel not in (4,5) or type(voltage) not in (float,int) or not 0 <= voltage <= 3.3:
                    raise ValueError('POT voltage must be 0–3.3 V on channel 4 or 5.')
                b.pots[channel] = voltage
            elif action == 'sw2-profile':
                if data.get('pin') not in (7,9):
                    raise ValueError('SW2 profile must be CNB1 pin 7 or 9.')
                b.sw2_pin = data['pin']
                b._graph_key = None
            elif action == 'release-inputs':
                b.sw2 = False
                b.keys.clear()
                for part in b.circuit.parts.values():
                    if part.kind in ('button', 'keypad') and any(part.stimuli.values()):
                        part.stimuli = {k: (-1 if part.kind == 'keypad' else 0) for k in part.stimuli}
                        b.circuit.touch()
            else:
                raise ValueError('Unknown physical input action.')
            self.machine.observe()
            return self.snapshot()

    # -- external circuit ---------------------------------------------------------------
    def circuit(self, data):
        with self.lock:
            circuit = self.machine.board.circuit
            action = data.get('action')
            info = None
            if action == 'add':
                part = circuit.add_part(data.get('type'), data.get('id'), data.get('props'),
                                        data.get('placement'), data.get('mount'))
                info = {'id': part.id}
            elif action == 'remove':
                circuit.remove_part(data.get('id'))
            elif action == 'move':
                circuit.move(data.get('id'), data.get('placement'), data.get('mount'))
            elif action == 'props':
                circuit.set_props(data.get('id'), data.get('props'))
            elif action == 'stimulus':
                circuit.set_stimulus(data.get('id'), data.get('name'), data.get('value'))
            elif action == 'connect':
                circuit.connect(data.get('a'), data.get('b'), data.get('color', '#d33'))
            elif action == 'disconnect':
                circuit.disconnect(data.get('a'), data.get('b'))
            elif action == 'clear':
                circuit.clear()
            elif action == 'load':
                project = data.get('project') or {}
                if project.get('target', self.target) != self.target:
                    self._set_target(project['target'])
                    circuit = self.machine.board.circuit
                # Jumper wires cannot share a header with a ribbon: unplug the ribbons
                # on headers the project wires, and say so.
                board = self.machine.board
                headers = {end.split('.')[1] for wire in project.get('wires', []) if isinstance(wire, list)
                           for end in wire[:2] if isinstance(end, str) and end.startswith('kit.CN')}
                unplugged = [cable for cable in board.cables if headers & set(cable)]
                for cable in unplugged:
                    board.disconnect(cable[0])
                circuit.load(project)
                if unplugged:
                    self.diagnostics = ('Unplugged ' + ', '.join(f'{a} ↔ {b}' for a, b in unplugged)
                                        + ' so jumper wires can use those header pins.')
            elif action == 'apply':
                circuit.apply(data.get('patch'))
            elif action == 'inspect':
                info = circuit.endpoint_info(data.get('endpoint'))
                if info is None:
                    raise ValueError('Unknown endpoint.')
            elif action == 'probes':
                circuit.set_probes(data.get('endpoints'))
            elif action == 'damage-mode':
                if data.get('mode') not in ('realistic', 'warn'):
                    raise ValueError("Damage mode must be 'realistic' or 'warn'.")
                circuit.damage_mode = data['mode']
            else:
                raise ValueError('Unknown circuit action.')
            self.machine.observe()
            state = self.snapshot()
            return {'state': state, 'info': info} if info is not None else state

    def export_project(self):
        with self.lock:
            return self.machine.board.circuit.export()

    # -- serial terminals ---------------------------------------------------------------
    def serial(self, data):
        with self.lock:
            action, key = data.get('action'), str(data.get('terminal', '0'))
            terminal, part = self._terminal(key)
            if action == 'send':
                text = data.get('text')
                if not isinstance(text, str) or len(text) > 4096:
                    raise ValueError('Serial text must be at most 4096 characters.')
                payload = text.encode('latin-1', 'replace')
                if part is not None:
                    part.uart_send(payload)
                else:
                    uart = self.machine.uarts[terminal.uart]
                    if uart.pad('RXD') is None:
                        raise ValueError(f'UART{terminal.uart} has no RXD pin selected in PINSEL; '
                                         'the firmware cannot receive.')
                    terminal.send(self.machine, payload,
                                  lambda b: uart.receive(b, terminal.baud, sender='PC terminal'))
            elif action == 'baud':
                baud = data.get('baud')
                if baud not in (1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200):
                    raise ValueError('Unsupported terminal baud rate.')
                if part is not None:
                    part.configure({'baud': baud})
                else:
                    terminal.baud = baud
            elif action == 'clear':
                terminal.clear()
            else:
                raise ValueError('Unknown serial action.')
            return self.snapshot()

    def _terminal(self, key):
        if key.isdigit() and int(key) in self.terminals:
            return self.terminals[int(key)], None
        part = self.machine.board.circuit.parts.get(key)
        if part is None or not hasattr(part, 'terminal'):
            raise ValueError('Unknown serial terminal.')
        return part.terminal, part

    # -- settings ---------------------------------------------------------------------------
    def settings(self, data):
        with self.lock:
            if 'target' in data:
                if data['target'] not in TARGETS:
                    raise ValueError(f'Target must be one of {", ".join(TARGETS)}.')
                if data['target'] != self.target:
                    self._set_target(data['target'])
            if 'timing' in data:
                if data['timing'] not in TIMING_MODES:
                    raise ValueError("Timing must be 'realtime' or 'precise'.")
                if data['timing'] != self.timing:
                    self.timing = data['timing']
                    self.realtime = self.live and self.timing == 'realtime'
                    running = self.status == 'running'
                    self._reset(running)
                    self.diagnostics = ('Precise timing: every peripheral runs on instruction-derived time, '
                                        'throttled to real time when the host is fast enough.'
                                        if self.timing == 'precise' else 'Real-time timing restored.')
            if 'floating' in data:
                if data['floating'] not in ('low', 'random'):
                    raise ValueError("Floating inputs must be 'low' or 'random'.")
                self.machine.floating_mode = data['floating']
            return self.snapshot()

    def _set_target(self, target):
        running = self.status == 'running'
        self.machine.pause_clock()
        self.target = target
        candidate = self._new_machine(self.machine.hex_text)
        self._replace(candidate)
        self.debugger.attach(self.machine)
        self.status = 'running' if running else ('ready' if self.loaded else 'empty')
        if running:
            self.machine.resume_clock()
            self.wake.set()
        self.diagnostics = {'als': 'Target: ALS-SDA-ARMCTXM3-01 evaluation kit.',
                            'mbed': 'Target: mbed LPC1768 module (DIP-40, pins p5–p30).',
                            'bare': 'Target: bare LPC1768 (all LQFP100 pads).'}[target]

    def check(self, exercise):
        spec = next((e for e in CATALOG if e['id'] == exercise),None)
        if not spec:
            raise ValueError('Unknown exercise.')
        with self.lock:
            b = self.machine.board
            issues = []
            highlight = set()
            for cable in spec['cables']:
                if not any(set(cable) == set(c) for c in b.cables):
                    issues.append('Connect ' + ' ↔ '.join(cable))
                    highlight.update(cable)
            for name,setting in spec['jumpers'].items():
                if b.jumpers[name] != setting:
                    issues.append(f'Set {name} to {setting}')
                    highlight.add(name)
            if any('CNB1' in c for c in spec['cables']) and b.sw2_pin != 7:
                issues.append('This reference uses the lab SW2 profile: CNB1 pin 7.')
            for cable in b.cables:
                if not any(set(cable) == set(c) for c in spec['cables']):
                    issues.append('Extra cable: ' + ' ↔ '.join(cable) + '; verify it does not conflict.')
                    highlight.update(cable)
            # References are specified as ribbons; a wire can ground or drive a
            # pin they use, so every patch wire is reported for review.
            for wire in b.wires:
                issues.append('Patch wire: ' + ' ↔ '.join(wire) + '; the reference uses ribbon cables only.')
                highlight.update(b.endpoint(end)[0] for end in wire)
            return {'ok':not issues,'issues':issues,'highlight':sorted(highlight)}

    def snapshot(self):
        with self.lock:
            return {**self.machine.snapshot(),'status':self.status,'loaded':self.loaded,
                    'firmwareName':self.name,'diagnostics':self.diagnostics,
                    'timing': self.timing, 'speed': round(self.speed, 3),
                    'floating': self.machine.floating_mode}
