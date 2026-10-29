"""Explicit WASM disposal ownership, exercised through the common Runtime."""
import pytest
from unicorn import Uc

from simulator.runtime import Runtime


def test_failed_elf_load_disposes_candidate_without_closing_current(monkeypatch):
    disposed = []
    monkeypatch.setattr(Uc, 'close', lambda uc: disposed.append(uc), raising=False)
    rt = Runtime(start_worker=False)
    old = rt.machine
    for _ in range(3):
        with pytest.raises(ValueError):
            rt.load(old.hex_text, elf=b'invalid ELF')
        assert rt.machine is old
        assert old.uc not in disposed
    assert len(disposed) == 3
    rt.load(old.hex_text)
    assert disposed[-1] is old.uc
    current = rt.machine.uc
    rt.close()
    assert disposed[-1] is current
