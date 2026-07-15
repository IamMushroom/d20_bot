FROM python:3.14-alpine AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir uv==0.11.28

FROM base AS test

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

COPY pytest.ini ./
COPY migrations ./migrations
COPY src ./src
COPY tests ./tests

RUN uv run --no-sync ruff check . \
    && uv run --no-sync ruff format --check . \
    && uv run --no-sync pytest

FROM base AS runtime

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev \
    && addgroup -S -g 10001 bot \
    && adduser -S -D -H -u 10001 -G bot bot \
    && mkdir -p /data /backups \
    && chown bot:bot /data /backups

COPY --chown=bot:bot src ./src
COPY --chown=bot:bot migrations ./migrations

USER bot

CMD [".venv/bin/python", "src/run.py"]
