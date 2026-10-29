#!/usr/bin/env python3
"""Bounded board-model keypad campaign; no firmware or physical hardware involved."""
import argparse
import hashlib
import json
import random
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from simulator.board import Board


class Pins:
    def __init__(self):
        self.rows = 0

    def pin_output(self, port, pin):
        if port == 2 and 10 <= pin <= 13:
            return (self.rows >> (pin - 10)) & 1
        return None

    def pin_pull(self, port, pin):
        return 1

    def observe(self):
        pass


def oracle(keys, rows):
    """Reachability over eight matrix vertices, with directed row sources."""
    adjacency = [0] * 8
    for bit in range(16):
        if keys & (1 << bit):
            row, col = divmod(bit, 4)
            adjacency[row] |= 1 << (col + 4)
            adjacency[col + 4] |= 1 << row
    reached = rows
    frontier = rows
    while frontier:
        vertex = (frontier & -frontier).bit_length() - 1
        frontier &= frontier - 1
        new = adjacency[vertex] & ~reached
        reached |= new
        frontier |= new
    return reached >> 4


def campaign(complete=False, seed=1768, fast_count=1024):
    pins = Pins()
    board = Board(pins)
    board.connect('CNB', 'CNB3')
    board.set_jumper('JP4', '1-2')
    cases = range(65536) if complete else sorted(random.Random(seed).sample(range(65536), fast_count))
    digest = hashlib.sha256()
    failures = []
    count = 0
    failure_count = 0
    for keys in cases:
        board.keys = {i for i in range(16) if keys & (1 << i)}
        for rows in (1, 2, 4, 8):
            pins.rows = rows
            levels = board.signals()
            actual = sum(levels.get(f'COL{i}', 0) << i for i in range(4))
            expected = oracle(keys, rows)
            digest.update(struct.pack('<HBBB', keys, rows, expected, actual))
            count += 1
            if actual != expected:
                failure_count += 1
            if actual != expected and len(failures) < 10:
                failures.append(dict(keys=f'0x{keys:04x}', rows=rows, expected=expected, actual=actual))
    return dict(mode='complete' if complete else 'fast', seed=seed, vectors=count,
                sha256=digest.hexdigest(), failure_count=failure_count, failures=failures)


class ReversePins:
    def __init__(self):
        self.selected = 0

    def pin_output(self, port, pin):
        if port == 1 and 23 <= pin <= 26:
            return int(pin - 23 != self.selected)
        return None

    def pin_pull(self, port, pin):
        return 1

    def observe(self):
        pass


def reverse_oracle(keys, selected):
    # Independently expand a connected component from the selected low
    # column across closed switches. Row diodes then pull reached inputs low.
    columns = {selected}
    rows = set()
    while True:
        new_rows = {r for r in range(4) for c in columns if keys & (1 << (4*r+c))}
        new_columns = {c for c in range(4) for r in new_rows if keys & (1 << (4*r+c))}
        if new_rows == rows and new_columns == columns:
            return 15 ^ sum(1 << r for r in rows)
        rows, columns = new_rows, new_columns


def reverse_campaign(complete=False, seed=1768, fast_count=1024):
    pins = ReversePins()
    board = Board(pins)
    board.connect('CNB', 'CNB3')
    board.set_jumper('JP4', '1-2')
    cases = range(65536) if complete else sorted(random.Random(seed).sample(range(65536), fast_count))
    digest = hashlib.sha256()
    failures = []
    failure_count = count = 0
    for keys in cases:
        board.keys = {i for i in range(16) if keys & (1 << i)}
        for col in range(4):
            pins.selected = col
            levels = board.signals()
            actual = sum(levels.get(f'ROW{i}', 0) << i for i in range(4))
            expected = reverse_oracle(keys, col)
            digest.update(struct.pack('<HBBB', keys, col, expected, actual))
            count += 1
            if actual != expected:
                failure_count += 1
                if len(failures) < 10:
                    failures.append(dict(keys=f'0x{keys:04x}', column=col, expected=expected, actual=actual))
    return dict(mode='reverse-complete' if complete else 'reverse-fast', seed=seed,
                vectors=count, sha256=digest.hexdigest(), failure_count=failure_count, failures=failures)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--complete', action='store_true')
    parser.add_argument('--reverse', action='store_true')
    parser.add_argument('--seed', type=int, default=1768)
    parser.add_argument('--fast-count', type=int, default=1024, choices=range(1, 65537), metavar='1..65536')
    args = parser.parse_args()
    result = (reverse_campaign if args.reverse else campaign)(args.complete, args.seed, args.fast_count)
    print(json.dumps(result, sort_keys=True))
    return bool(result['failures'])


if __name__ == '__main__':
    sys.exit(main())
