from dataclasses import dataclass
from pathlib import Path

from auth import IdentityProvider, RateLimiter, SQLiteLocalIdentityProvider, SQLiteRateLimiter
from database import Database, apply_migrations, create_database
from services import CampaignService, OutboxService, SessionService
from web import AdminAccessService, AdminWebServer
from web.session_store import SQLiteWebSessionStore


@dataclass(slots=True)
class CoreRuntime:
    database: Database
    campaigns: CampaignService
    sessions: SessionService
    outbox: OutboxService
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
            campaigns = CampaignService(database)
            sessions = SessionService(database)
            outbox = OutboxService(database)
            access = AdminAccessService(SQLiteWebSessionStore(database))
            identities = SQLiteLocalIdentityProvider(database)
            rate_limiter = SQLiteRateLimiter(database)
            web_server = AdminWebServer(
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
            access=access,
            identities=identities,
            rate_limiter=rate_limiter,
            web_server=web_server,
            web_base_url=web_base_url,
        )

    async def close(self) -> None:
        await self.web_server.close()
        await self.database.close()
