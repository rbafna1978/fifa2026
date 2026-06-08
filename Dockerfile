# World Cup 2026 fan-logistics agent — Cloud Run image.
# Python-only container (no Node/npx): the MCP `reflection` tool degrades gracefully
# (see worldcup_agent/agent.py); the live self-improvement loop uses the direct Phoenix
# read. All config/secrets come from Cloud Run env vars — nothing is baked in.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

# uv for fast, locked dependency installs.
RUN pip install --no-cache-dir uv==0.11.19

WORKDIR /app

# Install ONLY locked dependencies (not the local project) for a reproducible, cached layer.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# App code.
COPY agent/ ./agent/

WORKDIR /app/agent

# Cloud Run sets $PORT (default 8080). Bind to it.
EXPOSE 8080
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080}"]
