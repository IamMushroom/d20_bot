import sqlite3
from datetime import UTC, datetime

from database.connection import Database, Row
from database.models import Session


class ActiveSessionExistsError(Exception):
    """Raised when a campaign already has an active session."""


def _session(row: Row) -> Session:
    scheduled_at = row['scheduled_at']
    started_at = row['started_at']
    finished_at = row['finished_at']
    return Session(
        id=int(row['id']),
        campaign_id=int(row['campaign_id']),
        number=int(row['number']),
        title=str(row['title']) if row['title'] is not None else None,
        scheduled_at=(
            datetime.fromisoformat(str(scheduled_at)) if scheduled_at is not None else None
        ),
        started_at=datetime.fromisoformat(str(started_at)) if started_at is not None else None,
        finished_at=datetime.fromisoformat(str(finished_at)) if finished_at is not None else None,
        foundry_url=str(row['foundry_url']) if row['foundry_url'] is not None else None,
        message_id=int(row['message_id']) if row['message_id'] is not None else None,
        updated_at=datetime.fromisoformat(str(row['updated_at'])),
    )


class SessionRepository:
    def __init__(self, database: Database):
        self._database = database

    async def start(self, campaign_id: int, title: str | None = None) -> Session:
        now = datetime.now(UTC).isoformat()
        planned = await self._database.fetch_one(
            """
            UPDATE sessions
            SET started_at = ?, title = COALESCE(?, title), updated_at = ?
            WHERE campaign_id = ? AND scheduled_at IS NOT NULL AND started_at IS NULL
            RETURNING *
            """,
            (now, title, now, campaign_id),
        )
        if planned is not None:
            return _session(planned)
        try:
            row = await self._database.fetch_one(
                """
                INSERT INTO sessions (campaign_id, number, title, started_at, updated_at)
                SELECT ?, COALESCE(MAX(number), 0) + 1, ?, ?, ?
                FROM sessions WHERE campaign_id = ?
                RETURNING *
                """,
                (campaign_id, title, now, now, campaign_id),
            )
        except sqlite3.IntegrityError as error:
            if await self.get_active(campaign_id) is not None:
                raise ActiveSessionExistsError from error
            raise
        assert row is not None
        return _session(row)

    async def finish(self, session_id: int) -> Session | None:
        row = await self._database.fetch_one(
            """UPDATE sessions SET finished_at = ?, updated_at = ?
            WHERE id = ? AND started_at IS NOT NULL AND finished_at IS NULL RETURNING *""",
            (datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat(), session_id),
        )
        return _session(row) if row is not None else None

    async def get_active(self, campaign_id: int) -> Session | None:
        row = await self._database.fetch_one(
            """SELECT * FROM sessions
            WHERE campaign_id = ? AND started_at IS NOT NULL AND finished_at IS NULL""",
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

    async def get_planned(self, campaign_id: int) -> Session | None:
        row = await self._database.fetch_one(
            """SELECT * FROM sessions
            WHERE campaign_id = ? AND scheduled_at IS NOT NULL AND started_at IS NULL""",
            (campaign_id,),
        )
        return _session(row) if row is not None else None

    async def schedule(self, campaign_id: int, scheduled_at: datetime, foundry_url: str) -> Session:
        now = datetime.now(UTC).isoformat()
        row = await self._database.fetch_one(
            """
            INSERT INTO sessions (
                campaign_id, number, scheduled_at, foundry_url, updated_at
            )
            SELECT ?, COALESCE(MAX(number), 0) + 1, ?, ?, ?
            FROM sessions WHERE campaign_id = ?
            ON CONFLICT(campaign_id)
                WHERE scheduled_at IS NOT NULL AND started_at IS NULL
            DO UPDATE SET
                scheduled_at = excluded.scheduled_at,
                foundry_url = excluded.foundry_url,
                message_id = NULL,
                updated_at = excluded.updated_at
            RETURNING *
            """,
            (
                campaign_id,
                scheduled_at.isoformat(),
                foundry_url,
                now,
                campaign_id,
            ),
        )
        assert row is not None
        return _session(row)

    async def set_message_id(self, session_id: int, message_id: int) -> None:
        await self._database.execute(
            'UPDATE sessions SET message_id = ? WHERE id = ?', (message_id, session_id)
        )
