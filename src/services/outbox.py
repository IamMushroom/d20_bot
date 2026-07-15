import json
from dataclasses import dataclass
from datetime import UTC, datetime

from database.connection import Database
from database.repositories import OutboxRepository


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    id: int
    event_type: str
    payload: dict[str, object]


class OutboxService:
    def __init__(self, database: Database):
        self._events = OutboxRepository(database)

    async def publish(self, event_type: str, payload: dict[str, object]) -> int:
        return await self._events.add(
            event_type, json.dumps(payload, ensure_ascii=False), datetime.now(UTC)
        )

    async def pending(self) -> list[OutboxEvent]:
        return [
            OutboxEvent(event_id, event_type, json.loads(payload))
            for event_id, event_type, payload in await self._events.pending()
        ]

    async def acknowledge(self, event_id: int) -> None:
        await self._events.acknowledge(event_id, datetime.now(UTC))
