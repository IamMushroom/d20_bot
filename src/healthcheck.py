import asyncio
import contextlib
import json
import logging
import os
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import log_format

HEARTBEAT_TASK_KEY = 'healthcheck_heartbeat'
DEFAULT_HEARTBEAT_PATH = str(Path(tempfile.gettempdir()) / 'd20-bot-heartbeat')
HEARTBEAT_INTERVAL_SECONDS = 5
MAX_HEARTBEAT_AGE_SECONDS = 20
TELEGRAM_API_BASE_URL = 'https://api.telegram.org'
TELEGRAM_TIMEOUT_SECONDS = 1


def heartbeat_path() -> Path:
    return Path(os.getenv('D20_BOT_HEALTH_FILE', DEFAULT_HEARTBEAT_PATH))


async def maintain_heartbeat(path: Path) -> None:
    while True:
        path.touch()
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)


def start_heartbeat(application) -> None:
    path = heartbeat_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    application.bot_data[HEARTBEAT_TASK_KEY] = asyncio.create_task(
        maintain_heartbeat(path), name='healthcheck-heartbeat'
    )


async def stop_heartbeat(application) -> None:
    task = application.bot_data.pop(HEARTBEAT_TASK_KEY, None)
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    heartbeat_path().unlink(missing_ok=True)


def is_healthy(path: Path | None = None, *, now: float | None = None) -> bool:
    path = path or heartbeat_path()
    try:
        age = (time.time() if now is None else now) - path.stat().st_mtime
    except OSError:
        return False
    return 0 <= age <= MAX_HEARTBEAT_AGE_SECONDS


def telegram_is_ready(token: str | None = None) -> bool:
    token = (token or os.getenv('D20_BOT_TG_TOKEN', '')).strip()
    if not token:
        logging.warning(
            'Telegram readiness check failed: D20_BOT_TG_TOKEN is not set',
            extra={'health_check': 'telegram_readiness', 'error_type': 'MissingConfiguration'},
        )
        return False
    try:
        with urllib.request.urlopen(
            f'{TELEGRAM_API_BASE_URL}/bot{token}/getMe', timeout=TELEGRAM_TIMEOUT_SECONDS
        ) as response:
            payload = json.load(response)
    except Exception as error:
        logging.warning(
            'Telegram readiness check failed',
            extra={
                'health_check': 'telegram_readiness',
                'error_type': type(error).__name__,
                'error_message': str(error).replace(token, '[REDACTED]'),
            },
        )
        return False
    if response.status != 200 or payload.get('ok') is not True:
        logging.warning(
            'Telegram readiness check failed: API returned an unsuccessful response',
            extra={'health_check': 'telegram_readiness', 'error_type': 'UnsuccessfulResponse'},
        )
        return False
    return True


def readiness() -> bool:
    if not is_healthy():
        logging.warning(
            'Telegram readiness check failed: application heartbeat is stale',
            extra={'health_check': 'heartbeat', 'error_type': 'StaleHeartbeat'},
        )
        return False
    telegram_is_ready()
    return True


def main() -> int:
    log_format.configure_logging(os.getenv('D20_BOT_LOG_FORMAT', 'json'))
    check = readiness if '--readiness' in sys.argv[1:] else is_healthy
    return 0 if check() else 1


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
