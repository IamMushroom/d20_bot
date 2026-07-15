from dataclasses import dataclass
from enum import Enum, auto

from database.connection import Database
from database.models import Campaign, Character
from database.repositories import CampaignRepository, CharacterRepository


class PlayerRegistrationStatus(Enum):
    REGISTERED = auto()
    MASTER_CONFLICT = auto()


@dataclass(frozen=True, slots=True)
class PlayerRegistration:
    status: PlayerRegistrationStatus
    character: Character | None


class CampaignService:
    def __init__(self, database: Database):
        self._campaigns = CampaignRepository(database)
        self._characters = CharacterRepository(database)

    async def assign_master(self, chat_id: int, user_id: int, title: str | None = None) -> Campaign:
        return await self._campaigns.set_master(chat_id, user_id, title)

    async def register_player(
        self, chat_id: int, user_id: int, name: str, title: str | None = None
    ) -> PlayerRegistration:
        campaign = await self._campaigns.get_or_create(chat_id, title)
        if campaign.master_user_id == user_id:
            return PlayerRegistration(PlayerRegistrationStatus.MASTER_CONFLICT, None)
        character = await self._characters.register(campaign.id, user_id, name)
        return PlayerRegistration(PlayerRegistrationStatus.REGISTERED, character)
