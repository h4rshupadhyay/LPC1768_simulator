"""Public hosting: one simulator per visitor, and compile safeguards.

Locally the app serves one person with one shared simulator. On a public host
(LPC_PUBLIC=1) every browser tab sends a random session id in the
X-LPC-Session header and gets its own Runtime; idle ones are closed. Visitors
may compile C, but only against the project's own headers: source that could
read other files on the server (absolute or parent-relative includes, macro
includes, #embed, .incbin/.include) is rejected before the compiler runs.
"""
from __future__ import annotations

import re
import threading
import time

SESSION_ID = re.compile(r'[A-Za-z0-9_-]{16,64}')
INCLUDE = re.compile(r'^[ \t]*#[ \t]*(include_next|include|import)\b[ \t]*(.*)$', re.MULTILINE)
SAFE_HEADER = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_./+-]{0,120}')
FORBIDDEN = re.compile(r'#[ \t]*embed\b|__has_embed|\.incbin\b|\.include\b|\bincbin\b', re.IGNORECASE)


class AtCapacity(RuntimeError):
    pass


class SessionPool:
    """Runtimes keyed by visitor session id, closed after `idle_seconds` unused."""

    def __init__(self, factory, *, limit=12, idle_seconds=900, clock=time.monotonic):
        self.factory = factory
        self.limit = limit
        self.idle_seconds = idle_seconds
        self.clock = clock
        self.lock = threading.Lock()
        self.entries = {}  # session id -> [runtime, last used]

    def get(self, session_id):
        if not isinstance(session_id, str) or not SESSION_ID.fullmatch(session_id):
            raise ValueError('Missing or invalid X-LPC-Session header; reload the page.')
        self.sweep()
        with self.lock:
            entry = self.entries.get(session_id)
            if entry is None:
                if len(self.entries) >= self.limit:
                    raise AtCapacity(f'The simulator is serving its maximum of {self.limit} visitors. '
                                     'Please try again in a few minutes.')
                entry = self.entries[session_id] = [self.factory(), self.clock()]
            entry[1] = self.clock()
            return entry[0]

    def sweep(self):
        now = self.clock()
        with self.lock:
            idle = [sid for sid, (_, used) in self.entries.items() if now - used > self.idle_seconds]
            closing = [self.entries.pop(sid)[0] for sid in idle]
        for runtime in closing:
            runtime.close()
        return len(closing)

    def close_all(self):
        with self.lock:
            closing = [runtime for runtime, _ in self.entries.values()]
            self.entries.clear()
        for runtime in closing:
            runtime.close()

    def __len__(self):
        return len(self.entries)


def _normalize(source):
    """Undo the spellings the preprocessor accepts for '#' and line splices."""
    source = source.replace('??=', '#').replace('%:', '#')
    return re.sub(r'\\[ \t]*\r?\n', '', source)


def validate_source(source, language='c'):
    """Reject source that could make the compiler read files outside the project."""
    if not isinstance(source, str):
        raise ValueError('Expected source text.')
    text = _normalize(source)
    if found := FORBIDDEN.search(text):
        raise ValueError(f'"{found.group(0).strip()}" is disabled on the public simulator: '
                         'it can read files from the server.')
    if language == 'asm':
        return
    for match in INCLUDE.finditer(text):
        if match.group(1) != 'include':
            raise ValueError(f'#{match.group(1)} is disabled on the public simulator; use #include.')
        argument = re.sub(r'/\*.*?\*/|//.*$', '', match.group(2)).strip()
        if len(argument) < 3 or (argument[0], argument[-1]) not in (('<', '>'), ('"', '"')):
            raise ValueError(f'Only literal includes such as #include <LPC17xx.h> are allowed on the '
                             f'public simulator (line: {match.group(0).strip()[:80]}).')
        name = argument[1:-1]
        if not SAFE_HEADER.fullmatch(name) or '..' in name or name.startswith('/'):
            raise ValueError(f'#include {argument[:80]} is not allowed on the public simulator: '
                             'only the project headers and the C library headers can be included.')
