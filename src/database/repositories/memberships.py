from datetime import UTC, datetime
from typing import cast

from database.connection import Database, Row
from database.models import Campaign, CampaignMembership
from database.repositories.campaigns import _campaign


def _membership(row: Row) -> CampaignMembership:
    return CampaignMembership(
        campaign_id=cast(int, row['campaign_id']),
        user_id=cast(int, row['user_id']),
        telegram_user_id=cast(int, row['telegram_user_id']),
        role=str(row['role']),
        created_at=datetime.fromisoformat(str(row['created_at'])),
        updated_at=datetime.fromisoformat(str(row['updated_at'])),
    )


class MembershipRepository:
    def __init__(self, database: Database):
        self._database = database

    async def set_role(
        self, campaign_id: int, telegram_user_id: int, role: str
    ) -> CampaignMembership:
        if role not in {'player', 'master'}:
            raise ValueError(f'Unsupported campaign role: {role}')
        now = datetime.now(UTC).isoformat()
        await self._database.execute(
            """INSERT INTO users (telegram_user_id, created_at) VALUES (?, ?)
            ON CONFLICT(telegram_user_id) DO NOTHING""",
            (telegram_user_id, now),
        )
        row = await self._database.fetch_one(
            """INSERT INTO campaign_memberships (
                campaign_id, user_id, role, created_at, updated_at
            )
            SELECT ?, id, ?, ?, ? FROM users WHERE telegram_user_id = ?
            ON CONFLICT(campaign_id, user_id) DO UPDATE SET
                role = excluded.role,
                updated_at = excluded.updated_at
            RETURNING *, ? AS telegram_user_id""",
            (campaign_id, role, now, now, telegram_user_id, telegram_user_id),
        )
        assert row is not None
        return _membership(row)

    async def get_role(self, campaign_id: int, telegram_user_id: int) -> str | None:
        row = await self._database.fetch_one(
            """SELECT membership.role FROM campaign_memberships AS membership
            JOIN users AS user ON user.id = membership.user_id
            WHERE membership.campaign_id = ? AND user.telegram_user_id = ?""",
            (campaign_id, telegram_user_id),
        )
        return str(row['role']) if row is not None else None

    async def list_by_campaign(self, campaign_id: int) -> tuple[CampaignMembership, ...]:
        rows = await self._database.fetch_all(
            """SELECT membership.*, user.telegram_user_id
            FROM campaign_memberships AS membership
            JOIN users AS user ON user.id = membership.user_id
            WHERE membership.campaign_id = ?
            ORDER BY membership.role, user.telegram_user_id""",
            (campaign_id,),
        )
        return tuple(_membership(row) for row in rows)

    async def list_campaigns(self, telegram_user_id: int) -> tuple[Campaign, ...]:
        rows = await self._database.fetch_all(
            """SELECT campaign.* FROM campaigns AS campaign
            JOIN campaign_memberships AS membership ON membership.campaign_id = campaign.id
            JOIN users AS user ON user.id = membership.user_id
            WHERE user.telegram_user_id = ? ORDER BY campaign.title, campaign.id""",
            (telegram_user_id,),
        )
        return tuple(_campaign(row) for row in rows)

    async def remove_player(self, campaign_id: int, telegram_user_id: int) -> bool:
        changed = await self._database.execute(
            """DELETE FROM campaign_memberships
            WHERE campaign_id = ? AND role = 'player' AND user_id = (
                SELECT id FROM users WHERE telegram_user_id = ?
            )""",
            (campaign_id, telegram_user_id),
        )
        return changed > 0
