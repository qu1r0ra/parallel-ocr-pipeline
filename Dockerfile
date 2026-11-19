# syntax=docker/dockerfile:1
FROM python:3.15-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OMP_THREAD_LIMIT=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

COPY README.md ./
COPY src ./src
COPY scripts/run_container.py ./scripts/run_container.py
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable \
    && mkdir -p /app/local-assets \
    && tessdata_dir="$(find /usr/share/tesseract-ocr -type d -name tessdata -print -quit)" \
    && test -n "$tessdata_dir" \
    && ln -s "$tessdata_dir" /app/local-assets/models

ENV PATH="/app/.venv/bin:$PATH"

CMD ["python", "scripts/run_container.py", "worker"]
