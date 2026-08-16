from dataclasses import dataclass
from pathlib import Path

from auth import IdentityProvider, RateLimiter, SQLiteLocalIdentityProvider, SQLiteRateLimiter
from database import Database, apply_migrations, create_database
from database.repositories import (
    CampaignRepository,
    CharacterRepository,
    GameConfigRepository,
    MembershipRepository,
    OutboxRepository,
    SessionRepository,
)
from services import CampaignService, GameWorkflowService, OutboxService, SessionService
from web import AdminAccessService, AdminWebServer
from web.session_store import SQLiteWebSessionStore


@dataclass(slots=True)
class CoreRuntime:
    database: Database
    campaigns: CampaignService
    sessions: SessionService
    outbox: OutboxService
    workflows: GameWorkflowService
    access: AdminAccessService
    identities: IdentityProvider
    rate_limiter: RateLimiter
    web_server: AdminWebServer
    web_base_url: str

    @classmethod
    async def start(
        cls,
        *,
        database_url: str,
        migrations_directory: Path,
        web_host: str,
        web_port: int,
        web_base_url: str,
        internal_token: str,
    ) -> CoreRuntime:
        database = await create_database(database_url)
        try:
            await apply_migrations(database, migrations_directory)
            campaign_repository = CampaignRepository(database)
            character_repository = CharacterRepository(database)
            config_repository = GameConfigRepository(database)
            membership_repository = MembershipRepository(database)
            outbox_repository = OutboxRepository(database)
            session_repository = SessionRepository(database)

            campaigns = CampaignService(
                database,
                campaign_repository,
                character_repository,
                membership_repository,
            )
            sessions = SessionService(
                campaign_repository,
                session_repository,
                config_repository,
                membership_repository,
            )
            outbox = OutboxService(outbox_repository)
            workflows = GameWorkflowService(database, sessions, outbox)
            access = AdminAccessService(SQLiteWebSessionStore(database))
            identities = SQLiteLocalIdentityProvider(database)
            rate_limiter = SQLiteRateLimiter(database)
            web_server = AdminWebServer(
                workflows,
                access,
                campaigns,
                sessions,
                outbox,
                identities,
                rate_limiter,
                internal_token=internal_token,
                web_base_url=web_base_url,
            )
            await web_server.start(web_host, web_port)
        except BaseException:
            await database.close()
            raise
        return cls(
            database=database,
            campaigns=campaigns,
            sessions=sessions,
            outbox=outbox,
            workflows=workflows,
            access=access,
            identities=identities,
            rate_limiter=rate_limiter,
            web_server=web_server,
            web_base_url=web_base_url,
        )

    async def close(self) -> None:
        await self.web_server.close()
        await self.database.close()
