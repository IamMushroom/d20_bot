from datetime import datetime
from typing import cast

from database.connection import Database


class OutboxRepository:
    def __init__(self, database: Database):
        self._database = database

    async def add(self, event_type: str, payload: str, created_at: datetime) -> int:
        row = await self._database.fetch_one(
            """INSERT INTO outbox_events (event_type, payload, created_at)
            VALUES (?, ?, ?) RETURNING id""",
            (event_type, payload, created_at.isoformat()),
        )
        assert row is not None
        return cast(int, row['id'])

    async def pending(self, limit: int = 20) -> list[tuple[int, str, str]]:
        rows = await self._database.fetch_all(
            """SELECT id, event_type, payload FROM outbox_events
            WHERE delivered_at IS NULL ORDER BY id LIMIT ?""",
            (limit,),
        )
        return [(cast(int, row['id']), str(row['event_type']), str(row['payload'])) for row in rows]

    async def acknowledge(self, event_id: int, delivered_at: datetime) -> None:
        await self._database.execute(
            'UPDATE outbox_events SET delivered_at = ? WHERE id = ? AND delivered_at IS NULL',
            (delivered_at.isoformat(), event_id),
        )
