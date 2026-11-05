# Hugging Face Space (Docker SDK) for the LPC1768 simulator, in public mode.
# It builds the public GitHub repository, so the Space holds only this file and
# README.md. Use "Factory rebuild" in the Space settings to pick up new commits.

FROM node:22-bookworm-slim AS web
ARG REPO=https://github.com/KavyPings/LPC1768_simulator_extended.git
ARG REF=main
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch "$REF" "$REPO" /src
WORKDIR /src
RUN (npm ci --no-audit --no-fund || npm install --no-audit --no-fund) \
    && npm run build \
    && rm -rf node_modules .git

FROM python:3.12-slim
RUN useradd -m -u 1000 user
WORKDIR /app
COPY --from=web --chown=user /src /app
RUN pip install --no-cache-dir -r requirements.txt gunicorn==23.0.0
USER user
# LPC_ALLOWED_ORIGINS: other sites allowed to call the API (the Vercel frontend
# proxies /api here). LPC_MAX_SESSIONS: simultaneous visitors, each with its own
# simulator. Idle simulators are closed after LPC_IDLE_SECONDS.
ENV HOME=/home/user \
    PYTHONUNBUFFERED=1 \
    ZIG_GLOBAL_CACHE_DIR=/tmp/zig-cache \
    LPC_PUBLIC=1 \
    LPC_ALLOWED_ORIGINS="https://lpc-1768-simulator-extended*.vercel.app" \
    LPC_MAX_SESSIONS=8 \
    LPC_IDLE_SECONDS=300 \
    LPC_COMPILE_SLOTS=2
EXPOSE 7860
# One process: every visitor's simulator lives in its memory; threads serve requests.
CMD ["gunicorn", "--workers", "1", "--threads", "32", "--timeout", "180", \
     "--bind", "0.0.0.0:7860", "simulator.server:create_app()"]
