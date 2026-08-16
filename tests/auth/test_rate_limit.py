import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from auth import SQLiteRateLimiter
from database import SQLiteDatabase, apply_migrations

MIGRATIONS = Path(__file__).resolve().parents[2] / 'migrations'


def test_sqlite_rate_limiter_persists_and_resets_window(tmp_path):
    async def scenario():
        database = await SQLiteDatabase.connect(str(tmp_path / 'limits.sqlite3'))
        await apply_migrations(database, MIGRATIONS)
        limiter = SQLiteRateLimiter(database)
        first = await limiter.hit('login:127.0.0.1', limit=2, window=timedelta(minutes=10))
        second = await limiter.hit('login:127.0.0.1', limit=2, window=timedelta(minutes=10))
        blocked = await limiter.hit('login:127.0.0.1', limit=2, window=timedelta(minutes=10))
        stored = await database.fetch_one('SELECT * FROM auth_rate_limits')
        await database.execute(
            'UPDATE auth_rate_limits SET reset_at = ?',
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(),),
        )
        reset = await SQLiteRateLimiter(database).hit(
            'login:127.0.0.1', limit=2, window=timedelta(minutes=10)
        )
        await database.close()
        return first, second, blocked, stored, reset

    first, second, blocked, stored, reset = asyncio.run(scenario())
    assert first.allowed and second.allowed
    assert not blocked.allowed and blocked.retry_after > 0
    assert stored is not None and stored['key_hash'] != 'login:127.0.0.1'
    assert reset.allowed
