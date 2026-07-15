import logging
import sqlite3
from datetime import UTC, datetime
from os import getenv
from pathlib import Path

import log_format


def backup_database(source: Path, destination_directory: Path, keep: int) -> Path | None:
    if not source.is_file():
        logging.info('Database does not exist yet; backup skipped')
        return None
    destination_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
    destination = destination_directory / f'd20-{timestamp}.sqlite3'
    with sqlite3.connect(source) as source_database, sqlite3.connect(destination) as backup:
        source_database.backup(backup)
    backups = sorted(destination_directory.glob('d20-*.sqlite3'), reverse=True)
    for expired in backups[max(keep, 1) :]:
        expired.unlink()
    logging.info('Database backup created', extra={'backup_path': str(destination)})
    return destination


def main() -> None:
    log_format.configure_logging(getenv('D20_BOT_LOG_FORMAT', 'json'))
    backup_database(
        Path(getenv('D20_BOT_BACKUP_SOURCE', '/data/d20.sqlite3')),
        Path(getenv('D20_BOT_BACKUP_DIRECTORY', '/backups')),
        int(getenv('D20_BOT_BACKUP_KEEP', '10')),
    )


if __name__ == '__main__':  # pragma: no cover
    main()
