"""Reproducible evidence for the hardware audit; no production instrumentation.

Each audited pytest case has metadata, real initial registers, firmware hash,
physical setup, final device/render state and bounded MMIO trace. Large finite
sweeps additionally emit their per-vector records in the test modules.
"""
from collections import deque
import hashlib
import json
import os
from pathlib import Path

import pytest

from simulator.engine import Machine


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    setattr(item, 'audit_' + report.when, report)
    if report.when == 'teardown' and hasattr(item, '_hardware_audit_entry'):
        folder, entry = item._hardware_audit_entry
        phases = {phase: getattr(item, 'audit_' + phase, None)
                  for phase in ('setup', 'call', 'teardown')}
        entry['phases'] = {phase: result.outcome for phase, result in phases.items() if result}
        failed = [(phase, result) for phase, result in phases.items() if result and result.failed]
        if failed:
            entry['status'] = 'ERROR' if any(phase != 'call' for phase, _ in failed) else 'FAIL'
            entry['failure'] = '\n'.join(result.longreprtext for _, result in failed)
        elif any(result and result.skipped for result in phases.values()):
            entry['status'] = 'SKIP'
        else:
            entry['status'] = 'PASS' if phases['call'] and phases['call'].passed else 'ERROR'
        with (folder / 'cases.jsonl').open('a', encoding='utf-8') as output:
            output.write(json.dumps(entry, ensure_ascii=False) + '\n')


@pytest.fixture(autouse=True)
def hardware_audit_evidence(request, monkeypatch):
    if not any(part in request.node.name or part in request.node.path.name
               for part in ('fidelity', 'exhaustive', 'exercise_requirements')):
        yield
        return
    machines = []
    originals = {name: getattr(Machine, name) for name in ('__init__', 'read_word', 'write_word')}

    def init(machine, *args, **kwargs):
        originals['__init__'](machine, *args, **kwargs)
        machine._audit_trace = deque(maxlen=128)
        machine._audit_initial = dict(machine.regs)
        machine._audit_initial_gpio = [vars(g).copy() for g in machine.gpio]
        machines.append(machine)

    def read(machine, address):
        result = originals['read_word'](machine, address)
        if hasattr(machine, '_audit_trace'):
            machine._audit_trace.append(['read', machine.ticks, machine.elapsed_ns, hex(address), hex(result)])
        return result

    def write(machine, address, value, mask=0xFFFFFFFF):
        if hasattr(machine, '_audit_trace'):
            machine._audit_trace.append(['write', machine.ticks, machine.elapsed_ns, hex(address), hex(value), hex(mask)])
        return originals['write_word'](machine, address, value, mask)

    monkeypatch.setattr(Machine, '__init__', init)
    monkeypatch.setattr(Machine, 'read_word', read)
    monkeypatch.setattr(Machine, 'write_word', write)
    # Module-scoped compiled-program fixtures can predate this function's
    # instrumentation. Capture their actual state at the start of each case.
    for existing in request.node.funcargs.values():
        if isinstance(existing, Machine):
            existing._audit_trace = deque(maxlen=128)
            existing._audit_initial = dict(existing.regs)
            existing._audit_initial_gpio = [vars(g).copy() for g in existing.gpio]
            machines.append(existing)
    yield
    report = getattr(request.node, 'audit_call', None)
    folder = Path(os.environ.get('LPC_AUDIT_EVIDENCE_DIR', 'build/hardware-audit'))
    (folder / 'firmware').mkdir(parents=True, exist_ok=True)
    entry = {'id': request.node.nodeid, 'status': 'FAIL' if report and report.failed else 'PASS',
             'source': 'HARDWARE_SPEC.md; independent assertions in ' + str(request.node.path.name),
             'expected': 'See independent register/pin/render assertions in the identified test',
             'confidence': 'document-backed ideal digital model; no physical measurements',
             'properties': request.node.user_properties, 'machines': []}
    for machine in machines:
        digest = hashlib.sha256(machine.hex_text.encode()).hexdigest()
        firmware = folder / 'firmware' / (digest + '.hex')
        if not firmware.exists():
            firmware.write_text(machine.hex_text, encoding='ascii')
        entry['machines'].append({
            'firmware_sha256': digest, 'initial_registers': machine._audit_initial,
            'initial_gpio': machine._audit_initial_gpio,
            'final_registers': dict(machine.regs), 'observed': machine.snapshot(),
            'trace': list(machine._audit_trace),
        })
    if report and report.failed:
        entry['failure'] = report.longreprtext
    # Final status is assigned by makereport after all fixture teardowns finish.
    request.node._hardware_audit_entry = (folder, entry)
