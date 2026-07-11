FROM python:3.14-alpine AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir uv==0.11.28

FROM base AS test

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

COPY pytest.ini ./
COPY src ./src
COPY tests ./tests

RUN uv run --no-sync ruff check . \
    && uv run --no-sync ruff format --check . \
    && uv run --no-sync pytest

FROM base AS runtime

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev \
    && addgroup -S bot \
    && adduser -S bot -G bot

COPY --chown=bot:bot src ./src

USER bot

CMD [".venv/bin/python", "src/run.py"]
