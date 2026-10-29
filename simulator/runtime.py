"""One bounded firmware worker; all mutations serialize with CPU execution."""
from __future__ import annotations
from pathlib import Path
import json
import threading
import time

from .engine import Machine, FirmwareError
from .compiler import Compiler
from .board import MAPPING
from .debugger import Debugger

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / 'examples/catalog.json').read_text(encoding='utf-8'))


class Runtime:
    def __init__(self, start_worker=True, *, realtime=None):
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.closed = threading.Event()
        self.realtime = start_worker if realtime is None else realtime
        self.machine = Machine((ROOT / 'examples/idle.hex').read_text(), realtime=self.realtime)
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

    def _worker(self):
        while not self.closed.is_set():
            self.wake.wait(.1)
            if not self.wake.is_set():
                continue
            self._run_slice()
            # Yield to API/input threads without adding a 2 ms floor to each
            # firmware slice (the user's timer polling interval can be 1 ms).
            time.sleep(0)

    def _run_slice(self):
        with self.lock:
            if self.status != 'running':
                self.wake.clear()
                return
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
                if self.debugger.hit:
                    self.machine.pause_clock()
                    self.status = 'paused'
                    self.wake.clear()
            except FirmwareError as e:
                self.status = 'error'
                self.diagnostics = str(e)
                self.wake.clear()
                self.machine.pause_clock()

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
        candidate.observe()
        self.machine = candidate
        self._dispose(previous)

    def load(self, text, name='Uploaded HEX', diagnostics='HEX loaded and validated.', *, elf: bytes = b''):
        candidate = Machine(text, realtime=self.realtime) # validation is atomic
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
                self.machine.resume_clock()
                self.wake.set()
            elif action == 'pause':
                self.machine.pause_clock()
                if self.status == 'running':
                    self.status = 'paused'
                self.wake.clear()
            elif action in ('stop','reset'):
                running = self.status == 'running' and action == 'reset'
                self.machine.pause_clock()
                self._replace(Machine(self.machine.hex_text, realtime=self.realtime))
                self.debugger.attach(self.machine)
                self.status = 'running' if running else ('ready' if self.loaded else 'empty')
                self.diagnostics = 'MCU reset. Ribbon cables, patch wires and jumper settings retained.'
                if running:
                    self.machine.resume_clock()
                    self.wake.set()
                else:
                    self.wake.clear()
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
                    self.diagnostics = str(e)
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
            else:
                raise ValueError('Unknown physical input action.')
            self.machine.observe()
            return self.snapshot()

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
                    'firmwareName':self.name,'diagnostics':self.diagnostics}
