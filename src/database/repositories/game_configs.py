from datetime import datetime

from database.connection import Database


class GameConfigRepository:
    def __init__(self, database: Database):
        self._database = database

    async def get_default_url(self, chat_id: int) -> str | None:
        row = await self._database.fetch_one(
            'SELECT foundry_url FROM game_configs WHERE chat_id = ?', (chat_id,)
        )
        return (
            str(row['foundry_url']) if row is not None and row['foundry_url'] is not None else None
        )

    async def set_default_url(self, chat_id: int, foundry_url: str, updated_at: datetime) -> None:
        await self._database.execute(
            """
            INSERT INTO game_configs (chat_id, foundry_url, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                foundry_url = excluded.foundry_url,
                updated_at = excluded.updated_at
            """,
            (chat_id, foundry_url, updated_at.isoformat()),
        )

    async def get_web_base_url(self, chat_id: int) -> str | None:
        row = await self._database.fetch_one(
            'SELECT web_base_url FROM game_configs WHERE chat_id = ?', (chat_id,)
        )
        return (
            str(row['web_base_url'])
            if row is not None and row['web_base_url'] is not None
            else None
        )

    async def set_web_base_url(self, chat_id: int, web_base_url: str, updated_at: datetime) -> None:
        await self._database.execute(
            """
            INSERT INTO game_configs (chat_id, web_base_url, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                web_base_url = excluded.web_base_url,
                updated_at = excluded.updated_at
            """,
            (chat_id, web_base_url, updated_at.isoformat()),
        )

    async def get_announcement_timezone(self, chat_id: int) -> str | None:
        row = await self._database.fetch_one(
            'SELECT announcement_timezone FROM game_configs WHERE chat_id = ?', (chat_id,)
        )
        return str(row['announcement_timezone']) if row and row['announcement_timezone'] else None

    async def set_announcement_timezone(
        self, chat_id: int, timezone_name: str, updated_at: datetime
    ) -> None:
        await self._database.execute(
            """INSERT INTO game_configs (chat_id, announcement_timezone, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                announcement_timezone = excluded.announcement_timezone,
                updated_at = excluded.updated_at""",
            (chat_id, timezone_name, updated_at.isoformat()),
        )
