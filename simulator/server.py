"""Loopback-only API and production frontend server."""
from pathlib import Path
import atexit
import os
import base64
import binascii
import json

from flask import Flask, request, jsonify, send_from_directory
from werkzeug.exceptions import HTTPException

from .runtime import Runtime, ROOT, CATALOG
from .board import MAPPING


def create_app(runtime=None):
    app = Flask(__name__, static_folder=None)
    app.json.sort_keys = False
    app.config['MAX_CONTENT_LENGTH'] = 3_500_000
    rt = runtime or Runtime()
    app.extensions['runtime'] = rt
    if runtime is None:
        atexit.register(rt.close)

    @app.before_request
    def local_only():
        # Same-origin browser API; the Vite development server proxies /api.
        origin = request.headers.get('Origin')
        if origin and origin.rstrip('/') != request.host_url.rstrip('/'):
            return jsonify(error='This local API accepts same-origin requests only.'),403
        host = request.host
        # Strip the port; bracketed IPv6 literals such as [::1]:8765 keep their colons.
        host = host[1:host.index(']')] if host.startswith('[') and ']' in host else host.split(':')[0]
        if host not in ('127.0.0.1','localhost','::1','test.local'):
            return jsonify(error='Use localhost or 127.0.0.1.'),403

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
        return jsonify(board=MAPPING,compiler=rt.compiler.info(),exercises=CATALOG,
                       backend='Unicorn 2.1.4 / Cortex-M3',
                       timing='Real elapsed time for timers/PWM; host-limited CPU' if rt.realtime
                       else 'Deterministic instruction ticks (offline)')

    @app.get('/api/state')
    def state():
        return jsonify(rt.snapshot())

    @app.get('/api/examples/<name>')
    def example(name):
        spec = next((s for s in CATALOG if s['id'] == name),None)
        if not spec:
            raise ValueError('Unknown reference example.')
        return jsonify(source=(ROOT/'examples'/spec['file']).read_text(encoding='utf-8'))

    @app.post('/api/compile')
    def compile_code():
        source = body().get('source')
        if not isinstance(source,str):
            raise ValueError('Expected C source text.')
        return jsonify(rt.compile(source, body().get('language', 'c')))

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
        return jsonify(rt.load(data.get('hex'), name, elf=elf))

    @app.post('/api/control')
    def control():
        return jsonify(rt.control(body().get('action')))

    @app.post('/api/debug')
    def debug():
        return jsonify(rt.debug(body()))

    @app.post('/api/physical')
    def physical():
        return jsonify(rt.physical(body()))

    @app.post('/api/check')
    def check():
        return jsonify(rt.check(body().get('exercise')))

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
        return jsonify(rt.circuit(body()))

    @app.get('/api/project')
    def project():
        return jsonify(rt.export_project())

    @app.post('/api/serial')
    def serial():
        return jsonify(rt.serial(body()))

    @app.post('/api/settings')
    def settings():
        return jsonify(rt.settings(body()))

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
    create_app().run(host='127.0.0.1',port=int(os.environ.get('LPC_LAB_PORT','8765')),
                     threaded=True,debug=False,use_reloader=False)
