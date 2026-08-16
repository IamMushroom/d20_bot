from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto

from database.connection import Database
from database.repositories import (
    ActiveSessionExistsError,
    CampaignRepository,
    GameConfigRepository,
    MembershipRepository,
    SessionRepository,
)
from domain import Session


@dataclass(frozen=True, slots=True)
class ScheduleUpdate:
    session: Session
    previous_message_id: int | None


class SessionStartStatus(Enum):
    STARTED = auto()
    FORBIDDEN = auto()
    ALREADY_ACTIVE = auto()


@dataclass(frozen=True, slots=True)
class SessionStart:
    status: SessionStartStatus
    session: Session | None = None
    announcement_message_id: int | None = None


class SessionStopStatus(Enum):
    STOPPED = auto()
    FORBIDDEN = auto()
    NO_ACTIVE_SESSION = auto()


@dataclass(frozen=True, slots=True)
class SessionStop:
    status: SessionStopStatus
    session: Session | None = None


class SessionService:
    def __init__(self, database: Database):
        self._campaigns = CampaignRepository(database)
        self._sessions = SessionRepository(database)
        self._configs = GameConfigRepository(database)
        self._memberships = MembershipRepository(database)

    async def get_planned(self, chat_id: int) -> Session | None:
        campaign = await self._campaigns.get_by_chat_id(chat_id)
        return await self._sessions.get_planned(campaign.id) if campaign is not None else None

    async def get_active(self, chat_id: int) -> Session | None:
        campaign = await self._campaigns.get_by_chat_id(chat_id)
        return await self._sessions.get_active(campaign.id) if campaign is not None else None

    async def get_history(self, chat_id: int, limit: int = 10) -> list[Session]:
        campaign = await self._campaigns.get_by_chat_id(chat_id)
        return await self._sessions.list_finished(campaign.id, limit) if campaign else []

    async def schedule(
        self,
        chat_id: int,
        chat_title: str | None,
        scheduled_at: datetime,
        foundry_url: str,
    ) -> ScheduleUpdate:
        campaign = await self._campaigns.get_or_create(chat_id, chat_title)
        previous = await self._sessions.get_planned(campaign.id)
        session = await self._sessions.schedule(campaign.id, scheduled_at, foundry_url)
        return ScheduleUpdate(
            session=session,
            previous_message_id=previous.message_id if previous is not None else None,
        )

    async def set_announcement(self, session_id: int, message_id: int) -> None:
        await self._sessions.set_message_id(session_id, message_id)

    async def get_default_url(self, chat_id: int) -> str | None:
        return await self._configs.get_default_url(chat_id)

    async def set_default_url(self, chat_id: int, foundry_url: str, updated_at: datetime) -> None:
        await self._configs.set_default_url(chat_id, foundry_url, updated_at)

    async def get_web_base_url(self, chat_id: int) -> str | None:
        return await self._configs.get_web_base_url(chat_id)

    async def set_web_base_url(self, chat_id: int, web_base_url: str, updated_at: datetime) -> None:
        await self._configs.set_web_base_url(chat_id, web_base_url, updated_at)

    async def get_announcement_timezone(self, chat_id: int) -> str:
        return await self._configs.get_announcement_timezone(chat_id) or 'Europe/Moscow'

    async def set_announcement_timezone(
        self, chat_id: int, timezone_name: str, updated_at: datetime
    ) -> None:
        await self._configs.set_announcement_timezone(chat_id, timezone_name, updated_at)

    async def start(self, chat_id: int, user_id: int, title: str | None) -> SessionStart:
        campaign = await self._campaigns.get_by_chat_id(chat_id)
        if campaign is None or await self._memberships.get_role(campaign.id, user_id) != 'master':
            return SessionStart(SessionStartStatus.FORBIDDEN)
        planned = await self._sessions.get_planned(campaign.id)
        try:
            session = await self._sessions.start(campaign.id, title)
        except ActiveSessionExistsError:
            return SessionStart(SessionStartStatus.ALREADY_ACTIVE)
        return SessionStart(
            status=SessionStartStatus.STARTED,
            session=session,
            announcement_message_id=planned.message_id if planned is not None else None,
        )

    async def stop(self, chat_id: int, user_id: int) -> SessionStop:
        campaign = await self._campaigns.get_by_chat_id(chat_id)
        if campaign is None or await self._memberships.get_role(campaign.id, user_id) != 'master':
            return SessionStop(SessionStopStatus.FORBIDDEN)
        active = await self._sessions.get_active(campaign.id)
        if active is None:
            return SessionStop(SessionStopStatus.NO_ACTIVE_SESSION)
        session = await self._sessions.finish(active.id)
        if session is None:
            return SessionStop(SessionStopStatus.NO_ACTIVE_SESSION)
        return SessionStop(SessionStopStatus.STOPPED, session)
