FROM python:3.14-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && addgroup -S bot \
    && adduser -S bot -G bot

COPY --chown=bot:bot src ./src

USER bot

CMD ["python", "src/run.py"]
