from datetime import UTC, datetime

from database.connection import Database, Row
from database.models import Session


def _session(row: Row) -> Session:
    finished_at = row['finished_at']
    return Session(
        id=int(row['id']),
        campaign_id=int(row['campaign_id']),
        number=int(row['number']),
        title=str(row['title']) if row['title'] is not None else None,
        started_at=datetime.fromisoformat(str(row['started_at'])),
        finished_at=datetime.fromisoformat(str(finished_at)) if finished_at is not None else None,
    )


class SessionRepository:
    def __init__(self, database: Database):
        self._database = database

    async def start(self, campaign_id: int, title: str | None = None) -> Session:
        row = await self._database.fetch_one(
            """
            INSERT INTO sessions (campaign_id, number, title, started_at)
            SELECT ?, COALESCE(MAX(number), 0) + 1, ?, ?
            FROM sessions WHERE campaign_id = ?
            RETURNING *
            """,
            (campaign_id, title, datetime.now(UTC).isoformat(), campaign_id),
        )
        assert row is not None
        return _session(row)

    async def finish(self, session_id: int) -> Session | None:
        row = await self._database.fetch_one(
            """UPDATE sessions SET finished_at = ?
            WHERE id = ? AND finished_at IS NULL RETURNING *""",
            (datetime.now(UTC).isoformat(), session_id),
        )
        return _session(row) if row is not None else None

    async def get_active(self, campaign_id: int) -> Session | None:
        row = await self._database.fetch_one(
            'SELECT * FROM sessions WHERE campaign_id = ? AND finished_at IS NULL',
            (campaign_id,),
        )
        return _session(row) if row is not None else None

    async def get_latest(self, campaign_id: int) -> Session | None:
        row = await self._database.fetch_one(
            'SELECT * FROM sessions WHERE campaign_id = ? ORDER BY number DESC LIMIT 1',
            (campaign_id,),
        )
        return _session(row) if row is not None else None

    async def list(self, campaign_id: int) -> list[Session]:
        rows = await self._database.fetch_all(
            'SELECT * FROM sessions WHERE campaign_id = ? ORDER BY number', (campaign_id,)
        )
        return [_session(row) for row in rows]
