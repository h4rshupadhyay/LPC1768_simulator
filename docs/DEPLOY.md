# Deploying the simulator publicly

The simulator needs a long-running Python process: each visitor's emulated LPC1768 lives in
memory with its own CPU thread, and the Zig/LLVM compiler alone is ~370 MB. Vercel serverless
functions are stateless and limited to 250 MB, so Vercel hosts only the frontend and forwards
`/api` to a backend hosted on a Hugging Face Space (free, Docker).

```
browser ──► Vercel (dist/, static) ──/api, /board, /assets/board.jpg──► Hugging Face Space
                                                                         gunicorn + Flask
                                                                         one Runtime per visitor
```

The Space also serves the whole app by itself at `https://<space-host>`.

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

1. Create a Space at https://huggingface.co/new-space: SDK **Docker**, template **Blank**,
   hardware **CPU basic (free)**, visibility **Public**.
2. Add the two files from `deploy/huggingface/` (`Dockerfile`, `README.md`) to the Space
   (Files → Add file → Create new file, or upload). The build clones this repository's `main`
   branch, builds the frontend and starts gunicorn on port 7860.
3. Wait for the status to become **Running**, then open `https://<space-host>` (shown under
   ⋮ → Embed this Space → Direct URL, normally `https://<user>-<space-name>.hf.space`).
4. After pushing new commits to `main`, use Settings → **Factory rebuild**.

A free Space sleeps after 48 hours without visitors; the first request wakes it in about a
minute (the page asks you to reload).

## Vercel

`vercel.json` builds the frontend into `dist/` and rewrites `/api/*`, `/board/*` and
`/assets/board.jpg` to the Space, currently `https://kavypings-lpc1768-simulator.hf.space`
(user `KavyPings`, Space `lpc1768-simulator`). If the Space host differs, change the three
destinations and push. `LPC_ALLOWED_ORIGINS` in the Dockerfile must match the Vercel domains
(`https://lpc-1768-simulator-extended*.vercel.app` covers production and preview URLs).

## Any other Docker host

The same image runs anywhere (Render, Fly.io, Railway, a VPS):

```bash
docker build -t lpc1768 deploy/huggingface
docker run -p 7860:7860 lpc1768
```

Keep it to **one** gunicorn worker process: the visitor simulators live in that process.
