import asyncio
from os import getenv
from pathlib import Path
from time import time

DEFAULT_READY_FILE = '/tmp/d20-bot-ready'
DEFAULT_MAX_AGE = 30
HEARTBEAT_INTERVAL = 10


def mark_ready(path: str = DEFAULT_READY_FILE) -> None:
    Path(path).touch()


def is_ready(path: str = DEFAULT_READY_FILE, max_age: float = DEFAULT_MAX_AGE) -> bool:
    try:
        age = time() - Path(path).stat().st_mtime
    except OSError:
        return False
    return age <= max_age


async def heartbeat(path: str = DEFAULT_READY_FILE, interval: float = HEARTBEAT_INTERVAL) -> None:
    while True:
        mark_ready(path)
        await asyncio.sleep(interval)


def main() -> int:
    path = getenv('HEALTHCHECK_FILE', DEFAULT_READY_FILE)
    max_age = float(getenv('HEALTHCHECK_MAX_AGE', str(DEFAULT_MAX_AGE)))
    return 0 if is_ready(path, max_age) else 1


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
