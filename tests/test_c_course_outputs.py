"""Fast O2 subset of tools/test_c_course_outputs.py on unchanged Unlicense fixtures.

The full O0..O3 ledger over all 26 C sources is the tool itself; this keeps a
bounded regression for the exact output oracles.  A row passes here only if
the actual firmware trace equals the source-derived oracle; the per-source
status (including original-logic and wiring findings) is asserted separately.
"""
import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CORPUS = Path(os.environ.get('CURRICULAR_ES', ROOT / 'fixtures/curricular'))
spec = importlib.util.spec_from_file_location('c_course_outputs', ROOT / 'tools/test_c_course_outputs.py')
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

CASES = [
    ('Lab/Lab6/init.c', tool.probe_init, 'PASS_INTENDED_OUTPUT'),
    ('Lab/Lab6/BinaryUpCounter.c', tool.probe_binary_up_counter, 'ORIGINAL_LOGIC_ISSUE'),
    ('Lab/Lab7/BinaryUP_PIN.c', tool.probe_binary_up_pin, 'PASS_INTENDED_OUTPUT'),
    ('Lab/Lab7/JOHNSON_Up_Down_Same_GPIO.c', tool.johnson_same, 'PASS_INTENDED_OUTPUT'),
    ('Lab/Lab7/JOHNSON_Up_Down_Separate_GPIO.c', tool.johnson_separate, 'ORIGINAL_LOGIC_ISSUE'),
    ('Lab/Lab7/SwitchCounter.c', lambda l: tool.switch_counters(l, 'Lab/Lab7/SwitchCounter.c'), 'ORIGINAL_LOGIC_ISSUE'),
    ('Lab/Lab7/SwitchUPDOWN.c', lambda l: tool.switch_counters(l, 'Lab/Lab7/SwitchUPDOWN.c'), 'ORIGINAL_LOGIC_ISSUE'),
    ('Lab/Lab8/16KeyMatrixOn7Seg.c', lambda l: tool.keypad_seven(l, 'Lab/Lab8/16KeyMatrixOn7Seg.c'), 'PASS_INTENDED_OUTPUT'),
    ('Lab/Lab9/LCD_UPPERLINE.c', lambda l: tool.lcd_text(l, 'Lab/Lab9/LCD_UPPERLINE.c', 'We have fun.', ''), 'PASS_INTENDED_OUTPUT'),
    ('Lab/Lab9/LCD_LOWERLINE.c', lambda l: tool.lcd_text(l, 'Lab/Lab9/LCD_LOWERLINE.c', '', 'Santhosh Sir Gr8'), 'PASS_INTENDED_OUTPUT'),
    ('Lab/Lab9/LCD_DOUBLELINE.c', lambda l: tool.lcd_text(l, 'Lab/Lab9/LCD_DOUBLELINE.c', 'Long messages wo', 'rk well, heh.'), 'PASS_INTENDED_OUTPUT'),
    ('Lab/Lab10/ADC.c', tool.adc_plain, 'ORIGINAL_LOGIC_ISSUE'),
    ('Lab/Lab11/PWM_Keyboard.c', tool.pwm_keyboard, 'WIRING_MISMATCH'),
]


@pytest.mark.parametrize(('source', 'probe', 'status'), CASES, ids=[c[0] for c in CASES])
def test_original_source_output_matches_independent_oracle(source, probe, status):
    ledger = tool.Ledger(CORPUS, [2])
    probe(ledger)
    (row,) = [r for r in ledger.rows if r['source'] == source]
    assert row['model_matches_source'] is True, row['actual']
    assert row['status'] == status
