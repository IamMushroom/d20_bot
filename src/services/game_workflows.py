from datetime import datetime

from database.connection import Database
from services.outbox import OutboxService
from services.sessions import (
    ScheduleUpdate,
    SessionService,
    SessionStart,
    SessionStartStatus,
    SessionStop,
    SessionStopStatus,
)


class GameWorkflowService:
    def __init__(
        self,
        database: Database,
        sessions: SessionService,
        outbox: OutboxService,
    ) -> None:
        self._database = database
        self._sessions = sessions
        self._outbox = outbox

    async def schedule_and_notify(
        self,
        chat_id: int,
        chat_title: str | None,
        scheduled_at: datetime,
        foundry_url: str,
    ) -> ScheduleUpdate:
        async with self._database.transaction():
            result = await self._sessions.schedule(chat_id, chat_title, scheduled_at, foundry_url)
            timezone_name = await self._sessions.get_announcement_timezone(chat_id)
            session = result.session
            assert session.scheduled_at is not None
            assert session.foundry_url is not None
            await self._outbox.publish(
                'game_scheduled',
                {
                    'chat_id': chat_id,
                    'session_id': session.id,
                    'scheduled_at': session.scheduled_at.isoformat(),
                    'timezone': timezone_name,
                    'foundry_url': session.foundry_url,
                    'previous_message_id': result.previous_message_id,
                },
            )
            return result

    async def start_and_notify(self, chat_id: int, user_id: int, title: str | None) -> SessionStart:
        async with self._database.transaction():
            result = await self._sessions.start(chat_id, user_id, title)
            if result.status is not SessionStartStatus.STARTED:
                return result
            session = result.session
            assert session is not None
            await self._outbox.publish(
                'session_started',
                {
                    'chat_id': chat_id,
                    'number': session.number,
                    'title': session.title,
                    'announcement_message_id': result.announcement_message_id,
                },
            )
            return result

    async def stop_and_notify(self, chat_id: int, user_id: int) -> SessionStop:
        async with self._database.transaction():
            result = await self._sessions.stop(chat_id, user_id)
            if result.status is not SessionStopStatus.STOPPED:
                return result
            session = result.session
            assert session is not None
            await self._outbox.publish(
                'session_stopped',
                {'chat_id': chat_id, 'number': session.number},
            )
            return result

    async def invite_player(
        self,
        chat_id: int,
        requester_user_id: int,
        target_user_id: int,
        character_name: str,
    ) -> None:
        await self._outbox.publish(
            'player_invited',
            {
                'chat_id': chat_id,
                'requester_user_id': requester_user_id,
                'target_user_id': target_user_id,
                'character_name': character_name,
            },
        )
