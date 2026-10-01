# syntax=docker/dockerfile:1
# ==========================================
# 1. Builder Stage
# ==========================================
FROM python:3.13-slim-bookworm AS builder

# Install uv from the official image (Pinned version for deterministic builds)
COPY --from=ghcr.io/astral-sh/uv:0.6.1 /uv /uvx /bin/

WORKDIR /app

# Enable bytecode compilation and faster link mode
ENV UV_COMPILE_BYTECODE=1 
ENV UV_LINK_MODE=copy

# Cache and install dependencies
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# ==========================================
# 2. Runtime Stage
# ==========================================
FROM python:3.13-slim-bookworm AS runtime

# Install ffmpeg (required by yt-dlp & pydub for audio extraction) and curl (for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r appuser && useradd -r -g appuser -m -d /home/appuser appuser && \
    mkdir -p /app/.model_cache /app/downloads /home/appuser/.cache && \
    chown -R appuser:appuser /app /home/appuser

WORKDIR /app
USER appuser

# Copy virtual environment from builder and application source code
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --chown=appuser:appuser src /app/src
COPY --chown=appuser:appuser pyproject.toml /app/

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app
ENV HF_HOME=/app/.model_cache

# UTF-8 Encoding Setup (Crucial for Arabic support in Windows/Docker)
ENV PYTHONUTF8=1
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONIOENCODING=utf-8

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
