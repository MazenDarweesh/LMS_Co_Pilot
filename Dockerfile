# syntax=docker/dockerfile:1
# ==========================================
# 1. Builder Stage
# ==========================================
FROM python:3.12-slim-bookworm AS builder

# Install uv from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Enable bytecode compilation and faster link mode
ENV UV_COMPILE_BYTECODE=1 
ENV UV_LINK_MODE=copy

# Cache dependency layer
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Install the full project
COPY . .
RUN uv sync --frozen --no-dev

# ==========================================
# 2. Runtime Stage
# ==========================================
FROM python:3.12-slim-bookworm AS runtime

RUN groupadd -r appuser && useradd -r -g appuser appuser
USER appuser

WORKDIR /app

# Copy the environment and source code
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --from=builder --chown=appuser:appuser /app/src /app/src
COPY --from=builder --chown=appuser:appuser /app/pyproject.toml /app/

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app

# UTF-8 Encoding Setup (Crucial for Arabic support in Windows/Docker)
ENV PYTHONUTF8=1
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONIOENCODING=utf-8

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
