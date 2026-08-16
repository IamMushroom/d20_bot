from datetime import UTC, datetime
from typing import cast

from database.connection import Database, Row
from domain import Character


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
            """SELECT character.* FROM characters AS character
            JOIN users AS user ON user.telegram_user_id = character.telegram_user_id
            JOIN campaign_memberships AS membership
                ON membership.campaign_id = character.campaign_id
                AND membership.user_id = user.id
                AND membership.role = 'player'
            WHERE character.campaign_id = ? ORDER BY character.name, character.id""",
            (campaign_id,),
        )
        return [_character(row) for row in rows]

    async def rename(self, campaign_id: int, user_id: int, name: str) -> Character | None:
        row = await self._database.fetch_one(
            """UPDATE characters SET name = ?, updated_at = ?
            WHERE campaign_id = ? AND telegram_user_id = ? RETURNING *""",
            (name, datetime.now(UTC).isoformat(), campaign_id, user_id),
        )
        return _character(row) if row is not None else None
