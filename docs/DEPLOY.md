# Deploying the simulator publicly

The simulator needs a long-running Python process: each visitor's emulated LPC1768 lives in
memory with its own CPU thread, and the Zig/LLVM compiler alone is ~370 MB. Vercel serverless
functions are stateless and limited to 250 MB, so Vercel hosts only the frontend and forwards
`/api` to a backend hosted on a free Hugging Face Space.

```
browser ──► Vercel (dist/, static) ──/api, /board, /assets/board.jpg──► Hugging Face Space
                                                                         uvicorn: Gradio page + Flask API
                                                                         one Runtime per visitor
```

Live: frontend https://lpc-1768-simulator-extended.vercel.app, backend Space
https://huggingface.co/spaces/kavyyyyy/lpc1768-simulator (`https://kavyyyyy-lpc1768-simulator.hf.space`).

## Public mode

`LPC_PUBLIC=1` switches the server from the local exam-practice mode to public mode:

| Local (default) | Public |
|---|---|
| Only `localhost`/`127.0.0.1`, same-origin requests | Any host (or `LPC_ALLOWED_HOSTS`), same-origin plus `LPC_ALLOWED_ORIGINS` (wildcards allowed) |
| One shared simulator | One simulator per browser tab (`X-LPC-Session` header), at most `LPC_MAX_SESSIONS`, closed after `LPC_IDLE_SECONDS` idle |
| Unrestricted compiler | Restricted compiler (below), at most `LPC_COMPILE_SLOTS` compiles at once |

Restricted compilation keeps visitors from reading files on the server:

* Only literal `#include <name>` / `#include "name"` with a relative name and no `..`
  (project headers and the C library). `#include_next`, `#import`, `#embed`, macro includes,
  trigraph/digraph `#` and line-splice tricks are rejected before the compiler runs.
* `.incbin`, `.include`, `.macro`, `.irp`, `.irpc`, `.rept`, `.altmacro` and `.purgem` are
  rejected in assembly programs and in C inline asm. C is first compiled to LLVM IR, where
  inline asm is still unparsed text, so escapes and string concatenation cannot hide them.
* The compiler runs with a minimal environment, so it never sees the server's variables.

The Space holds no secrets: it builds the public GitHub repository.

## Hugging Face Space

Free accounts get Gradio Spaces only (the Docker SDK and CPU Basic hardware need PRO), so the
Space runs `deploy/huggingface/app.py`: one uvicorn server on port 7860 that sends `/api/*`,
`/board/*` and `/assets/board.jpg` to the Flask simulator (through `a2wsgi`) and everything
else to a small Gradio page linking to the frontend. No GPU is used.

1. Create a Space at https://huggingface.co/new-space: SDK **Gradio**, template **Blank**,
   the free hardware offered, visibility **Public**.
2. Replace its files with the three in `deploy/huggingface/` (`app.py`, `requirements.txt`,
   `README.md`). At startup `app.py` clones this repository's `main` branch.
3. Wait for **Running**. `https://<user>-<space-name>.hf.space/api/parts` should return JSON.
4. After pushing new commits to `main`, **Restart** the Space (Settings) so it clones again.

A free Space sleeps after a period without visitors; the first request wakes it, which takes a
minute or two (the page says to reload).

## Vercel

`vercel.json` builds the frontend into `dist/` and rewrites `/api/*`, `/board/*` and
`/assets/board.jpg` to `https://kavyyyyy-lpc1768-simulator.hf.space`. If the Space host
changes, change the three destinations and push. `LPC_ALLOWED_ORIGINS` (set in `app.py`)
must match the Vercel domains: `https://lpc-1768-simulator-extended*.vercel.app` covers the
production and preview URLs.

## Any other Docker host

`deploy/docker/Dockerfile` builds the frontend and serves the whole app in public mode with
gunicorn (Render, Railway, a VPS, or a PRO Hugging Face Docker Space):

```bash
docker build -t lpc1768 deploy/docker
docker run -p 7860:7860 lpc1768
```

Keep it to **one** worker process: the visitor simulators live in that process.
