# syntax=docker/dockerfile:1.7
# uv-first build: dependency resolution and venv management both go through uv.
FROM python:3.13-slim AS builder

# Install uv from the official image.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install dependencies with cache mount (layer-cached, no project install yet).
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# Copy source and install the project itself.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


FROM python:3.13-slim AS runtime

# Create non-root user before any file copies so we can chown cleanly.
RUN useradd --create-home --shell /bin/bash --uid 10001 appuser

# Carry the resolved venv and uv into the runtime image.
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /bin/uv /bin/uvx /bin/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY --chown=appuser:appuser src ./src

EXPOSE 8000

# Run the installed `prod` script (entry point from pyproject.toml).
# Same as `uv run prod` — uses the venv and respects settings.app.HOST/PORT.
USER appuser
CMD ["uv", "run", "prod"]
