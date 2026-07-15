from datetime import UTC, datetime
from typing import cast

from database.connection import Database, Row
from database.models import Character


def _character(row: Row) -> Character:
    return Character(
        id=cast(int, row['id']),
        campaign_id=cast(int, row['campaign_id']),
        telegram_user_id=cast(int, row['telegram_user_id']),
        name=str(row['name']),
        created_at=datetime.fromisoformat(str(row['created_at'])),
        updated_at=datetime.fromisoformat(str(row['updated_at'])),
    )


class CharacterRepository:
    def __init__(self, database: Database):
        self._database = database

    async def register(self, campaign_id: int, user_id: int, name: str) -> Character:
        now = datetime.now(UTC).isoformat()
        row = await self._database.fetch_one(
            """
            INSERT INTO characters (
                campaign_id, telegram_user_id, name, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(campaign_id, telegram_user_id)
            DO UPDATE SET name = excluded.name, updated_at = excluded.updated_at
            RETURNING *
            """,
            (campaign_id, user_id, name, now, now),
        )
        assert row is not None
        return _character(row)

    async def get_by_user(self, campaign_id: int, user_id: int) -> Character | None:
        row = await self._database.fetch_one(
            """SELECT * FROM characters
            WHERE campaign_id = ? AND telegram_user_id = ?""",
            (campaign_id, user_id),
        )
        return _character(row) if row is not None else None

    async def list(self, campaign_id: int) -> list[Character]:
        rows = await self._database.fetch_all(
            'SELECT * FROM characters WHERE campaign_id = ? ORDER BY name, id',
            (campaign_id,),
        )
        return [_character(row) for row in rows]
