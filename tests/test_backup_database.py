from contextlib import closing
from pathlib import Path
from sqlite3 import connect

from backup_database import backup_database


def test_backup_database_creates_consistent_copy_and_applies_retention(tmp_path):
    source = tmp_path / 'source.sqlite3'
    backups = tmp_path / 'backups'
    with closing(connect(source)) as database:
        database.execute('CREATE TABLE example (value TEXT NOT NULL)')
        database.execute("INSERT INTO example VALUES ('saved')")
        database.commit()

    first = backup_database(source, backups, keep=10)
    assert first is not None
    with closing(connect(first)) as database:
        assert database.execute('SELECT value FROM example').fetchone() == ('saved',)

    old = backups / 'd20-20000101T000000Z.sqlite3'
    old.touch()
    backup_database(source, backups, keep=1)
    assert not old.exists()


def test_backup_database_skips_missing_source(tmp_path):
    destination = tmp_path / 'backups'
    assert backup_database(Path(tmp_path / 'missing.sqlite3'), destination, keep=10) is None
    assert not destination.exists()
