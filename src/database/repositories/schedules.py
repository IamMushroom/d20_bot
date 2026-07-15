from datetime import datetime

from database.connection import Database, Row
from database.models import GameSchedule


def _schedule(row: Row) -> GameSchedule:
    return GameSchedule(
        chat_id=int(row['chat_id']),
        scheduled_at=datetime.fromisoformat(str(row['scheduled_at'])),
        foundry_url=str(row['foundry_url']),
        message_id=int(row['message_id']) if row['message_id'] is not None else None,
        updated_at=datetime.fromisoformat(str(row['updated_at'])),
    )


class GameScheduleRepository:
    def __init__(self, database: Database):
        self._database = database

    async def get(self, chat_id: int) -> GameSchedule | None:
        row = await self._database.fetch_one(
            'SELECT * FROM game_schedules WHERE chat_id = ?', (chat_id,)
        )
        return _schedule(row) if row is not None else None

    async def save(self, schedule: GameSchedule) -> GameSchedule:
        row = await self._database.fetch_one(
            """
            INSERT INTO game_schedules
                (chat_id, scheduled_at, foundry_url, message_id, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                scheduled_at = excluded.scheduled_at,
                foundry_url = excluded.foundry_url,
                message_id = excluded.message_id,
                updated_at = excluded.updated_at
            RETURNING *
            """,
            (
                schedule.chat_id,
                schedule.scheduled_at.isoformat(),
                schedule.foundry_url,
                schedule.message_id,
                schedule.updated_at.isoformat(),
            ),
        )
        assert row is not None
        return _schedule(row)

    async def set_message_id(self, chat_id: int, message_id: int) -> None:
        await self._database.execute(
            'UPDATE game_schedules SET message_id = ? WHERE chat_id = ?',
            (message_id, chat_id),
        )

    async def get_default_url(self, chat_id: int) -> str | None:
        row = await self._database.fetch_one(
            'SELECT foundry_url FROM game_configs WHERE chat_id = ?', (chat_id,)
        )
        return str(row['foundry_url']) if row is not None else None

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
