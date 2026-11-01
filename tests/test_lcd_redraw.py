"""Observe redraw chronology through compiled GPIO firmware, without display injection.

This tests controller state, not optical response or instruction timing compliance.
"""
from test_display_fidelity import build, lcd_machine, lcd_send


def test_compiled_redraw_exposes_clear_and_each_new_prefix(build):
    m = lcd_machine(build)
    blank = [' ' * 16] * 2
    for char in 'OLD':
        lcd_send(m, ord(char), 1)
    old = ['OLD' + ' ' * 13, ' ' * 16]
    assert m.snapshot()['lcd'] == old

    # First nibble of clear must not execute a complete command.
    assert lcd_send(m, 0, single=True) == old
    assert lcd_send(m, 1, single=True) == blank
    # No later write is required to make the clear observable.
    m.run(20000)
    assert m.snapshot()['lcd'] == blank

    observed = []
    for char in 'NEW':
        observed.append(lcd_send(m, ord(char), 1))
    assert observed == [
        ['N' + ' ' * 15, ' ' * 16],
        ['NE' + ' ' * 14, ' ' * 16],
        ['NEW' + ' ' * 13, ' ' * 16],
    ]
    m.run(20000)
    assert m.snapshot()['lcd'] == observed[-1]

    # The ADC references erase with spaces, rather than command 0x01.
    lcd_send(m, 0x80)
    assert lcd_send(m, ord(' '), 1) == [' EW' + ' ' * 13, ' ' * 16]
    assert lcd_send(m, ord(' '), 1) == ['  W' + ' ' * 13, ' ' * 16]
    assert lcd_send(m, ord(' '), 1) == blank
