from datetime import UTC, datetime
from typing import cast

from database.connection import Database, Row
from domain import RecapEntry


def _recap(row: Row) -> RecapEntry:
    return RecapEntry(
        id=cast(int, row['id']),
        session_id=cast(int, row['session_id']),
        character_id=cast(int, row['character_id']),
        text=str(row['text']),
        position=cast(int, row['position']),
        created_at=datetime.fromisoformat(str(row['created_at'])),
        updated_at=datetime.fromisoformat(str(row['updated_at'])),
    )


class RecapRepository:
    def __init__(self, database: Database):
        self._database = database

    async def add(self, session_id: int, character_id: int, text: str) -> RecapEntry:
        now = datetime.now(UTC).isoformat()
        row = await self._database.fetch_one(
            """
            INSERT INTO recap_entries (
                session_id, character_id, text, position, created_at, updated_at
            )
            SELECT ?, ?, ?, COALESCE(MAX(position), 0) + 1, ?, ?
            FROM recap_entries WHERE session_id = ?
            RETURNING *
            """,
            (session_id, character_id, text, now, now, session_id),
        )
        assert row is not None
        return _recap(row)

    async def list_by_session(self, session_id: int) -> list[RecapEntry]:
        rows = await self._database.fetch_all(
            'SELECT * FROM recap_entries WHERE session_id = ? ORDER BY position',
            (session_id,),
        )
        return [_recap(row) for row in rows]

    async def delete_last(self, session_id: int, character_id: int) -> bool:
        deleted = await self._database.execute(
            """DELETE FROM recap_entries WHERE id = (
                SELECT id FROM recap_entries
                WHERE session_id = ? AND character_id = ?
                ORDER BY position DESC LIMIT 1
            )""",
            (session_id, character_id),
        )
        return deleted == 1
