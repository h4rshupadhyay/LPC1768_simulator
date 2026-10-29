"""Windows-friendly local launcher. First run installs project-local dependencies."""
from pathlib import Path
import argparse
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    port=int(os.environ.get('LPC_LAB_PORT','8765'))
    url=f'http://127.0.0.1:{port}'
    def ready():
        try:
            with urllib.request.urlopen(url+'/api/info',timeout=1) as response:
                return b'ALS-SDA-ARMCTXM3-01' in response.read()
        except OSError:
            return False
    if not ready():
        python=ROOT/('.venv/Scripts/python.exe' if os.name=='nt' else '.venv/bin/python')
        # Sync existing environments so older installations gain new dependencies.
        subprocess.run(['uv', 'sync', '--frozen'], cwd=ROOT, check=True)
        if not (ROOT/'dist/index.html').exists():
            bun = 'bun.exe' if os.name == 'nt' else 'bun'
            subprocess.run([bun, 'install'], cwd=ROOT, check=True)
            subprocess.run([bun, 'run', 'build'], cwd=ROOT, check=True)
        (ROOT/'build').mkdir(exist_ok=True)
        with (ROOT/'build/server.log').open('a',encoding='utf-8') as log:
            process=subprocess.Popen([str(python),'-m','simulator.server'],cwd=ROOT,
                 stdout=log,stderr=subprocess.STDOUT,
                 creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        (ROOT/'build/server.pid').write_text(str(process.pid))
        for _ in range(60):
            if ready():
                break
            if process.poll() is not None:
                raise SystemExit('Server exited. See build/server.log (port may already be occupied).')
            time.sleep(.2)
        else:
            raise SystemExit('Server did not start. See build/server.log.')
    print('LPC1768 Virtual Lab: '+url)
    if not args.no_browser:
        webbrowser.open(url)


if __name__=='__main__':
    main()
