from datetime import UTC, datetime

from database.connection import Database, Row
from database.models import Campaign


def _campaign(row: Row) -> Campaign:
    return Campaign(
        id=int(row['id']),
        chat_id=int(row['chat_id']),
        title=str(row['title']) if row['title'] is not None else None,
        created_at=datetime.fromisoformat(str(row['created_at'])),
    )


class CampaignRepository:
    def __init__(self, database: Database):
        self._database = database

    async def get_or_create(self, chat_id: int, title: str | None = None) -> Campaign:
        now = datetime.now(UTC).isoformat()
        row = await self._database.fetch_one(
            """
            INSERT INTO campaigns (chat_id, title, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET title = COALESCE(excluded.title, campaigns.title)
            RETURNING *
            """,
            (chat_id, title, now),
        )
        assert row is not None
        return _campaign(row)

    async def get_by_chat_id(self, chat_id: int) -> Campaign | None:
        row = await self._database.fetch_one(
            'SELECT * FROM campaigns WHERE chat_id = ?', (chat_id,)
        )
        return _campaign(row) if row is not None else None
