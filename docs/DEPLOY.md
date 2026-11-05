# Deploying the simulator publicly

The simulator needs a long-running Python process: each visitor's emulated LPC1768 lives in
memory with its own CPU thread, and the Zig/LLVM compiler alone is ~370 MB. Vercel serverless
functions are stateless and limited to 250 MB, so Vercel hosts only the frontend and forwards
`/api` to a backend running the Docker image on Render's free plan.

```
browser ──► Vercel (dist/, static) ──/api, /board, /assets/board.jpg──► Render web service
                                                                         gunicorn + Flask
                                                                         one Runtime per visitor
```

Live: frontend https://lpc-1768-simulator-extended.vercel.app, backend
https://lpc1768-simulator.onrender.com (which also serves the whole app by itself).

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

The image holds no secrets: it is built from the public repository.

## Docker image

`deploy/docker/Dockerfile` builds the frontend, installs the Python requirements, warms the
compiler cache and serves the whole app in public mode with gunicorn on `$PORT` (default 7860):

```bash
docker build -f deploy/docker/Dockerfile -t lpc1768 .
docker run -p 7860:7860 lpc1768
```

Keep it to **one** worker process: the visitor simulators live in that process.

## Render (free)

`render.yaml` is a Render Blueprint for this image on the free plan, with 3 visitors and one
compile at a time to fit 512 MB.

1. Sign in at https://dashboard.render.com with GitHub.
2. New → **Blueprint**, pick this repository, and apply `render.yaml`. The first build takes
   several minutes.
3. `https://<service>.onrender.com/api/parts` should return JSON.
4. Every push to `main` redeploys automatically.

The free plan has a fraction of a CPU: compiling takes longer than locally and fast firmware
runs slower than real time. The service sleeps after 15 minutes without requests; the first
request wakes it in about a minute (the page says to reload). Hugging Face Spaces were tried
first, but free accounts can now only create GPU (ZeroGPU) Gradio Spaces, which refuse apps
without GPU functions.

## Vercel

`vercel.json` builds the frontend into `dist/` and rewrites `/api/*`, `/board/*` and
`/assets/board.jpg` to `https://lpc1768-simulator.onrender.com`. If the backend address
changes, change the three destinations and push. `LPC_ALLOWED_ORIGINS` (set in the
Dockerfile) must match the Vercel domains: `https://lpc-1768-simulator-extended*.vercel.app`
covers the production and preview URLs.
