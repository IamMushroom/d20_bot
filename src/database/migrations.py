import re
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from database.connection import Database

MIGRATION_NAME = re.compile(r'(?P<version>\d{3})_.+\.sql$')


async def apply_migrations(database: Database, directory: Path) -> None:
    await database.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    rows = await database.fetch_all('SELECT version FROM schema_migrations')
    applied = {cast(int, row['version']) for row in rows}

    migrations: list[tuple[int, Path]] = []
    for path in directory.glob('*.sql'):
        match = MIGRATION_NAME.fullmatch(path.name)
        if match is None:
            raise ValueError(f'Invalid migration filename: {path.name}')
        migrations.append((int(match['version']), path))

    versions = [version for version, _ in migrations]
    if len(versions) != len(set(versions)):
        raise ValueError('Duplicate migration version')

    for version, path in sorted(migrations):
        if version in applied:
            continue
        script = path.read_text(encoding='utf-8')
        applied_at = datetime.now(UTC).isoformat().replace("'", "''")
        await database.executescript(
            f"""BEGIN IMMEDIATE;
{script}
INSERT INTO schema_migrations (version, applied_at)
VALUES ({version}, '{applied_at}');
COMMIT;"""
        )
