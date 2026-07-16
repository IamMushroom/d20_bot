FROM python:3.14-alpine AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

FROM base AS builder

RUN pip install --no-cache-dir uv==0.11.28

COPY pyproject.toml uv.lock ./

FROM builder AS test

RUN uv sync --frozen

COPY pytest.ini ./
COPY migrations ./migrations
COPY src ./src
COPY tests ./tests

RUN uv run --no-sync ruff check . \
    && uv run --no-sync ruff format --check . \
    && uv run --no-sync pytest

FROM builder AS runtime-dependencies

RUN uv sync --frozen --no-dev

FROM base AS runtime

RUN addgroup -S -g 10001 bot \
    && adduser -S -D -H -u 10001 -G bot bot \
    && mkdir -p /data /backups \
    && chown bot:bot /data /backups

COPY --from=runtime-dependencies --chown=bot:bot /app/.venv ./.venv

COPY --chown=bot:bot src ./src
COPY --chown=bot:bot migrations ./migrations

USER bot

CMD [".venv/bin/python", "src/run.py"]
