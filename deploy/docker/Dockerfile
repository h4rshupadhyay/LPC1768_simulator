# Docker image of the LPC1768 simulator in public mode (frontend and API).
# Build from the repository root:  docker build -f deploy/docker/Dockerfile -t lpc1768 .
# Render builds it from render.yaml on every push to main.

FROM node:22-bookworm-slim AS web
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY index.html vite.config.ts tsconfig.json ./
COPY web ./web
COPY board ./board
RUN npm run build

FROM python:3.12-slim
RUN useradd -m -u 1000 user
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt gunicorn==23.0.0
COPY --chown=user . .
COPY --from=web --chown=user /src/dist ./dist
USER user
# LPC_ALLOWED_ORIGINS: other sites allowed to call the API (the Vercel frontend
# proxies /api here). LPC_MAX_SESSIONS: simultaneous visitors, each with its own
# simulator. Idle simulators are closed after LPC_IDLE_SECONDS.
ENV HOME=/home/user \
    PYTHONUNBUFFERED=1 \
    ZIG_GLOBAL_CACHE_DIR=/home/user/zig-cache \
    LPC_PUBLIC=1 \
    LPC_ALLOWED_ORIGINS="https://lpc-1768-simulator-extended*.vercel.app" \
    LPC_MAX_SESSIONS=8 \
    LPC_IDLE_SECONDS=300 \
    LPC_COMPILE_SLOTS=2
# Compile once so the compiler's cache is part of the image (slow hosts start faster).
RUN python -c "from simulator.compiler import Compiler; Compiler(restricted=True).compile('#include <LPC17xx.h>\nint main(void){ while(1); }')"
EXPOSE 7860
# One process: every visitor's simulator lives in its memory; threads serve requests.
# Hosts such as Render pass the port in $PORT.
CMD ["sh", "-c", "exec gunicorn --workers 1 --threads 16 --timeout 300 --bind 0.0.0.0:${PORT:-7860} 'simulator.server:create_app()'"]
