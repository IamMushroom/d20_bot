import asyncio
import logging
from os import getenv
from pathlib import Path

from dotenv import load_dotenv

import log_format
from core import CoreRuntime

MIGRATIONS_DIRECTORY = Path(__file__).resolve().parent.parent / 'migrations'


def required_environment(name: str) -> str:
    value = getenv(name, '').strip()
    if not value:
        raise RuntimeError(f'{name} environment variable is not set')
    return value


async def run_core() -> None:
    runtime: CoreRuntime | None = None
    try:
        runtime = await CoreRuntime.start(
            database_url=getenv('DATABASE_URL', 'sqlite:////data/d20.sqlite3'),
            migrations_directory=MIGRATIONS_DIRECTORY,
            web_host=getenv('WEB_HOST', '0.0.0.0'),
            web_port=int(getenv('WEB_PORT', '8190')),
            web_base_url=getenv('WEB_BASE_URL', '').strip(),
            internal_token=required_environment('CORE_TOKEN'),
        )
        await runtime.web_server.serve_forever()
    finally:
        if runtime is not None:
            await runtime.close()


def bootstrap() -> None:
    load_dotenv()
    log_format.configure_logging(getenv('LOG_FORMAT', 'json'))
    logging.getLogger('httpx').setLevel(logging.WARNING)
    try:
        asyncio.run(run_core())
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':  # pragma: no cover
    bootstrap()
