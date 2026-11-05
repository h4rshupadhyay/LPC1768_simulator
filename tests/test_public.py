"""Public hosting mode: per-visitor simulators, allowed callers, compile safeguards."""
import pytest

from simulator.compiler import CompileError, Compiler, check_assembly
from simulator.public import AtCapacity, SessionPool, validate_source
from simulator.runtime import Runtime
from simulator.server import create_app

A = 'a' * 24
B = 'b' * 24
HOST = 'https://lpc.example.hf.space'


class FakeRuntime:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def test_pool_gives_each_session_its_own_runtime_and_reuses_it():
    pool = SessionPool(FakeRuntime, limit=2)
    first = pool.get(A)
    assert pool.get(A) is first
    assert pool.get(B) is not first
    with pytest.raises(AtCapacity):
        pool.get('c' * 24)


@pytest.mark.parametrize('bad', [None, '', 'short', 'x' * 65, 'a' * 20 + '/../', 'a' * 20 + ' '])
def test_pool_rejects_invalid_session_ids(bad):
    with pytest.raises(ValueError):
        SessionPool(FakeRuntime).get(bad)


def test_pool_closes_idle_runtimes():
    clock = Clock()
    pool = SessionPool(FakeRuntime, idle_seconds=60, clock=clock)
    old = pool.get(A)
    clock.now = 30
    fresh = pool.get(B)
    clock.now = 80
    assert pool.sweep() == 1
    assert old.closed and not fresh.closed
    assert pool.get(A) is not old


@pytest.mark.parametrize('source', [
    '#include <LPC17xx.h>\n#include <stdio.h>\n#include "sys/types.h"\nint main(void){}',
    '#  include <LPC17xx.h> // comment\nint main(void){}',
    # Mentioning a directive inside a string is not a directive line.
    'int main(void){ const char *s = "#include /etc/passwd"; return 0; }',
])
def test_validate_accepts_ordinary_programs(source):
    validate_source(source)


@pytest.mark.parametrize('source', [
    '#include "/etc/passwd"',
    '#include </etc/passwd>',
    '#include "../simulator/server.py"',
    '#include "C:\\\\Windows\\\\win.ini"',
    '#define F "/etc/passwd"\n#include F',
    '#include_next <stdio.h>',
    '#import "x.h"',
    '??=include "/etc/passwd"',
    '%:include "/etc/passwd"',
    '#inc\\\nlude "/etc/passwd"',
    'const char data[] = {\n#embed "/etc/passwd"\n};',
    '__asm__(".incbin \\"/etc/passwd\\"");',
])
def test_validate_rejects_file_reading_source(source):
    with pytest.raises(ValueError):
        validate_source(source)


@pytest.mark.parametrize('text', [
    '.incbin "/etc/passwd"', '  .include "x.s"', '.macro m a\n.inc\\a "x"\n.endm', '.irp x,1,2\n.endr',
    '.rept 3\n.endr', '.altmacro',
])
def test_check_assembly_rejects_file_directives(text):
    with pytest.raises(CompileError):
        check_assembly(text)


def test_check_assembly_accepts_compiler_output():
    check_assembly('\t.text\n\t.file\t"main.c"\n\t.section\t.text.main,"ax",%progbits\n'
                   '\t.asciz\t"toolchain/sysroot/include"\nmain:\n\tbx lr\n')


@pytest.fixture
def public_client():
    pool = SessionPool(FakeRuntime, limit=3)
    app = create_app(public=True, pool=pool, allowed_hosts=['lpc.example.hf.space', 'localhost'],
                     allowed_origins=['https://lpc-sim*.vercel.app'])
    return app.test_client(), pool


def test_public_mode_requires_a_session_and_allows_configured_callers(public_client):
    client, pool = public_client
    # Static data needs no simulator.
    assert client.get('/api/parts', base_url=HOST).status_code == 200
    assert client.get('/api/bench-examples', base_url=HOST).status_code == 200
    # Simulator calls need a session id.
    assert client.get('/api/state', base_url=HOST).status_code == 400
    # Unknown hosts and foreign origins are refused.
    assert client.get('/api/parts', base_url='https://evil.example').status_code == 403
    assert client.get('/api/parts', base_url=HOST,
                      headers={'Origin': 'https://evil.example'}).status_code == 403
    for origin in (HOST, 'https://lpc-sim.vercel.app', 'https://lpc-sim-git-main-me.vercel.app'):
        assert client.get('/api/parts', base_url=HOST, headers={'Origin': origin}).status_code == 200
    assert len(pool) == 0


def test_public_mode_rejects_unsafe_compile_before_creating_work(public_client):
    client, pool = public_client
    response = client.post('/api/compile', base_url=HOST, headers={'X-LPC-Session': A},
                           json={'source': '#include "/etc/passwd"\nint main(void){}'})
    assert response.status_code == 400
    assert 'not allowed' in response.get_json()['error']


def test_public_mode_runs_one_simulator_per_visitor():
    pool = SessionPool(lambda: Runtime(start_worker=False, restricted=True), limit=4)
    client = create_app(public=True, pool=pool, allowed_hosts=[]).test_client()
    try:
        one = {'X-LPC-Session': A}
        two = {'X-LPC-Session': B}
        assert client.post('/api/control', base_url=HOST, headers=one, json={'action': 'run'}).status_code in (200, 400)
        state_one = client.get('/api/state', base_url=HOST, headers=one).get_json()
        state_two = client.get('/api/state', base_url=HOST, headers=two).get_json()
        assert state_one is not None and state_two is not None
        assert len(pool) == 2
        info = client.get('/api/info', base_url=HOST, headers=one).get_json()
        assert info['public'] is True and info['compiler']['path'] == ''
    finally:
        pool.close_all()


def test_restricted_compiler_still_builds_normal_firmware():
    compiler = Compiler(restricted=True)
    if not compiler.command:
        pytest.skip('No compiler installed')
    result = compiler.compile('#include <LPC17xx.h>\nint main(void){ LPC_GPIO0->FIODIR = 1; while(1); }')
    assert result.hex.startswith(':')


@pytest.mark.parametrize('source', [
    # String escapes and literal concatenation hide the directive from a source scan.
    '__asm__(".inc" "\\x62in \\"main.c\\"");\nint main(void){ while(1); }',
    'int main(void){ __asm volatile("nop\\n\\t.inc" "lude \\"main.c\\""); while(1); }',
    '#define S(x) #x\n__asm__(S(.ma) "cro m a\\n.endm");\nint main(void){ while(1); }',
])
def test_restricted_compiler_blocks_obfuscated_inline_directives(source):
    compiler = Compiler(restricted=True)
    if not compiler.command:
        pytest.skip('No compiler installed')
    with pytest.raises(CompileError, match='disabled on the public simulator'):
        compiler.compile(source)


def test_local_mode_is_unchanged():
    rt = Runtime(start_worker=False)
    try:
        client = create_app(rt).test_client()
        assert client.get('/api/state').status_code == 200
        assert client.get('/api/state', base_url='https://lpc.example.hf.space').status_code == 403
    finally:
        rt.close()
