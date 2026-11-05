"""API and production frontend server.

Local (default): loopback only, one shared simulator.
Public (LPC_PUBLIC=1): any allowed host, one simulator per visitor session and
restricted compilation; see simulator/public.py and docs/DEPLOY.md.
"""
from fnmatch import fnmatch
from pathlib import Path
from urllib.parse import urlsplit
import atexit
import os
import base64
import binascii
import json
import threading

from flask import Flask, request, jsonify, send_from_directory
from werkzeug.exceptions import HTTPException

from .runtime import Runtime, ROOT, CATALOG
from .board import MAPPING
from .public import SessionPool, AtCapacity, validate_source


def _env_list(name):
    return [item.strip() for item in os.environ.get(name, '').split(',') if item.strip()]


def _host_name(host):
    # Strip the port; bracketed IPv6 literals such as [::1]:8765 keep their colons.
    return host[1:host.index(']')] if host.startswith('[') and ']' in host else host.split(':')[0]


def create_app(runtime=None, *, public=None, pool=None, allowed_hosts=None, allowed_origins=None):
    app = Flask(__name__, static_folder=None)
    app.json.sort_keys = False
    app.config['MAX_CONTENT_LENGTH'] = 3_500_000
    if public is None:
        public = os.environ.get('LPC_PUBLIC', '').lower() in ('1', 'true', 'yes')
    app.extensions['public'] = public
    rt = None
    compile_slots = None
    if public:
        # Hosts the server answers to (empty: any) and other sites allowed to
        # call it, such as the Vercel frontend that proxies /api here.
        allowed_hosts = _env_list('LPC_ALLOWED_HOSTS') if allowed_hosts is None else allowed_hosts
        allowed_origins = _env_list('LPC_ALLOWED_ORIGINS') if allowed_origins is None else allowed_origins
        if pool is None:
            pool = SessionPool(lambda: Runtime(restricted=True),
                               limit=int(os.environ.get('LPC_MAX_SESSIONS', '8')),
                               idle_seconds=int(os.environ.get('LPC_IDLE_SECONDS', '300')))
            atexit.register(pool.close_all)

            def sweeper():
                while True:
                    threading.Event().wait(30)
                    pool.sweep()
            threading.Thread(target=sweeper, name='lpc1768-session-sweeper', daemon=True).start()
        app.extensions['sessions'] = pool
        compile_slots = threading.BoundedSemaphore(int(os.environ.get('LPC_COMPILE_SLOTS', '2')))
    else:
        rt = runtime or Runtime()
        app.extensions['runtime'] = rt
        if runtime is None:
            atexit.register(rt.close)

    def current():
        """The simulator this request talks to."""
        return pool.get(request.headers.get('X-LPC-Session')) if public else rt

    @app.before_request
    def allowed_caller():
        origin = request.headers.get('Origin')
        host = _host_name(request.host)
        if public:
            if origin and urlsplit(origin).netloc != request.host and not any(
                    fnmatch(origin.rstrip('/'), pattern) for pattern in allowed_origins):
                return jsonify(error='This origin may not use the simulator API.'),403
            if allowed_hosts and not any(fnmatch(host, pattern) for pattern in allowed_hosts):
                return jsonify(error='Unknown host.'),403
            return None
        # Same-origin browser API; the Vite development server proxies /api.
        if origin and origin.rstrip('/') != request.host_url.rstrip('/'):
            return jsonify(error='This local API accepts same-origin requests only.'),403
        if host not in ('127.0.0.1','localhost','::1','test.local'):
            return jsonify(error='Use localhost or 127.0.0.1.'),403

    @app.errorhandler(AtCapacity)
    def busy(error):
        return jsonify(error=str(error)),503

    @app.errorhandler(ValueError)
    def invalid(error):
        return jsonify(error=str(error)),400

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description),error.code

    def body():
        data = request.get_json()
        if not isinstance(data,dict):
            raise ValueError('Expected a JSON object.')
        return data

    @app.get('/api/info')
    def info():
        sim = current()
        compiler = sim.compiler.info() | ({'path': ''} if public else {})
        return jsonify(board=MAPPING,compiler=compiler,exercises=CATALOG,
                       backend='Unicorn 2.1.4 / Cortex-M3', public=public,
                       timing='Real elapsed time for timers/PWM; host-limited CPU' if sim.realtime
                       else 'Deterministic instruction ticks (offline)')

    @app.get('/api/state')
    def state():
        return jsonify(current().snapshot())

    @app.get('/api/examples/<name>')
    def example(name):
        spec = next((s for s in CATALOG if s['id'] == name),None)
        if not spec:
            raise ValueError('Unknown reference example.')
        return jsonify(source=(ROOT/'examples'/spec['file']).read_text(encoding='utf-8'))

    @app.post('/api/compile')
    def compile_code():
        data = body()
        source, language = data.get('source'), data.get('language', 'c')
        if not isinstance(source,str):
            raise ValueError('Expected C source text.')
        sim = current()
        if not public:
            return jsonify(sim.compile(source, language))
        validate_source(source, language)
        if not compile_slots.acquire(timeout=45):
            raise AtCapacity('The compiler is busy with other visitors. Try again in a moment.')
        try:
            return jsonify(sim.compile(source, language))
        finally:
            compile_slots.release()

    @app.post('/api/firmware')
    def firmware():
        data = body()
        name = data.get('name','Uploaded HEX')
        if not isinstance(name,str) or len(name)>200:
            raise ValueError('Firmware filename must be at most 200 characters.')
        try:
            elf = base64.b64decode(data.get('elfBase64', ''), validate=True)
        except (ValueError, TypeError, binascii.Error) as e:
            raise ValueError('Invalid base64 ELF.') from e
        return jsonify(current().load(data.get('hex'), name, elf=elf))

    @app.post('/api/control')
    def control():
        return jsonify(current().control(body().get('action')))

    @app.post('/api/debug')
    def debug():
        return jsonify(current().debug(body()))

    @app.post('/api/physical')
    def physical():
        return jsonify(current().physical(body()))

    @app.post('/api/check')
    def check():
        return jsonify(current().check(body().get('exercise')))

    bench_examples = json.loads((ROOT / 'examples/bench/catalog.json').read_text(encoding='utf-8'))

    @app.get('/api/bench-examples')
    def bench_example_list():
        return jsonify(examples=[{k: e[k] for k in ('id', 'title', 'description', 'timing')}
                                 | {'target': e['project']['target']} for e in bench_examples])

    @app.get('/api/bench-examples/<name>')
    def bench_example(name):
        spec = next((e for e in bench_examples if e['id'] == name), None)
        if not spec:
            raise ValueError('Unknown bench example.')
        return jsonify(source=(ROOT / 'examples/bench' / spec['file']).read_text(encoding='utf-8'),
                       project=spec['project'], timing=spec['timing'], title=spec['title'])

    @app.get('/api/parts')
    def parts():
        from .parts import catalog
        return jsonify(parts=catalog())

    @app.post('/api/circuit')
    def circuit():
        return jsonify(current().circuit(body()))

    @app.get('/api/project')
    def project():
        return jsonify(current().export_project())

    @app.post('/api/serial')
    def serial():
        return jsonify(current().serial(body()))

    @app.post('/api/settings')
    def settings():
        return jsonify(current().settings(body()))

    @app.get('/board/layout.json')
    def layout():
        return send_from_directory(ROOT/'board','layout.json')

    @app.get('/assets/board.jpg')
    def photo():
        return send_from_directory(ROOT, 'WhatsApp Image 2026-10-28 at 9.05.56 PM (1).jpeg')

    @app.get('/')
    @app.get('/<path:name>')
    def frontend(name='index.html'):
        dist = ROOT/'dist'
        if not (dist/'index.html').is_file():
            return 'Build the frontend first: bun install && bun run build',503
        # index.html names the hashed bundles of the current build: never cache it.
        return send_from_directory(dist,name,max_age=0 if name=='index.html' else None)

    return app


if __name__ == '__main__':
    create_app().run(host=os.environ.get('LPC_LAB_HOST','127.0.0.1'),port=int(os.environ.get('LPC_LAB_PORT','8765')),
                     threaded=True,debug=False,use_reloader=False)
