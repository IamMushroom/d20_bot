from dataclasses import dataclass
from enum import Enum, auto

from database.connection import Database
from database.repositories import CampaignRepository, CharacterRepository, MembershipRepository
from domain import Campaign, CampaignMembership, Character


class PlayerRegistrationStatus(Enum):
    REGISTERED = auto()
    MASTER_CONFLICT = auto()


@dataclass(frozen=True, slots=True)
class PlayerRegistration:
    status: PlayerRegistrationStatus
    character: Character | None


@dataclass(frozen=True, slots=True)
class CampaignRoster:
    campaign: Campaign
    characters: tuple[Character, ...]
    memberships: tuple[CampaignMembership, ...] = ()


class CampaignService:
    def __init__(self, database: Database):
        self._database = database
        self._campaigns = CampaignRepository(database)
        self._characters = CharacterRepository(database)
        self._memberships = MembershipRepository(database)

    async def assign_master(self, chat_id: int, user_id: int, title: str | None = None) -> Campaign:
        async with self._database.transaction():
            return await self._campaigns.set_master(chat_id, user_id, title)

    async def is_master(self, chat_id: int, user_id: int) -> bool:
        campaign = await self._campaigns.get_by_chat_id(chat_id)
        return (
            campaign is not None
            and await self._memberships.get_role(campaign.id, user_id) == 'master'
        )

    async def get_role(self, chat_id: int, user_id: int) -> str | None:
        campaign = await self._campaigns.get_by_chat_id(chat_id)
        return await self._memberships.get_role(campaign.id, user_id) if campaign else None

    async def get_roster(self, chat_id: int) -> CampaignRoster | None:
        campaign = await self._campaigns.get_by_chat_id(chat_id)
        if campaign is None:
            return None
        characters = await self._characters.list(campaign.id)
        memberships = await self._memberships.list_by_campaign(campaign.id)
        return CampaignRoster(campaign, tuple(characters), memberships)

    async def list_for_user(self, user_id: int) -> tuple[Campaign, ...]:
        return await self._memberships.list_campaigns(user_id)

    async def set_title(self, chat_id: int, title: str) -> Campaign | None:
        return await self._campaigns.set_title(chat_id, title)

    async def register_player(
        self, chat_id: int, user_id: int, name: str, title: str | None = None
    ) -> PlayerRegistration:
        async with self._database.transaction():
            campaign = await self._campaigns.get_or_create(chat_id, title)
            if await self._memberships.get_role(campaign.id, user_id) == 'master':
                return PlayerRegistration(PlayerRegistrationStatus.MASTER_CONFLICT, None)
            await self._memberships.set_role(campaign.id, user_id, 'player')
            character = await self._characters.register(campaign.id, user_id, name)
            return PlayerRegistration(PlayerRegistrationStatus.REGISTERED, character)

    async def rename_player(self, chat_id: int, user_id: int, name: str) -> Character | None:
        campaign = await self._campaigns.get_by_chat_id(chat_id)
        if campaign is None or await self._memberships.get_role(campaign.id, user_id) != 'player':
            return None
        return await self._characters.rename(campaign.id, user_id, name)

    async def remove_player(self, chat_id: int, user_id: int) -> bool:
        campaign = await self._campaigns.get_by_chat_id(chat_id)
        return (
            await self._memberships.remove_player(campaign.id, user_id)
            if campaign is not None
            else False
        )

    async def transfer_master(
        self, chat_id: int, current_master_id: int, new_master_id: int
    ) -> bool:
        async with self._database.transaction():
            campaign = await self._campaigns.get_by_chat_id(chat_id)
            if (
                campaign is None
                or await self._memberships.get_role(campaign.id, current_master_id) != 'master'
                or await self._memberships.get_role(campaign.id, new_master_id) != 'player'
            ):
                return False
            await self._campaigns.set_master(chat_id, new_master_id)
            await self._memberships.set_role(campaign.id, current_master_id, 'player')
            return True
