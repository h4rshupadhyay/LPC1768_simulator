import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('script', ['test_c_course_outputs.py', 'test_assembly_corpus.py'])
def test_full_study_report_requires_external_corpus_before_execution(script, tmp_path):
    env = dict(os.environ)
    env.pop('CURRICULAR_ES', None)
    output = tmp_path / 'report.json'
    result = subprocess.run([sys.executable, str(ROOT / 'tools' / script), '--output', str(output)],
                            env=env, cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert result.returncode == 2
    assert 'requires --corpus' in result.stderr
    assert 'Traceback' not in result.stderr
    assert not output.exists()


def test_explicit_bundled_probe_records_selected_coverage(tmp_path):
    env = dict(os.environ)
    env.pop('CURRICULAR_ES', None)
    output = tmp_path / 'report.json'
    result = subprocess.run([sys.executable, str(ROOT / 'tools/test_c_course_outputs.py'),
                             '--only', 'Lab6/init.c', '--opts', '2', '--output', str(output)],
                            env=env, cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text())
    assert report['scope'] == 'selected probes'
    assert report['selected_probes'] == ['Lab6/init.c']
    assert len(report['rows']) == 1
    assert report['model_mismatches'] == []
