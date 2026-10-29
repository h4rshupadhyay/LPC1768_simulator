"""The evidence ledger must retain pytest setup/teardown errors and skips."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('phase,expected,exit_code', [
    ('setup', 'ERROR', 1), ('teardown', 'ERROR', 1), ('skip', 'SKIP', 0),
])
def test_audit_uses_final_pytest_outcome(tmp_path, phase, expected, exit_code):
    (tmp_path / 'conftest.py').write_bytes((ROOT / 'tests/conftest.py').read_bytes())
    program = '''import pytest
@pytest.fixture
def controlled():
    if PHASE == 'setup':
        raise RuntimeError('controlled setup failure')
    if PHASE == 'skip':
        pytest.skip('controlled skip')
    yield
    if PHASE == 'teardown':
        raise RuntimeError('controlled teardown failure')
def test_case(controlled):
    assert True
'''.replace('PHASE', repr(phase))
    (tmp_path / 'test_fidelity_evidence_status.py').write_text(program)
    evidence = tmp_path / 'evidence'
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:faulthandler',
                             str(tmp_path / 'test_fidelity_evidence_status.py')],
                            capture_output=True, text=True, timeout=30,
                            env={**os.environ, 'PYTHONPATH': str(ROOT),
                                 'LPC_AUDIT_EVIDENCE_DIR': str(evidence)})
    assert result.returncode == exit_code, result.stdout + result.stderr
    records = [json.loads(line) for line in (evidence / 'cases.jsonl').read_text().splitlines()]
    assert len(records) == 1
    assert records[0]['status'] == expected
    assert records[0]['phases']['setup' if phase == 'setup' else 'teardown' if phase == 'teardown' else 'setup'] == ('skipped' if phase == 'skip' else 'failed')
