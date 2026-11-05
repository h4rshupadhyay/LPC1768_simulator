"""Hugging Face Space (Gradio SDK) entry point for the LPC1768 simulator backend.

Free Spaces must use the Gradio SDK, so this file runs a Gradio page and the
simulator's Flask API in one ASGI server on port 7860:

* /api/*, /board/*, /assets/board.jpg -> the simulator (public mode, one
  simulator per visitor, restricted compilation)
* everything else                      -> a Gradio page linking to the app

The simulator code is cloned from the public GitHub repository at startup;
restart the Space to pick up new commits.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO = os.environ.get('LPC_REPO', 'https://github.com/KavyPings/LPC1768_simulator_extended.git')
REF = os.environ.get('LPC_REF', 'main')
FRONTEND = os.environ.get('LPC_FRONTEND_URL', 'https://lpc-1768-simulator-extended.vercel.app')
SOURCE = Path(os.environ.get('LPC_SOURCE', Path.home() / 'lpc1768'))

if not (SOURCE / 'simulator').is_dir():
    subprocess.run(['git', 'clone', '--depth', '1', '--branch', REF, REPO, str(SOURCE)], check=True)

for name, value in {
    'LPC_PUBLIC': '1',
    'LPC_ALLOWED_ORIGINS': 'https://lpc-1768-simulator-extended*.vercel.app',
    'LPC_MAX_SESSIONS': '8',
    'LPC_IDLE_SECONDS': '300',
    'LPC_COMPILE_SLOTS': '2',
    'ZIG_GLOBAL_CACHE_DIR': '/tmp/zig-cache',
}.items():
    os.environ.setdefault(name, value)
sys.path.insert(0, str(SOURCE))
os.chdir(SOURCE)

import gradio as gr  # noqa: E402
import uvicorn  # noqa: E402
from a2wsgi import WSGIMiddleware  # noqa: E402
from fastapi import FastAPI  # noqa: E402

from simulator.server import create_app  # noqa: E402

simulator = WSGIMiddleware(create_app(), workers=32)

with gr.Blocks(title='LPC1768 Simulator') as page:
    gr.Markdown(f"""
# LPC1768 Simulator backend

This Space runs the simulator for the ALS LPC1768 kit: Embedded C compiled for an
emulated Cortex-M3, the kit's peripherals, and a 3D Workbench for external parts.

**Open the simulator: [{FRONTEND}]({FRONTEND})**

Every visitor gets their own simulator. Source:
[github.com/KavyPings/LPC1768_simulator_extended](https://github.com/KavyPings/LPC1768_simulator_extended)
""")

gradio_app = gr.mount_gradio_app(FastAPI(), page, path='/')


def is_simulator(path):
    return path.startswith(('/api/', '/board/')) or path == '/assets/board.jpg'


async def app(scope, receive, send):
    if scope['type'] == 'http' and is_simulator(scope.get('path', '')):
        await simulator(scope, receive, send)
    else:
        await gradio_app(scope, receive, send)


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', '7860')))
