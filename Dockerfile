FROM python:3.14-alpine AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

FROM base AS test

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY pyproject.toml pytest.ini ./
COPY src ./src
COPY tests ./tests

RUN python -m ruff check . \
    && python -m ruff format --check . \
    && python -m pytest

FROM base AS runtime

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && addgroup -S bot \
    && adduser -S bot -G bot

COPY --chown=bot:bot src ./src

USER bot

CMD ["python", "src/run.py"]
