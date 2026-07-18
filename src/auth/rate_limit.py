import hashlib
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

from database import Database


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    retry_after: int


class RateLimiter(Protocol):
    async def hit(self, key: str, *, limit: int, window: timedelta) -> RateLimitResult: ...


class SQLiteRateLimiter:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def hit(self, key: str, *, limit: int, window: timedelta) -> RateLimitResult:
        now = datetime.now(UTC)
        reset_at = now + window
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        await self._database.execute(
            'DELETE FROM auth_rate_limits WHERE reset_at <= ?', (now.isoformat(),)
        )
        row = await self._database.fetch_one(
            """INSERT INTO auth_rate_limits (key_hash, attempts, reset_at)
            VALUES (?, 1, ?)
            ON CONFLICT(key_hash) DO UPDATE SET
                attempts = CASE
                    WHEN auth_rate_limits.reset_at <= ? THEN 1
                    ELSE auth_rate_limits.attempts + 1
                END,
                reset_at = CASE
                    WHEN auth_rate_limits.reset_at <= ? THEN excluded.reset_at
                    ELSE auth_rate_limits.reset_at
                END
            RETURNING attempts, reset_at""",
            (key_hash, reset_at.isoformat(), now.isoformat(), now.isoformat()),
        )
        assert row is not None
        attempts = cast(int, row['attempts'])
        stored_reset = datetime.fromisoformat(str(row['reset_at']))
        retry_after = max(1, math.ceil((stored_reset - now).total_seconds()))
        return RateLimitResult(attempts <= limit, retry_after)


__all__ = ['RateLimiter', 'RateLimitResult', 'SQLiteRateLimiter']
