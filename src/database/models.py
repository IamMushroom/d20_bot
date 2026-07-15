from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Campaign:
    id: int
    chat_id: int
    title: str | None
    master_user_id: int | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Character:
    id: int
    campaign_id: int
    telegram_user_id: int
    name: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Session:
    id: int
    campaign_id: int
    number: int
    title: str | None
    scheduled_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    foundry_url: str | None
    message_id: int | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class RecapEntry:
    id: int
    session_id: int
    character_id: int
    text: str
    position: int
    created_at: datetime
    updated_at: datetime
